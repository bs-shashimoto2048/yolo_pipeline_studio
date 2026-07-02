"""YOLO学習ジョブ基盤。

HTTPリクエスト内で model.train() を直接実行せず、subprocess.Popen で
workers/train_worker.py を起動する。これにより:
- HTTPリクエストをブロックしない
- ログをファイル(train.log)へ流せる
- 学習プロセスをFastAPI本体から分離できる

job.json を runs/train/{job_id} に保存し、状態管理に使う。
パスは pathlib、返却する相対パスはPOSIX区切り。
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

import yaml

from ..core import paths
from ..schemas.training import (
    TrainJobCreate,
    TrainJobInfo,
    TrainJobListResponse,
    TrainJobStartResponse,
    TrainLogLine,
    TrainLogResponse,
)
from . import augmentation_service, log_utils, project_service
from .augmentation_service import AugmentationValidationError
from .project_service import ProjectError, project_exists

# backend/app/services/training_service.py → backend/workers/train_worker.py
_WORKER = Path(__file__).resolve().parents[2] / "workers" / "train_worker.py"

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")


class TrainError(Exception):
    """学習ジョブ操作の業務エラー。"""


class TrainNotFoundError(TrainError):
    """対象が見つからない（HTTP 404相当）。"""


class TrainValidationError(TrainError):
    """事前チェック失敗（HTTP 400相当）。"""


class TrainConflictError(TrainError):
    """同名ジョブの衝突（HTTP 409相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _safe_rmtree(path: Path) -> None:
    """既存ジョブディレクトリを削除する。

    Windowsでは、直前のワーカープロセスが train.log 等のハンドルを解放する
    までの短時間 PermissionError(WinError 32) になることがあるため、数回リトライ
    する。それでも消えない場合（実行中の可能性が高い）は TrainConflictError。
    """

    def _on_error(func, p, _exc):  # 読み取り専用属性を外して再試行
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    last_err: Exception | None = None
    for attempt in range(6):
        try:
            shutil.rmtree(path, onerror=_on_error)
            if not path.exists():
                return
        except OSError as e:  # noqa: PERF203
            last_err = e
        if not path.exists():
            return
        time.sleep(0.3)
    raise TrainConflictError(
        "既存ジョブの削除に失敗しました（学習プロセスが実行中の可能性があります）。"
        f" 詳細: {last_err!r}"
    )


def _count_images(d: Path) -> int:
    if not d.exists():
        return 0
    return sum(
        1 for p in d.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    )


def _job_json_path(name: str, job_id: str) -> Path:
    return paths.train_job_dir(name, job_id) / "job.json"


