"""SAM支援アノテーション。

bbox / 点プロンプトから SAM で mask 候補を生成し、mask を polygon 化して返す。
SAM 呼び出しは service 層で抽象化し、将来 公式 segment-anything へ切り替え可能にする。
候補は一時的にレスポンスで返すだけで保存しない（採用時はフロントが既存の
segment annotation 保存API を使う）。

- SAM/torch/ultralytics/opencv は backend/requirements.txt には入れない（軽量起動維持）。
  requirements-sam.txt で導入する。未導入時は分かりやすいエラーを返す。
- 環境変数 YTS_SAM_DRY_RUN=1 のときは SAM を読み込まず、bbox/点から擬似polygon候補を
  生成する（テスト用）。
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from PIL import Image

from ..core import paths
from ..schemas.sam import (
    ALLOWED_SAM_DEVICES,
    ALLOWED_SAM_MODELS,
    SamBox,
    SamCandidate,
    SamPoint,
    SamProposeRequest,
    SamProposeResponse,
    SamSettings,
)
from . import project_service
from .project_service import ProjectError, project_exists


class SamError(Exception):
    """SAM操作の業務エラー。"""


class SamValidationError(SamError):
    """不正なリクエスト（HTTP 400相当）。"""


class SamNotFoundError(SamError):
    """対象が見つからない（HTTP 404相当）。"""


class SamDependencyError(SamError):
    """SAM依存未導入/モデル未取得（HTTP 400・friendly）。"""


class SamRuntimeError(SamError):
    """SAM実行時エラー（GPUメモリ不足など・HTTP 500・friendly）。"""


# プロセス内モデルキャッシュ（開発reload時は再ロードされる）
_MODEL_CACHE: dict[tuple[str, str], object] = {}


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


# ---------------- 設定 ----------------
def default_settings() -> SamSettings:
    return SamSettings()


def get_settings(name: str) -> SamSettings:
    _require_project(name)
    p = paths.sam_settings_path(name)
    if not p.exists():
        return default_settings()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return default_settings()
    try:
        return SamSettings(**data)
    except (TypeError, ValueError):
        return default_settings()


def _validate_settings(s: SamSettings) -> None:
    if s.model not in ALLOWED_SAM_MODELS:
        raise SamValidationError(
            f"model は {' / '.join(ALLOWED_SAM_MODELS)} のいずれかです。"
        )
    if s.device not in ALLOWED_SAM_DEVICES:
        raise SamValidationError(
            f"device は {' / '.join(ALLOWED_SAM_DEVICES)} のいずれかです。"
        )
    if not (0.0 <= s.polygon_simplify_epsilon <= 20.0):
        raise SamValidationError("polygon_simplify_epsilon は 0.0〜20.0 です。")
    if not (1 <= s.min_area <= 100000):
        raise SamValidationError("min_area は 1〜100000 です。")
    if not (10 <= s.max_points <= 2000):
        raise SamValidationError("max_points は 10〜2000 です。")
    if not (0 <= s.merge_distance_px <= 100):
        raise SamValidationError("merge_distance_px は 0〜100 です。")


def save_settings(name: str, s: SamSettings) -> SamSettings:
    _require_project(name)
    _validate_settings(s)
    paths.sam_dir(name).mkdir(parents=True, exist_ok=True)
    paths.sam_settings_path(name).write_text(
        json.dumps(s.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return s


# ---------------- 画像解決 ----------------
def _resolve_image(name: str, image_id: str, source: str) -> Path:
    img_dir = paths.images_dir_for_source(name, source)
    if not img_dir.exists():
        raise SamNotFoundError(f"画像 '{image_id}' が見つかりません。")
    stem = Path(image_id).stem
    if stem != Path(stem).name or stem in ("", ".", ".."):
        raise SamValidationError("不正な image_id です。")
    for p in sorted(img_dir.iterdir()):
        if p.is_file() and p.stem == stem:
            return p
    raise SamNotFoundError(f"画像 '{image_id}' が見つかりません。")


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.size  # (w, h)
    except (OSError, ValueError) as e:
        raise SamNotFoundError(f"画像を読み込めません: {path.name}") from e


# ---------------- プロンプト検証 ----------------
def _coord_ok(v: float) -> bool:
    return 0.0 <= v <= 1.0 and not math.isnan(v) and not math.isinf(v)


def _validate_prompt(req: SamProposeRequest) -> None:
    pr = req.prompt
    if pr.type not in ("box", "point"):
        raise SamValidationError("prompt.type は box または point です。")
    if pr.type == "box":
        if pr.box is None:
            raise SamValidationError("box プロンプトには box 座標が必要です。")
        b = pr.box
        if not all(_coord_ok(v) for v in (b.x1, b.y1, b.x2, b.y2)):
            raise SamValidationError("box 座標が範囲外です（0〜1）。")
        if b.x2 <= b.x1 or b.y2 <= b.y1:
            raise SamValidationError("box は x1<x2 かつ y1<y2 にしてください。")
    else:  # point
        if len(pr.positive_points) == 0:
            raise SamValidationError("point プロンプトには positive point が1つ以上必要です。")
        for p in pr.positive_points + pr.negative_points:
            if not (_coord_ok(p.x) and _coord_ok(p.y)):
                raise SamValidationError("point 座標が範囲外です（0〜1）。")


# ---------------- mask → polygon ----------------
def _contour_to_points(contour, cv2, w: int, h: int, s: SamSettings):
    """輪郭を正規化polygon点列へ。max_points を超える場合は簡略化を強める。"""
    eps = max(0.1, s.polygon_simplify_epsilon)
    approx = cv2.approxPolyDP(contour, eps, True)
    guard = 0
    while len(approx) > s.max_points and guard < 40:
        eps *= 1.5
        approx = cv2.approxPolyDP(contour, eps, True)
        guard += 1
    pts = [(float(p[0][0]) / w, float(p[0][1]) / h) for p in approx]
    return pts


def _extract_candidates(masks: list, s: SamSettings) -> list[SamCandidate]:
    """複数maskをOR合成し、近接領域をマージして polygon 候補（最大輪郭）を返す。

    masks: 各要素は 2値(bool/0-1) の numpy 配列（同一サイズ）。
    - merge_nearby_regions=true のとき cv2.morphologyEx(CLOSE) で近接領域を接続。
    - MVP: 面積最大の輪郭のみを1候補として返す。
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    if not masks:
        return []
    src_count = len(masks)
    h, w = np.asarray(masks[0]).shape[:2]
    combined = np.zeros((h, w), dtype="uint8")
    for m in masks:
        combined = np.maximum(combined, (np.asarray(m) > 0.5).astype("uint8") * 255)

    if s.merge_nearby_regions and s.merge_distance_px > 0:
        k = int(s.merge_distance_px) * 2 + 1
        kernel = np.ones((k, k), np.uint8)
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [(float(cv2.contourArea(c)), c) for c in contours]
    valid = [(a, c) for a, c in valid if a >= s.min_area]
    if not valid:
        return []
    valid.sort(key=lambda t: t[0], reverse=True)

    # MVP: 面積最大の輪郭のみを候補にする（近接領域は上でマージ済み）
    area, best = valid[0]
    pts = _contour_to_points(best, cv2, w, h, s)
    if len(pts) < 3:
        return []
    return [
        _make_candidate(
            1, pts, area, None,
            merged=src_count > 1,
            source_mask_count=src_count,
        )
    ]


