"""ONNXエクスポートジョブ関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .training import TrainLogLine


class OnnxExportCreate(BaseModel):
    """ONNXエクスポート作成リクエスト。"""

    train_job_id: str = Field(..., examples=["train_001"])
    weight_type: str = "best"  # best | last
    export_job_name: str | None = None  # 省略時は onnx_{train_job_id}_{weight}
    imgsz: int | None = None  # 省略時は学習ジョブの imgsz（無ければ640）
    opset: int = 12
    simplify: bool = True
    dynamic: bool = False
    half: bool = False
    device: str = "cpu"  # auto | cpu | cuda
    overwrite: bool = False


class OnnxExportStartResponse(BaseModel):
    project_name: str
    export_job_id: str
    status: str
    export_path: str
    log_path: str


class OnnxExportInfo(BaseModel):
    """ONNXエクスポート状態（job.json の内容 + project_name）。"""

    project_name: str | None = None
    export_job_id: str
    train_job_id: str | None = None
    weight_type: str | None = None
    source_weight_path: str | None = None
    task: str | None = None
    format: str | None = "onnx"
    imgsz: int | None = None
    opset: int | None = None
    simplify: bool | None = None
    dynamic: bool | None = None
    half: bool | None = None
    device: str | None = None
    status: str = "unknown"
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    onnx_path: str | None = None
    export_path: str | None = None
    message: str | None = None


class OnnxExportListResponse(BaseModel):
    project_name: str
    exports: list[OnnxExportInfo]


class OnnxExportLogResponse(BaseModel):
    export_job_id: str
    log: str
    lines: list[TrainLogLine] = []
    error_summary: str | None = None
