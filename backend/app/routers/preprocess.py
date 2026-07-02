"""前処理 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas.preprocess import (
    PreprocessInfoResponse,
    PreprocessPreviewResponse,
    PreprocessRunResponse,
    PreprocessSettings,
)
from ..services import preprocess_service
from ..services.preprocess_service import (
    PreprocessConflictError,
    PreprocessValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/preprocess", tags=["preprocess"])


@router.get("", response_model=PreprocessInfoResponse)
def get_info(name: str) -> PreprocessInfoResponse:
    try:
        return preprocess_service.get_info(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/run", response_model=PreprocessRunResponse)
def run(name: str, payload: PreprocessSettings) -> PreprocessRunResponse:
    try:
        return preprocess_service.run(name, payload)
    except PreprocessConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except PreprocessValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/preview", response_model=PreprocessPreviewResponse)
def preview(
    name: str, payload: PreprocessSettings, image_id: str | None = None
) -> PreprocessPreviewResponse:
    try:
        return preprocess_service.preview(name, image_id, payload)
    except PreprocessValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/preview-image/{filename}")
def preview_image(name: str, filename: str) -> FileResponse:
    try:
        path = preprocess_service.preview_image_path(name, filename)
    except PreprocessValidationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path)
