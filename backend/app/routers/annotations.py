"""アノテーション（YOLO形式ラベル）取得・保存 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.annotation import (
    AnnotationGetResponse,
    AnnotationSaveRequest,
    AnnotationSaveResponse,
)
from ..services import annotation_service
from ..services.annotation_service import (
    AnnotationError,
    AnnotationValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(
    prefix="/api/projects/{name}/images/{image_id}/annotations",
    tags=["annotations"],
)


@router.get("", response_model=AnnotationGetResponse)
def get_annotations(name: str, image_id: str) -> AnnotationGetResponse:
    try:
        data = annotation_service.get_annotations(name, image_id)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AnnotationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return AnnotationGetResponse(**data)


@router.put("", response_model=AnnotationSaveResponse)
def save_annotations(
    name: str, image_id: str, payload: AnnotationSaveRequest
) -> AnnotationSaveResponse:
    try:
        data = annotation_service.save_annotations(
            name, image_id, payload.annotations
        )
    except AnnotationValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AnnotationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return AnnotationSaveResponse(**data)
