"""映像（カメラ）推論。

サーバー(=同一PC)に接続されたカメラを OpenCV で開き、別プロセスのワーカーで
前処理＋推論を行い、注釈フレームを live/latest.jpg に書き出す。FastAPI 側は
そのファイルを繰り返し読んで MJPEG (multipart/x-mixed-replace) でライブ配信する。

- video_fps: キャプチャ/表示FPS、infer_fps: 推論FPS（間引き、video_fps以下）
- preprocess_mode=latest なら最新前処理設定を各フレームに適用
- 停止は stop.flag を置く。元画像/processed本体は破壊しない。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from ..core import paths
from ..schemas.video import (
    CameraInfo,
    VideoJobCreate,
    VideoJobInfo,
    VideoJobListResponse,
    VideoJobSettingsUpdate,
)
from . import preprocess_service
from .project_service import ProjectError, project_exists

_WORKER = Path(__file__).resolve().parents[2] / "workers" / "predict_video_worker.py"
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class VideoError(Exception):
    pass


class VideoNotFoundError(VideoError):
    """404相当。"""


class VideoValidationError(VideoError):
    """400相当。"""


class VideoConflictError(VideoError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _validate_fps_settings(*, video_fps: int, infer_fps: int) -> None:
    """video_fps/infer_fps の共通validation（start_job/update_settingsで同一仕様を適用する）。"""
    if not (1 <= video_fps <= 60):
        raise VideoValidationError("video_fps は 1〜60 です。")
    if not (1 <= infer_fps <= video_fps):
        raise VideoValidationError("infer_fps は 1〜video_fps の範囲です。")


def _validate_inference_settings(*, conf: float, iou: float, imgsz: int) -> None:
    """conf/iou/imgsz の共通validation（start_job/update_settingsで同一仕様を適用する）。

    これまでupdate_settings()側にのみ存在していた仕様を正としてstart_job()にも
    適用し、作成時と更新時でvalidationが非対称にならないようにする（Issue #3
    Checkpoint 2で判明した既知の非対称性の修正）。

    device はここでは検証しない。training/prediction/video のいずれのschemaも
    device に制約を課しておらず、Ultralyticsのdevice引数自体が
    "cpu" / "mps" / "cuda" / "cuda:0" / "0" / "0,1" 等、多様な表記を正当な値として
    受理するため、単一の仕様（正規表現・ホワイトリスト等）を決め打ちすると将来の
    マルチGPU指定や他バックエンド指定を誤って拒否するリスクがある。明確な仕様が
    定義できない現状では、無理にvalidationを追加しない。
    """
    if not (0.0 <= conf <= 1.0):
        raise VideoValidationError("conf は0〜1です。")
    if not (0.0 <= iou <= 1.0):
        raise VideoValidationError("iou は0〜1です。")
    if imgsz < 32:
        raise VideoValidationError("imgsz は32以上です。")


def list_cameras(max_index: int = 5) -> list[CameraInfo]:
    """利用可能なカメラ index を列挙する（OpenCVで 0..max_index-1 を試行）。"""
    cams: list[CameraInfo] = []
    try:
        import cv2  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - 未導入なら空
        return cams
    backend = getattr(cv2, "CAP_DSHOW", 0)  # Windowsでは DSHOW が速い
    for i in range(max_index):
        cap = None
        try:
            cap = cv2.VideoCapture(i, backend) if backend else cv2.VideoCapture(i)
            if cap is not None and cap.isOpened():
                cams.append(CameraInfo(index=i, label=f"Camera {i}"))
        except Exception:  # noqa: BLE001
            pass
        finally:
            if cap is not None:
                cap.release()
    return cams


def mask_url_credentials(url: str) -> str:
    """ログ・エラーメッセージ表示用に、URL中の認証情報（user:password@host）をマスクする。

    表示専用のヘルパーであり、実際の接続処理や job.json への保存には使わない
    （接続にはパスワードそのものが必要なため）。パスワードを含まないURLはそのまま返す。
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if not parsed.password:
        return url
    user = parsed.username or ""
    host = parsed.hostname or ""
    netloc = f"{user}:***@{host}" if user else f"***@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


# imagepath等のクエリに実ストリームパスを持つビューワページ（ネットワークカメラの
# view.shtml 等）を自動解決するためのキー候補。
_IMAGEPATH_QUERY_KEYS = ("imagepath", "imgpath", "streampath", "path")


