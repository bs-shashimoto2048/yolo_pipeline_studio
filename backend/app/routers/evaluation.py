"""学習結果評価 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas.evaluation import EvaluationResponse, MetricsResponse
from ..services import evaluation_service
from ..services.evaluation_service import (
    EvaluationBadRequestError,
    EvaluationNotFoundError,
)
from ..services.project_service import ProjectError

router = APIRouter(
    prefix="/api/projects/{name}/train-jobs/{job_id}", tags=["evaluation"]
)


@router.get("/evaluation", response_model=EvaluationResponse)
def get_evaluation(name: str, job_id: str) -> EvaluationResponse:
    try:
        return evaluation_service.get_evaluation(name, job_id)
    except (EvaluationNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(name: str, job_id: str) -> MetricsResponse:
    try:
        return evaluation_service.get_metrics(name, job_id)
    except (EvaluationNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/artifacts/{filename}")
def get_artifact(name: str, job_id: str, filename: str) -> FileResponse:
    try:
        path = evaluation_service.resolve_artifact(name, job_id, filename)
    except EvaluationBadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (EvaluationNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path)
