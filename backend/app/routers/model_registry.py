"""モデル管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.model_registry import (
    ModelDetailResponse,
    ModelListResponse,
    SelectedModelResponse,
    SelectModelRequest,
)
from ..services import model_registry_service
from ..services.model_registry_service import (
    ModelNotFoundError,
    ModelValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/models", tags=["models"])


@router.get("", response_model=ModelListResponse)
def list_models(name: str) -> ModelListResponse:
    try:
        return model_registry_service.list_models(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/selected", response_model=SelectedModelResponse)
def get_selected(name: str) -> SelectedModelResponse:
    try:
        return model_registry_service.get_selected(name)
    except (ModelNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/selected", response_model=SelectedModelResponse)
def set_selected(name: str, payload: SelectModelRequest) -> SelectedModelResponse:
    try:
        return model_registry_service.set_selected(name, payload)
    except ModelValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ModelNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{train_job_id}/{weight_type}", response_model=ModelDetailResponse)
def get_model(name: str, train_job_id: str, weight_type: str) -> ModelDetailResponse:
    try:
        return model_registry_service.get_model(name, train_job_id, weight_type)
    except ModelValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ModelNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
