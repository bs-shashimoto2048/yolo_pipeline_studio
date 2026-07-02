"""モデル管理（モデルレジストリ）関連スキーマ。

学習ジョブ配下の best.pt / last.pt を「モデル」として扱う。
model_id = "{train_job_id}:{weight_type}"
"""

from __future__ import annotations

from pydantic import BaseModel

from .experiment import ExperimentEvaluation, ExperimentPrediction, LatestAnalysis
from .training import TrainJobInfo


class ModelItem(BaseModel):
    model_id: str
    train_job_id: str
    weight_type: str
    model_path: str
    exists: bool
    file_size_bytes: int | None = None
    created_at: str | None = None
    train_status: str | None = None
    dataset_name: str | None = None
    base_model: str | None = None
    epochs: int | None = None
    imgsz: int | None = None
    batch: int | None = None
    device: str | None = None
    precision: float | None = None
    recall: float | None = None
    map50: float | None = None
    map50_95: float | None = None
    augmentation_preset: str | None = None
    latest_analysis: LatestAnalysis | None = None
    is_selected: bool = False


class ModelListResponse(BaseModel):
    project_name: str
    selected_model_id: str | None = None
    models: list[ModelItem]


class ModelDetailResponse(BaseModel):
    project_name: str
    model_id: str
    train_job_id: str
    weight_type: str
    model_path: str
    exists: bool
    file_size_bytes: int | None = None
    train_job: TrainJobInfo | None = None
    evaluation: ExperimentEvaluation | None = None
    predictions: list[ExperimentPrediction] = []
    is_selected: bool = False


class SelectModelRequest(BaseModel):
    train_job_id: str
    weight_type: str = "best"
    memo: str = ""


class SelectedModelResponse(BaseModel):
    project_name: str
    selected_model_id: str
    train_job_id: str
    weight_type: str
    model_path: str
    selected_at: str | None = None
    memo: str = ""