def resolve_source_url(raw_url: str) -> tuple[str, str | None]:
    """URL文字列を実際の映像ストリームURLへ解決する。

    ネットワークカメラのビューワページ（例: `view.shtml?...&imagepath=%2Fmjpg%2Fvideo.mjpg%3Fcamera%3D1`）
    は、クエリ文字列に実ストリームのパスを保持していることが多い。該当するクエリキーを
    検出した場合はそれを同一オリジンの絶対URLへ解決して返す。該当しなければ入力をそのまま返す。

    戻り値: (解決後のURL, 解決内容の説明メモ or None)
    """
    url = (raw_url or "").strip()
    if not url:
        raise VideoValidationError("source_url が空です。")

    parsed = urlsplit(url)
    if not parsed.scheme:
        # スキーム省略時のみ http を仮定する（"://" の有無で判定すると、
        # "http:/host/..." のようにスラッシュが1つ足りない入力を誤って
        # "http://http:/host/..." に変換してしまうため、scheme の有無で判定する）。
        url = "http://" + url
        parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https", "rtsp", "rtsps"):
        raise VideoValidationError(
            "source_url は http(s):// または rtsp(s):// で始めてください。"
        )
    if not parsed.netloc:
        raise VideoValidationError(
            "URLの形式が正しくありません（ホスト部分を認識できません）。"
            "スキームの後のスラッシュが1つ足りない、または認証情報の '@' の位置が誤っている"
            "可能性があります。例: http://ユーザー名:パスワード@192.0.2.10/view/view.shtml?..."
        )
    if parsed.scheme in ("rtsp", "rtsps") or not parsed.query:
        return url, None

    qs = parse_qs(parsed.query)
    for key, values in qs.items():
        if key.lower() in _IMAGEPATH_QUERY_KEYS and values and values[0]:
            candidate = values[0]
            resolved = urljoin(url, candidate)
            return resolved, (
                f"ビューワページのクエリ '{key}' から実映像ストリームのパスを検出し、"
                f"'{mask_url_credentials(resolved)}' へ解決しました。"
            )
    return url, None


# プロジェクトごとに「実際に映像を取得できたURL」を記憶しておく件数の上限。
_MAX_KNOWN_SOURCES = 20


