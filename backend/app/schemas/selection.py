"""画像選別関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class SelectionRunRequest(BaseModel):
    """画像選別チェック実行リクエスト。"""

    source: str = "auto"  # raw | processed | auto
    min_width: int = 320
    min_height: int = 320
    blur_threshold: float = 80.0
    dark_threshold: float = 30.0
    bright_threshold: float = 240.0
    detect_duplicates: bool = True
    overwrite: bool = False


class SelectionItem(BaseModel):
    image_id: str
    image_name: str
    source: str
    width: int
    height: int
    status: str  # included | excluded | review
    warnings: list[str] = []
    reasons: list[str] = []
    hash: str | None = None
    brightness_mean: float | None = None
    blur_score: float | None = None
    duplicate_of: str | None = None
    manual_reason: str | None = None


class SelectionSummary(BaseModel):
    image_count: int = 0
    included_count: int = 0
    excluded_count: int = 0
    review_count: int = 0
    duplicate_count: int = 0
    small_count: int = 0
    dark_count: int = 0
    bright_count: int = 0
    blur_count: int = 0


class SelectionRunResponse(BaseModel):
    project_name: str
    source: str
    summary: SelectionSummary
    selection_path: str


class SelectionGetResponse(BaseModel):
    project_name: str
    source: str
    summary: SelectionSummary
    items: list[SelectionItem]


class SelectionStatusUpdate(BaseModel):
    status: str
    manual_reason: str | None = None


class SelectionStatusResponse(BaseModel):
    image_id: str
    status: str
    manual_reason: str | None = None


class SelectionRotateRequest(BaseModel):
    source: str = "processed"
    angle: int = 90  # 90 | -90 | 180


class SelectionRotateResponse(BaseModel):
    image_id: str
    source: str
    angle: int
    width: int
    height: int
    warning: str | None = None
