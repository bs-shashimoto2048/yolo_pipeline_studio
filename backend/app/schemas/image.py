"""画像関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class ImageInfo(BaseModel):
    """登録画像1件分のメタ情報。"""

    filename: str
    width: int
    height: int
    size_bytes: int
    sha1: str
    has_label: bool = False
    low_resolution: bool = False


class ImageListResponse(BaseModel):
    """画像一覧応答。"""

    images: list[ImageInfo]
    total: int


class UploadResultItem(BaseModel):
    """アップロード結果1件。"""

    original_name: str
    stored_name: str | None = None
    status: str  # "added" | "duplicate" | "unsupported" | "corrupt" | "error"
    detail: str = ""


class UploadResponse(BaseModel):
    """アップロード結果まとめ。"""

    results: list[UploadResultItem]
    added: int
    skipped: int


class ImportItem(BaseModel):
    """フォルダ取り込み1件分の結果。"""

    filename: str
    status: str  # imported | duplicate | broken | unsupported
    width: int | None = None
    height: int | None = None
    hash: str | None = None
    detail: str = ""


class FolderImportResponse(BaseModel):
    """フォルダ取り込み結果。"""

    project_name: str
    imported_count: int
    skipped_count: int
    duplicate_count: int
    broken_count: int
    unsupported_count: int
    items: list[ImportItem]
