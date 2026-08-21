"""カメラ/URL映像からの静止画撮影（プロジェクト準備・画像取り込み）。

学習前の「プロジェクト準備」段階では学習済みモデルがまだ無いため、
`video_service`（YOLO推論を伴う映像テスト）とは別に、推論なしで軽量に
プレビュー＋撮影だけを行う。カメラ/URLのオープン・再接続・URL解決ロジックは
`video_service`（`resolve_source_url`）と `predict_video_worker.py`
（`_open_camera` 等）を再利用し、実装の重複を避けている。

- video_fps: プレビュー表示FPS
- 撮影は「ボタン押下（capture.flag）」または「interval_minutes おきの自動撮影」
- 撮影した画像は `image_service.save_uploads` 経由で raw/images へ保存され、
  重複/破損チェック・ファイル名正規化など既存の取り込み処理と完全に同じ規約に従う
- 停止は stop.flag を置く
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import paths
from ..schemas.capture import (
    CaptureNowResult,
    CaptureSessionCreate,
    CaptureSessionInfo,
    CaptureSessionListResponse,
    CaptureSourceCreate,
    CaptureSourceInfo,
    CaptureSourceListResponse,
    CaptureSourceUpdate,
)
from . import video_service
from .project_service import ProjectError, project_exists

_WORKER = Path(__file__).resolve().parents[2] / "workers" / "capture_worker.py"
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def next_aligned_time(interval_minutes: float, now: datetime | None = None) -> datetime | None:
    """次回自動撮影の予定時刻を「壁時計基準」で計算する。

    複数の撮影ソースが同じ間隔で自動撮影する場合、開始タイミングに関わらず
    UNIX epoch を interval 秒で割った境界（例: 5分間隔なら毎時00分・05分・10分…）
    に足並みを揃えることで、中央の一斉トリガー機構なしに同時撮影を実現する。
    """
    if interval_minutes <= 0:
        return None
    now = now or datetime.now()
    interval_seconds = interval_minutes * 60.0
    epoch = now.timestamp()
    next_epoch = (epoch // interval_seconds + 1) * interval_seconds
    return datetime.fromtimestamp(next_epoch)


class CaptureError(Exception):
    pass


class CaptureNotFoundError(CaptureError):
    """404相当。"""


class CaptureValidationError(CaptureError):
    """400相当。"""


class CaptureConflictError(CaptureError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


# カメラ列挙・URL解決は video_service のものをそのまま使う（重複実装を避ける）。
list_cameras = video_service.list_cameras
resolve_source_url = video_service.resolve_source_url


def _job_json_path(name: str, sid: str) -> Path:
    return paths.capture_session_dir(name, sid) / "job.json"


def _job_lock_path(name: str, sid: str) -> Path:
    """job.json のread-modify-write（start/stop・ワーカー自身の状態更新）を直列化する
    ための簡易ロック。ワーカー(capture_worker.py、実体はpredict_video_worker._update_job)
    側も同じ規約（job.jsonパス + ".lock"）でロックするため、同じファイルで排他できる
    （video_service._job_lock_path と同じ考え方）。
    """
    return Path(str(_job_json_path(name, sid)) + ".lock")


def _read_job(name: str, sid: str) -> dict | None:
    p = _job_json_path(name, sid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


# セッションIDは video_job_name と同じ命名規約（英数・アンダースコア・ハイフンのみ）を
# 要求する。session_id/source_id はそのままファイルパスの一部として使われるため、
# パストラバーサル（"../" 等）を含む値を早期に拒否する（Issue #4 Checkpoint 2）。
def _validate_id_format(value: str) -> bool:
    return paths.is_valid_project_name(value)


_ACTIVE_STATUSES = {"queued", "running"}


def _is_session_active(sdir: Path) -> bool:
    """既存の撮影セッションが実行中（＝ディレクトリへ一切触れてはいけない状態）かどうかを判定する。

    job.json が読めない場合は判定不能として安全側（実行中とみなす）に倒す。
    status が queued/running でなくても、記録済みPIDのプロセスがまだ生きていれば
    実行中とみなす（video_service._is_job_active と同じ考え方）。
    """
    job_json = sdir / "job.json"
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return True
    if data.get("status") in _ACTIVE_STATUSES:
        return True
    pid = data.get("pid")
    if isinstance(pid, int) and video_service._pid_alive(pid):
        return True
    return False


def _stream_url(name: str, sid: str) -> str:
    return f"/api/projects/{name}/capture-sessions/{sid}/stream"


def _terminate_existing_worker(sdir: Path, wait_seconds: float = 3.0) -> None:
    """同名セッションを上書き起動する前に、残っている可能性のある旧ワーカープロセスを終了させる。

    以前は overwrite 時にディレクトリを rmtree するだけで、旧ワーカープロセス自体は
    終了させていなかった。旧プロセスは stop.flag をメインループでしか確認できないため、
    ディレクトリごと消してしまうと確認する術を失い、孤立プロセスとして残ってしまう
    （二重起動・多重接続の原因になり得る）。起動時に記録したPIDへ直接シグナルを送ることで
    確実に終了させる。

    SIGTERM送信後、旧プロセスが実際に終了するまで短時間だけ待つ（Issue #4 Checkpoint 2:
    旧プロセスがまだファイルへ書き込み中のディレクトリを直後にrmtreeしにいく競合を減らす
    ため）。待ちきれなかった場合でも、呼び出し側の _safe_rmtree（rename→delete方式）が
    安全側に働く（rename失敗時は既存ジョブを一切変更しない）。
    """
    job_json = sdir / "job.json"
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    pid = data.get("pid")
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return  # 既に終了している等は無視してよい
    deadline = time.time() + wait_seconds
    while time.time() < deadline and video_service._pid_alive(pid):
        time.sleep(0.2)


def start_session(name: str, req: CaptureSessionCreate) -> CaptureSessionInfo:
    _require_project(name)
    if not paths.is_valid_project_name(req.session_name):
        raise CaptureValidationError("session_name は英数・アンダースコア・ハイフンのみです。")
    if not (1 <= req.video_fps <= 60):
        raise CaptureValidationError("video_fps は 1〜60 です。")
    if req.source_type not in ("camera", "url"):
        raise CaptureValidationError("source_type は camera または url です。")

    interval_minutes = req.interval_minutes or 0.0
    if interval_minutes < 0:
        raise CaptureValidationError("interval_minutes は0以上です。")
    if interval_minutes and interval_minutes != int(interval_minutes):
        raise CaptureValidationError("interval_minutes は1分単位（整数）で指定してください。")
    if interval_minutes and not (1 <= interval_minutes <= 1440):
        raise CaptureValidationError("interval_minutes は1〜1440（24時間）分の範囲です。")

    resolved_url: str | None = None
    resolve_note: str | None = None
    if req.source_type == "url":
        resolved_url, resolve_note = resolve_source_url(req.source_url or "")
    elif req.camera_index < 0:
        raise CaptureValidationError("camera_index は0以上の整数です。")

    sid = req.session_name
    sdir = paths.capture_session_dir(name, sid)
    if sdir.exists():
        # 実行中セッションは overwrite の値に関わらず一切削除・変更しない
        # （_safe_rmtree が実行中プロセスのディレクトリを削除しにいくのを防ぐ。
        # video_service.start_job と同じ考え方。Issue #4 Checkpoint 2で追加）。
        if _is_session_active(sdir):
            raise CaptureConflictError(
                f"撮影セッション '{sid}' は実行中のため上書きできません。"
                "停止を待つか、別の session_name を指定してください。"
            )
        if not req.overwrite:
            raise CaptureConflictError(f"撮影セッション '{sid}' は既に存在します。")
        _terminate_existing_worker(sdir)
        try:
            video_service._safe_rmtree(sdir)
        except video_service.VideoConflictError as e:
            # video_service._safe_rmtree は video_service.VideoConflictError を投げるため、
            # capture routerが認識できる例外型へ変換する（router/呼び出し側はcapture_service
            # の例外階層のみを見ればよいようにする）。
            raise CaptureConflictError(str(e)) from e
    live = sdir / "live"
    live.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    aligned = next_aligned_time(interval_minutes, now)
    next_auto_capture_at = aligned.isoformat(timespec="seconds") if aligned else None
    job = {
        "session_id": sid,
        "source_type": req.source_type,
        "camera_index": req.camera_index if req.source_type == "camera" else None,
        "source_url": req.source_url if req.source_type == "url" else None,
        "resolved_source_url": resolved_url,
        "video_fps": req.video_fps,
        "interval_minutes": interval_minutes,
        "status": "queued",
        "message": f"queued（{resolve_note}）" if resolve_note else "queued",
        "created_at": now.isoformat(timespec="seconds"),
        "started_at": None,
        "finished_at": None,
        "captured_count": 0,
        "last_captured_at": None,
        "last_captured_filename": None,
        "next_auto_capture_at": next_auto_capture_at,
    }
    _job_json_path(name, sid).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_path = sdir / "capture.log"
    log_path.touch()

    source_arg = resolved_url if req.source_type == "url" else str(req.camera_index)
    cmd = [
        sys.executable, str(_WORKER),
        "--job-json", str(_job_json_path(name, sid)),
        "--live-dir", str(live),
        "--raw-images-dir", str(paths.raw_images_dir(name)),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", req.source_type,
        "--source", source_arg,
        "--video-fps", str(req.video_fps),
        "--interval-minutes", str(interval_minutes),
    ]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, env=env)
    finally:
        log_f.close()

    # 起動直後にPIDを記録しておく（同名で再起動する際に旧プロセスを確実に終了させるため）。
    # ワーカーは起動後すぐ status=running 等で job.json を更新し得るため、メモリ上の
    # 古い job dict でそのまま上書きすると更新が消える。ロックを取って現在の内容を
    # 読み直してから pid だけ加える（stop_session/ワーカー側 _update_job と同じ
    # ロックファイルで排他する。video_service.start_job と同じ考え方）。
    lock_path = _job_lock_path(name, sid)
    video_service._acquire_file_lock(lock_path)
    try:
        current = _read_job(name, sid) or job
        current["pid"] = proc.pid
        _job_json_path(name, sid).write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        video_service._release_file_lock(lock_path)

    return get_session(name, sid)


def get_session(name: str, sid: str) -> CaptureSessionInfo:
    _require_project(name)
    if not _validate_id_format(sid):
        # 不正な形式（"../" 等）はパストラバーサル対策として、存在しないセッションと
        # 同じ404で扱う（Issue #4 Checkpoint 2）。
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    job = _read_job(name, sid)
    if job is None:
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    if job.get("status") == "running" and job.get("source_type") == "url" and job.get("source_url"):
        # 実際に映像が取得できた（フレームが書き出されている）URLを記憶する。
        # 映像推論テストと同じ known_sources.json（video/ 配下）を共有する。
        # （記憶にはraw URL＝job["source_url"]を使う。以降のAPI応答マスク処理より前に実行する。）
        frame_path = paths.capture_session_dir(name, sid) / "live" / "latest.jpg"
        try:
            if frame_path.exists() and frame_path.stat().st_size > 0:
                video_service._remember_source_at(paths.video_jobs_dir(name), sid, job["source_url"])
        except OSError:
            pass

    # API応答（CaptureSessionInfo）はUI表示にそのまま使われるため、source_url/
    # resolved_source_url は password等の認証情報をマスクした表示用の値にする
    # （video_service.get_job と同じ考え方。現在のUIはこれらの値を編集フォームへ
    # 再利用しないため、raw値との分離フィールドは不要）。
    display = dict(job)
    if display.get("source_url"):
        display["source_url"] = video_service.mask_url_credentials(display["source_url"])
    if display.get("resolved_source_url"):
        display["resolved_source_url"] = video_service.mask_url_credentials(display["resolved_source_url"])
    return CaptureSessionInfo(project_name=name, stream_url=_stream_url(name, sid), **display)


def list_sessions(name: str) -> CaptureSessionListResponse:
    _require_project(name)
    root = paths.capture_sessions_dir(name)
    sessions: list[CaptureSessionInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "job.json").exists():
                try:
                    sessions.append(get_session(name, child.name))
                except CaptureError:
                    pass
    return CaptureSessionListResponse(project_name=name, sessions=sessions)


def stop_session(name: str, sid: str) -> CaptureSessionInfo:
    _require_project(name)
    if not _validate_id_format(sid):
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    sdir = paths.capture_session_dir(name, sid)
    if not sdir.exists():
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    (sdir / "stop.flag").write_text("stop", encoding="utf-8")
    # ワーカー(capture_worker.py)も job.json を定期的に read-modify-write するため、
    # ロックなしだと片方の更新が失われ得る。同じロックファイルで直列化する
    # （video_service.stop_job と同じ考え方。Issue #4 Checkpoint 2）。
    lock_path = _job_lock_path(name, sid)
    video_service._acquire_file_lock(lock_path)
    try:
        job = _read_job(name, sid) or {}
        if job.get("status") in ("queued", "running"):
            job["status"] = "stopped"
            job["finished_at"] = datetime.now().isoformat(timespec="seconds")
            job["message"] = "stopped by user"
            _job_json_path(name, sid).write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        video_service._release_file_lock(lock_path)
    return get_session(name, sid)


def capture_now(name: str, sid: str, timeout: float = 4.0) -> CaptureNowResult:
    """「今すぐ撮影」を要求する。ワーカーが検知して保存するまで短時間だけ待つ。"""
    _require_project(name)
    if not _validate_id_format(sid):
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    sdir = paths.capture_session_dir(name, sid)
    if not sdir.exists():
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    job = _read_job(name, sid) or {}
    if job.get("status") != "running":
        raise CaptureValidationError(
            f"撮影セッションは running 状態ではありません（現在: {job.get('status')}）。"
        )
    before_count = int(job.get("captured_count") or 0)
    (sdir / "capture.flag").write_text("capture", encoding="utf-8")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.2)
        cur = _read_job(name, sid) or {}
        cur_count = int(cur.get("captured_count") or 0)
        if cur_count > before_count:
            return CaptureNowResult(
                status="captured",
                filename=cur.get("last_captured_filename"),
                captured_at=cur.get("last_captured_at"),
                captured_count=cur_count,
            )
        if cur.get("status") not in ("running",):
            return CaptureNowResult(
                status="failed",
                captured_count=cur_count,
                message=cur.get("message"),
            )
    # タイムアウトしても撮影自体はワーカー側で処理され次第反映される
    return CaptureNowResult(
        status="pending",
        captured_count=before_count,
        message="撮影を受け付けました（反映まで少し時間がかかる場合があります）。",
    )


def latest_frame_path(name: str, sid: str) -> Path:
    _require_project(name)
    if not _validate_id_format(sid):
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    sdir = paths.capture_session_dir(name, sid)
    if not sdir.exists():
        raise CaptureNotFoundError(f"撮影セッション '{sid}' が見つかりません。")
    return sdir / "live" / "latest.jpg"


# --- 撮影ソース（カメラ/URLの定義を再利用できるよう永続化する設定） ---
# 4台以上の複数ソースを毎回設定し直さずに済むよう、プロジェクト単位で保存する。
# セッション（実行中インスタンス）とは別物: ソースは「定義」、セッションは「今動いているか」。

_MAX_CAPTURE_SOURCES = 50


def _source_configs_path(name: str) -> Path:
    return paths.capture_sessions_dir(name) / "sources.json"


def _load_source_configs_raw(name: str) -> list[dict]:
    p = _source_configs_path(name)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    sources = data.get("sources")
    return sources if isinstance(sources, list) else []


def _save_source_configs_raw(name: str, sources: list[dict]) -> None:
    p = _source_configs_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.json")
    tmp.write_text(json.dumps({"sources": sources}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _to_source_info(entry: dict) -> CaptureSourceInfo:
    """保存済みソース定義（dict）をAPI応答へ変換する。

    source_url はソース編集フォームへの再入力に使うため raw のまま保持しつつ、
    表示専用の masked_source_url（password等をマスク済み）を別フィールドで
    付与する（video_service.VideoSourceInfo.masked_url と同じ考え方。
    Issue #4 Checkpoint 2）。
    """
    data = dict(entry)
    url = data.get("source_url")
    data["masked_source_url"] = video_service.mask_url_credentials(url) if url else None
    return CaptureSourceInfo(**data)


def list_source_configs(name: str) -> CaptureSourceListResponse:
    _require_project(name)
    return CaptureSourceListResponse(
        project_name=name,
        sources=[_to_source_info(s) for s in _load_source_configs_raw(name)],
    )


def add_source_config(name: str, req: CaptureSourceCreate) -> CaptureSourceInfo:
    _require_project(name)
    if not req.label.strip():
        raise CaptureValidationError("label は必須です。")
    if req.source_type not in ("camera", "url"):
        raise CaptureValidationError("source_type は camera または url です。")
    if req.source_type == "url" and not (req.source_url or "").strip():
        raise CaptureValidationError("source_type=url の場合、source_url が必要です。")
    if req.source_type == "camera" and req.camera_index < 0:
        raise CaptureValidationError("camera_index は0以上の整数です。")

    lock_path = paths.capture_sessions_dir(name) / "sources.lock"
    video_service._acquire_file_lock(lock_path)
    try:
        sources = _load_source_configs_raw(name)
        if len(sources) >= _MAX_CAPTURE_SOURCES:
            raise CaptureValidationError(f"撮影ソースは最大{_MAX_CAPTURE_SOURCES}件までです。")
        existing_ids = {s.get("source_id") for s in sources}
        n = 1
        while f"src_{n:03d}" in existing_ids:
            n += 1
        source_id = f"src_{n:03d}"
        entry = {
            "source_id": source_id,
            "label": req.label.strip(),
            "source_type": req.source_type,
            "camera_index": req.camera_index if req.source_type == "camera" else None,
            "source_url": req.source_url if req.source_type == "url" else None,
        }
        sources.append(entry)
        _save_source_configs_raw(name, sources)
    finally:
        video_service._release_file_lock(lock_path)
    return _to_source_info(entry)


def update_source_config(name: str, source_id: str, req: CaptureSourceUpdate) -> CaptureSourceInfo:
    _require_project(name)
    if not _validate_id_format(source_id):
        raise CaptureNotFoundError(f"撮影ソース '{source_id}' が見つかりません。")
    lock_path = paths.capture_sessions_dir(name) / "sources.lock"
    video_service._acquire_file_lock(lock_path)
    try:
        sources = _load_source_configs_raw(name)
        target = next((s for s in sources if s.get("source_id") == source_id), None)
        if target is None:
            raise CaptureNotFoundError(f"撮影ソース '{source_id}' が見つかりません。")
        if req.label is not None:
            if not req.label.strip():
                raise CaptureValidationError("label は空にできません。")
            target["label"] = req.label.strip()
        if req.source_type is not None:
            if req.source_type not in ("camera", "url"):
                raise CaptureValidationError("source_type は camera または url です。")
            target["source_type"] = req.source_type
        if req.camera_index is not None:
            if req.camera_index < 0:
                raise CaptureValidationError("camera_index は0以上の整数です。")
            target["camera_index"] = req.camera_index
        if req.source_url is not None:
            target["source_url"] = req.source_url
        if target.get("source_type") == "url" and not (target.get("source_url") or "").strip():
            raise CaptureValidationError("source_type=url の場合、source_url が必要です。")
        _save_source_configs_raw(name, sources)
    finally:
        video_service._release_file_lock(lock_path)
    return _to_source_info(target)


def delete_source_config(name: str, source_id: str) -> None:
    _require_project(name)
    if not _validate_id_format(source_id):
        raise CaptureNotFoundError(f"撮影ソース '{source_id}' が見つかりません。")
    # 実行中セッションがあれば先に停止しておく（設定を消しても撮影が残り続けないように）。
    sdir = paths.capture_session_dir(name, source_id)
    if sdir.exists():
        try:
            stop_session(name, source_id)
        except CaptureError:
            pass
    lock_path = paths.capture_sessions_dir(name) / "sources.lock"
    video_service._acquire_file_lock(lock_path)
    try:
        sources = _load_source_configs_raw(name)
        remaining = [s for s in sources if s.get("source_id") != source_id]
        if len(remaining) == len(sources):
            raise CaptureNotFoundError(f"撮影ソース '{source_id}' が見つかりません。")
        _save_source_configs_raw(name, remaining)
    finally:
        video_service._release_file_lock(lock_path)


def mjpeg_generator(name: str, sid: str):
    """live/latest.jpg を繰り返し読み、multipart/x-mixed-replace で配信する。"""
    frame_path = latest_frame_path(name, sid)
    boundary = b"--frame"
    job = _read_job(name, sid) or {}
    fps = job.get("video_fps") or 10
    interval = max(0.03, 1.0 / float(fps))
    deadline = time.time() + 1800  # 安全のため最大30分（撮影自体は継続する）
    while time.time() < deadline:
        cur = _read_job(name, sid) or {}
        if cur.get("status") in ("stopped", "failed", "completed"):
            if frame_path.exists():
                data = frame_path.read_bytes()
                yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            break
        if frame_path.exists():
            try:
                data = frame_path.read_bytes()
                if data:
                    yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            except OSError:
                pass
        time.sleep(interval)
