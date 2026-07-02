"""ラベル品質チェック API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.label_validation import LabelValidationResponse
from ..services import label_validation_service
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/labels", tags=["labels"])


@router.post("/validate", response_model=LabelValidationResponse)
def validate_labels(name: str) -> LabelValidationResponse:
    try:
        return label_validation_service.validate_labels(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
