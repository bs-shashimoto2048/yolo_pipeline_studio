"""推論ジョブ基盤。

学習ジョブ（training_service）と同じく、HTTPリクエスト内で model.predict() を
直接実行せず、subprocess.Popen で workers/predict_worker.py を起動する。

predictions/{predict_job_id} 配下に job.json / predict.log / inputs / outputs /
results.json を保存する。パスは pathlib、相対パスはPOSIX区切り。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import paths
from ..core.config import settings
from ..schemas.prediction import (
    Detection,
    PredictJobCreate,
    PredictJobInfo,
    PredictJobListResponse,
    PredictJobStartResponse,
    PredictResultItem,
    PredictResultsResponse,
    PredictLogResponse,
)
from . import preprocess_service
from .project_service import ProjectError, project_exists

# backend/app/services/prediction_service.py → backend/workers/predict_worker.py
_WORKER = Path(__file__).resolve().parents[2] / "workers" / "predict_worker.py"

_IMAGE_EXTS = (".jpg", ".jpeg", ".png")


class PredictError(Exception):
    """推論ジョブ操作の業務エラー。"""


class PredictNotFoundError(PredictError):
    """対象が見つからない（HTTP 404相当）。"""


class PredictValidationError(PredictError):
    """事前チェック失敗（HTTP 400相当）。"""


class PredictConflictError(PredictError):
    """同名ジョブの衝突（HTTP 409相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _safe_rmtree(path: Path) -> None:
    """既存ジョブディレクトリを削除（worker のログハンドル解放待ちでリトライ）。"""

    def _on_error(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    last_err: Exception | None = None
    for _ in range(6):
        try:
            shutil.rmtree(path, onerror=_on_error)
        except OSError as e:
            last_err = e
        if not path.exists():
            return
        time.sleep(0.3)
    raise PredictConflictError(
        "既存ジョブの削除に失敗しました（推論プロセスが実行中の可能性があります）。"
        f" 詳細: {last_err!r}"
    )


def _resolve_image(name: str, image_id: str) -> Path:
    """画像ID（stem）から登録済み画像の実パスを解決する。"""
    img_dir = paths.raw_images_dir(name)
    stem = Path(image_id).stem
    if stem != Path(stem).name or stem in ("", ".", ".."):
        raise PredictValidationError(f"不正な image_id です: {image_id}")
    if img_dir.exists():
        for suffix in settings.allowed_image_suffixes:
            cand = img_dir / f"{stem}{suffix}"
            if cand.exists():
                return cand
        for p in img_dir.iterdir():
            if p.is_file() and p.stem == stem:
                return p
    raise PredictNotFoundError(f"画像 '{image_id}' が見つかりません。")


def _job_json_path(name: str, predict_job_id: str) -> Path:
    return paths.predict_job_dir(name, predict_job_id) / "job.json"


def _read_job(name: str, predict_job_id: str) -> dict | None:
    p = _job_json_path(name, predict_job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def start_job(name: str, req: PredictJobCreate) -> PredictJobStartResponse:
    _require_project(name)

    if not paths.is_valid_project_name(req.predict_job_name):
        raise PredictValidationError(
            "predict_job_name は英数・アンダースコア・ハイフンのみ使用できます。"
        )
    if req.weight_type not in ("best", "last"):
        raise PredictValidationError("weight_type は best または last です。")
    if req.source_type != "project_images":
        raise PredictValidationError(
            "source_type は現在 project_images のみ対応しています。"
        )

    # --- 事前チェック ---
    train_dir = paths.train_job_dir(name, req.train_job_id)
    if not train_dir.exists():
        raise PredictNotFoundError(
            f"学習ジョブ '{req.train_job_id}' が見つかりません。"
        )
    weight = train_dir / "weights" / f"{req.weight_type}.pt"
    if not weight.exists():
        raise PredictValidationError(
            f"モデル '{req.weight_type}.pt' が見つかりません: "
            f"{weight.relative_to(paths.project_dir(name)).as_posix()}"
        )
    if not req.image_ids:
        raise PredictValidationError("image_ids が空です。")
    resolved = [(img_id, _resolve_image(name, img_id)) for img_id in req.image_ids]

    predict_job_id = req.predict_job_name
    pred_dir = paths.predict_job_dir(name, predict_job_id)
    if pred_dir.exists():
        if not req.overwrite:
            raise PredictConflictError(
                f"推論ジョブ '{predict_job_id}' は既に存在します。"
            )
        _safe_rmtree(pred_dir)

    # --- 推論前処理モードの解決 ---
    if req.preprocess_mode not in ("none", "latest"):
        raise PredictValidationError("preprocess_mode は none または latest です。")
    pre_settings = None
    if req.preprocess_mode == "latest":
        pre_settings = preprocess_service.load_latest_settings(name)
        if pre_settings is None:
            raise PredictValidationError(
                "最新前処理設定がありません（前処理を実行してから 'latest' を選択してください）。"
            )

    # --- フォルダ作成 + 入力画像コピー ---
    inputs_dir = pred_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    (pred_dir / "outputs" / "images").mkdir(parents=True, exist_ok=True)
    (pred_dir / "outputs" / "labels").mkdir(parents=True, exist_ok=True)
    for _img_id, src in resolved:
        shutil.copy2(src, inputs_dir / src.name)

    # 推論前処理を適用する場合は preprocessed_inputs/ を作り、それを推論ソースにする
    source_dir = inputs_dir
    if pre_settings is not None:
        pp_dir = pred_dir / "preprocessed_inputs"
        pp_dir.mkdir(parents=True, exist_ok=True)
        out_fmt = (pre_settings.output_format or "jpg").lower()
        ext = ".png" if out_fmt == "png" else ".jpg"
        pil_fmt = "PNG" if ext == ".png" else "JPEG"
        for _img_id, src in resolved:
            try:
                result = preprocess_service.apply(src.read_bytes(), pre_settings)
                result.save(pp_dir / f"{src.stem}{ext}", format=pil_fmt)
            except Exception:  # noqa: BLE001 - 個別失敗はスキップ
                continue
        source_dir = pp_dir

    proj_dir = paths.project_dir(name)
    rel_pred = pred_dir.relative_to(proj_dir).as_posix()
    log_path = pred_dir / "predict.log"
    log_path.touch()

    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "predict_job_id": predict_job_id,
        "predict_job_name": req.predict_job_name,
        "train_job_id": req.train_job_id,
        "weight_type": req.weight_type,
        "source_type": req.source_type,
        "conf": req.conf,
        "iou": req.iou,
        "imgsz": req.imgsz,
        "device": req.device,
        "save_txt": req.save_txt,
        "save_conf": req.save_conf,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "return_code": None,
        "message": "queued",
        "image_count": len(resolved),
        "detection_count": None,
        "total_count": len(resolved),
        "processed_count": 0,
        "prediction_path": rel_pred,
        "results_json_path": f"{rel_pred}/results.json",
        "preprocess_mode": req.preprocess_mode,
    }
    _job_json_path(name, predict_job_id).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cmd = [
        sys.executable,
        str(_WORKER),
        "--job-json", str(_job_json_path(name, predict_job_id)),
        "--inputs-dir", str(source_dir),
        "--predict-dir", str(pred_dir),
        "--project-dir", str(proj_dir),
        "--weight", str(weight),
        "--conf", str(req.conf),
        "--iou", str(req.iou),
        "--imgsz", str(req.imgsz),
        "--device", req.device,
    ]
    if req.save_txt:
        cmd.append("--save-txt")
    if req.save_conf:
        cmd.append("--save-conf")

    log_f = log_path.open("a", encoding="utf-8")
    try:
        subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, cwd=str(proj_dir))
    finally:
        log_f.close()

    return PredictJobStartResponse(
        project_name=name,
        predict_job_id=predict_job_id,
        status="queued",
        prediction_path=rel_pred,
        log_path=f"{rel_pred}/predict.log",
    )


