"""shared server mode: 学習ジョブのFIFOキュー + single GPU lock（Issue #49）。

責務（training_service.pyとは分離）:
- training_queue.json（projects_root/.shared_server/）でFIFOキューと
  「現在実行中のジョブ」を一元管理する（どのプロジェクトにも属さない全体状態）。
- GPU(RTX 4070 Laptop想定、1台)での学習は常に同時1件のみに制限する。
- 実際の起動/停止/job.json操作は training_service.py へ委譲する
  （本モジュールは training_service を一方向にimportするのみで、
  training_service側からは本モジュールをimportしない。循環import回避）。

排他制御は既存の video_service._acquire_file_lock/_release_file_lock
（排他生成方式ロックファイル、Issue #30で確立）をそのまま再利用する。
single-process backend前提（Issue #49 §75/§76、複数uvicorn worker運用時は
別途プロセス間で安全なロック機構への置き換えが必要。docsに明記）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import paths
from ..core.config import settings
from ..core.identity import UserIdentity
from ..schemas.training import TrainJobStartResponse
from ..schemas.training_queue import QueueEntry, TrainingQueueStatus
from . import training_service, video_service
from .training_service import (
    TrainConflictError,
    TrainForbiddenError,
    TrainNotFoundError,
)

def _lock_path() -> Path:
    return Path(str(paths.training_queue_path()) + ".lock")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_state() -> dict[str, Any]:
    p = paths.training_queue_path()
    if not p.exists():
        return {"running": None, "queued": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"running": None, "queued": []}
    if not isinstance(data, dict):
        return {"running": None, "queued": []}
    data.setdefault("running", None)
    data.setdefault("queued", [])
    return data


def _write_state(state: dict[str, Any]) -> None:
    video_service._write_job_json(paths.training_queue_path(), state)


def _job_owner(name: str, job_id: str) -> tuple[str | None, str | None]:
    job = training_service._read_job(name, job_id)
    if job is None:
        return None, None
    return job.get("owner_user_id"), job.get("owner_display_name")


def _enforce_limits(state: dict[str, Any], owner_user_id: str | None) -> None:
    if len(state["queued"]) >= settings.max_queued_jobs_global:
        raise TrainConflictError(
            f"キュー全体の待機上限（{settings.max_queued_jobs_global}件）に達しています。"
            "しばらく待ってから再試行してください。"
        )
    if owner_user_id is None:
        return
    per_user = sum(
        1 for e in state["queued"] if e.get("owner_user_id") == owner_user_id
    )
    running = state.get("running")
    if running is not None and running.get("owner_user_id") == owner_user_id:
        per_user += 1
    if per_user >= settings.max_queued_jobs_per_user:
        raise TrainConflictError(
            "同時に投入・待機できるジョブ数の上限"
            f"（{settings.max_queued_jobs_per_user}件）に達しています。"
            "既存ジョブの完了・キャンセルを待ってから再試行してください。"
        )


def enqueue(name: str, job_id: str) -> TrainJobStartResponse:
    """prepare_job済み（status=queued）のジョブをキューへ投入する。

    GPUが空いていれば即座にlaunch_job()を呼んで起動し、埋まっていれば
    FIFOキューへ積んで待機させる（Issue #49 §15/§16）。
    """
    owner_user_id, _owner_display_name = _job_owner(name, job_id)
    lock = _lock_path()
    video_service._acquire_file_lock(lock)
    released = False
    try:
        state = _read_state()
        _enforce_limits(state, owner_user_id)
        if state["running"] is None:
            state["running"] = {
                "project_name": name,
                "job_id": job_id,
                "owner_user_id": owner_user_id,
                "started_at": _now(),
            }
            _write_state(state)
            video_service._release_file_lock(lock)
            released = True
            response = training_service.launch_job(name, job_id)
            response.queue_position = None
            return response

        state["queued"].append(
            {
                "project_name": name,
                "job_id": job_id,
                "owner_user_id": owner_user_id,
                "queued_at": _now(),
            }
        )
        _write_state(state)
        position = len(state["queued"])
    finally:
        if not released:
            video_service._release_file_lock(lock)

    job = training_service.get_job(name, job_id)
    return TrainJobStartResponse(
        project_name=name,
        job_id=job_id,
        job_name=job.job_name or job_id,
        status="queued",
        run_path=job.run_path or "",
        log_path=f"{job.run_path}/train.log" if job.run_path else "",
        queue_position=position,
    )


def _advance_locked(state: dict[str, Any]) -> dict[str, Any] | None:
    """ロック保持中に呼ぶ。queuedの先頭を昇格させ、起動すべき(name, job_id)を返す。

    呼び出し側は戻り値を使って、ロック解放後に training_service.launch_job を
    呼び出すこと（Popen自体はファイルロックを長時間保持したくないため）。
    """
    if state["queued"]:
        nxt = state["queued"].pop(0)
        state["running"] = {
            "project_name": nxt["project_name"],
            "job_id": nxt["job_id"],
            "owner_user_id": nxt.get("owner_user_id"),
            "started_at": _now(),
        }
        return nxt
    return None


def poll_and_advance() -> None:
    """runningジョブの終了を検知し、終わっていればqueuedの先頭を昇格させる。

    backend起動中は定期的なbackground taskから呼ばれる（shared_server_mode時のみ、
    Issue #49 §22）。多少遅延してもFIFO順序自体は壊れない（job.json/queue.jsonは
    常に正）ため、例外は握りつぶして次回へ回す（queue監視自体でserverを落とさない）。
    """
    lock = _lock_path()
    video_service._acquire_file_lock(lock)
    released = False
    try:
        state = _read_state()
        running = state.get("running")
        to_launch = None
        if running is not None:
            job = training_service._read_job(running["project_name"], running["job_id"])
            pid = job.get("pid") if job else None
            status = job.get("status") if job else None
            terminal = status in ("completed", "failed", "cancelled")
            crashed = (
                not terminal
                and isinstance(pid, int)
                and not training_service._pid_alive(pid)
            )
            if not terminal and not crashed and job is not None:
                return  # まだ実行中
            if crashed:
                # PIDが消えているのにstatusが終端でない＝クラッシュ相当（Issue #49 §23）。
                # 同じoutput directoryへは絶対に自動再開しない。failedとして明示するのみ。
                training_service._mark_interrupted(running["project_name"], running["job_id"])
            state["running"] = None
            to_launch = _advance_locked(state)
        elif state["queued"]:
            to_launch = _advance_locked(state)
        _write_state(state)
        if to_launch is not None:
            video_service._release_file_lock(lock)
            released = True
            training_service.launch_job(to_launch["project_name"], to_launch["job_id"])
    finally:
        if not released:
            video_service._release_file_lock(lock)


def cancel(name: str, job_id: str, identity: UserIdentity | None = None) -> Any:
    """キュー内ジョブ（queued）または実行中ジョブ（running）をキャンセルする。"""
    lock = _lock_path()
    video_service._acquire_file_lock(lock)
    was_running = False
    try:
        state = _read_state()
        before = len(state["queued"])
        owner_user_id, _ = _job_owner(name, job_id)
        if identity is not None and identity.user_id and owner_user_id:
            if identity.user_id != owner_user_id:
                raise TrainForbiddenError("自分が投入したジョブのみキャンセルできます。")
        state["queued"] = [
            e
            for e in state["queued"]
            if not (e["project_name"] == name and e["job_id"] == job_id)
        ]
        removed_from_queue = len(state["queued"]) != before
        running = state.get("running")
        if running is not None and running["project_name"] == name and running["job_id"] == job_id:
            was_running = True
            state["running"] = None
        if not removed_from_queue and not was_running:
            raise TrainNotFoundError(
                f"学習ジョブ '{job_id}' はキューに存在しません（既に終了している可能性があります）。"
            )
        to_launch = _advance_locked(state) if was_running else None
        _write_state(state)
    finally:
        video_service._release_file_lock(lock)

    result = training_service.terminate_and_mark_cancelled(name, job_id, identity)
    if to_launch is not None:
        training_service.launch_job(to_launch["project_name"], to_launch["job_id"])
    return result


def recover() -> None:
    """backend起動時の呼び出し専用（shared_server_mode時のみ）。

    running中だった(可能性のある)ジョブのPID生存を確認し、死んでいれば
    interrupted/failedとして明示する（勝手に同じoutput directoryへ再学習しない、
    Issue #49 §24/§25）。queuedはそのまま（queue.json自体が永続化されているため
    特別な復元処理は不要）。最後にqueue先頭を昇格できるか試す。
    """
    poll_and_advance()


def _enrich(entry: dict[str, Any], position: int, status: str) -> QueueEntry:
    job = training_service._read_job(entry["project_name"], entry["job_id"])
    return QueueEntry(
        project_name=entry["project_name"],
        job_id=entry["job_id"],
        job_name=(job.get("job_name") if job else None) or entry["job_id"],
        owner_display_name=(job.get("owner_display_name") if job else None),
        status=status,
        queued_at=entry.get("queued_at"),
        position=position,
    )


def get_status() -> TrainingQueueStatus:
    if not settings.shared_server_mode:
        return TrainingQueueStatus(shared_server_mode=False, running=None, queued=[])
    state = _read_state()
    running_entry = state.get("running")
    running = _enrich(running_entry, 0, "running") if running_entry else None
    queued = [
        _enrich(e, i + 1, "queued") for i, e in enumerate(state.get("queued", []))
    ]
    return TrainingQueueStatus(
        shared_server_mode=True, running=running, queued=queued
    )
