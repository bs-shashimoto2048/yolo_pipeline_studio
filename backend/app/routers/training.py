"""YOLO学習ジョブ API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.training import (
    TrainJobCreate,
    TrainJobInfo,
    TrainJobListResponse,
    TrainJobStartResponse,
    TrainLogResponse,
)
from ..services import training_service
from ..services.training_service import (
    TrainConflictError,
    TrainNotFoundError,
    TrainValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/train-jobs", tags=["training"])


@router.get("", response_model=TrainJobListResponse)
def list_jobs(name: str) -> TrainJobListResponse:
    try:
        return training_service.list_jobs(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=TrainJobStartResponse, status_code=201)
def start_job(name: str, payload: TrainJobCreate) -> TrainJobStartResponse:
    try:
        return training_service.start_job(name, payload)
    except TrainConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except TrainValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (TrainNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{job_id}", response_model=TrainJobInfo)
def get_job(name: str, job_id: str) -> TrainJobInfo:
    try:
        return training_service.get_job(name, job_id)
    except (TrainNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{job_id}/logs", response_model=TrainLogResponse)
def get_logs(name: str, job_id: str) -> TrainLogResponse:
    try:
        return training_service.get_logs(name, job_id)
    except (TrainNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
