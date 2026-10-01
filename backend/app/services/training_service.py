"""YOLO学習ジョブ基盤。

HTTPリクエスト内で model.train() を直接実行せず、subprocess.Popen で
workers/train_worker.py を起動する。これにより:
- HTTPリクエストをブロックしない
- ログをファイル(train.log)へ流せる
- 学習プロセスをFastAPI本体から分離できる

job.json を runs/train/{job_id} に保存し、状態管理に使う。
パスは pathlib、返却する相対パスはPOSIX区切り。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from ..core import paths
from ..core.config import settings
from ..core.identity import UserIdentity
from ..schemas.training import (
    TrainJobCreate,
    TrainJobInfo,
    TrainJobListResponse,
    TrainJobStartResponse,
    TrainLogLine,
    TrainLogResponse,
)
from . import augmentation_service, log_utils, project_service, video_service
from .augmentation_service import AugmentationValidationError
from .project_service import ProjectError, project_exists

# backend/app/services/training_service.py → backend/workers/train_worker.py
_WORKER = Path(__file__).resolve().parents[2] / "workers" / "train_worker.py"

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")


class TrainError(Exception):
    """学習ジョブ操作の業務エラー。"""


class TrainNotFoundError(TrainError):
    """対象が見つからない（HTTP 404相当）。"""


class TrainValidationError(TrainError):
    """事前チェック失敗（HTTP 400相当）。"""


class TrainConflictError(TrainError):
    """同名ジョブの衝突（HTTP 409相当）。"""


class TrainForbiddenError(TrainError):
    """所有者以外によるcancel要求（HTTP 403相当、Issue #49 §33 UX boundary）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _safe_rmtree(path: Path) -> None:
    """既存ジョブディレクトリを削除する。

    「一部のファイルだけ消えて中途半端な状態になる」ことを避けるため、まず
    同じファイルシステム上のゴミ箱名へリネームしてから削除する。リネームは
    単一のメタデータ操作なので、成功すれば元のパスは即座に空になる（途中で
    一部だけ消えるという状態が起きない）。リネーム自体が失敗する場合
    （中のファイルが使用中で改名すらできない等）は、元のディレクトリを一切
    変更せず例外を送出する。

    以前の実装は shutil.rmtree の onerror でファイルごとの削除失敗を握りつぶし
    ながら処理を継続していたため、ロックされたファイル（train.log等）だけが
    残り、job.json 等の他のファイルは削除済みという中途半端な状態を生んでいた
    （実行中ジョブを誤って上書きした際に job.json が消失した根本原因）。
    """
    if not path.exists():
        return

    trash = path.with_name(f"{path.name}.__deleting_{os.getpid()}_{int(time.time() * 1000)}")
    try:
        os.rename(path, trash)
    except OSError as e:
        raise TrainConflictError(
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
    # リネームには成功しているので、元の job_id のパスは既に空いており新規ジョブは
    # 安全に作成できる。ゴミ箱側の削除だけが残った場合は警告に留め、処理は継続する。
    print(f"[WARN] 削除予定ディレクトリの完全な削除に失敗しました（残存: {trash}）: {last_err!r}")


_ACTIVE_STATUSES = {"queued", "running"}


def _pid_alive(pid: int) -> bool:
    """PIDのプロセスが現在も存在するかを確認する（シグナル送信・終了は行わない）。

    Windowsでは os.kill(pid, 0) が実際に TerminateProcess を呼び出してしまうため
    生存確認には使えない。tasklist で確認する
    （backend/tests/smoke_capture.py 等、他のワーカーPID確認と同じ手法）。
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


def _terminate(pid: int) -> None:
    """学習プロセス（Ultralytics含む子プロセスツリー）を終了させる（Issue #49 §32）。

    Ultralyticsのmodel.train()はブロッキング呼び出しでepoch間フックによる
    協調的停止の仕組みを持たないため、video_service.stop_job()のような
    stop.flag方式ではなく直接プロセスを終了させる。Windowsでは子プロセス
    （dataloader worker等）も含めて終了させるため taskkill /T を使う。
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError:
            pass
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def _is_job_active(run_dir: Path) -> bool:
    """既存ジョブが実行中（＝ディレクトリへ一切触れてはいけない状態）かどうかを判定する。

    job.json が読めない場合は判定不能として安全側（実行中とみなす）に倒す
    （壊れたjob.jsonを理由に誤って削除してしまうことを防ぐ）。
    status が queued/running でなくても、記録済みPIDのプロセスがまだ生きていれば
    実行中とみなす（statusの更新漏れ・クラッシュ以外の理由で古いままのケースへの保険）。
    """
    job_json = run_dir / "job.json"
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


def _count_images(d: Path) -> int:
    if not d.exists():
        return 0
    return sum(
        1 for p in d.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    )


def _job_json_path(name: str, job_id: str) -> Path:
    return paths.train_job_dir(name, job_id) / "job.json"


def _job_lock_path(name: str, job_id: str) -> Path:
    """job.jsonのread-modify-write（起動直後のPID記録・ワーカー自身の状態更新）を
    直列化するための簡易ロック。video_service._job_lock_pathと同じ考え方（同名の
    ロックファイル規約・同じ排他生成方式）。train_worker.py側もpredict_video_worker.py
    の_update_job（同じロック実装）を再利用しているため、両者は同じロックで排他される。
    """
    return Path(str(_job_json_path(name, job_id)) + ".lock")


def _prepare_data_train_yaml(ds_dir: Path) -> Path:
    """学習用の data_train.yaml を生成する（既存 data.yaml は破壊しない）。

    Ultralytics は相対 `path` を自身の datasets_dir 基準で解決してしまうため、
    `path` を必ずデータセットの絶対パス(POSIX)へ正規化して書き出す。
    train/val/test/names は元の data.yaml を踏襲する。
    """
    src = ds_dir / "data.yaml"
    data: dict = {}
    if src.exists():
        try:
            data = yaml.safe_load(src.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError:
            data = {}
    data["path"] = ds_dir.resolve().as_posix()
    data.setdefault("train", "images/train")
    data.setdefault("val", "images/val")
    data.setdefault("test", "images/test")
    out = ds_dir / "data_train.yaml"
    # Issue #49: shared server modeのFIFOキューでは、同一datasetへ複数ジョブが
    # ほぼ同時にprepare_job()される状況が起き得る（直列実行だったlocal modeでは
    # 顕在化しなかった既存の潜在バグ）。同一ファイルへの並行書き込みで
    # Windows上 OSError: [Errno 22] Invalid argument を実際に観測したため、
    # 一意な一時ファイル名 + os.replace による原子的置換へ変更する
    # （video_service._write_job_jsonと同じ考え方）。書き込む内容自体は
    # 呼び出し元に依らず決定的（同一ds_dirなら同一内容）なので、置換順が
    # 入れ替わっても最終結果は壊れない。
    tmp = ds_dir / f"data_train.yaml.tmp.{os.getpid()}.{threading.get_ident()}"
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    for attempt in range(20):
        try:
            os.replace(tmp, out)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01)
    return out


def _validate_dataset_paths(ds_dir: Path) -> None:
    """学習前に train/val の実在と画像枚数、labels の存在を検証する（400用）。"""
    train_img = ds_dir / "images" / "train"
    val_img = ds_dir / "images" / "val"
    if not train_img.exists():
        raise TrainValidationError(
            f"data.yaml の train パスが存在しません: {train_img.resolve().as_posix()}。"
            "データセットを再作成してください。"
        )
    if not val_img.exists():
        raise TrainValidationError(
            f"data.yaml の val パスが存在しません: {val_img.resolve().as_posix()}。"
            "データセットを再作成してください。"
        )
    if _count_images(train_img) < 1:
        raise TrainValidationError("train画像が1枚もありません。")
    if _count_images(val_img) < 1:
        raise TrainValidationError("val画像が1枚もありません。")
    if not (ds_dir / "labels" / "train").exists():
        raise TrainValidationError("labels/train が存在しません。データセットを再作成してください。")
    if not (ds_dir / "labels" / "val").exists():
        raise TrainValidationError("labels/val が存在しません。データセットを再作成してください。")


def _read_job(name: str, job_id: str) -> dict | None:
    p = _job_json_path(name, job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # workerのjob.json書き込み（atomicなos.replace）と稀にタイミングが重なると、
        # Windowsでは読込側が一時的にPermissionErrorになり得る（Issue #30/#33で実測確認）。
        return None


def _iso_mtime(p: Path) -> str | None:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


def _synthesize_external_job(name: str, run_dir: Path) -> dict | None:
    """job.json が存在しないrun（Ultralytics直接実行等、アプリの学習APIを経由しない
    外部/直接生成run）向けに、weights(best.pt/last.pt)が存在する場合のみ最小限の
    TrainJobInfo相当を合成する（Issue #14 Checkpoint 2）。

    job.json が存在するrun（内容が壊れている場合を含む）には一切適用しない
    （呼び出し側で job.json の存在有無を判定してから呼ぶこと）。
    weightsが1つも無いrunはNoneを返し、一覧には含めない（空runの誤表示防止）。
    """
    weights_dir = run_dir / "weights"
    best = weights_dir / "best.pt"
    last = weights_dir / "last.pt"
    has_best = best.exists()
    has_last = last.exists()
    if not (has_best or has_last):
        return None

    proj_dir = paths.project_dir(name)

    def _rel(p: Path) -> str:
        return p.relative_to(proj_dir).as_posix()

    results_csv = run_dir / "results.csv"
    created = _iso_mtime(run_dir) or _iso_mtime(best if has_best else last)
    finished_candidates = [
        t for t in (_iso_mtime(best) if has_best else None, _iso_mtime(last) if has_last else None) if t
    ]
    finished = max(finished_candidates) if finished_candidates else created

    return {
        "job_id": run_dir.name,
        "job_name": run_dir.name,
        # weightsが存在する時点で学習自体は完了しているとみなす（既存enum制約はなく
        # 単なる文字列フィールドのため、既存statusの一つ"completed"をそのまま使う）。
        "status": "completed",
        "created_at": created,
        "started_at": None,
        "finished_at": finished,
        "return_code": 0,
        "run_path": _rel(run_dir),
        "best_model_path": _rel(best) if has_best else None,
        "last_model_path": _rel(last) if has_last else None,
        "results_csv_path": _rel(results_csv) if results_csv.exists() else None,
        "message": (
            "外部/直接実行run（job.json無し）として検出されたエントリです。"
            "学習条件（dataset/epochs等）の詳細情報は保持されていません。"
        ),
    }


def _check_free_disk(proj_dir: Path) -> None:
    """学習開始前の空きディスク容量チェック（Issue #49 §54、軽量・stdlibのみ）。

    GPU空き容量の確認は行わない（training_service はFastAPI本体内で常時importされる
    軽量プロセス側のモジュールであり、torch等の重量依存を持ち込まない方針のため。
    CLAUDE.md「軽量/重量依存の分離」参照）。
    """
    try:
        free = shutil.disk_usage(proj_dir).free
    except OSError:
        return  # 取得できない場合はチェックをスキップ（安全側: ブロックしない）
    if free < settings.train_min_free_disk_bytes:
        min_gb = settings.train_min_free_disk_bytes / (1024**3)
        raise TrainValidationError(
            f"空きディスク容量が不足しています（最低 {min_gb:.1f}GB 必要）。"
            "不要なデータを削除してから再試行してください。"
        )


def prepare_job(
    name: str, req: TrainJobCreate, identity: UserIdentity | None = None
) -> str:
    """学習ジョブを検証し、job.json(status=queued)を書き込む（起動はしない）。

    Popen自体はlaunch_job()が別途行う。shared server modeではこの間に
    TrainingQueueServiceがGPU空き待ちでキューイングし得るため、
    「検証・job.json作成」と「実際の起動」を分離している（Issue #49 §18）。
    """
    _require_project(name)

    if not paths.is_valid_project_name(req.job_name):
        raise TrainValidationError(
            "job_name は英数・アンダースコア・ハイフンのみ使用できます。"
        )

    # タスク種別（未指定ならプロジェクトの task を使用）
    task = req.task or project_service.get_task(name)
    if task not in project_service.VALID_TASKS:
        raise TrainValidationError(
            f"task は {' / '.join(project_service.VALID_TASKS)} のいずれかです。"
        )

    # --- 事前チェック ---
    ds_dir = paths.dataset_dir(name, req.dataset_name)
    if not ds_dir.exists():
        raise TrainNotFoundError(
            f"データセット '{req.dataset_name}' が見つかりません。"
        )
    data_yaml = ds_dir / "data.yaml"
    if not data_yaml.exists():
        raise TrainValidationError("data.yaml が存在しません。")
    # train/val パスを事前検証（分かりやすく失敗させる）
    _validate_dataset_paths(ds_dir)
    # Ultralytics 実行用に path を絶対パス化した data_train.yaml を用意（既存data.yaml非破壊）
    _prepare_data_train_yaml(ds_dir)

    # 学習時オーギュメンテーションの解決（未指定なら standard）
    try:
        aug_preset, aug_params = augmentation_service.resolve(
            name, req.augmentation_preset, req.augmentation_params
        )
    except AugmentationValidationError as e:
        raise TrainValidationError(str(e)) from e

    job_id = req.job_name
    run_dir = paths.train_job_dir(name, job_id)
    if run_dir.exists():
        # 実行中ジョブは overwrite の値に関わらず一切削除しない（ファイルにも触れない）。
        # ここで弾かなければ、_safe_rmtree が実行中プロセスのディレクトリを削除しにいってしまう。
        if _is_job_active(run_dir):
            raise TrainConflictError(
                f"学習ジョブ '{job_id}' は実行中のため上書きできません。"
                "完了を待つか、別の job_name を指定してください。"
            )
        if not req.overwrite:
            raise TrainConflictError(
                f"学習ジョブ '{job_id}' は既に存在します。"
            )
        _safe_rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    proj_dir = paths.project_dir(name)
    _check_free_disk(proj_dir)
    rel_run = run_dir.relative_to(proj_dir).as_posix()
    log_path = run_dir / "train.log"
    log_path.touch()  # ログ取得APIが即座に動くように空ファイルを用意

    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "job_id": job_id,
        "job_name": req.job_name,
        "dataset_name": req.dataset_name,
        "task": task,
        "model": req.model,
        "epochs": req.epochs,
        "imgsz": req.imgsz,
        "batch": req.batch,
        "device": req.device,
        "workers": req.workers,
        "patience": req.patience,
        "seed": req.seed,
        "status": "queued",
        "created_at": now,
        "queued_at": now,
        "started_at": None,
        "finished_at": None,
        "return_code": None,
        "run_path": rel_run,
        "best_model_path": None,
        "last_model_path": None,
        "results_csv_path": None,
        "message": "queued",
        "augmentation_preset": aug_preset,
        "augmentation_params": aug_params,
        # Issue #49: job所有者識別用（認証ではない）。未指定(local mode等)はNone。
        "owner_user_id": identity.user_id if identity else None,
        "owner_display_name": identity.display_name if identity else None,
    }
    video_service._write_job_json(_job_json_path(name, job_id), job)
    return job_id


def launch_job(name: str, job_id: str) -> TrainJobStartResponse:
    """job.json(status=queued)が既に存在するジョブを実際に起動する（Popen）。

    job.jsonに保存済みの学習条件からコマンドを再構築するため、backend再起動後
    (restart recovery)や、キュー内で待機していたジョブの昇格時にも、prepare_job
    呼び出し時のメモリ上の値を保持する必要なく呼び出せる（Issue #49 §22/§23）。
    """
    job = _read_job(name, job_id)
    if job is None:
        raise TrainNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")

    run_dir = paths.train_job_dir(name, job_id)
    proj_dir = paths.project_dir(name)
    rel_run = run_dir.relative_to(proj_dir).as_posix()
    log_path = run_dir / "train.log"
    ds_dir = paths.dataset_dir(name, job["dataset_name"])
    data_train_yaml = ds_dir / "data_train.yaml"

    # --- worker をサブプロセスで起動（ノンブロッキング）---
    cmd = [
        sys.executable,
        str(_WORKER),
        "--job-json", str(_job_json_path(name, job_id)),
        "--data-yaml", str(data_train_yaml),
        "--run-dir", str(run_dir),
        "--project-dir", str(proj_dir),
        "--model", job["model"],
        "--epochs", str(job["epochs"]),
        "--imgsz", str(job["imgsz"]),
        "--batch", str(job["batch"]),
        "--device", job["device"],
        "--workers", str(job["workers"]),
        "--patience", str(job["patience"]),
        "--seed", str(job["seed"]),
    ]
    # 子プロセスの出力を UTF-8 に固定（Windows CP932 による文字化け防止）
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=str(proj_dir),
            env=env,
        )
    finally:
        # 子プロセスは自身のOSハンドルを保持するので親側は閉じてよい
        log_f.close()

    # 起動直後にPIDを記録しておく（実行中判定の保険。capture/video系と同じ考え方）。
    # ワーカーは起動後すぐ status=running 等で job.json を更新し得るため、メモリ上の
    # 古い job dict でそのまま上書きすると更新が消える。ロックを取って現在の内容を
    # 読み直してから pid だけ加える（train_worker.py側もpredict_video_worker.pyの
    # _update_job（同じロック実装）を再利用しているため、同じロックファイルで排他される。
    # Issue #33で他job種別（capture/video/selection）と同じ方式へ揃えた）。
    lock_path = _job_lock_path(name, job_id)
    video_service._acquire_file_lock(lock_path)
    try:
        current = _read_job(name, job_id) or job
        current["pid"] = proc.pid
        video_service._write_job_json(_job_json_path(name, job_id), current)
    finally:
        video_service._release_file_lock(lock_path)

    return TrainJobStartResponse(
        project_name=name,
        job_id=job_id,
        job_name=job["job_name"],
        status="queued",
        run_path=rel_run,
        log_path=f"{rel_run}/train.log",
    )


