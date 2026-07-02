"""YOLO学習ジョブ関連スキーマ。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TrainJobCreate(BaseModel):
    """学習ジョブ作成リクエスト。"""

    dataset_name: str = Field(..., examples=["dataset_001"])
    job_name: str = Field(..., examples=["train_001"])
    task: str | None = None  # detect | segment（未指定ならプロジェクトの task を使用）
    model: str = "yolov8n.pt"
    epochs: int = Field(50, ge=1)
    imgsz: int = Field(640, ge=32)
    batch: int = Field(8, ge=1)
    device: str = "auto"  # auto | cpu | mps | cuda
    workers: int = Field(2, ge=0)
    patience: int = Field(20, ge=0)
    seed: int = 42
    overwrite: bool = False
    # 学習時オーギュメンテーション（Issue 013）
    augmentation_preset: str | None = None
    augmentation_params: dict[str, Any] | None = None


class TrainJobStartResponse(BaseModel):
    """学習ジョブ開始レスポンス。"""

    project_name: str
    job_id: str
    job_name: str
    status: str
    run_path: str
    log_path: str


class TrainJobInfo(BaseModel):
    """学習ジョブ状態（job.json の内容 + project_name）。"""

    project_name: str | None = None
    job_id: str
    job_name: str | None = None
    dataset_name: str | None = None
    task: str | None = None
    model: str | None = None
    epochs: int | None = None
    imgsz: int | None = None
    batch: int | None = None
    device: str | None = None
    workers: int | None = None
    patience: int | None = None
    seed: int | None = None
    status: str = "unknown"
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    run_path: str | None = None
    best_model_path: str | None = None
    last_model_path: str | None = None
    results_csv_path: str | None = None
    message: str | None = None
    augmentation_preset: str | None = None
    augmentation_params: dict[str, Any] | None = None


class TrainJobListResponse(BaseModel):
    project_name: str
    jobs: list[TrainJobInfo]


class TrainLogLine(BaseModel):
    level: str  # error | warning | info | normal
    text: str


class TrainLogResponse(BaseModel):
    job_id: str
    log: str
    lines: list[TrainLogLine] = []
    error_summary: str | None = None
