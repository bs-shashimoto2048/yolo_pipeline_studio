"""データセット作成関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    """データセット作成リクエスト。"""

    dataset_name: str = Field(..., examples=["dataset_001"])
    train_ratio: float = Field(0.8, ge=0.0, le=1.0)
    val_ratio: float = Field(0.2, ge=0.0, le=1.0)
    test_ratio: float = Field(0.0, ge=0.0, le=1.0)
    seed: int = 42
    include_empty_labels: bool = True
    include_unlabeled_images: bool = False
    overwrite: bool = False
    image_source: str = "auto"  # auto | raw | processed
    use_selection: bool = True
    include_review_images: bool = False


class DatasetSummary(BaseModel):
    """分割結果サマリー。"""

    train_image_count: int
    val_image_count: int
    test_image_count: int
    total_image_count: int
    class_count: int


class DatasetCreateResponse(BaseModel):
    """データセット作成レスポンス。"""

    project_name: str
    dataset_name: str
    dataset_path: str
    summary: DatasetSummary
    data_yaml_path: str
    image_source: str = "auto"
    task: str = "detect"
    warning: str | None = None


class DatasetListItem(BaseModel):
    """データセット一覧の1件。"""

    dataset_name: str
    dataset_path: str
    created_at: str | None = None
    train_image_count: int = 0
    val_image_count: int = 0
    test_image_count: int = 0
    class_count: int = 0
    task: str = "detect"
    data_yaml_path: str


class DatasetListResponse(BaseModel):
    """データセット一覧レスポンス。"""

    project_name: str
    datasets: list[DatasetListItem]