def _acquire_file_lock(lock_path: Path, timeout: float = 5.0) -> None:
    """known_sources.json 更新用の簡易ファイルロック（排他生成方式）。

    known_sources.json は FastAPI 本体（ポーリングでの状態取得時）と、
    別プロセスの映像推論ワーカー（接続確立を確認した直後）の**両方**から
    更新される。前者はスレッドプールで並行実行されるためスレッド間の
    read-modify-write 競合があり、後者は別OSプロセスのためスレッドロックでは
    守れない。ファイルの排他生成はOS/プロセスをまたいで有効なため、
    両者を同じ仕組みで守れる。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except OSError:
            # 通常は FileExistsError（他者がロック保持中）だが、Windowsでは
            # 削除直後の再生成タイミングで PermissionError になることもあるため
            # OSError全体を「今は取れない」として扱い、リトライへ回す。
            if time.time() > deadline:
                # 異常終了などでロックファイルが残置された場合は奪取して継続する
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                deadline = time.time() + timeout
                continue
            time.sleep(0.05)


def _release_file_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        pass


def _known_sources_path(name: str) -> Path:
    return paths.video_jobs_dir(name) / "known_sources.json"


def _load_known_sources_at(known_path: Path) -> list[dict]:
    if not known_path.exists():
        return []
    try:
        data = json.loads(known_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    sources = data.get("sources")
    return sources if isinstance(sources, list) else []


def _save_known_sources_at(known_path: Path, sources: list[dict]) -> None:
    known_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = known_path.with_suffix(".tmp.json")
    tmp.write_text(json.dumps({"sources": sources}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, known_path)  # 書き込み中のクラッシュでも既存ファイルを壊さないよう原子的に置換


def _load_known_sources(name: str) -> list[dict]:
    return _load_known_sources_at(_known_sources_path(name))


def _save_known_sources(name: str, sources: list[dict]) -> None:
    _save_known_sources_at(_known_sources_path(name), sources)


def _remember_source_at(video_dir: Path, vid: str, url: str) -> None:
    """known_sources.json（video_dir 直下）へURLを記憶する（同一URLは先頭へ移動して更新）。

    プロジェクト名ではなく `video/` ディレクトリのパスを直接受け取るため、
    プロジェクト名を知らない映像推論ワーカー（別プロセス）からも呼び出せる。
    """
    known_path = video_dir / "known_sources.json"
    lock_path = video_dir / "known_sources.lock"
    _acquire_file_lock(lock_path)
    try:
        sources = [s for s in _load_known_sources_at(known_path) if s.get("url") != url]
        sources.insert(0, {
            "url": url,
            "video_job_id": vid,
            "last_verified_at": datetime.now().isoformat(timespec="seconds"),
        })
        _save_known_sources_at(known_path, sources[:_MAX_KNOWN_SOURCES])
    finally:
        _release_file_lock(lock_path)


def _remember_source(name: str, vid: str, url: str) -> None:
    """実際に映像を取得できたURLを記憶する（同一URLは先頭へ移動して更新）。"""
    _remember_source_at(paths.video_jobs_dir(name), vid, url)


def _with_masked_url(sources: list[dict]) -> list[dict]:
    """API応答用に、各エントリへ表示用の masked_url を追加する。

    known_sources.json自体には masked_url を保存しない（rawの url のみ保持）。
    url は選択時にそのまま接続用URLとして再利用する必要があるため raw のまま返すが、
    UI側は表示に masked_url を使うことで password がUI上に平文表示されないようにする。
    """
    return [dict(s, masked_url=mask_url_credentials(s.get("url", ""))) for s in sources]


def list_known_sources(name: str) -> list[dict]:
    """プロジェクトで過去に映像取得に成功したURLの一覧（新しい順）。"""
    _require_project(name)
    return _with_masked_url(_load_known_sources(name))


def delete_known_source(name: str, url: str) -> list[dict]:
    """記憶済みURLを1件削除する（認証情報を含むURLの削除用）。"""
    _require_project(name)
    video_dir = paths.video_jobs_dir(name)
    lock_path = video_dir / "known_sources.lock"
    _acquire_file_lock(lock_path)
    try:
        sources = [s for s in _load_known_sources(name) if s.get("url") != url]
        _save_known_sources(name, sources)
    finally:
        _release_file_lock(lock_path)
    return _with_masked_url(sources)


def _job_json_path(name: str, vid: str) -> Path:
    return paths.video_job_dir(name, vid) / "job.json"


def _job_lock_path(name: str, vid: str) -> Path:
    """job.json のread-modify-write（設定PATCH・stop・ワーカー自身の状態更新）を
    直列化するための簡易ロック。ワーカー(predict_video_worker.py)側にも同名の
    ロック生成ロジックを持たせ、同じパス（job.json.lock）を使って競合を防ぐ
    （別プロセスのため、ここでも _acquire_file_lock と同じOS排他生成方式を使う）。
    """
    return Path(str(_job_json_path(name, vid)) + ".lock")


def _read_job(name: str, vid: str) -> dict | None:
    p = _job_json_path(name, vid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def _stream_url(name: str, vid: str) -> str:
    return f"/api/projects/{name}/video-jobs/{vid}/stream"


def _terminate_existing_worker(vdir: Path) -> None:
    """同名ジョブを上書き起動する前に、残っている可能性のある旧ワーカープロセスを終了させる。

    以前は overwrite 時にディレクトリを rmtree するだけで、旧ワーカープロセス自体は
    終了させていなかった。旧プロセスは stop.flag をメインループでしか確認できないため、
    ディレクトリごと消してしまうと確認する術を失い、孤立プロセスとして残ってしまう。
    起動時に記録したPIDへ直接シグナルを送ることで確実に終了させる
    （capture_service._terminate_existing_worker と同じ考え方）。
    """
    job_json = vdir / "job.json"
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
        pass  # 既に終了している等は無視してよい


_ACTIVE_STATUSES = {"queued", "running"}


def _pid_alive(pid: int) -> bool:
    """PIDのプロセスが現在も存在するかを確認する（シグナル送信・終了は行わない）。

    Windowsでは os.kill(pid, 0) が実際に TerminateProcess を呼び出してしまうため
    生存確認には使えない。tasklist で確認する
    （training_service._pid_alive と同じ手法。ワーカー起動経路が異なる別モジュールの
    ため、依存を増やさずここでも同じ実装を持たせている）。
    """
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in res.stdout
        except OSError:
            return True  # 確認できない場合は安全側（実行中とみなす）
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # 権限等で確認できない場合は安全側
    return True


def _is_job_active(vdir: Path) -> bool:
    """既存の映像ジョブが実行中（＝ディレクトリへ一切触れてはいけない状態）かどうかを判定する。

    job.json が読めない場合は判定不能として安全側（実行中とみなす）に倒す
    （壊れたjob.jsonを理由に誤って削除してしまうことを防ぐ）。
    status が queued/running でなくても、記録済みPIDのプロセスがまだ生きていれば
    実行中とみなす（training_service._is_job_active と同じ考え方。statusの
    更新漏れ・クラッシュ以外の理由で古いままのケースへの保険）。
    """
    job_json = vdir / "job.json"
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return True
    if data.get("status") in _ACTIVE_STATUSES:
        return True
    pid = data.get("pid")
    if isinstance(pid, int) and _pid_alive(pid):
        return True
    return False


def _safe_rmtree(path: Path) -> None:
    """既存の映像ジョブディレクトリを削除する（training_service._safe_rmtree と同じ方式）。

    まず同じファイルシステム上のゴミ箱名へリネームしてから削除することで、
    「一部のファイルだけ消えて job.json や video.log が中途半端に残る」状態を避ける。
    リネーム自体が失敗する場合（中のファイルが使用中で改名すらできない等）は、
    元のディレクトリを一切変更せず例外を送出する
    （以前の shutil.rmtree(..., ignore_errors=True) は削除失敗を握りつぶしており、
    ロックされたファイルだけが残る中途半端な状態を生み得た）。
    """
    if not path.exists():
        return

    trash = path.with_name(f"{path.name}.__deleting_{os.getpid()}_{int(time.time() * 1000)}")
    try:
        os.rename(path, trash)
    except OSError as e:
        raise VideoConflictError(
            "既存ジョブディレクトリの削除を開始できませんでした"
            "（ファイルが使用中の可能性があります）。既存ジョブのファイルは変更していません。"
            f" 詳細: {e!r}"
        ) from e

    def _on_error(func, p, _exc):  # 読み取り専用属性を外して再試行
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    last_err: Exception | None = None
    for _attempt in range(6):
        try:
            shutil.rmtree(trash, onerror=_on_error)
            if not trash.exists():
                return
        except OSError as e:  # noqa: PERF203
            last_err = e
        if not trash.exists():
            return
        time.sleep(0.3)
    # リネームには成功しているので、元の video_job_id のパスは既に空いており新規ジョブは
    # 安全に作成できる。ゴミ箱側の削除だけが残った場合は警告に留め、処理は継続する。
    print(f"[WARN] 削除予定ディレクトリの完全な削除に失敗しました（残存: {trash}）: {last_err!r}")


def start_job(name: str, req: VideoJobCreate) -> VideoJobInfo:
    _require_project(name)
    if not paths.is_valid_project_name(req.video_job_name):
        raise VideoValidationError("video_job_name は英数・アンダースコア・ハイフンのみです。")
    if req.weight_type not in ("best", "last"):
        raise VideoValidationError("weight_type は best または last です。")
    _validate_fps_settings(video_fps=req.video_fps, infer_fps=req.infer_fps)
    _validate_inference_settings(conf=req.conf, iou=req.iou, imgsz=req.imgsz)
    if req.source_type not in ("camera", "url"):
        raise VideoValidationError("source_type は camera または url です。")

    resolved_url: str | None = None
    resolve_note: str | None = None
    if req.source_type == "url":
        resolved_url, resolve_note = resolve_source_url(req.source_url or "")
    elif req.camera_index < 0:
        raise VideoValidationError("camera_index は0以上の整数です。")

    train_dir = paths.train_job_dir(name, req.train_job_id)
    if not train_dir.exists():
        raise VideoNotFoundError(f"学習ジョブ '{req.train_job_id}' が見つかりません。")
    weight = train_dir / "weights" / f"{req.weight_type}.pt"
    if not weight.exists():
        raise VideoValidationError(
            f"モデル '{req.weight_type}.pt' が見つかりません。"
        )

    if req.preprocess_mode not in ("none", "latest"):
        raise VideoValidationError("preprocess_mode は none または latest です。")
    pre_settings = None
    if req.preprocess_mode == "latest":
        pre_settings = preprocess_service.load_latest_settings(name)
        if pre_settings is None:
            raise VideoValidationError(
                "最新前処理設定がありません（前処理を実行してから 'latest' を選択してください）。"
            )

    vid = req.video_job_name
    vdir = paths.video_job_dir(name, vid)
    if vdir.exists():
        # 実行中ジョブは overwrite の値に関わらず一切削除・変更しない
        # （_safe_rmtree が実行中プロセスのディレクトリを削除しにいくのを防ぐ）。
        if _is_job_active(vdir):
            raise VideoConflictError(
                f"映像ジョブ '{vid}' は実行中のため上書きできません。"
                "停止を待つか、別の video_job_name を指定してください。"
            )
        if not req.overwrite:
            raise VideoConflictError(f"映像ジョブ '{vid}' は既に存在します。")
        _terminate_existing_worker(vdir)
        _safe_rmtree(vdir)
    live = vdir / "live"
    live.mkdir(parents=True, exist_ok=True)

    pre_json = ""
    if pre_settings is not None:
        pre_path = vdir / "preprocess.json"
        pre_path.write_text(pre_settings.model_dump_json(), encoding="utf-8")
        pre_json = str(pre_path)

    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "video_job_id": vid,
        "train_job_id": req.train_job_id,
        "weight_type": req.weight_type,
        "source_type": req.source_type,
        "camera_index": req.camera_index if req.source_type == "camera" else None,
        "source_url": req.source_url if req.source_type == "url" else None,
        "resolved_source_url": resolved_url,
        "video_fps": req.video_fps,
        "infer_fps": req.infer_fps,
        "preprocess_mode": req.preprocess_mode,
        "conf": req.conf,
        "iou": req.iou,
        "imgsz": req.imgsz,
        "device": req.device,
        "status": "queued",
        "message": f"queued（{resolve_note}）" if resolve_note else "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    _job_json_path(name, vid).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_path = vdir / "video.log"
    log_path.touch()

    source_arg = resolved_url if req.source_type == "url" else str(req.camera_index)
    cmd = [
        sys.executable, str(_WORKER),
        "--job-json", str(_job_json_path(name, vid)),
        "--live-dir", str(live),
        "--weight", str(weight),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", req.source_type,
        "--source", source_arg,
        "--video-fps", str(req.video_fps),
        "--infer-fps", str(req.infer_fps),
        "--conf", str(req.conf),
        "--iou", str(req.iou),
        "--imgsz", str(req.imgsz),
        "--device", req.device,
    ]
    if pre_json:
        cmd += ["--preprocess-json", pre_json]

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
    # 読み直してから pid だけ加える（update_settings/ワーカー側 _update_job と同じ
    # ロックファイルで排他する）。
    lock_path = _job_lock_path(name, vid)
    _acquire_file_lock(lock_path)
    try:
        current = _read_job(name, vid) or job
        current["pid"] = proc.pid
        _job_json_path(name, vid).write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        _release_file_lock(lock_path)

    return get_job(name, vid)


def update_settings(name: str, vid: str, payload: VideoJobSettingsUpdate) -> VideoJobInfo:
    """実行中/待機中ジョブのFPS・推論設定を即時変更する（未指定項目は現状維持）。

    ワーカーは job.json を定期的に読み直して反映するため、ここでは値を検証して
    job.json を更新するだけでよい（再接続を伴うカメラ/URL/モデル/前処理は対象外）。
    """
    _require_project(name)
    vdir = paths.video_job_dir(name, vid)
    if not vdir.exists():
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")

    # ワーカー(predict_video_worker.py)も job.json を定期的に read-modify-write するため、
    # ロックなしだと片方の更新が失われ得る。同じロックファイルで直列化する。
    lock_path = _job_lock_path(name, vid)
    _acquire_file_lock(lock_path)
    try:
        job = _read_job(name, vid)
        if job is None:
            raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")

        video_fps = payload.video_fps if payload.video_fps is not None else job.get("video_fps", 15)
        infer_fps = payload.infer_fps if payload.infer_fps is not None else job.get("infer_fps", 5)
        conf = payload.conf if payload.conf is not None else job.get("conf", 0.25)
        iou = payload.iou if payload.iou is not None else job.get("iou", 0.7)
        imgsz = payload.imgsz if payload.imgsz is not None else job.get("imgsz", 640)
        # 変更対象フィールドだけでなく、現状維持されるフィールドも含めた「更新後の値」で
        # まとめて検証してから書き込む。一部フィールドだけ検証・反映して途中で失敗する
        # partial update（例: confだけ更新されimgszのvalidationで失敗する）を防ぐため、
        # 検証をすべて終えるまで job dict への書き込みは一切行わない。
        _validate_fps_settings(video_fps=video_fps, infer_fps=infer_fps)
        _validate_inference_settings(conf=conf, iou=iou, imgsz=imgsz)

        if payload.video_fps is not None:
            job["video_fps"] = payload.video_fps
        if payload.infer_fps is not None:
            job["infer_fps"] = payload.infer_fps
        if payload.conf is not None:
            job["conf"] = payload.conf
        if payload.iou is not None:
            job["iou"] = payload.iou
        if payload.imgsz is not None:
            job["imgsz"] = payload.imgsz
        if payload.device is not None:
            job["device"] = payload.device

        _job_json_path(name, vid).write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        _release_file_lock(lock_path)
    return get_job(name, vid)


def get_job(name: str, vid: str) -> VideoJobInfo:
    _require_project(name)
    job = _read_job(name, vid)
    if job is None:
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")
    if job.get("status") == "running" and job.get("source_type") == "url" and job.get("source_url"):
        # 実際に映像が取得できている（フレームが書き出されている）ことを確認できたURLを記憶する。
        # （記憶にはraw URL＝job["source_url"]を使う。以降のAPI応答マスク処理より前に実行する。）
        frame_path = paths.video_job_dir(name, vid) / "live" / "latest.jpg"
        try:
            if frame_path.exists() and frame_path.stat().st_size > 0:
                _remember_source(name, vid, job["source_url"])
        except OSError:
            pass

    # API応答（VideoJobInfo）はUI表示にそのまま使われるため、source_url/resolved_source_url は
    # password等の認証情報をマスクした表示用の値にする。実接続・再接続にはjob.json上のraw値
    # （このdictをコピーする前の job）を使うため、この変換はAPI応答にのみ影響する。
    display = dict(job)
    if display.get("source_url"):
        display["source_url"] = mask_url_credentials(display["source_url"])
    if display.get("resolved_source_url"):
        display["resolved_source_url"] = mask_url_credentials(display["resolved_source_url"])
    return VideoJobInfo(project_name=name, stream_url=_stream_url(name, vid), **display)


def list_jobs(name: str) -> VideoJobListResponse:
    _require_project(name)
    root = paths.video_jobs_dir(name)
    jobs: list[VideoJobInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "job.json").exists():
                try:
                    jobs.append(get_job(name, child.name))
                except VideoError:
                    pass
    return VideoJobListResponse(project_name=name, jobs=jobs)


def stop_job(name: str, vid: str) -> VideoJobInfo:
    _require_project(name)
    vdir = paths.video_job_dir(name, vid)
    if not vdir.exists():
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")
    (vdir / "stop.flag").write_text("stop", encoding="utf-8")
    # ワーカー側の read-modify-write と競合しないよう、ここも同じロックで直列化する。
    lock_path = _job_lock_path(name, vid)
    _acquire_file_lock(lock_path)
    try:
        job = _read_job(name, vid) or {}
        if job.get("status") in ("queued", "running"):
            job["status"] = "stopped"
            job["finished_at"] = datetime.now().isoformat(timespec="seconds")
            job["message"] = "stopped by user"
            _job_json_path(name, vid).write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        _release_file_lock(lock_path)
    return get_job(name, vid)


def latest_frame_path(name: str, vid: str) -> Path:
    _require_project(name)
    vdir = paths.video_job_dir(name, vid)
    if not vdir.exists():
        raise VideoNotFoundError(f"映像ジョブ '{vid}' が見つかりません。")
    return vdir / "live" / "latest.jpg"


def mjpeg_generator(name: str, vid: str):
    """live/latest.jpg を繰り返し読み、multipart/x-mixed-replace で配信する。"""
    frame_path = latest_frame_path(name, vid)
    boundary = b"--frame"
    interval = 0.1
    job = _read_job(name, vid) or {}
    fps = job.get("video_fps") or 10
    interval = max(0.03, 1.0 / float(fps))
    deadline = time.time() + 1800  # 安全のため最大30分
    while time.time() < deadline:
        cur = _read_job(name, vid) or {}
        if cur.get("status") in ("stopped", "failed", "completed"):
            # 最終フレームを1枚返して終了
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
