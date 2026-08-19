"""画像選別 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.selection import (
    SelectionDeleteResponse,
    SelectionGetResponse,
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


@router.post("/run", response_model=SelectionRunResponse)
def run(name: str, payload: SelectionRunRequest) -> SelectionRunResponse:
    try:
        return selection_service.run(name, payload)
    except SelectionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/images/{image_id}", response_model=SelectionStatusResponse)
def update_status(
    name: str, image_id: str, payload: SelectionStatusUpdate
) -> SelectionStatusResponse:
    try:
        return selection_service.update_status(name, image_id, payload)
    except SelectionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
