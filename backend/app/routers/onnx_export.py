"""ONNXエクスポート API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas.onnx_export import (
    OnnxExportCreate,
    OnnxExportInfo,
    OnnxExportListResponse,
    OnnxExportLogResponse,
    OnnxExportStartResponse,
)
from ..services import onnx_export_service
from ..services.onnx_export_service import (
    OnnxExportConflictError,
    OnnxExportNotFoundError,
    OnnxExportValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/onnx-exports", tags=["onnx-export"])


@router.post("", response_model=OnnxExportStartResponse, status_code=201)
def start_export(name: str, payload: OnnxExportCreate) -> OnnxExportStartResponse:
    try:
        return onnx_export_service.start_export(name, payload)
    except OnnxExportConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OnnxExportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OnnxExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("", response_model=OnnxExportListResponse)
def list_exports(name: str) -> OnnxExportListResponse:
    try:
        return onnx_export_service.list_exports(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{export_job_id}", response_model=OnnxExportInfo)
def get_export(name: str, export_job_id: str) -> OnnxExportInfo:
    try:
        return onnx_export_service.get_export(name, export_job_id)
    except (OnnxExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{export_job_id}/logs", response_model=OnnxExportLogResponse)
def get_logs(name: str, export_job_id: str) -> OnnxExportLogResponse:
    try:
        return onnx_export_service.get_logs(name, export_job_id)
    except (OnnxExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{export_job_id}/download")
def download_onnx(name: str, export_job_id: str) -> FileResponse:
    try:
        path = onnx_export_service.download_path(name, export_job_id)
    except OnnxExportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OnnxExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type="application/octet-stream", filename=f"{export_job_id}.onnx")
