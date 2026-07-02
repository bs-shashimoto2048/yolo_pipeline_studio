"""実験履歴 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.experiment import ExperimentDetailResponse, ExperimentListResponse
from ..services import experiment_service
from ..services.experiment_service import ExperimentNotFoundError
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/experiments", tags=["experiments"])


@router.get("", response_model=ExperimentListResponse)
def list_experiments(name: str) -> ExperimentListResponse:
    try:
        return experiment_service.list_experiments(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{experiment_id}", response_model=ExperimentDetailResponse)
def get_experiment(name: str, experiment_id: str) -> ExperimentDetailResponse:
    try:
        return experiment_service.get_experiment(name, experiment_id)
    except (ExperimentNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
