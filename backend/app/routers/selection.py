"""画像選別 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.selection import (
    SelectionDeleteResponse,
    SelectionGetResponse,
    SelectionJobStatus,
    SelectionResetResponse,
    SelectionRotateRequest,
    SelectionRotateResponse,
    SelectionRunRequest,
    SelectionRunResponse,
    SelectionStatusResponse,
    SelectionStatusUpdate,
)
from ..services import selection_service
from ..services.selection_service import (
    SelectionConflictError,
    SelectionNotFoundError,
    SelectionValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/selection", tags=["selection"])


@router.get("", response_model=SelectionGetResponse)
def get_selection(name: str) -> SelectionGetResponse:
    try:
        return selection_service.get_selection(name)
    except (SelectionNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/run", response_model=SelectionRunResponse, status_code=202)
def run(name: str, payload: SelectionRunRequest) -> SelectionRunResponse:
    """画像選別の実行を開始する（非同期）。

    7,000枚規模でもHTTPリクエストをブロックしないよう、実際のPIL解析は
    別プロセスのワーカーへ委譲し、ここではジョブを起動して即座に返す。
    進捗・完了は `GET /run/status` をポーリングして確認する。
    """
    try:
        return selection_service.start_run_job(name, payload)
    except SelectionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SelectionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/run/status", response_model=SelectionJobStatus)
def get_run_status(name: str) -> SelectionJobStatus:
    try:
        return selection_service.get_run_job_status(name)
    except (SelectionNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/images/{image_id}", response_model=SelectionStatusResponse)
def update_status(
    name: str, image_id: str, payload: SelectionStatusUpdate
) -> SelectionStatusResponse:
    try:
        return selection_service.update_status(name, image_id, payload)
    except SelectionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SelectionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (SelectionNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/images/{image_id}/reset-to-auto", response_model=SelectionResetResponse)
def reset_to_auto(name: str, image_id: str) -> SelectionResetResponse:
    """manual/unknownな判定を、現在の閾値で再解析した自動判定へ単一画像だけ戻す。"""
    try:
        item = selection_service.reset_to_auto(name, image_id)
        return SelectionResetResponse(item=item)
    except SelectionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SelectionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (SelectionNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/images/{image_id}/rotate", response_model=SelectionRotateResponse)
def rotate_image(
    name: str, image_id: str, payload: SelectionRotateRequest
) -> SelectionRotateResponse:
    try:
        return selection_service.rotate_image(name, image_id, payload.source, payload.angle)
    except SelectionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SelectionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (SelectionNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/images/{image_id}", response_model=SelectionDeleteResponse)
def delete_image(name: str, image_id: str) -> SelectionDeleteResponse:
    """画像を完全に削除する（raw/processed/サムネイル/ラベル/selection.json、元に戻せない）。"""
    try:
        return selection_service.delete_image(name, image_id)
    except SelectionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SelectionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (SelectionNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
