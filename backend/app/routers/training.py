"""YOLO学習ジョブ API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import settings
from ..core.identity import UserIdentity, get_current_user
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
    TrainForbiddenError,
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
def start_job(
    name: str,
    payload: TrainJobCreate,
    identity: UserIdentity = Depends(get_current_user),
) -> TrainJobStartResponse:
    try:
        job_id = training_service.prepare_job(name, payload, identity)
        if settings.shared_server_mode:
            # 循環import回避のため遅延import（training_queue_serviceが
            # training_serviceを一方向にimportする構成、Issue #49）。
            from ..services import training_queue_service

            return training_queue_service.enqueue(name, job_id)
        return training_service.launch_job(name, job_id)
    except TrainConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except TrainValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (TrainNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{job_id}/cancel", response_model=TrainJobInfo)
def cancel_job(
    name: str,
    job_id: str,
    identity: UserIdentity = Depends(get_current_user),
) -> TrainJobInfo:
    try:
        if settings.shared_server_mode:
            from ..services import training_queue_service

            return training_queue_service.cancel(name, job_id, identity)
        return training_service.terminate_and_mark_cancelled(name, job_id, identity)
    except TrainForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except TrainConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
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
