"""レポート API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas.report import (
    ReportCreate,
    ReportDetailResponse,
    ReportGenerateResponse,
    ReportListResponse,
)
from ..services import report_service
from ..services.report_service import (
    ReportNotFoundError,
    ReportValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
def list_reports(name: str) -> ReportListResponse:
    try:
        return report_service.list_reports(name)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=ReportGenerateResponse, status_code=201)
def generate(name: str, payload: ReportCreate) -> ReportGenerateResponse:
    try:
        return report_service.generate(name, payload)
    except ReportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(name: str, report_id: str) -> ReportDetailResponse:
    try:
        record = report_service.get_report(name, report_id)
    except ReportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ReportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ReportDetailResponse(
        project_name=name,
        report_id=record.get("report_id", report_id),
        content=record.get("content", {}),
    )


@router.get("/{report_id}/download")
def download(name: str, report_id: str, format: str = "markdown") -> FileResponse:
    try:
        path = report_service.resolve_download(name, report_id, format)
    except ReportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ReportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    media = "text/markdown" if format == "markdown" else "application/json"
    return FileResponse(path, media_type=media, filename=path.name)