def _prepare_data_train_yaml(ds_dir: Path) -> Path:
    """学習用の data_train.yaml を生成する（既存 data.yaml は破壊しない）。

    Ultralytics は相対 `path` を自身の datasets_dir 基準で解決してしまうため、
    `path` を必ずデータセットの絶対パス(POSIX)へ正規化して書き出す。
    train/val/test/names は元の data.yaml を踏襲する。
    """
    src = ds_dir / "data.yaml"
    data: dict = {}
    if src.exists():
        try:
            data = yaml.safe_load(src.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError:
            data = {}
    data["path"] = ds_dir.resolve().as_posix()
    data.setdefault("train", "images/train")
    data.setdefault("val", "images/val")
    data.setdefault("test", "images/test")
    out = ds_dir / "data_train.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return out


def _validate_dataset_paths(ds_dir: Path) -> None:
    """学習前に train/val の実在と画像枚数、labels の存在を検証する（400用）。"""
    train_img = ds_dir / "images" / "train"
    val_img = ds_dir / "images" / "val"
    if not train_img.exists():
        raise TrainValidationError(
            f"data.yaml の train パスが存在しません: {train_img.resolve().as_posix()}。"
            "データセットを再作成してください。"
        )
    if not val_img.exists():
        raise TrainValidationError(
            f"data.yaml の val パスが存在しません: {val_img.resolve().as_posix()}。"
            "データセットを再作成してください。"
        )
    if _count_images(train_img) < 1:
        raise TrainValidationError("train画像が1枚もありません。")
    if _count_images(val_img) < 1:
        raise TrainValidationError("val画像が1枚もありません。")
    if not (ds_dir / "labels" / "train").exists():
        raise TrainValidationError("labels/train が存在しません。データセットを再作成してください。")
    if not (ds_dir / "labels" / "val").exists():
        raise TrainValidationError("labels/val が存在しません。データセットを再作成してください。")


def _read_job(name: str, job_id: str) -> dict | None:
    p = _job_json_path(name, job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def start_job(name: str, req: TrainJobCreate) -> TrainJobStartResponse:
    _require_project(name)

    if not paths.is_valid_project_name(req.job_name):
        raise TrainValidationError(
            "job_name は英数・アンダースコア・ハイフンのみ使用できます。"
        )

    # タスク種別（未指定ならプロジェクトの task を使用）
    task = req.task or project_service.get_task(name)
    if task not in project_service.VALID_TASKS:
        raise TrainValidationError(
            f"task は {' / '.join(project_service.VALID_TASKS)} のいずれかです。"
        )

    # --- 事前チェック ---
    ds_dir = paths.dataset_dir(name, req.dataset_name)
    if not ds_dir.exists():
        raise TrainNotFoundError(
            f"データセット '{req.dataset_name}' が見つかりません。"
        )
    data_yaml = ds_dir / "data.yaml"
    if not data_yaml.exists():
        raise TrainValidationError("data.yaml が存在しません。")
    # train/val パスを事前検証（分かりやすく失敗させる）
    _validate_dataset_paths(ds_dir)
    # Ultralytics 実行用に path を絶対パス化した data_train.yaml を用意（既存data.yaml非破壊）
    data_train_yaml = _prepare_data_train_yaml(ds_dir)

    # 学習時オーギュメンテーションの解決（未指定なら standard）
    try:
        aug_preset, aug_params = augmentation_service.resolve(
            name, req.augmentation_preset, req.augmentation_params
        )
    except AugmentationValidationError as e:
        raise TrainValidationError(str(e)) from e

    job_id = req.job_name
    run_dir = paths.train_job_dir(name, job_id)
    if run_dir.exists():
        if not req.overwrite:
            raise TrainConflictError(
                f"学習ジョブ '{job_id}' は既に存在します。"
            )
        _safe_rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    proj_dir = paths.project_dir(name)
    rel_run = run_dir.relative_to(proj_dir).as_posix()
    log_path = run_dir / "train.log"
    log_path.touch()  # ログ取得APIが即座に動くように空ファイルを用意

    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "job_id": job_id,
        "job_name": req.job_name,
        "dataset_name": req.dataset_name,
        "task": task,
        "model": req.model,
        "epochs": req.epochs,
        "imgsz": req.imgsz,
        "batch": req.batch,
        "device": req.device,
        "workers": req.workers,
        "patience": req.patience,
        "seed": req.seed,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "return_code": None,
        "run_path": rel_run,
        "best_model_path": None,
        "last_model_path": None,
        "results_csv_path": None,
        "message": "queued",
        "augmentation_preset": aug_preset,
        "augmentation_params": aug_params,
    }
    _job_json_path(name, job_id).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- worker をサブプロセスで起動（ノンブロッキング）---
    cmd = [
        sys.executable,
        str(_WORKER),
        "--job-json", str(_job_json_path(name, job_id)),
        "--data-yaml", str(data_train_yaml),
        "--run-dir", str(run_dir),
        "--project-dir", str(proj_dir),
        "--model", req.model,
        "--epochs", str(req.epochs),
        "--imgsz", str(req.imgsz),
        "--batch", str(req.batch),
        "--device", req.device,
        "--workers", str(req.workers),
        "--patience", str(req.patience),
        "--seed", str(req.seed),
    ]
    # 子プロセスの出力を UTF-8 に固定（Windows CP932 による文字化け防止）
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=str(proj_dir),
            env=env,
        )
    finally:
        # 子プロセスは自身のOSハンドルを保持するので親側は閉じてよい
        log_f.close()

    return TrainJobStartResponse(
        project_name=name,
        job_id=job_id,
        job_name=req.job_name,
        status="queued",
        run_path=rel_run,
        log_path=f"{rel_run}/train.log",
    )


def get_job(name: str, job_id: str) -> TrainJobInfo:
    _require_project(name)
    job = _read_job(name, job_id)
    if job is None:
        raise TrainNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")
    return TrainJobInfo(project_name=name, **job)


def list_jobs(name: str) -> TrainJobListResponse:
    _require_project(name)
    root = paths.train_runs_dir(name)
    jobs: list[TrainJobInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            job = _read_job(name, child.name)
            if job is not None:
                jobs.append(TrainJobInfo(project_name=name, **job))
    return TrainJobListResponse(project_name=name, jobs=jobs)


def get_logs(name: str, job_id: str) -> TrainLogResponse:
    _require_project(name)
    run_dir = paths.train_job_dir(name, job_id)
    if not run_dir.exists():
        raise TrainNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")
    log_path = run_dir / "train.log"
    raw = log_path.read_text(encoding="utf-8-sig", errors="replace") if log_path.exists() else ""
    log = log_utils.strip_ansi(raw)
    lines = [TrainLogLine(**d) for d in log_utils.build_lines(log)]
    summary = log_utils.error_summary(log)
    # job.json の message に分かりやすい要約があればそれも優先候補に
    if summary is None:
        job = _read_job(name, job_id)
        if job and job.get("status") == "failed" and job.get("message"):
            summary = job["message"]
    return TrainLogResponse(job_id=job_id, log=log, lines=lines, error_summary=summary)
