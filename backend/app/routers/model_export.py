"""モデル配布パッケージ出力 API。

model_registry の `/models/{train_job_id}/{weight_type}` と衝突しないよう、
配布系は `model-export` / `model-packages` の別プレフィックスに置く。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..schemas.model_export import ModelPackageCreate, ModelPackageResponse
from ..services import model_export_service
from ..services.model_export_service import (
    ModelExportNotFoundError,
    ModelExportValidationError,
)
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}", tags=["model-export"])


@router.get("/model-export/{train_job_id}/{weight}/download")
def download_weight(name: str, train_job_id: str, weight: str) -> FileResponse:
    try:
        path = model_export_service.weight_download_path(name, train_job_id, weight)
    except ModelExportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ModelExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{train_job_id}_{weight}.pt",
    )


@router.post("/model-export/{train_job_id}/{weight}/package", response_model=ModelPackageResponse)
def create_package(
    name: str, train_job_id: str, weight: str, payload: ModelPackageCreate | None = None
) -> ModelPackageResponse:
    req = payload or ModelPackageCreate()
    try:
        return model_export_service.create_package(
            name, train_job_id, weight,
            include_onnx=req.include_onnx,
            onnx_export_job_id=req.onnx_export_job_id,
        )
    except ModelExportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ModelExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/model-packages/{package_id}/download")
def download_package(name: str, package_id: str) -> FileResponse:
    try:
        path = model_export_service.package_zip_path(name, package_id)
    except ModelExportValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ModelExportNotFoundError, ProjectError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type="application/zip", filename=path.name)