def terminate_and_mark_cancelled(
    name: str, job_id: str, identity: UserIdentity | None = None
) -> TrainJobInfo:
    """実行中/待機中の学習ジョブを強制終了し、job.jsonをcancelledにする（Issue #49 §32）。

    queued状態（まだPopenされていない）の場合はプロセス終了は不要でstatus更新のみ。
    所有者チェックはセキュリティ境界ではなくUX境界（Issue #49 §33）: identityの
    user_idが指定され、かつjob側にもowner_user_idが記録されている場合のみ、
    不一致ならTrainForbiddenErrorとする（どちらか未指定なら従来通り許可する）。
    """
    job = _read_job(name, job_id)
    if job is None:
        raise TrainNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")

    status = job.get("status")
    if status in ("completed", "failed", "cancelled"):
        raise TrainConflictError(
            f"学習ジョブ '{job_id}' は既に終了しています（status={status}）。"
        )

    owner_user_id = job.get("owner_user_id")
    if identity is not None and identity.user_id and owner_user_id:
        if identity.user_id != owner_user_id:
            raise TrainForbiddenError(
                "自分が投入したジョブのみキャンセルできます。"
            )

    pid = job.get("pid")
    if isinstance(pid, int) and _pid_alive(pid):
        _terminate(pid)

    lock_path = _job_lock_path(name, job_id)
    video_service._acquire_file_lock(lock_path)
    try:
        current = _read_job(name, job_id) or job
        current["status"] = "cancelled"
        current["finished_at"] = datetime.now().isoformat(timespec="seconds")
        current["message"] = "cancelled by user"
        video_service._write_job_json(_job_json_path(name, job_id), current)
    finally:
        video_service._release_file_lock(lock_path)

    return get_job(name, job_id)


