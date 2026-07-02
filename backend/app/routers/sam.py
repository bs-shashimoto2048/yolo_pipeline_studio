"""SAM支援アノテーション API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.sam import SamProposeRequest, SamProposeResponse, SamSettings
from ..services import sam_service
from ..services.sam_service import (
    SamDependencyError,
    SamNotFoundError,
    SamRuntimeError,
    SamValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}", tags=["sam"])


@router.get("/sam/settings", response_model=SamSettings)
def get_sam_settings(name: str) -> SamSettings:
    try:
        return sam_service.get_settings(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/sam/settings", response_model=SamSettings)
def save_sam_settings(name: str, payload: SamSettings) -> SamSettings:
    try:
        return sam_service.save_settings(name, payload)
    except SamValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/images/{image_id}/sam/propose", response_model=SamProposeResponse)
def propose(name: str, image_id: str, payload: SamProposeRequest) -> SamProposeResponse:
    try:
        return sam_service.propose(name, image_id, payload)
    except SamValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SamDependencyError as e:
        # 依存未導入/モデル未取得は利用者が対処可能なので 400（friendly message）
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SamRuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except (SamNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
