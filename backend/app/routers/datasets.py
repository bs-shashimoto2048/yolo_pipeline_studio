"""データセット作成・一覧 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.dataset import (
    DatasetCreate,
    DatasetCreateResponse,
    DatasetListResponse,
)
from ..services import dataset_service
from ..services.dataset_service import (
    DatasetConflictError,
    DatasetValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/datasets", tags=["datasets"])


@router.get("", response_model=DatasetListResponse)
def list_datasets(name: str) -> DatasetListResponse:
    try:
        return dataset_service.list_datasets(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=DatasetCreateResponse, status_code=201)
def create_dataset(name: str, payload: DatasetCreate) -> DatasetCreateResponse:
    try:
        return dataset_service.create_dataset(name, payload)
    except DatasetConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except DatasetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
