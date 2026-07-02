"""映像（カメラ）推論。

サーバー(=同一PC)に接続されたカメラを OpenCV で開き、別プロセスのワーカーで
前処理＋推論を行い、注釈フレームを live/latest.jpg に書き出す。FastAPI 側は
そのファイルを繰り返し読んで MJPEG (multipart/x-mixed-replace) でライブ配信する。

- video_fps: キャプチャ/表示FPS、infer_fps: 推論FPS（間引き、video_fps以下）
- preprocess_mode=latest なら最新前処理設定を各フレームに適用
- 停止は stop.flag を置く。元画像/processed本体は破壊しない。
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
from ..schemas.video import (
    CameraInfo,
    VideoJobCreate,
    VideoJobInfo,
    VideoJobListResponse,
)
from . import preprocess_service
from .project_service import ProjectError, project_exists

_WORKER = Path(__file__).resolve().parents[2] / "workers" / "predict_video_worker.py"
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class VideoError(Exception):
    pass


class VideoNotFoundError(VideoError):
    """404相当。"""


class VideoValidationError(VideoError):
    """400相当。"""


class VideoConflictError(VideoError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def list_cameras(max_index: int = 5) -> list[CameraInfo]:
    """利用可能なカメラ index を列挙する（OpenCVで 0..max_index-1 を試行）。"""
    cams: list[CameraInfo] = []
    try:
        import cv2  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - 未導入なら空
        return cams
    backend = getattr(cv2, "CAP_DSHOW", 0)  # Windowsでは DSHOW が速い
    for i in range(max_index):
        cap = None
        try:
            cap = cv2.VideoCapture(i, backend) if backend else cv2.VideoCapture(i)
            if cap is not None and cap.isOpened():
                cams.append(CameraInfo(index=i, label=f"Camera {i}"))
        except Exception:  # noqa: BLE001
            pass
        finally:
            if cap is not None:
                cap.release()
    return cams


def _job_json_path(name: str, vid: str) -> Path:
    return paths.video_job_dir(name, vid) / "job.json"


def _read_job(name: str, vid: str) -> dict | None:
    p = _job_json_path(name, vid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def _stream_url(name: str, vid: str) -> str:
    return f"/api/projects/{name}/video-jobs/{vid}/stream"


def start_job(name: str, req: VideoJobCreate) -> VideoJobInfo:
    _require_project(name)
    if not paths.is_valid_project_name(req.video_job_name):
        raise VideoValidationError("video_job_name は英数・アンダースコア・ハイフンのみです。")
    if req.weight_type not in ("best", "last"):
        raise VideoValidationError("weight_type は best または last です。")
    if not (1 <= req.video_fps <= 60):
        raise VideoValidationError("video_fps は 1〜60 です。")
    if not (1 <= req.infer_fps <= req.video_fps):
        raise VideoValidationError("infer_fps は 1〜video_fps の範囲です。")

    train_dir = paths.train_job_dir(name, req.train_job_id)
    if not train_dir.exists():
        raise VideoNotFoundError(f"学習ジョブ '{req.train_job_id}' が見つかりません。")
    weight = train_dir / "weights" / f"{req.weight_type}.pt"
    if not weight.exists():
        raise VideoValidationError(
            f"モデル '{req.weight_type}.pt' が見つかりません。"
        )

    if req.preprocess_mode not in ("none", "latest"):
        raise VideoValidationError("preprocess_mode は none または latest です。")
    pre_settings = None
    if req.preprocess_mode == "latest":
        pre_settings = preprocess_service.load_latest_settings(name)
        if pre_settings is None:
            raise VideoValidationError(
                "最新前処理設定がありません（前処理を実行してから 'latest' を選択してください）。"
            )

    vid = req.video_job_name
    vdir = paths.video_job_dir(name, vid)
    if vdir.exists():
        if not req.overwrite:
            raise VideoConflictError(f"映像ジョブ '{vid}' は既に存在します。")
        shutil.rmtree(vdir, ignore_errors=True)
    live = vdir / "live"
    live.mkdir(parents=True, exist_ok=True)

    pre_json = ""
    if pre_settings is not None:
        pre_path = vdir / "preprocess.json"
        pre_path.write_text(pre_settings.model_dump_json(), encoding="utf-8")
        pre_json = str(pre_path)

    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "video_job_id": vid,
        "train_job_id": req.train_job_id,
        "weight_type": req.weight_type,
        "camera_index": req.camera_index,
        "video_fps": req.video_fps,
        "infer_fps": req.infer_fps,
        "preprocess_mode": req.preprocess_mode,
        "conf": req.conf,
        "iou": req.iou,
        "imgsz": req.imgsz,
        "device": req.device,
        "status": "queued",
        "message": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    _job_json_path(name, vid).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_path = vdir / "video.log"
    log_path.touch()

    cmd = [
        sys.executable, str(_WORKER),
        "--job-json", str(_job_json_path(name, vid)),
        "--live-dir", str(live),
        "--weight", str(weight),
        "--backend-dir", str(_BACKEND_DIR),
        "--camera-index", str(req.camera_index),
        "--video-fps", str(req.video_fps),
        "--infer-fps", str(req.infer_fps),
        "--conf", str(req.conf),
        "--iou", str(req.iou),
        "--imgsz", str(req.imgsz),
        "--device", req.device,
    ]
    if pre_json:
        cmd += ["--preprocess-json", pre_json]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, env=env)
    finally:
        log_f.close()

    return get_job(name, vid)


def get_job(name: str, vid: str) -> VideoJobInfo:
    _require_project(name)
    job = _read_job(name, vid)
    if job is None:
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")
    return VideoJobInfo(project_name=name, stream_url=_stream_url(name, vid), **job)


def list_jobs(name: str) -> VideoJobListResponse:
    _require_project(name)
    root = paths.video_jobs_dir(name)
    jobs: list[VideoJobInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "job.json").exists():
                try:
                    jobs.append(get_job(name, child.name))
                except VideoError:
                    pass
    return VideoJobListResponse(project_name=name, jobs=jobs)


def stop_job(name: str, vid: str) -> VideoJobInfo:
    _require_project(name)
    vdir = paths.video_job_dir(name, vid)
    if not vdir.exists():
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")
    (vdir / "stop.flag").write_text("stop", encoding="utf-8")
    job = _read_job(name, vid) or {}
    if job.get("status") in ("queued", "running"):
        job["status"] = "stopped"
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        job["message"] = "stopped by user"
        _job_json_path(name, vid).write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return get_job(name, vid)


def latest_frame_path(name: str, vid: str) -> Path:
    _require_project(name)
    vdir = paths.video_job_dir(name, vid)
    if not vdir.exists():
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")
    return vdir / "live" / "latest.jpg"


def mjpeg_generator(name: str, vid: str):
    """live/latest.jpg を繰り返し読み、multipart/x-mixed-replace で配信する。"""
    frame_path = latest_frame_path(name, vid)
    boundary = b"--frame"
    interval = 0.1
    job = _read_job(name, vid) or {}
    fps = job.get("video_fps") or 10
    interval = max(0.03, 1.0 / float(fps))
    deadline = time.time() + 1800  # 安全のため最大30分
    while time.time() < deadline:
        cur = _read_job(name, vid) or {}
        if cur.get("status") in ("stopped", "failed", "completed"):
            # 最終フレームを1枚返して終了
            if frame_path.exists():
                data = frame_path.read_bytes()
                yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            break
        if frame_path.exists():
            try:
                data = frame_path.read_bytes()
                if data:
                    yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            except OSError:
                pass
        time.sleep(interval)
