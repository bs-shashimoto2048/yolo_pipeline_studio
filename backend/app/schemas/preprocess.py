"""前処理関連スキーマ。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PreprocessSettings(BaseModel):
    """前処理実行リクエスト。"""

    job_name: str = "preprocess_001"
    overwrite: bool = False
    output_format: str = "jpg"  # jpg | png

    resize_enabled: bool = False
    # 新仕様: width/height のどちらかを resize_size px にし、他方はアスペクト比維持で自動計算
    resize_mode: str | None = None  # "width" | "height"
    resize_size: int = 640
    # 旧仕様（後方互換のため受理。resize_mode 未指定時のみ使用）
    resize_width: int = 640
    resize_height: int = 640
    keep_aspect_ratio: bool = True
    padding: bool = True
    padding_color: str = "black"  # black | white | gray

    brightness_enabled: bool = False
    brightness: float = 0.0  # -100 ～ 100

    contrast_enabled: bool = False
    contrast: float = 1.0  # 0.5 ～ 3.0

    grayscale_enabled: bool = False

    binary_enabled: bool = False
    binary_threshold: int = 128  # 0〜255
    binary_invert: bool = False

    sharpen_enabled: bool = False
    sharpen_strength: float = 1.0  # 0.0 ～ 3.0

    clahe_enabled: bool = False
    clahe_clip_limit: float = 2.0  # 1.0 ～ 10.0
    clahe_tile_grid_size: int = 8  # 4 ～ 16


class PreprocessRunResponse(BaseModel):
    project_name: str
    job_name: str
    status: str
    input_count: int
    processed_count: int
    skipped_count: int
    processed_dir: str
    metadata_path: str
    warning: str | None = None


class PreprocessInfoResponse(BaseModel):
    project_name: str
    has_processed_images: bool
    processed_count: int
    processed_dir: str
    metadata: dict[str, Any] | None = None


class PreprocessPreviewResponse(BaseModel):
    project_name: str
    image_id: str
    before_url: str
    preview_url: str
    before_width: int
    before_height: int
    after_width: int
    after_height: int
