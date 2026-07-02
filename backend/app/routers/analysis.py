"""誤検出分析 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.analysis import AnalysisRequest, AnalysisResponse
from ..services import analysis_service
from ..services.analysis_service import (
    AnalysisNotFoundError,
    AnalysisValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(
    prefix="/api/projects/{name}/predict-jobs/{predict_job_id}/analysis",
    tags=["analysis"],
)


@router.post("", response_model=AnalysisResponse)
def run_analysis(
    name: str, predict_job_id: str, payload: AnalysisRequest
) -> AnalysisResponse:
    try:
        return analysis_service.run_and_save(
            name, predict_job_id, payload.iou_threshold, payload.conf_threshold
        )
    except AnalysisValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (AnalysisNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("", response_model=AnalysisResponse)
def get_analysis(name: str, predict_job_id: str) -> AnalysisResponse:
    try:
        return analysis_service.get_saved(name, predict_job_id)
    except (AnalysisNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
