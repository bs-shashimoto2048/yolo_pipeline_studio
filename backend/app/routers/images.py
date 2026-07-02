"""画像取り込み・一覧・取得・サムネイル API。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..schemas.image import FolderImportResponse, ImageListResponse, UploadResponse
from ..services import image_service
from ..services.project_service import ProjectError

router = APIRouter(prefix="/api/projects/{name}/images", tags=["images"])


@router.get("", response_model=ImageListResponse)
def list_images(name: str, source: str = "raw") -> ImageListResponse:
    try:
        images = image_service.list_images(name, source)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ImageListResponse(images=images, total=len(images))


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_images(
    name: str, files: list[UploadFile] = File(...)
) -> UploadResponse:
    payload: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        payload.append((f.filename or "image", data))
    try:
        return image_service.save_uploads(name, payload)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/import-folder", response_model=FolderImportResponse, status_code=201)
async def import_folder(
    name: str,
    files: list[UploadFile] = File(...),
    allowed_extensions: list[str] = Form(default=[]),
    include_subfolders: bool = Form(default=True),  # noqa: ARG001 - フロントで絞込済
) -> FolderImportResponse:
    payload: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        payload.append((f.filename or "image", data))
    try:
        return image_service.import_folder(name, payload, allowed_extensions)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{filename}")
def get_image(name: str, filename: str, source: str = "raw") -> FileResponse:
    try:
        path = image_service.image_path(name, filename, source)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path)


@router.get("/{filename}/thumbnail")
def get_thumbnail(name: str, filename: str, source: str = "raw") -> Response:
    try:
        data = image_service.make_thumbnail(name, filename, source)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(content=data, media_type="image/png")
