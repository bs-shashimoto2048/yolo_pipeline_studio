"""ONNXエクスポートジョブ基盤。

学習ジョブと同様、HTTP内で export を実行せず subprocess.Popen で
workers/onnx_export_worker.py を起動する（ノンブロッキング・ログをファイルへ）。
出力は exports/onnx/{export_job_id}/（job.json / export.log / model.onnx / metadata.json）。

ONNX export には ultralytics が必要（requirements-train.txt）。通常起動用
requirements.txt には ONNX/torch/ultralytics を追加しない。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import paths
from ..schemas.onnx_export import (
    OnnxExportCreate,
    OnnxExportInfo,
    OnnxExportListResponse,
    OnnxExportLogResponse,
    OnnxExportStartResponse,
)
from ..schemas.training import TrainLogLine
from . import log_utils, preprocess_service, project_service
from .project_service import ProjectError, project_exists

_WORKER = Path(__file__).resolve().parents[2] / "workers" / "onnx_export_worker.py"
_WEIGHTS = ("best", "last")
_DEVICES = ("auto", "cpu", "cuda")


class OnnxExportError(Exception):
    """ONNXエクスポートの業務エラー。"""


class OnnxExportNotFoundError(OnnxExportError):
    """対象が見つからない（404相当）。"""


class OnnxExportValidationError(OnnxExportError):
    """事前チェック失敗（400相当）。"""


class OnnxExportConflictError(OnnxExportError):
    """同名ジョブの衝突（409相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _read_train_job(name: str, train_job_id: str) -> dict:
    p = paths.train_job_dir(name, train_job_id) / "job.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def _job_json_path(name: str, export_job_id: str) -> Path:
    return paths.onnx_export_dir(name, export_job_id) / "job.json"


def _read_job(name: str, export_job_id: str) -> dict | None:
    p = _job_json_path(name, export_job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def _export_path_rel(name: str, export_job_id: str) -> str:
    return paths.onnx_export_dir(name, export_job_id).relative_to(paths.project_dir(name)).as_posix()


def _safe_rmtree(path: Path) -> None:
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.3)
    raise OnnxExportConflictError(
        "既存エクスポートの削除に失敗しました（処理が実行中の可能性があります）。"
    )


def start_export(name: str, req: OnnxExportCreate) -> OnnxExportStartResponse:
    _require_project(name)

    if req.weight_type not in _WEIGHTS:
        raise OnnxExportValidationError("weight_type は best または last です。")
    if not (11 <= req.opset <= 18):
        raise OnnxExportValidationError("opset は 11〜18 です。")
    if req.imgsz is not None and not (32 <= req.imgsz <= 4096):
        raise OnnxExportValidationError("imgsz は 32〜4096 です。")
    if req.device not in _DEVICES:
        raise OnnxExportValidationError("device は auto / cpu / cuda です。")

    train_dir = paths.train_job_dir(name, req.train_job_id)
    if not train_dir.exists():
        raise OnnxExportNotFoundError(f"学習ジョブ '{req.train_job_id}' が見つかりません。")
    weight = paths.model_weight_path(name, req.train_job_id, req.weight_type)
    if not weight.exists():
        raise OnnxExportNotFoundError(f"重み '{req.weight_type}.pt' が見つかりません。")

    train_job = _read_train_job(name, req.train_job_id)
    imgsz = req.imgsz or train_job.get("imgsz") or 640
    task = project_service.get_task(name)

    export_job_id = req.export_job_name or f"onnx_{req.train_job_id}_{req.weight_type}"
    if not paths.is_valid_project_name(export_job_id):
        raise OnnxExportValidationError(
            "export_job_name は英数・アンダースコア・ハイフンのみ使用できます。"
        )

    export_dir = paths.onnx_export_dir(name, export_job_id)
    if export_dir.exists():
        if not req.overwrite:
            raise OnnxExportConflictError(
                f"ONNXエクスポート '{export_job_id}' は既に存在します。"
            )
        _safe_rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    proj_dir = paths.project_dir(name)
    src_weight_rel = weight.relative_to(proj_dir).as_posix()
    preprocess_required = preprocess_service.load_latest_settings(name) is not None
    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "export_job_id": export_job_id,
        "project_name": name,
        "train_job_id": req.train_job_id,
        "weight_type": req.weight_type,
        "source_weight_path": src_weight_rel,
        "task": task,
        "format": "onnx",
        "imgsz": imgsz,
        "opset": req.opset,
        "simplify": req.simplify,
        "dynamic": req.dynamic,
        "half": req.half,
        "device": req.device,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "return_code": None,
        "onnx_path": None,
        "message": "queued",
    }
    _job_json_path(name, export_job_id).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_path = export_dir / "export.log"
    log_path.touch()

    cmd = [
        sys.executable, str(_WORKER),
        "--job-json", str(_job_json_path(name, export_job_id)),
        "--weight", str(weight),
        "--export-dir", str(export_dir),
        "--project-dir", str(proj_dir),
        "--imgsz", str(imgsz),
        "--opset", str(req.opset),
        "--device", req.device,
        "--task", task,
        "--source-weight-rel", src_weight_rel,
        "--preprocess-required", "1" if preprocess_required else "0",
    ]
    if req.simplify:
        cmd.append("--simplify")
    if req.dynamic:
        cmd.append("--dynamic")
    if req.half:
        cmd.append("--half")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, env=env)
    finally:
        log_f.close()

    return OnnxExportStartResponse(
        project_name=name,
        export_job_id=export_job_id,
        status="queued",
        export_path=_export_path_rel(name, export_job_id),
        log_path=f"{_export_path_rel(name, export_job_id)}/export.log",
    )


