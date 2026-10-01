"""shared server mode: FIFO学習キューの状態参照API（Issue #49）。"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.training_queue import TrainingQueueStatus
from ..services import training_queue_service

router = APIRouter(prefix="/api/training-queue", tags=["training-queue"])


@router.get("/status", response_model=TrainingQueueStatus)
def get_status() -> TrainingQueueStatus:
    return training_queue_service.get_status()