def _mark_interrupted(name: str, job_id: str) -> None:
    """backend再起動後、running中だったはずのジョブのPIDが消えていた場合に呼ぶ
    （Issue #49 §23/§24/§25）。

    同じoutput directoryへの自動再学習は絶対に行わない。failedとして明示し、
    ユーザーが内容を確認した上で必要なら再投入する方式を採る。
    """
    lock_path = _job_lock_path(name, job_id)
    video_service._acquire_file_lock(lock_path)
    try:
        current = _read_job(name, job_id)
        if current is None:
            return
        if current.get("status") in ("completed", "failed", "cancelled"):
            return
        current["status"] = "failed"
        current["finished_at"] = datetime.now().isoformat(timespec="seconds")
        current["message"] = (
            "host reboot/backend再起動によりジョブが中断されました。"
            "安全のため自動再開はしていません。必要な場合は再投入してください"
            "（Issue #49 §24/§25）。"
        )
        video_service._write_job_json(_job_json_path(name, job_id), current)
    finally:
        video_service._release_file_lock(lock_path)


def start_job(
    name: str, req: TrainJobCreate, identity: UserIdentity | None = None
) -> TrainJobStartResponse:
    """従来互換のショートカット（prepare_job→launch_jobを連続実行）。

    local mode（shared_server_mode=False）はこの関数のまま常に即時起動する
    （既存の1ユーザー利用の挙動を一切変えない、Issue #49 §4）。
    shared server modeではrouter層がprepare_job/launch_jobを個別に呼び出し、
    TrainingQueueService経由でキューイングする。
    """
    job_id = prepare_job(name, req, identity)
    return launch_job(name, job_id)


