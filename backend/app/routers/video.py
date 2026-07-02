"""映像（カメラ）推論 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..schemas.common import MessageResponse
from ..schemas.video import (
    CameraListResponse,
    VideoJobCreate,
    VideoJobInfo,
    VideoJobListResponse,
)
from ..services import video_service
from ..services.video_service import (
    VideoConflictError,
    VideoNotFoundError,
    VideoValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}", tags=["video"])


@router.get("/cameras", response_model=CameraListResponse)
def list_cameras(name: str) -> CameraListResponse:
    return CameraListResponse(cameras=video_service.list_cameras())


@router.get("/video-jobs", response_model=VideoJobListResponse)
def list_video_jobs(name: str) -> VideoJobListResponse:
    try:
        return video_service.list_jobs(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/video-jobs", response_model=VideoJobInfo, status_code=201)
def start_video_job(name: str, payload: VideoJobCreate) -> VideoJobInfo:
    try:
        return video_service.start_job(name, payload)
    except VideoConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except VideoValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (VideoNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/video-jobs/{vid}", response_model=VideoJobInfo)
def get_video_job(name: str, vid: str) -> VideoJobInfo:
    try:
        return video_service.get_job(name, vid)
    except (VideoNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/video-jobs/{vid}/stop", response_model=VideoJobInfo)
def stop_video_job(name: str, vid: str) -> VideoJobInfo:
    try:
        return video_service.stop_job(name, vid)
    except (VideoNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/video-jobs/{vid}/stream")
def stream_video_job(name: str, vid: str) -> StreamingResponse:
    try:
        # 存在確認（404を早期に返す）
        video_service.latest_frame_path(name, vid)
    except (VideoNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return StreamingResponse(
        video_service.mjpeg_generator(name, vid),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
