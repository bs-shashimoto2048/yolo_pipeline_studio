"""学習結果評価関連スキーマ。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EvaluationSummary(BaseModel):
    """results.csv 最終行から抽出した評価サマリー（無い項目は null）。"""

    epoch: int | None = None
    precision: float | None = None
    recall: float | None = None
    map50: float | None = None
    map50_95: float | None = None
    # segment（Mask）メトリクス（detect では null）
    mask_precision: float | None = None
    mask_recall: float | None = None
    mask_map50: float | None = None
    mask_map50_95: float | None = None
    train_box_loss: float | None = None
    train_cls_loss: float | None = None
    train_dfl_loss: float | None = None
    val_box_loss: float | None = None
    val_cls_loss: float | None = None
    val_dfl_loss: float | None = None


class Artifact(BaseModel):
    """学習成果物（画像）。"""

    name: str
    type: str = "image"
    path: str
    url: str


class EvaluationResponse(BaseModel):
    """評価サマリーレスポンス。"""

    project_name: str
    job_id: str
    status: str
    run_path: str
    has_results_csv: bool
    has_best_model: bool
    has_last_model: bool
    summary: EvaluationSummary | None = None
    artifacts: list[Artifact] = []


class MetricsResponse(BaseModel):
    """results.csv のメトリクス推移。"""

    project_name: str
    job_id: str
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