# ---------------- SAMモデル ----------------
def _resolve_device(device: str) -> str | None:
    if device == "auto":
        return None  # ultralytics に委ねる
    return device


def get_sam_model(model_name: str, device: str):
    key = (model_name, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        from ultralytics import SAM  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise SamDependencyError(
            "SAMモデルが利用できません。backend/requirements-sam.txt を導入してください。"
        ) from e
    try:
        model = SAM(model_name)
    except Exception as e:  # noqa: BLE001
        raise SamDependencyError(
            f"SAMモデル '{model_name}' を読み込めませんでした。"
            "初回はモデルの自動ダウンロードにネットワークが必要です。"
        ) from e
    _MODEL_CACHE[key] = model
    return model


def _run_sam(img_path: Path, req: SamProposeRequest, s: SamSettings, img_w: int, img_h: int) -> list[SamCandidate]:
    model = get_sam_model(s.model, s.device)
    pr = req.prompt
    kwargs: dict = {"verbose": False}
    dev = _resolve_device(s.device)
    if dev:
        kwargs["device"] = dev
    if pr.type == "box" and pr.box is not None:
        b = pr.box
        kwargs["bboxes"] = [[b.x1 * img_w, b.y1 * img_h, b.x2 * img_w, b.y2 * img_h]]
    pts: list[list[float]] = []
    labels: list[int] = []
    for p in pr.positive_points:
        pts.append([p.x * img_w, p.y * img_h])
        labels.append(1)
    for p in pr.negative_points:
        pts.append([p.x * img_w, p.y * img_h])
        labels.append(0)
    if pts:
        kwargs["points"] = pts
        kwargs["labels"] = labels

    try:
        results = model(str(img_path), **kwargs)
    except Exception as e:  # noqa: BLE001
        msg = f"{e!r}".lower()
        if "out of memory" in msg or "cuda" in msg and "memory" in msg:
            raise SamRuntimeError(
                "GPUメモリ不足です。SAMモデルを軽量化するか device=cpu を試してください。"
            ) from e
        raise SamRuntimeError(f"SAM実行に失敗しました: {e!r}") from e

    if not results:
        return []
    masks = getattr(results[0], "masks", None)
    if masks is None or getattr(masks, "data", None) is None:
        return []
    data = masks.data
    mask_arrays = []
    for i in range(len(data)):
        arr = data[i]
        arr = arr.cpu().numpy() if hasattr(arr, "cpu") else arr
        mask_arrays.append(arr)
    return _extract_candidates(mask_arrays, s)


# ---------------- 候補生成（mock / real）----------------
def _make_candidate(
    idx: int,
    pts_norm,
    area: float,
    score: float | None,
    merged: bool | None = None,
    source_mask_count: int | None = None,
) -> SamCandidate:
    xs = [p[0] for p in pts_norm]
    ys = [p[1] for p in pts_norm]
    return SamCandidate(
        candidate_id=f"cand_{idx:03d}",
        score=score,
        area=area,
        points=[SamPoint(x=p[0], y=p[1]) for p in pts_norm],
        bbox=SamBox(x1=min(xs), y1=min(ys), x2=max(xs), y2=max(ys)),
        merged=merged,
        source_mask_count=source_mask_count,
    )


def _mock_candidates(req: SamProposeRequest, s: SamSettings, img_w: int, img_h: int) -> list[SamCandidate]:
    """SAMを使わず、プロンプトから擬似maskを合成して候補を作る（テスト用）。

    - box: bbox内の楕円を1つのmaskに描く。
    - point: positive点ごとに円maskを作る（→ _extract_candidates で近接マージを検証）。
    実際のマージ/輪郭抽出は本番と同じ _extract_candidates を通す。
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    pr = req.prompt
    masks: list = []
    if pr.type == "box" and pr.box is not None:
        m = np.zeros((img_h, img_w), dtype="uint8")
        cx = int((pr.box.x1 + pr.box.x2) / 2 * img_w)
        cy = int((pr.box.y1 + pr.box.y2) / 2 * img_h)
        ax = max(1, int((pr.box.x2 - pr.box.x1) / 2 * img_w))
        ay = max(1, int((pr.box.y2 - pr.box.y1) / 2 * img_h))
        cv2.ellipse(m, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
        masks.append(m)
    else:
        r = max(3, int(min(img_w, img_h) * 0.04))
        for p in pr.positive_points:
            m = np.zeros((img_h, img_w), dtype="uint8")
            cv2.circle(m, (int(p.x * img_w), int(p.y * img_h)), r, 255, -1)
            masks.append(m)

    cands = _extract_candidates(masks, s)
    # mockは擬似スコアを付ける
    for c in cands:
        c.score = 0.9
    return cands


# ---------------- 公開: propose ----------------
def propose(name: str, image_id: str, req: SamProposeRequest) -> SamProposeResponse:
    _require_project(name)
    if project_service.get_task(name) != "segment":
        raise SamValidationError("SAM支援はsegmentプロジェクトでのみ使用できます。")

    settings = req.settings or get_settings(name)
    _validate_settings(settings)
    _validate_prompt(req)

    img_path = _resolve_image(name, image_id, req.source)
    img_w, img_h = _image_size(img_path)

    # 依存未導入の疑似テスト用
    if os.environ.get("YTS_SAM_SIMULATE_NO_DEP"):
        raise SamDependencyError(
            "SAMモデルが利用できません。backend/requirements-sam.txt を導入してください。"
        )

    if os.environ.get("YTS_SAM_DRY_RUN"):
        candidates = _mock_candidates(req, settings, img_w, img_h)
    else:
        candidates = _run_sam(img_path, req, settings, img_w, img_h)

    stem = Path(img_path).stem
    message = None if candidates else "候補が見つかりませんでした（min_area や範囲を見直してください）。"
    return SamProposeResponse(
        project_name=name,
        image_id=stem,
        class_id=req.class_id,
        source=req.source,
        candidates=candidates,
        message=message,
    )