def get_export(name: str, export_job_id: str) -> OnnxExportInfo:
    _require_project(name)
    job = _read_job(name, export_job_id)
    if job is None:
        raise OnnxExportNotFoundError(f"ONNXエクスポート '{export_job_id}' が見つかりません。")
    return OnnxExportInfo(export_path=_export_path_rel(name, export_job_id), **job)


def list_exports(name: str) -> OnnxExportListResponse:
    _require_project(name)
    root = paths.onnx_exports_dir(name)
    exports: list[OnnxExportInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "job.json").exists():
                job = _read_job(name, child.name)
                if job is not None:
                    exports.append(
                        OnnxExportInfo(export_path=_export_path_rel(name, child.name), **job)
                    )
    return OnnxExportListResponse(project_name=name, exports=exports)


def get_logs(name: str, export_job_id: str) -> OnnxExportLogResponse:
    _require_project(name)
    export_dir = paths.onnx_export_dir(name, export_job_id)
    if not export_dir.exists():
        raise OnnxExportNotFoundError(f"ONNXエクスポート '{export_job_id}' が見つかりません。")
    log_path = export_dir / "export.log"
    raw = log_path.read_text(encoding="utf-8-sig", errors="replace") if log_path.exists() else ""
    log = log_utils.strip_ansi(raw)
    lines = [TrainLogLine(**d) for d in log_utils.build_lines(log)]
    summary = log_utils.error_summary(log)
    if summary is None:
        job = _read_job(name, export_job_id)
        if job and job.get("status") == "failed" and job.get("message"):
            summary = job["message"]
    return OnnxExportLogResponse(export_job_id=export_job_id, log=log, lines=lines, error_summary=summary)


def download_path(name: str, export_job_id: str) -> Path:
    """model.onnx の実パスを返す（ダウンロード用）。"""
    _require_project(name)
    if not paths.is_valid_project_name(export_job_id):
        raise OnnxExportValidationError("不正な export_job_id です。")
    export_dir = paths.onnx_export_dir(name, export_job_id)
    if not export_dir.exists():
        raise OnnxExportNotFoundError(f"ONNXエクスポート '{export_job_id}' が見つかりません。")
    onnx = export_dir / "model.onnx"
    if not onnx.exists():
        raise OnnxExportNotFoundError("model.onnx がまだ生成されていません（エクスポート未完了/失敗）。")
    return onnx
