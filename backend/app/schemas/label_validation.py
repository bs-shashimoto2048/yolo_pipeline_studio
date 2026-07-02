"""ラベル品質チェック関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class LabelIssue(BaseModel):
    """検出された1件の問題。"""

    severity: str  # "error" | "warning"
    type: str
    image_id: str | None = None
    image_name: str | None = None
    label_path: str | None = None
    line_number: int | None = None
    message: str


class ClassStat(BaseModel):
    """クラス別の集計。"""

    class_id: int
    class_name: str
    bbox_count: int
    image_count: int


class ValidationSummary(BaseModel):
    """全体サマリー。"""

    image_count: int
    label_file_count: int
    annotated_image_count: int
    empty_label_image_count: int
    missing_label_count: int
    orphan_label_count: int
    total_bbox_count: int
    error_count: int
    warning_count: int


class LabelValidationResponse(BaseModel):
    """ラベル品質チェック結果。"""

    project_name: str
    summary: ValidationSummary
    class_stats: list[ClassStat]
    issues: list[LabelIssue]
