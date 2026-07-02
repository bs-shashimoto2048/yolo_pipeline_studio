"""映像（カメラ）推論関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class CameraInfo(BaseModel):
    index: int
    label: str


class CameraListResponse(BaseModel):
    cameras: list[CameraInfo]


class VideoJobCreate(BaseModel):
    video_job_name: str
    train_job_id: str
    weight_type: str = "best"
    camera_index: int = 0
    video_fps: int = 15  # キャプチャ/表示FPS
    infer_fps: int = 5   # 推論FPS（video_fps以下）
    conf: float = 0.25
    iou: float = 0.7
    imgsz: int = 640
    device: str = "auto"
    preprocess_mode: str = "none"  # none | latest
    overwrite: bool = False


class VideoJobInfo(BaseModel):
    project_name: str | None = None
    video_job_id: str
    train_job_id: str | None = None
    weight_type: str | None = None
    camera_index: int | None = None
    video_fps: int | None = None
    infer_fps: int | None = None
    preprocess_mode: str | None = None
    status: str = "unknown"  # queued | running | stopped | failed | completed
    message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    stream_url: str | None = None


class VideoJobListResponse(BaseModel):
    project_name: str
    jobs: list[VideoJobInfo]
