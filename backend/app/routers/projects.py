"""プロジェクト管理 + クラス設計 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.cls import ClassListResponse, ClassListUpdate
from ..schemas.project import ProjectCreate, ProjectSummary
from ..schemas.common import MessageResponse
from ..services import class_service, project_service
from ..services.project_service import ProjectConflictError, ProjectError

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
def list_projects() -> list[ProjectSummary]:
    return project_service.list_projects()


@router.post("", response_model=ProjectSummary, status_code=201)
def create_project(payload: ProjectCreate) -> ProjectSummary:
    try:
        return project_service.create_project(
            payload.name, payload.description, payload.task
        )
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{name}", response_model=ProjectSummary)
def get_project(name: str) -> ProjectSummary:
    try:
        return project_service.get_summary(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{name}", response_model=MessageResponse)
def delete_project(name: str) -> MessageResponse:
    try:
        project_service.delete_project(name)
    except ProjectConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MessageResponse(message=f"プロジェクト '{name}' を削除しました。")


@router.get("/{name}/classes", response_model=ClassListResponse)
def get_classes(name: str) -> ClassListResponse:
    try:
        return ClassListResponse(classes=class_service.get_classes(name))
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{name}/classes", response_model=ClassListResponse)
def save_classes(name: str, payload: ClassListUpdate) -> ClassListResponse:
    try:
        return ClassListResponse(
            classes=class_service.save_classes(name, payload.to_inputs())
        )
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
