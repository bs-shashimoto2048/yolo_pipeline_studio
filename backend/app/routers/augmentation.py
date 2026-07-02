"""学習時オーギュメンテーション・プリセット API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.augmentation import PresetItem, PresetListResponse, PresetSave
from ..schemas.common import MessageResponse
from ..services import augmentation_service
from ..services.augmentation_service import (
    AugmentationConflictError,
    AugmentationNotFoundError,
    AugmentationValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(
    prefix="/api/projects/{name}/augmentation/presets", tags=["augmentation"]
)


@router.get("", response_model=PresetListResponse)
def list_presets(name: str) -> PresetListResponse:
    try:
        return augmentation_service.list_presets(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{preset_name}", response_model=PresetItem)
def get_preset(name: str, preset_name: str) -> PresetItem:
    try:
        return augmentation_service.get_preset(name, preset_name)
    except (AugmentationNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{preset_name}", response_model=PresetItem)
def save_preset(name: str, preset_name: str, payload: PresetSave) -> PresetItem:
    try:
        return augmentation_service.save_preset(name, preset_name, payload)
    except AugmentationConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except AugmentationValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{preset_name}", response_model=MessageResponse)
def delete_preset(name: str, preset_name: str) -> MessageResponse:
    try:
        augmentation_service.delete_preset(name, preset_name)
    except AugmentationValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (AugmentationNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MessageResponse(message=f"プリセット '{preset_name}' を削除しました。")
