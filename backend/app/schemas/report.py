"""レポート関連スキーマ。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ReportCreate(BaseModel):
    report_name: str | None = None
    include_images: bool = False
    include_predictions: bool = True
    include_analysis: bool = True
    format: str = "markdown"  # markdown | json | both


class ReportGenerateResponse(BaseModel):
    project_name: str
    report_id: str
    created_at: str
    markdown_path: str | None = None
    json_path: str


class ReportListItem(BaseModel):
    report_id: str
    created_at: str | None = None
    markdown_path: str | None = None
    json_path: str


class ReportListResponse(BaseModel):
    project_name: str
    reports: list[ReportListItem]


class ReportDetailResponse(BaseModel):
    """レポートJSONの内容（柔軟なdict）。"""

    project_name: str
    report_id: str
    content: dict[str, Any]
