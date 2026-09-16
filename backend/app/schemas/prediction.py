"""推論ジョブ関連スキーマ。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PredictJobCreate(BaseModel):
    """推論ジョブ作成リクエスト。

    train_job_id / weight_type / conf は省略可（Checkpoint 5AE）。省略時は
    project の採用モデル設定（selected_model.json）へフォールバックし、それも
    無ければ後方互換な安全なdefault（weight_type="best", conf=0.25）を用いる。
    明示指定は常にselected model設定より優先される。
    """

    predict_job_name: str = Field(..., examples=["predict_001"])
    train_job_id: str | None = Field(default=None, examples=["train_001"])
    weight_type: str | None = None  # best | last。省略時はselected model優先、次点で"best"
    source_type: str = "project_images"  # project_images | upload
    image_ids: list[str] = Field(default_factory=list)
    conf: float | None = Field(default=None, ge=0.0, le=1.0)  # 省略時はselected model優先、次点で0.25
    iou: float = Field(0.7, ge=0.0, le=1.0)
    imgsz: int = Field(640, ge=32)
    device: str = "auto"
    save_txt: bool = True
    save_conf: bool = True
    overwrite: bool = False
    preprocess_mode: str = "none"  # none | latest | selected（selectedはselected modelのpreprocess_profileを使用）


class PredictJobStartResponse(BaseModel):
    project_name: str
    predict_job_id: str
    status: str
    prediction_path: str
    log_path: str


class PredictJobInfo(BaseModel):
    """推論ジョブ状態（job.json の内容 + project_name）。"""

    project_name: str | None = None
    predict_job_id: str
    predict_job_name: str | None = None
    train_job_id: str | None = None
    weight_type: str | None = None
    source_type: str | None = None
    status: str = "unknown"
    conf: float | None = None
    iou: float | None = None
    imgsz: int | None = None
    device: str | None = None
    save_txt: bool | None = None
    save_conf: bool | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    message: str | None = None
    image_count: int | None = None
    detection_count: int | None = None
    total_count: int | None = None
    processed_count: int | None = None
    prediction_path: str | None = None
    results_json_path: str | None = None
    preprocess_mode: str | None = None
    # 実際に解決されたtrain_job_id/weight_type/conf/preprocessの由来（Checkpoint 5AE）。
    # 値は "request" | "selected_model" | "default" のいずれか。
    resolution_source: dict[str, str] | None = None
    # preprocess_mode="latest"/"selected"の場合に実際に適用されたPreprocessSettings（dict）
    resolved_preprocess_profile: dict[str, Any] | None = None
    # 実際に適用された前処理ステップの列（例: ["roi_crop","resize","grayscale","sharpen"]）
    processing_order: list[str] | None = None


class PredictJobListResponse(BaseModel):
    project_name: str
    jobs: list[PredictJobInfo]


class PredictLogResponse(BaseModel):
    predict_job_id: str
    log: str


class Detection(BaseModel):
    class_id: int
    class_name: str | None = None
    confidence: float
    x_center: float
    y_center: float
    width: float
    height: float


class PredictResultItem(BaseModel):
    image_id: str
    image_name: str
    result_image_url: str | None = None
    detections: list[Detection] = []


class PredictResultsResponse(BaseModel):
    project_name: str
    predict_job_id: str
    image_count: int
    detection_count: int
    results: list[PredictResultItem]