def get_job(name: str, predict_job_id: str) -> PredictJobInfo:
    _require_project(name)
    job = _read_job(name, predict_job_id)
    if job is None:
        raise PredictNotFoundError(f"推論ジョブ '{predict_job_id}' が見つかりません。")
    return PredictJobInfo(project_name=name, **job)


def list_jobs(name: str) -> PredictJobListResponse:
    _require_project(name)
    root = paths.predictions_dir(name)
    jobs: list[PredictJobInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            job = _read_job(name, child.name)
            if job is not None:
                jobs.append(PredictJobInfo(project_name=name, **job))
    return PredictJobListResponse(project_name=name, jobs=jobs)


def get_logs(name: str, predict_job_id: str) -> PredictLogResponse:
    _require_project(name)
    pred_dir = paths.predict_job_dir(name, predict_job_id)
    if not pred_dir.exists():
        raise PredictNotFoundError(f"推論ジョブ '{predict_job_id}' が見つかりません。")
    log_path = pred_dir / "predict.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return PredictLogResponse(predict_job_id=predict_job_id, log=log)


def get_results(name: str, predict_job_id: str) -> PredictResultsResponse:
    _require_project(name)
    pred_dir = paths.predict_job_dir(name, predict_job_id)
    if not pred_dir.exists():
        raise PredictNotFoundError(f"推論ジョブ '{predict_job_id}' が見つかりません。")
    results_json = pred_dir / "results.json"
    if not results_json.exists():
        # まだ生成されていない（queued/running/failed）
        return PredictResultsResponse(
            project_name=name,
            predict_job_id=predict_job_id,
            image_count=0,
            detection_count=0,
            results=[],
        )

    data = json.loads(results_json.read_text(encoding="utf-8-sig"))
    items: list[PredictResultItem] = []
    for r in data.get("results", []):
        image_name = r.get("image_name", "")
        items.append(
            PredictResultItem(
                image_id=r.get("image_id", ""),
                image_name=image_name,
                result_image_url=(
                    f"/api/projects/{name}/predict-jobs/{predict_job_id}/images/{image_name}"
                    if image_name
                    else None
                ),
                detections=[Detection(**d) for d in r.get("detections", [])],
            )
        )
    return PredictResultsResponse(
        project_name=name,
        predict_job_id=predict_job_id,
        image_count=data.get("image_count", len(items)),
        detection_count=data.get("detection_count", 0),
        results=items,
    )


def resolve_result_image(name: str, predict_job_id: str, filename: str) -> Path:
    """推論結果画像の実パスを安全に解決する（パストラバーサル対策）。"""
    _require_project(name)
    pred_dir = paths.predict_job_dir(name, predict_job_id)
    if not pred_dir.exists():
        raise PredictNotFoundError(f"推論ジョブ '{predict_job_id}' が見つかりません。")

    if filename != Path(filename).name or filename in ("", ".", ".."):
        raise PredictValidationError("不正なファイル名です。")
    if Path(filename).suffix.lower() not in _IMAGE_EXTS:
        raise PredictValidationError("画像ファイル（jpg/jpeg/png）のみ配信できます。")

    images_dir = (pred_dir / "outputs" / "images").resolve()
    target = (images_dir / filename).resolve()
    if images_dir not in target.parents:
        raise PredictValidationError("不正なファイルパスです。")
    if not target.is_file():
        raise PredictNotFoundError(f"結果画像 '{filename}' が見つかりません。")
    return target
