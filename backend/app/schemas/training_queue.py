"""shared server mode: FIFO学習キュー関連スキーマ（Issue #49）。"""

from __future__ import annotations

from pydantic import BaseModel


class QueueEntry(BaseModel):
    """キュー表示用のジョブ1件（他ユーザーへは最小限の情報のみ公開、Issue #49 §36）。"""

    project_name: str
    job_id: str
    job_name: str | None = None
    owner_display_name: str | None = None
    status: str
    queued_at: str | None = None
    position: int  # 0 = running中, 1.. = 待機順位


class TrainingQueueStatus(BaseModel):
    shared_server_mode: bool
    running: QueueEntry | None = None
    queued: list[QueueEntry] = []