def get_job(name: str, job_id: str) -> TrainJobInfo:
    _require_project(name)
    job = _read_job(name, job_id)
    if job is None:
        raise TrainNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")
    return TrainJobInfo(project_name=name, **job)


def list_jobs(name: str) -> TrainJobListResponse:
    _require_project(name)
    root = paths.train_runs_dir(name)
    jobs: list[TrainJobInfo] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            job = _read_job(name, child.name)
            if job is None and not _job_json_path(name, child.name).exists():
                # job.json自体が存在しない外部/直接実行runのみ合成対象とする。
                # job.jsonはあるが読めない(壊れている)場合はNoneのまま=従来どおり除外する
                # (既存の「壊れたjob.jsonは一覧から除外」という挙動を変えない)。
                job = _synthesize_external_job(name, child)
            if job is not None:
                jobs.append(TrainJobInfo(project_name=name, **job))
    return TrainJobListResponse(project_name=name, jobs=jobs)


def get_logs(name: str, job_id: str) -> TrainLogResponse:
    _require_project(name)
    run_dir = paths.train_job_dir(name, job_id)
    if not run_dir.exists():
        raise TrainNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")
    log_path = run_dir / "train.log"
    raw = log_path.read_text(encoding="utf-8-sig", errors="replace") if log_path.exists() else ""
    log = log_utils.strip_ansi(raw)
    lines = [TrainLogLine(**d) for d in log_utils.build_lines(log)]
    summary = log_utils.error_summary(log)
    # job.json の message に分かりやすい要約があればそれも優先候補に
    if summary is None:
        job = _read_job(name, job_id)
        if job and job.get("status") == "failed" and job.get("message"):
            summary = job["message"]
    return TrainLogResponse(job_id=job_id, log=log, lines=lines, error_summary=summary)
