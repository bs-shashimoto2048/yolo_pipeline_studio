"""FastAPI エントリポイント。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core import paths
from .routers import (
    analysis,
    annotations,
    augmentation,
    datasets,
    evaluation,
    experiments,
    images,
    label_validation,
    model_export,
    model_registry,
    onnx_export,
    prediction,
    preprocess,
    projects,
    reports,
    sam,
    selection,
    training,
    video,
)
from .routers.stubs import all_stub_routers
from .schemas.common import MessageResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 起動時に案件データのルートディレクトリを用意する
    paths.projects_root()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=MessageResponse, tags=["meta"])
def health() -> MessageResponse:
    return MessageResponse(message=f"{settings.app_name} v{settings.version} ok")


# 実働ルーター
app.include_router(projects.router)
app.include_router(images.router)
app.include_router(annotations.router)
app.include_router(label_validation.router)
app.include_router(datasets.router)
app.include_router(training.router)
app.include_router(evaluation.router)
app.include_router(prediction.router)
app.include_router(analysis.router)
app.include_router(experiments.router)
app.include_router(model_registry.router)
app.include_router(model_export.router)
app.include_router(onnx_export.router)
app.include_router(augmentation.router)
app.include_router(preprocess.router)
app.include_router(selection.router)
app.include_router(reports.router)
app.include_router(video.router)
app.include_router(sam.router)

# 未実装工程スタブ
for stub in all_stub_routers():
    app.include_router(stub)
