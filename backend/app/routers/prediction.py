"""推論ジョブ API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas.prediction import (
    PredictJobCreate,
    PredictJobInfo,
    PredictJobListResponse,
    PredictJobStartResponse,
    PredictLogResponse,
    PredictResultsResponse,
)
from ..services import prediction_service
from ..services.prediction_service import (
    PredictConflictError,
    PredictNotFoundError,
    PredictValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/predict-jobs", tags=["prediction"])


@router.get("", response_model=PredictJobListResponse)
def list_jobs(name: str) -> PredictJobListResponse:
    try:
        return prediction_service.list_jobs(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=PredictJobStartResponse, status_code=201)
def start_job(name: str, payload: PredictJobCreate) -> PredictJobStartResponse:
    try:
        return prediction_service.start_job(name, payload)
    except PredictConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except PredictValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (PredictNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{predict_job_id}", response_model=PredictJobInfo)
def get_job(name: str, predict_job_id: str) -> PredictJobInfo:
    try:
        return prediction_service.get_job(name, predict_job_id)
    except (PredictNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{predict_job_id}/logs", response_model=PredictLogResponse)
def get_logs(name: str, predict_job_id: str) -> PredictLogResponse:
    try:
        return prediction_service.get_logs(name, predict_job_id)
    except (PredictNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{predict_job_id}/results", response_model=PredictResultsResponse)
def get_results(name: str, predict_job_id: str) -> PredictResultsResponse:
    try:
        return prediction_service.get_results(name, predict_job_id)
    except (PredictNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{predict_job_id}/images/{filename}")
def get_result_image(name: str, predict_job_id: str, filename: str) -> FileResponse:
    try:
        path = prediction_service.resolve_result_image(name, predict_job_id, filename)
    except PredictValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (PredictNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path)
