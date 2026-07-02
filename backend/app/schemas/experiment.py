"""実験履歴関連スキーマ。

実験は MVP では train_job 1件 = 1実験（experiment_id = train_job_id）として扱う。
既存の job.json / metadata.json / results.csv / analysis.json を集約する。
"""

from __future__ import annotations

from pydantic import BaseModel

from .training import TrainJobInfo


class AnalysisBrief(BaseModel):
    tp_count: int = 0
    fp_count: int = 0
    fn_count: int = 0
    class_mismatch_count: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class LatestAnalysis(AnalysisBrief):
    predict_job_id: str


class ExperimentListItem(BaseModel):
    experiment_id: str
    train_job_id: str
    status: str
    dataset_name: str | None = None
    model: str | None = None
    epochs: int | None = None
    imgsz: int | None = None
    batch: int | None = None
    device: str | None = None
    created_at: str | None = None
    finished_at: str | None = None
    train_image_count: int | None = None
    val_image_count: int | None = None
    class_count: int | None = None
    precision: float | None = None
    recall: float | None = None
    map50: float | None = None
    map50_95: float | None = None
    best_model_path: str | None = None
    augmentation_preset: str | None = None
    latest_analysis: LatestAnalysis | None = None


class ExperimentListResponse(BaseModel):
    project_name: str
    experiments: list[ExperimentListItem]


class ExperimentDataset(BaseModel):
    dataset_name: str | None = None
    train_image_count: int | None = None
    val_image_count: int | None = None
    test_image_count: int | None = None
    total_image_count: int | None = None
    class_count: int | None = None
    train_ratio: float | None = None
    val_ratio: float | None = None
    test_ratio: float | None = None
    include_empty_labels: bool | None = None
    include_unlabeled_images: bool | None = None
    seed: int | None = None


class ExperimentEvaluation(BaseModel):
    precision: float | None = None
    recall: float | None = None
    map50: float | None = None
    map50_95: float | None = None
    train_box_loss: float | None = None
    val_box_loss: float | None = None
    has_best_model: bool = False
    has_last_model: bool = False
    has_results_csv: bool = False


class ExperimentPrediction(BaseModel):
    predict_job_id: str
    status: str | None = None
    image_count: int | None = None
    detection_count: int | None = None
    analysis: AnalysisBrief | None = None


class ExperimentDetailResponse(BaseModel):
    project_name: str
    experiment_id: str
    train_job: TrainJobInfo | None = None
    dataset: ExperimentDataset | None = None
    evaluation: ExperimentEvaluation | None = None
    predictions: list[ExperimentPrediction] = []
