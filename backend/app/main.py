"""FastAPI エントリポイント。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core import paths
from .routers import (
    analysis,
    annotations,
    augmentation,
    capture,
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
    training_queue,
    video,
)
from .routers.stubs import all_stub_routers
from .schemas.common import MessageResponse, ServerInfo

_logger = logging.getLogger(__name__)

# shared server modeでのqueue監視間隔（秒）。短すぎるとidle時のCPU消費が増える、
# 長すぎると次ジョブの昇格が遅延する。3秒は既存のPID確認(tasklist呼び出し)が
# 軽量なことを踏まえた妥当な値（Issue #49 §55: idle時に高CPU/GPU使用しない）。
_QUEUE_POLL_INTERVAL_SECONDS = 3.0


async def _queue_poll_loop() -> None:
    from .services import training_queue_service

    while True:
        await asyncio.sleep(_QUEUE_POLL_INTERVAL_SECONDS)
        try:
            training_queue_service.poll_and_advance()
        except Exception:  # noqa: BLE001 - キュー監視自体でserverを落とさない
            _logger.exception("training queue poll failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 起動時に案件データのルートディレクトリを用意する
    paths.projects_root()

    poll_task: asyncio.Task | None = None
    if settings.shared_server_mode:
        # shared server modeのみ: backend再起動後のqueue復旧(Issue #49 §22/§23)と、
        # 以後の定期監視タスクを起動する。local modeではこのタスク自体を一切
        # 生成しないため、既存の1ユーザー利用に追加の負荷は発生しない(§4)。
        from .services import training_queue_service

        training_queue_service.recover()
        poll_task = asyncio.create_task(_queue_poll_loop())

    yield

    if poll_task is not None:
        poll_task.cancel()


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


@app.get("/api/server-info", response_model=ServerInfo, tags=["meta"])
def server_info() -> ServerInfo:
    return ServerInfo(shared_server_mode=settings.shared_server_mode)


# 実働ルーター
app.include_router(projects.router)
app.include_router(images.router)
app.include_router(capture.router)
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
app.include_router(training_queue.router)

# 未実装工程スタブ
for stub in all_stub_routers():
    app.include_router(stub)
