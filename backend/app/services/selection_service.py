"""画像選別。

画像を物理削除せず、選別結果を selection.json に保存する。低品質（小サイズ・
暗/明・ブレ）・重複を検出し、status（included/excluded/review）を付与する。

OpenCV/NumPy は使わず Pillow のみ。ブレはグレースケールの FIND_EDGES 後の
画素分散（ヒストグラムから算出）で近似する。
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from ..core import paths
from ..core.config import settings
from ..schemas.selection import (
    SelectionGetResponse,
    SelectionItem,
    SelectionRotateResponse,
    SelectionRunRequest,
    SelectionRunResponse,
    SelectionStatusResponse,
    SelectionStatusUpdate,
    SelectionSummary,
)
from .project_service import ProjectError, project_exists

_VALID_STATUS = {"included", "excluded", "review"}


class SelectionError(Exception):
    pass


class SelectionNotFoundError(SelectionError):
    """404相当。"""


class SelectionValidationError(SelectionError):
    """400相当。"""


class SelectionConflictError(SelectionError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _hist_stats(hist: list[int]) -> tuple[float, float]:
    """ヒストグラム(256)から (mean, variance) を返す。"""
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
    return mean, var


def _analyze_image(data: bytes) -> tuple[int, int, float, float]:
    """(width, height, brightness_mean, blur_score) を返す。"""
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        gray = im.convert("L")
    brightness_mean, _ = _hist_stats(gray.histogram())
    edges = gray.filter(ImageFilter.FIND_EDGES)
    # FIND_EDGES は画像端で偽のエッジ（高値）を出すため、内側のみで分散を測る
    ew, eh = edges.size
    if ew > 4 and eh > 4:
        edges = edges.crop((2, 2, ew - 2, eh - 2))
    _, blur_score = _hist_stats(edges.histogram())
    return w, h, round(brightness_mean, 2), round(blur_score, 2)


def run(name: str, req: SelectionRunRequest) -> SelectionRunResponse:
    _require_project(name)

    path = paths.selection_path(name)
    if path.exists() and not req.overwrite:
        raise SelectionConflictError(
            "selection.json が既に存在します。overwrite=true で再実行してください。"
        )

    img_dir = paths.images_dir_for_source(name, req.source)
    used_source = "processed" if img_dir == paths.processed_images_dir(name) else "raw"

    files = sorted(
        p for p in img_dir.iterdir()
        if p.is_file() and p.suffix.lower() in settings.allowed_image_suffixes
    ) if img_dir.exists() else []

    items: list[SelectionItem] = []
    hash_first: dict[str, str] = {}  # hash -> 最初の image_id

    for p in files:
        try:
            data = p.read_bytes()
            w, h, brightness, blur = _analyze_image(data)
        except (UnidentifiedImageError, OSError, ValueError):
            continue
        digest = hashlib.sha1(data).hexdigest()
        image_id = p.stem

        warnings: list[str] = []
        reasons: list[str] = []
        duplicate_of: str | None = None

        if w < req.min_width or h < req.min_height:
            warnings.append("small_image")
            reasons.append("画像サイズが小さすぎます")
        if brightness < req.dark_threshold:
            warnings.append("dark_image")
            reasons.append("画像が暗すぎます")
        if brightness > req.bright_threshold:
            warnings.append("bright_image")
            reasons.append("画像が明るすぎます")
        if blur < req.blur_threshold:
            warnings.append("blur_image")
            reasons.append("画像がブレている可能性があります")
        if req.detect_duplicates:
            if digest in hash_first:
                duplicate_of = hash_first[digest]
                warnings.append("duplicate_image")
                reasons.append("重複画像です")
            else:
                hash_first[digest] = image_id

        # status: 重複2枚目以降は excluded、その他の警告は review、無ければ included
        if duplicate_of is not None:
            status = "excluded"
        elif warnings:
            status = "review"
        else:
            status = "included"

        items.append(SelectionItem(
            image_id=image_id, image_name=p.name, source=used_source,
            width=w, height=h, status=status, warnings=warnings, reasons=reasons,
            hash=digest, brightness_mean=brightness, blur_score=blur,
            duplicate_of=duplicate_of,
        ))

    summary = _summarize(items)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": used_source,
        "settings": {
            "min_width": req.min_width, "min_height": req.min_height,
            "blur_threshold": req.blur_threshold, "dark_threshold": req.dark_threshold,
            "bright_threshold": req.bright_threshold, "duplicate_hash": req.detect_duplicates,
        },
        "summary": summary.model_dump(),
        "items": [it.model_dump() for it in items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return SelectionRunResponse(
        project_name=name, source=used_source, summary=summary,
        selection_path="selection/selection.json",
    )


def _summarize(items: list[SelectionItem]) -> SelectionSummary:
    def warned(w: str) -> int:
        return sum(1 for it in items if w in it.warnings)

    return SelectionSummary(
        image_count=len(items),
        included_count=sum(1 for it in items if it.status == "included"),
        excluded_count=sum(1 for it in items if it.status == "excluded"),
        review_count=sum(1 for it in items if it.status == "review"),
        duplicate_count=warned("duplicate_image"),
        small_count=warned("small_image"),
        dark_count=warned("dark_image"),
        bright_count=warned("bright_image"),
        blur_count=warned("blur_image"),
    )


def _load(name: str) -> dict:
    path = paths.selection_path(name)
    if not path.exists():
        raise SelectionNotFoundError("画像選別が未実行です。")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_selection(name: str) -> SelectionGetResponse:
    _require_project(name)
    data = _load(name)
    items = [SelectionItem(**it) for it in data.get("items", [])]
    return SelectionGetResponse(
        project_name=name,
        source=data.get("source", "raw"),
        summary=_summarize(items),
        items=items,
    )


def update_status(name: str, image_id: str, upd: SelectionStatusUpdate) -> SelectionStatusResponse:
    _require_project(name)
    if upd.status not in _VALID_STATUS:
        raise SelectionValidationError("status は included/excluded/review のいずれかです。")
    data = _load(name)
    found = None
    for it in data.get("items", []):
        if it.get("image_id") == image_id:
            it["status"] = upd.status
            it["manual_reason"] = upd.manual_reason
            found = it
            break
    if found is None:
        raise SelectionNotFoundError(f"画像 '{image_id}' が選別結果にありません。")
    # summaryを再計算
    items = [SelectionItem(**it) for it in data["items"]]
    data["summary"] = _summarize(items).model_dump()
    paths.selection_path(name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return SelectionStatusResponse(
        image_id=image_id, status=upd.status, manual_reason=upd.manual_reason
    )


def rotate_image(name: str, image_id: str, source: str, angle: int) -> SelectionRotateResponse:
    """画像を回転保存する。raw と processed の両方（存在する側）に適用し、
    どの表示（選別・前処理・アノテーション）でも向きが一致するようにする。
    processed はプリ生成サムネイルも再生成する。source は無視して両方を回す。
    """
    _require_project(name)
    if angle not in (90, -90, 180):
        raise SelectionValidationError("angle は 90 / -90 / 180 のいずれかです。")

    stem = Path(image_id).stem
    if stem != Path(stem).name:
        raise SelectionValidationError("不正な image_id です。")

    rotated_sources: list[str] = []
    last_w = last_h = 0
    # raw と processed の両方を対象に、存在するファイルを回転
    for src_name in ("raw", "processed"):
        img_dir = paths.images_dir_for_source(name, src_name)
        if not img_dir.exists():
            continue
        target = None
        for p in img_dir.iterdir():
            if p.is_file() and p.stem == stem and p.suffix.lower() in settings.allowed_image_suffixes:
                target = p
                break
        if target is None:
            continue

        fmt = "PNG" if target.suffix.lower() == ".png" else "JPEG"
        with Image.open(target) as im:
            # PILのrotateは反時計回りが正。expand=Trueで枠を広げる。
            # EXIF Orientation を焼き込んでから回すため、保存後は向きが確定する。
            rotated = ImageOps.exif_transpose(im).convert("RGB").rotate(angle, expand=True)
        rotated.save(target, format=fmt)
        rotated_sources.append(src_name)
        last_w, last_h = rotated.width, rotated.height

        # processed はプリ生成サムネイルも再生成
        if src_name == "processed":
            thumbs = paths.processed_thumbnails_dir(name)
            thumbs.mkdir(parents=True, exist_ok=True)
            thumb = rotated.copy()
            thumb.thumbnail((settings.thumbnail_max_size, settings.thumbnail_max_size))
            thumb.save(thumbs / target.name, format=fmt)

    if not rotated_sources:
        raise SelectionNotFoundError(f"画像 '{image_id}' が見つかりません。")

    warning = None
    if paths.labels_dir(name).exists() and any(paths.labels_dir(name).glob("*.txt")):
        warning = (
            "既存ラベルがある状態で画像を回転すると、bbox座標と画像が一致しなくなる可能性があります。"
        )

    return SelectionRotateResponse(
        image_id=stem, source="+".join(rotated_sources), angle=angle,
        width=last_w, height=last_h, warning=warning,
    )


def load_allowed_stems(name: str, include_review: bool) -> tuple[set[str] | None, str | None]:
    """dataset作成用: 採用する image_id(stem) の集合と warning を返す。

    selection 未実行/破損時は (None, warning) を返し、呼び出し側は全画像対象とする。
    """
    path = paths.selection_path(name)
    if not path.exists():
        return None, "selection.json が無いため、全画像を対象にします。"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None, "selection.json が壊れているため、全画像を対象にします。"
    allowed: set[str] = set()
    for it in data.get("items", []):
        st = it.get("status")
        if st == "included" or (st == "review" and include_review):
            allowed.add(it.get("image_id"))
    return allowed, None
