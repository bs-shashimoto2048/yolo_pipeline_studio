"""カメラ/URL映像からの静止画撮影 API（プロジェクト準備・画像取り込み用）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from ..schemas.capture import (
    CaptureNowResult,
    CaptureSessionCreate,
    CaptureSessionInfo,
    CaptureSessionListResponse,
    CaptureSourceCreate,
    CaptureSourceInfo,
    CaptureSourceListResponse,
    CaptureSourceUpdate,
)
from ..services import capture_service
from ..services.capture_service import (
    CaptureConflictError,
    CaptureNotFoundError,
    CaptureValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}", tags=["capture"])


@router.get("/capture-sources", response_model=CaptureSourceListResponse)
def list_capture_sources(name: str) -> CaptureSourceListResponse:
    """プロジェクトに保存済みの撮影ソース（カメラ/URLの定義）一覧。"""
    try:
        return capture_service.list_source_configs(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/capture-sources", response_model=CaptureSourceInfo, status_code=201)
def add_capture_source(name: str, payload: CaptureSourceCreate) -> CaptureSourceInfo:
    try:
        return capture_service.add_source_config(name, payload)
    except CaptureValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/capture-sources/{source_id}", response_model=CaptureSourceInfo)
def update_capture_source(name: str, source_id: str, payload: CaptureSourceUpdate) -> CaptureSourceInfo:
    try:
        return capture_service.update_source_config(name, source_id, payload)
    except CaptureValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/capture-sources/{source_id}", status_code=204)
def delete_capture_source(name: str, source_id: str) -> None:
    try:
        capture_service.delete_source_config(name, source_id)
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/capture-sessions", response_model=CaptureSessionListResponse)
def list_capture_sessions(name: str) -> CaptureSessionListResponse:
    try:
        return capture_service.list_sessions(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/capture-sessions", response_model=CaptureSessionInfo, status_code=201)
def start_capture_session(name: str, payload: CaptureSessionCreate) -> CaptureSessionInfo:
    try:
        return capture_service.start_session(name, payload)
    except CaptureConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except CaptureValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/capture-sessions/{sid}", response_model=CaptureSessionInfo)
def get_capture_session(name: str, sid: str) -> CaptureSessionInfo:
    try:
        return capture_service.get_session(name, sid)
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/capture-sessions/{sid}/capture", response_model=CaptureNowResult)
def capture_now(name: str, sid: str) -> CaptureNowResult:
    """「今すぐ撮影」ボタン用。撮影完了まで短時間だけ待って結果を返す。"""
    try:
        return capture_service.capture_now(name, sid)
    except CaptureValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/capture-sessions/{sid}/stop", response_model=CaptureSessionInfo)
def stop_capture_session(name: str, sid: str) -> CaptureSessionInfo:
    try:
        return capture_service.stop_session(name, sid)
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/capture-sessions/{sid}/frame")
def get_capture_frame(name: str, sid: str) -> Response:
    """最新の1フレームを画像として返す（都度取得・接続を保持しないポーリング用）。

    複数ソースを同時にプレビューする画面（撮影ソース一覧）では、MJPEG(multipart)の
    持続接続をソース数だけ張り続けるとブラウザの同時接続数上限（HTTP/1.1では通常
    オリジンあたり6程度）に達し、他のAPI呼び出しが失敗する（`Failed to fetch`）ことがある。
    このエンドポイントは1回のリクエストで完結するため接続をすぐ解放でき、定期的に
    ポーリングする用途（複数ソースの一覧表示）に向く。単一ソースの詳細表示等で
    滑らかな映像が必要な場合は `/stream`（MJPEG）を使う。
    """
    try:
        p = capture_service.latest_frame_path(name, sid)
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not p.exists():
        raise HTTPException(status_code=404, detail="フレームがまだありません。")
    try:
        data = p.read_bytes()
    except OSError as e:
        raise HTTPException(status_code=404, detail="フレームの読み込みに失敗しました。") from e
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/capture-sessions/{sid}/stream")
def stream_capture_session(name: str, sid: str) -> StreamingResponse:
    try:
        capture_service.latest_frame_path(name, sid)  # 存在確認（404を早期に返す）
    except (CaptureNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return StreamingResponse(
        capture_service.mjpeg_generator(name, sid),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
