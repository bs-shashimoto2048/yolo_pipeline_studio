"""モデル配布パッケージ出力関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class ModelPackageCreate(BaseModel):
    """配布パッケージ作成リクエスト（ONNX同梱は任意）。"""

    include_onnx: bool = False
    onnx_export_job_id: str | None = None


class ModelPackageResponse(BaseModel):
    """配布パッケージ作成レスポンス。"""

    project_name: str
    model_id: str  # "{train_job_id}:{weight}"
    package_id: str
    status: str = "completed"
    zip_path: str  # プロジェクトルートからの相対パス（POSIX）
    files: list[str] = []  # ZIP内に含めたファイル一覧
