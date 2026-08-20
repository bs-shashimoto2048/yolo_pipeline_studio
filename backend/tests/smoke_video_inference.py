"""映像（カメラ）推論基盤の軽量スモークテスト。

実カメラ/Ultralyticsは使わない。ワーカーは YTS_VIDEO_DRY_RUN=1 で合成フレームを
live/latest.jpg に書き出すだけ。検証項目:
  - GET /cameras が 200
  - バリデーション（学習ジョブ不在/weight不在/fps範囲/preprocess_mode）
  - ジョブ作成 → job.json 生成 → 合成フレーム出力
  - ジョブ取得/一覧
  - 停止後に /stream が最終フレームを1枚返して終了する

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_video_inference.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_video_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_VIDEO_DRY_RUN"] = "1"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas.video import VideoJobSettingsUpdate  # noqa: E402
from app.services import video_service  # noqa: E402
import predict_video_worker  # noqa: E402

client = TestClient(app)
PROJ = "video_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_fake_train_job(job_id: str, with_best: bool = True) -> None:
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"job_id": job_id, "status": "completed"}), encoding="utf-8"
    )
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"fake-weight")


def wait_frame(vid: str) -> bool:
    latest = ROOT / PROJ / "video" / vid / "live" / "latest.jpg"
    for _ in range(50):
        time.sleep(0.2)
        if latest.exists() and latest.stat().st_size > 0:
            return True
    return False


def vdir(vid: str) -> Path:
    return ROOT / PROJ / "video" / vid


def read_job(vid: str) -> dict:
    p = vdir(vid) / "job.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def wait_status(vid: str, targets: set, timeout: float = 20.0) -> str | None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = read_job(vid).get("status")
        if last in targets:
            return last
        time.sleep(0.2)
    return last


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    tl = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
    return str(pid) in tl.stdout


def wait_pid_gone(pid: int | None, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    return not pid_alive(pid)


def job_body(vid: str, **overrides) -> dict:
    body = {
        "video_job_name": vid,
        "train_job_id": "train_001",
        "weight_type": "best",
        "source_type": "camera",
        "camera_index": 0,
        "video_fps": 15,
        "infer_fps": 5,
        "conf": 0.25,
        "iou": 0.7,
        "imgsz": 640,
        "device": "auto",
        "preprocess_mode": "none",
        "overwrite": False,
    }
    body.update(overrides)
    return body


def start_dryrun_job(vid: str, **overrides) -> dict:
    """dry-run（合成フレーム）で実際に動くワーカーを起動する（overwrite保護テスト用）。"""
    make_fake_train_job("train_001", with_best=True)
    r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, **overrides))
    check(f"start_dryrun_job({vid}) 201", r.status_code == 201)
    return r.json()


def stop_and_wait(vid: str) -> None:
    r = client.post(f"/api/projects/{PROJ}/video-jobs/{vid}/stop")
    check(f"stop {vid} 200", r.status_code == 200)
    pid = read_job(vid).get("pid")
    check(f"{vid} worker pid exits after stop", wait_pid_gone(pid, timeout=10.0))


def test_url_validation_and_resolve() -> None:
    """resolve_source_url() のバリデーション・URL解決（外部アクセス不要・純粋なURL文字列処理）。"""
    # --- 正常なHTTP/HTTPS URL ---
    url, note = video_service.resolve_source_url("http://192.168.1.10/stream.mjpg")
    check("resolve: plain http unchanged", url == "http://192.168.1.10/stream.mjpg" and note is None)
    url, note = video_service.resolve_source_url("https://192.168.1.10:8443/stream.mjpg")
    check("resolve: plain https unchanged", url == "https://192.168.1.10:8443/stream.mjpg" and note is None)

    # --- RTSP/RTSPS はクエリ解決の対象外（そのまま） ---
    url, note = video_service.resolve_source_url("rtsp://192.168.1.10:554/ch1?imagepath=/x")
    check("resolve: rtsp unchanged even with query", url == "rtsp://192.168.1.10:554/ch1?imagepath=/x" and note is None)
    url, note = video_service.resolve_source_url("rtsps://192.168.1.10:554/ch1")
    check("resolve: rtsps unchanged", url == "rtsps://192.168.1.10:554/ch1" and note is None)

    # --- スキーム省略時は http を補完 ---
    url, note = video_service.resolve_source_url("192.168.1.10/view.shtml")
    check("resolve: scheme omitted -> http補完", url.startswith("http://192.168.1.10"))

    # --- file:// は拒否 ---
    try:
        video_service.resolve_source_url("file:///etc/passwd")
        check("resolve: file scheme rejected", False)
    except video_service.VideoValidationError:
        check("resolve: file scheme rejected", True)

    # --- 未対応スキーム（ftp等）は拒否 ---
    try:
        video_service.resolve_source_url("ftp://192.168.1.10/x")
        check("resolve: unsupported scheme rejected", False)
    except video_service.VideoValidationError:
        check("resolve: unsupported scheme rejected", True)

    # --- ホスト無し等の不正URL ---
    try:
        video_service.resolve_source_url("http:///no-host")
        check("resolve: hostless url rejected", False)
    except video_service.VideoValidationError:
        check("resolve: hostless url rejected", True)

    # --- 空URL ---
    try:
        video_service.resolve_source_url("   ")
        check("resolve: empty url rejected", False)
    except video_service.VideoValidationError:
        check("resolve: empty url rejected", True)

    # --- imagepath/imgpath/streampath/path クエリの解決 ---
    for key in ("imagepath", "imgpath", "streampath", "path"):
        viewer = f"http://192.168.1.10/view/view.shtml?id=1&{key}=%2Fmjpg%2Fvideo.mjpg%3Fcamera%3D1"
        url, note = video_service.resolve_source_url(viewer)
        check(f"resolve: {key} query resolved", url == "http://192.168.1.10/mjpg/video.mjpg?camera=1")
        check(f"resolve: {key} note present", note is not None and "video.mjpg" in note)

    # --- 代表的なHTML/ビューワURL → 実ストリームURL解決（ネットワークカメラのview.shtml系を想定） ---
    viewer = "http://192.168.1.10/axis-cgi/view.shtml?resolution=640x480&imagepath=%2Fmjpg%2Fvideo.mjpg"
    url, note = video_service.resolve_source_url(viewer)
    check("resolve: viewer-page url resolved to real stream url", url == "http://192.168.1.10/mjpg/video.mjpg")

    # --- クエリはあるが対象キーが無ければそのまま ---
    url, note = video_service.resolve_source_url("http://192.168.1.10/stream.mjpg?token=abc")
    check("resolve: unrelated query untouched", url == "http://192.168.1.10/stream.mjpg?token=abc" and note is None)


def test_mask_url_credentials() -> None:
    """URL中の認証情報マスク（ログ・エラーメッセージ表示用）の回帰テスト。"""
    masked = video_service.mask_url_credentials("http://admin:secret123@192.168.1.10:8080/view.shtml")
    check("mask: password masked", "secret123" not in masked and "***" in masked and "admin" in masked)

    plain = "http://192.168.1.10/stream.mjpg"
    check("mask: no credentials -> unchanged", video_service.mask_url_credentials(plain) == plain)

    user_only = "http://admin@192.168.1.10/stream.mjpg"
    check("mask: username only (no password) -> unchanged", video_service.mask_url_credentials(user_only) == user_only)

    # ワーカー側の自己完結な実装（別プロセスのため意図的に重複実装）も同じ結果になること
    sample = "http://admin:secret123@192.168.1.10/x"
    check(
        "mask: worker implementation matches video_service",
        predict_video_worker._mask_url_credentials(sample) == video_service.mask_url_credentials(sample),
    )

    # resolve_source_url のノート（表示用メッセージ）にパスワードが平文で出ないこと
    viewer = "http://admin:secret123@192.168.1.10/view/view.shtml?imagepath=%2Fmjpg%2Fvideo.mjpg"
    resolved, note = video_service.resolve_source_url(viewer)
    check("resolve note masks password", note is not None and "secret123" not in note and "***" in note)
    # 接続そのものには実URL（パスワード含む）が使われる（マスクは表示のみ）
    check("resolve return value keeps real credentials for connecting", "secret123" in resolved)

    # ワーカーの表示用ラベル（接続失敗メッセージ等に使われる）もパスワードを含まない
    label = predict_video_worker._source_label("url", sample)
    check("worker source label masks password", "secret123" not in label and "***" in label)


def test_known_sources() -> None:
    """known_sources.json の保存・再読込・重複登録・削除・破損時の復旧。"""
    video_dir = ROOT / PROJ / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    known_path = video_dir / "known_sources.json"
    if known_path.exists():
        known_path.unlink()

    # --- 保存 ---
    video_service._remember_source(PROJ, "vidA", "http://cam1.example/stream.mjpg")
    r = client.get(f"/api/projects/{PROJ}/video-sources")
    check("known_sources: save 200", r.status_code == 200)
    urls = [s["url"] for s in r.json()["sources"]]
    check("known_sources: saved url present", "http://cam1.example/stream.mjpg" in urls)

    # --- 再読込（プロセス内キャッシュに依存せず、ファイルから読める） ---
    reloaded = video_service._load_known_sources_at(known_path)
    check("known_sources: reload from disk", any(s["url"] == "http://cam1.example/stream.mjpg" for s in reloaded))

    # --- 重複登録時の挙動（同一URLは先頭へ更新、重複エントリは作らない） ---
    video_service._remember_source(PROJ, "vidB", "http://cam2.example/stream.mjpg")
    video_service._remember_source(PROJ, "vidC", "http://cam1.example/stream.mjpg")  # 既存URLを別ジョブから再登録
    sources = video_service._load_known_sources(PROJ)
    cam1_entries = [s for s in sources if s["url"] == "http://cam1.example/stream.mjpg"]
    check("known_sources: no duplicate entries", len(cam1_entries) == 1)
    check("known_sources: video_job_id updated to latest", cam1_entries[0]["video_job_id"] == "vidC")
    check("known_sources: re-registered url moved to front", sources[0]["url"] == "http://cam1.example/stream.mjpg")

    # --- 削除 ---
    r = client.delete(f"/api/projects/{PROJ}/video-sources", params={"url": "http://cam2.example/stream.mjpg"})
    check("known_sources: delete 200", r.status_code == 200)
    urls_after = [s["url"] for s in r.json()["sources"]]
    check("known_sources: deleted url gone", "http://cam2.example/stream.mjpg" not in urls_after)

    # --- 存在しないsource削除時の仕様（エラーにせず、現状のリストをそのまま返す） ---
    r = client.delete(f"/api/projects/{PROJ}/video-sources", params={"url": "http://not-registered.example/x"})
    check("known_sources: delete missing url -> 200 (idempotent)", r.status_code == 200)
    check("known_sources: delete missing url leaves list unchanged", len(r.json()["sources"]) == len(urls_after))

    # --- 壊れたknown_sources.jsonから安全に復旧 ---
    known_path.write_text("{not valid json!!", encoding="utf-8")
    r = client.get(f"/api/projects/{PROJ}/video-sources")
    check("known_sources: corrupt file -> 200", r.status_code == 200)
    check("known_sources: corrupt file -> empty list (no crash)", r.json()["sources"] == [])

    # 壊れたファイルの後でも新規登録は正しく上書き保存できる
    video_service._remember_source(PROJ, "vidD", "http://cam3.example/stream.mjpg")
    r = client.get(f"/api/projects/{PROJ}/video-sources")
    check(
        "known_sources: recovers and saves after corruption",
        any(s["url"] == "http://cam3.example/stream.mjpg" for s in r.json()["sources"]),
    )


def test_overwrite_protection() -> None:
    """実行中Video Jobのoverwrite保護（training_serviceと同じ考え方）の回帰テスト。"""
    vid = "ov_active"

    res = start_dryrun_job(vid)
    check("ov: initial status queued/running", res["status"] in ("queued", "running"))
    check("ov: frame written", wait_frame(vid))
    status = wait_status(vid, {"running"}, timeout=10.0)
    check("ov: reached running", status == "running")

    job_before = read_job(vid)
    log_path = vdir(vid) / "video.log"
    log_before = log_path.read_bytes() if log_path.exists() else b""
    pid = job_before.get("pid")
    check("ov: pid recorded", isinstance(pid, int))
    check("ov: pid is alive", pid_alive(pid))

    # --- 実行中 + overwrite=false -> 409、ファイル無変更 ---
    r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, overwrite=False))
    check("ov: active+overwrite=false -> 409", r.status_code == 409)
    check("ov: job.json unchanged after overwrite=false attempt", read_job(vid) == job_before)
    check(
        "ov: video.log unchanged after overwrite=false attempt",
        (log_path.read_bytes() if log_path.exists() else b"") == log_before,
    )

    # --- 実行中 + overwrite=true -> 409（実行中チェックが優先）、ファイル無変更 ---
    r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, overwrite=True))
    check("ov: active+overwrite=true -> 409", r.status_code == 409)
    check("ov: job.json unchanged after overwrite=true attempt", read_job(vid) == job_before)
    check(
        "ov: video.log unchanged after overwrite=true attempt",
        (log_path.read_bytes() if log_path.exists() else b"") == log_before,
    )
    check("ov: worker still alive (untouched)", pid_alive(pid))

    # --- statusがstale（既知の値以外に更新漏れ）でもPID生存なら実行中扱い -> 409、ファイル無変更 ---
    # 注意: "stopped"/"failed"/"completed" は実ワーカー自身の _stopped() が停止合図として
    # 検知してしまい、ワーカーが本当に停止してしまうため使えない。ここで確かめたいのは
    # 「status が queued/running 以外の未知の値でも、PIDが生きていれば実行中扱いする」
    # という _is_job_active の PID フォールバックなので、ワーカーに影響しない値を使う。
    stale = dict(job_before)
    stale["status"] = "unexpected_stale_status"
    (vdir(vid) / "job.json").write_text(json.dumps(stale, ensure_ascii=False, indent=2), encoding="utf-8")
    stale_snapshot = read_job(vid)
    r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, overwrite=True))
    check("ov: stale status but pid alive -> 409", r.status_code == 409)
    check("ov: job.json unchanged (stale-status case)", read_job(vid) == stale_snapshot)

    # --- 停止して完了させる ---
    stop_and_wait(vid)
    check("ov: pid no longer alive after stop", not pid_alive(pid))

    # --- 完了済み + PID非生存 + overwrite=true -> 正常に上書き可能 ---
    old_created_at = read_job(vid).get("created_at")
    r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, overwrite=True))
    check("ov: completed+pid dead+overwrite=true -> 201", r.status_code == 201)
    new_job = read_job(vid)
    check("ov: overwrite produced a new job (created_at changed)", new_job.get("created_at") != old_created_at)
    check("ov: overwrite got a new pid", new_job.get("pid") != pid)
    stop_and_wait(vid)


def test_safe_rmtree_rename_failure() -> None:
    """安全削除（rename→delete）でrenameが失敗した場合、既存ジョブを一切変更しないこと。"""
    vid = "ov_rename_fail"
    start_dryrun_job(vid)
    check("rename_fail: frame written", wait_frame(vid))
    stop_and_wait(vid)

    job_before = read_job(vid)
    log_path = vdir(vid) / "video.log"
    log_before = log_path.read_bytes() if log_path.exists() else b""
    check("rename_fail: job not active before test", not video_service._is_job_active(vdir(vid)))

    orig_rename = video_service.os.rename

    def _boom(*_a, **_kw):
        raise OSError("simulated: rename failed (file in use)")

    video_service.os.rename = _boom
    try:
        r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, overwrite=True))
        check("rename_fail: overwrite -> 409 when rename fails", r.status_code == 409)
        check("rename_fail: job.json unchanged", read_job(vid) == job_before)
        check(
            "rename_fail: video.log unchanged",
            (log_path.read_bytes() if log_path.exists() else b"") == log_before,
        )
        check("rename_fail: directory still exists (not partially deleted)", vdir(vid).exists())
    finally:
        video_service.os.rename = orig_rename

    # モンキーパッチ解除後は通常どおり上書きできることも確認（テスト自体の副作用が残っていないこと）
    r = client.post(f"/api/projects/{PROJ}/video-jobs", json=job_body(vid, overwrite=True))
    check("rename_fail: overwrite succeeds after unpatch", r.status_code == 201)
    stop_and_wait(vid)


def test_settings_patch() -> None:
    """PATCH /video-jobs/{vid}/settings の正常系・異常系。"""
    vid = "settings_job"
    start_dryrun_job(vid)
    check("settings: frame written", wait_frame(vid))
    base = f"/api/projects/{PROJ}/video-jobs/{vid}/settings"

    # --- 正常系 ---
    r = client.patch(base, json={"video_fps": 20})
    check("settings: video_fps 200", r.status_code == 200 and r.json()["video_fps"] == 20)
    check("settings: video_fps persisted to job.json", read_job(vid).get("video_fps") == 20)

    r = client.patch(base, json={"infer_fps": 4})
    check("settings: infer_fps 200", r.status_code == 200 and r.json()["infer_fps"] == 4)
    check("settings: infer_fps persisted to job.json", read_job(vid).get("infer_fps") == 4)

    r = client.patch(base, json={"conf": 0.5})
    check("settings: conf 200", r.status_code == 200)
    check("settings: conf persisted to job.json", read_job(vid).get("conf") == 0.5)

    r = client.patch(base, json={"iou": 0.4})
    check("settings: iou 200", r.status_code == 200)
    check("settings: iou persisted to job.json", read_job(vid).get("iou") == 0.4)

    # --- imgsz（32以上のみ許容） ---
    # 注意: VideoJobInfoレスポンススキーマにはimgsz/device/conf/iouフィールドが無いため
    # （既存のconf/iouテストと同様）、応答JSONではなくjob.json実体で検証する。
    r = client.patch(base, json={"imgsz": 320})
    check("settings: imgsz 200", r.status_code == 200)
    check("settings: imgsz persisted to job.json", read_job(vid).get("imgsz") == 320)
    r = client.patch(base, json={"imgsz": 31})
    check("settings: imgsz out of range -> 400", r.status_code == 400)
    check("settings: imgsz value intact after rejected update", read_job(vid).get("imgsz") == 320)

    # --- device（現状は範囲validationなし。任意文字列がそのまま保存されること） ---
    r = client.patch(base, json={"device": "cpu"})
    check("settings: device 200", r.status_code == 200)
    check("settings: device persisted to job.json", read_job(vid).get("device") == "cpu")

    # --- 複数フィールド同時更新（1リクエストで一括反映され、job.jsonへ全て正しく書き込まれること） ---
    r = client.patch(
        base,
        json={"video_fps": 30, "infer_fps": 10, "conf": 0.6, "iou": 0.5, "imgsz": 416, "device": "cuda:0"},
    )
    check("settings: multi-field update 200", r.status_code == 200)
    multi = r.json()
    check(
        "settings: multi-field update response reflects response-schema fields",
        multi["video_fps"] == 30 and multi["infer_fps"] == 10,
    )
    persisted = read_job(vid)
    check(
        "settings: multi-field update persisted to job.json (no field lost)",
        persisted.get("video_fps") == 30
        and persisted.get("infer_fps") == 10
        and persisted.get("conf") == 0.6
        and persisted.get("iou") == 0.5
        and persisted.get("imgsz") == 416
        and persisted.get("device") == "cuda:0",
    )

    # --- 複数フィールド同時更新で一部がvalidationに引っかかる場合、全体が拒否され部分適用されないこと ---
    r = client.patch(base, json={"video_fps": 25, "imgsz": 8})
    check("settings: multi-field update rejected when any field invalid -> 400", r.status_code == 400)
    check(
        "settings: multi-field rejected update -> no partial apply (video_fps unchanged)",
        read_job(vid).get("video_fps") == 30,
    )
    check(
        "settings: multi-field rejected update -> no partial apply (imgsz unchanged)",
        read_job(vid).get("imgsz") == 416,
    )

    # --- 異常系 ---
    r = client.patch(base, json={"video_fps": 0})
    check("settings: video_fps out of range -> 400", r.status_code == 400)
    r = client.patch(base, json={"video_fps": 61})
    check("settings: video_fps out of range(high) -> 400", r.status_code == 400)
    r = client.patch(base, json={"video_fps": 5, "infer_fps": 10})
    check("settings: infer_fps>video_fps -> 400", r.status_code == 400)
    r = client.patch(base, json={"conf": -0.1})
    check("settings: conf out of range -> 400", r.status_code == 400)
    r = client.patch(base, json={"conf": 1.5})
    check("settings: conf out of range(high) -> 400", r.status_code == 400)
    r = client.patch(base, json={"iou": -0.1})
    check("settings: iou out of range -> 400", r.status_code == 400)
    r = client.patch(base, json={"iou": 1.5})
    check("settings: iou out of range(high) -> 400", r.status_code == 400)

    r = client.patch(f"/api/projects/{PROJ}/video-jobs/no_such_job/settings", json={"conf": 0.3})
    check("settings: missing job_id -> 404", r.status_code == 404)

    # 異常系の後でも既存の正常な値が壊れていないこと（多フィールド更新後の値が基準）
    check("settings: values intact after rejected updates", read_job(vid).get("video_fps") == 30)

    stop_and_wait(vid)


def test_create_time_validation_symmetry() -> None:
    """Job作成(start_job)時のconf/iou/imgsz validationが、PATCH(update_settings)と対称であること。

    Checkpoint 2で判明した「PATCHでは拒否されるが作成時は無条件に受理されてしまう」
    非対称性（Production側は video_service._validate_inference_settings への集約で修正済み）
    の回帰防止。作成時にvalidationで拒否された場合、ジョブディレクトリ自体が作成されず
    （部分的な状態を残さず）、既存の他ジョブへも影響しないことも合わせて確認する。
    """
    base = f"/api/projects/{PROJ}/video-jobs"

    def assert_create_rejected(vid: str, **overrides) -> None:
        r = client.post(base, json=job_body(vid, **overrides))
        check(f"create: {vid} invalid -> 400", r.status_code == 400)
        check(f"create: {vid} rejected -> no job directory created", not vdir(vid).exists())

    # --- conf（PATCH側と同じ0.0〜1.0の境界） ---
    assert_create_rejected("create_conf_low", conf=-0.1)
    assert_create_rejected("create_conf_high", conf=1.5)

    # --- iou（PATCH側と同じ0.0〜1.0の境界） ---
    assert_create_rejected("create_iou_low", iou=-0.1)
    assert_create_rejected("create_iou_high", iou=1.5)

    # --- imgsz（PATCH側と同じ32以上） ---
    assert_create_rejected("create_imgsz_low", imgsz=31)

    # --- 正常系（PATCH側で許容される境界値ちょうどで作成できること） ---
    vid = "create_valid_bounds"
    r = client.post(base, json=job_body(vid, conf=0.0, iou=1.0, imgsz=32))
    check("create: boundary conf=0.0/iou=1.0/imgsz=32 -> 201", r.status_code == 201)
    persisted = read_job(vid)
    check(
        "create: boundary values persisted as-is",
        persisted.get("conf") == 0.0 and persisted.get("iou") == 1.0 and persisted.get("imgsz") == 32,
    )
    stop_and_wait(vid)

    # --- device: 現状仕様どおり検証を行わないため、多様な表記のdeviceで作成できること ---
    #     （device専用のvalidationは意図的に未実装。理由は video_service._validate_inference_settings
    #     のdocstring、およびCheckpoint 2/3の報告を参照。Ultralyticsのdevice引数はcpu/mps/cuda/
    #     cuda:0/0/0,1等、多様な表記を正当な値として受理するため、単一の仕様を決め打ちしない）。
    vid = "create_device_arbitrary"
    r = client.post(base, json=job_body(vid, device="cuda:1"))
    check("create: arbitrary device string accepted (no validation by design) -> 201", r.status_code == 201)
    check("create: device persisted as-is", read_job(vid).get("device") == "cuda:1")
    stop_and_wait(vid)


def test_job_lock_mutual_exclusion() -> None:
    """job.json 用ロック（_acquire_file_lock/_release_file_lock）が実際に排他できていること。

    別プロセス間の排他まではスレッドテストで直接は確認できないが、OSの排他生成
    (O_CREAT|O_EXCL) はプロセスをまたいで有効な仕組みのため、スレッド間で排他できて
    いれば同じ機構がプロセス間でも機能する根拠になる。
    """
    lock_path = ROOT / PROJ / "video" / "lock_test.json.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        lock_path.unlink()

    intervals: list[tuple[float, float, int]] = []
    guard = threading.Lock()  # intervals リストへのappend自体を守るだけ（検証対象のロックではない）

    def worker(idx: int) -> None:
        video_service._acquire_file_lock(lock_path, timeout=5.0)
        try:
            start = time.time()
            time.sleep(0.05)
            end = time.time()
            with guard:
                intervals.append((start, end, idx))
        finally:
            video_service._release_file_lock(lock_path)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("lock: all 5 threads recorded", len(intervals) == 5)
    intervals.sort()
    overlap = any(intervals[i][1] > intervals[i + 1][0] for i in range(len(intervals) - 1))
    check("lock: no overlapping lock holds (mutual exclusion works)", not overlap)

    # video_service側とワーカー側で同じロックファイルパス規約を使っていること
    # （path.job.json + ".lock"）を確認し、双方が同じロックで直列化されることを保証する。
    job_json_path = video_service._job_json_path(PROJ, "lock_path_check")
    check(
        "lock: video_service and worker use the same lock path convention",
        str(video_service._job_lock_path(PROJ, "lock_path_check")) == str(job_json_path) + ".lock",
    )


def test_settings_lock_no_lost_update() -> None:
    """update_settings() とワーカー側 _update_job() の同時書き込みで更新が失われないこと。

    実ワーカーは通常時ほとんど job.json を書き換えないため、競合を確実に再現するために
    video_service.update_settings() とワーカー側 _update_job() を直接・大量に並行実行し、
    双方の最後の書き込みが最終ファイルへ両方反映されていることを確認する。
    """
    vid = "lock_race_job"
    d = vdir(vid)
    (d / "live").mkdir(parents=True, exist_ok=True)
    job_json = d / "job.json"
    job_json.write_text(json.dumps({
        "video_job_id": vid, "status": "running", "video_fps": 10, "infer_fps": 5,
        "conf": 0.25, "iou": 0.7, "imgsz": 640, "device": "auto",
        "created_at": None, "started_at": None, "finished_at": None, "message": "running",
    }), encoding="utf-8")

    n = 60
    errors: list[Exception] = []

    def settings_writer() -> None:
        try:
            for i in range(n):
                video_service.update_settings(PROJ, vid, VideoJobSettingsUpdate(conf=round(0.01 + (i % 60) * 0.01, 4)))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def worker_writer() -> None:
        try:
            for i in range(n):
                predict_video_worker._update_job(job_json, iou=round(0.01 + (i % 60) * 0.01, 4))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=settings_writer)
    t2 = threading.Thread(target=worker_writer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    check("settings_lock: no exceptions during concurrent writes", errors == [])
    final = json.loads(job_json.read_text(encoding="utf-8-sig"))
    expected_conf = round(0.01 + ((n - 1) % 60) * 0.01, 4)
    expected_iou = round(0.01 + ((n - 1) % 60) * 0.01, 4)
    check("settings_lock: video_service's last write survived", final.get("conf") == expected_conf)
    check("settings_lock: worker's last write survived", final.get("iou") == expected_iou)


def test_url_job_lifecycle() -> None:
    """source_type=url でのジョブ作成・resolve済みURLの伝播・不正URL・到達不能URLの扱い。"""
    make_fake_train_job("train_001", with_best=True)
    base = f"/api/projects/{PROJ}/video-jobs"

    # --- 不正URL（file:// 等の拒否スキーム）では400 ---
    r = client.post(base, json=job_body("url_bad_scheme", source_type="url", source_url="file:///etc/passwd"))
    check("url_job: invalid scheme -> 400", r.status_code == 400)

    r = client.post(base, json=job_body("url_no_host", source_type="url", source_url="http:///no-host"))
    check("url_job: hostless url -> 400", r.status_code == 400)

    # --- imagepathクエリを含むURLでジョブ作成 → 解決済みURLがjob.json（ひいてはワーカー起動引数）へ渡る ---
    viewer_url = "http://127.0.0.1:9/view/view.shtml?imagepath=%2Fmjpg%2Fvideo.mjpg"
    r = client.post(base, json=job_body("url_resolved", source_type="url", source_url=viewer_url))
    check("url_job: create with url -> 201", r.status_code == 201)
    res = r.json()
    check("url_job: source_url stored as-is", res["source_url"] == viewer_url)
    check("url_job: resolved_source_url resolved", res["resolved_source_url"] == "http://127.0.0.1:9/mjpg/video.mjpg")
    job_after = read_job("url_resolved")
    check("url_job: resolved url present in job.json (worker起動引数のもと)", job_after.get("resolved_source_url") == "http://127.0.0.1:9/mjpg/video.mjpg")
    stop_and_wait("url_resolved")

    # --- 到達不能URLでは、リトライを使い切った上で failed になり、残骸を残さず自ら終了すること ---
    #     実測では、実際に到達不能なURLに対して cv2.VideoCapture(..., CAP_FFMPEG) が
    #     CAP_PROP_OPEN_TIMEOUT_MSEC を尊重せず数十秒以上ブロックすることを確認した
    #     （OpenCV/FFmpegのビルドに依存する既知の制約。コード中にも「対応バージョンのみ有効」
    #     とコメントあり）。実ネットワークに依存するとスモークテストが非常に遅く不安定になるため、
    #     cv2 をフェイクに差し替え、「オープン失敗を検知した後の後続動作
    #     （リトライ→到達性診断→failed→残骸なしで自ら終了）」を高速・決定的に検証する。
    vid = "url_unreachable"
    d = vdir(vid)
    (d / "live").mkdir(parents=True, exist_ok=True)
    job_json = d / "job.json"
    job_json.write_text(json.dumps({
        "video_job_id": vid, "status": "queued", "source_type": "url",
        "source_url": "http://127.0.0.1:1/unreachable", "video_fps": 15, "infer_fps": 5,
    }), encoding="utf-8")
    (d / "video.log").touch()

    class _FakeCap:
        def isOpened(self) -> bool:
            return False

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _FakeCv2:
        CAP_FFMPEG = 1900
        CAP_DSHOW = 700
        CAP_PROP_BUFFERSIZE = 38
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54

        def VideoCapture(self, *_a, **_kw):
            return _FakeCap()

        def __getattr__(self, _name):
            # ultralytics(YOLO読み込み時)がGUI関連(imshow等)の有無を探索的に
            # 呼び出すことがあるため、未知の属性は何もしないダミーを返す
            # （このテストではcv2のオープン失敗パス自体の検証だけが目的）。
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_VIDEO_DRY_RUN", None)  # 実処理（open失敗パス）を通す
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "predict_video_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(d / "live"),
        "--weight", str(ROOT / PROJ / "runs" / "train" / "train_001" / "weights" / "best.pt"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", "http://127.0.0.1:1/unreachable",
        "--video-fps", "15", "--infer-fps", "5",
    ]
    try:
        rc = predict_video_worker.main()
    finally:
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_VIDEO_DRY_RUN"] = orig_dry_run

    check("url_job: unreachable url -> main() returns failure (1)", rc == 1)
    final = read_job(vid)
    check("url_job: unreachable url ends in failed", final.get("status") == "failed")
    check("url_job: failure message present (open failed)", "開けませんでした" in (final.get("message") or ""))
    check("url_job: main() returned (no hang / no residue)", True)


def test_credential_display_masking() -> None:
    """Issue #3 Checkpoint 3.5: API応答・known_sourcesのUI表示用URLでpasswordが平文露出しないこと。

    実UI検証（Checkpoint 3）で、mask_url_credentials() はログ・エラーメッセージ表示
    （resolve_source_url()のnoteやworker起動ログ）にのみ適用され、VideoJobInfo.source_url /
    resolved_source_url、VideoSourceInfo.url（known_sources）そのものはrawのまま
    API応答・known_sources一覧に返っており、UI（PredictPage.tsx）がそれをそのまま表示していた
    ことが判明した（password平文露出）。get_job()/list_known_sources()/delete_known_source()の
    修正（表示用マスク値の追加）がregressionしないことを確認する。
    """
    cred_url = "http://admin:secret123@192.168.1.10/mjpg/video.mjpg"
    viewer_cred_url = (
        "http://admin:secret123@192.168.1.10/view/view.shtml?imagepath=%2Fmjpg%2Fvideo2.mjpg"
    )

    # --- ジョブ作成時のレスポンス（201）でpasswordが平文で返らないこと ---
    vid = "cred_mask_job"
    r = client.post(
        f"/api/projects/{PROJ}/video-jobs",
        json=job_body(vid, source_type="url", source_url=cred_url),
    )
    check("cred_mask: create 201", r.status_code == 201)
    created = r.json()
    check("cred_mask: create response source_url has no plaintext password", "secret123" not in created["source_url"])
    check("cred_mask: create response source_url masked", "***" in created["source_url"])
    check(
        "cred_mask: create response resolved_source_url has no plaintext password",
        "secret123" not in (created.get("resolved_source_url") or ""),
    )

    # --- フレーム書き出し・running到達を待つ（get_job()のURL記憶(_remember_source)が
    #     status=="running" かつフレーム有りの時にのみ発火するため、known_sources検証の
    #     ためにここで確実に条件を満たしてから GET する） ---
    check("cred_mask: frame written", wait_frame(vid))
    check("cred_mask: reached running", wait_status(vid, {"running"}, timeout=10.0) == "running")

    # --- GET のレスポンスでも同様（一覧 list_jobs も get_job() を経由するため同時に確認） ---
    r = client.get(f"/api/projects/{PROJ}/video-jobs/{vid}")
    fetched = r.json()
    check("cred_mask: GET response source_url has no plaintext password", "secret123" not in fetched["source_url"])
    r_list = client.get(f"/api/projects/{PROJ}/video-jobs")
    list_entry = next(j for j in r_list.json()["jobs"] if j["video_job_id"] == vid)
    check("cred_mask: list response source_url has no plaintext password", "secret123" not in list_entry["source_url"])

    # --- サーバー内部（job.json）はrawのまま保持し、接続処理自体は壊れないこと ---
    raw_job = read_job(vid)
    check("cred_mask: job.json keeps raw source_url (needed for actual connection)", raw_job.get("source_url") == cred_url)
    stop_and_wait(vid)

    # --- resolved_source_url: credential + imagepath解決を同時に行った場合もマスクされること ---
    vid2 = "cred_mask_resolved_job"
    r = client.post(
        f"/api/projects/{PROJ}/video-jobs",
        json=job_body(vid2, source_type="url", source_url=viewer_cred_url),
    )
    check("cred_mask: resolved job create 201", r.status_code == 201)
    resolved_created = r.json()
    check(
        "cred_mask: resolved_source_url correctly resolved to real stream path",
        resolved_created["resolved_source_url"].endswith("/mjpg/video2.mjpg"),
    )
    check(
        "cred_mask: resolved_source_url has no plaintext password",
        "secret123" not in resolved_created["resolved_source_url"],
    )
    check("cred_mask: resolved_source_url masked", "***" in resolved_created["resolved_source_url"])
    raw_job2 = read_job(vid2)
    check(
        "cred_mask: job.json keeps raw resolved_source_url (worker起動引数のもと)",
        raw_job2.get("resolved_source_url") == "http://admin:secret123@192.168.1.10/mjpg/video2.mjpg",
    )
    stop_and_wait(vid2)

    # --- known_sources: masked_url にはpasswordが含まれず、url（再接続用）はrawのまま ---
    r = client.get(f"/api/projects/{PROJ}/video-sources")
    check("cred_mask: known_sources list 200", r.status_code == 200)
    sources = r.json()["sources"]
    entry = next((s for s in sources if s["url"] == cred_url), None)
    check("cred_mask: known_sources kept raw url for reconnect", entry is not None)
    check("cred_mask: known_sources masked_url has no plaintext password", "secret123" not in entry["masked_url"])
    check("cred_mask: known_sources masked_url masked", "***" in entry["masked_url"])

    # --- delete_known_source() の戻り値にも masked_url が含まれ続けること ---
    r = client.delete(f"/api/projects/{PROJ}/video-sources", params={"url": "http://192.168.1.10/does-not-exist"})
    check("cred_mask: delete (unrelated url) response still has masked_url field", "masked_url" in r.json()["sources"][0])

    # --- video.log（実プロセスの起動ログ）は既存どおりmaskされること（regression） ---
    log_text = (vdir(vid) / "video.log").read_text(encoding="utf-8", errors="replace")
    check("cred_mask: video.log has no plaintext password", "secret123" not in log_text)
    check("cred_mask: video.log shows masked credential", "admin:***@192.168.1.10" in log_text)

    # --- 接続処理自体（cv2.VideoCapture呼び出し）にはrawのpassword付きURLが渡ること ---
    #     （表示用マスクはAPI応答レイヤーのみに適用され、実接続経路には影響しないことの直接確認）
    seen_sources: list[str] = []

    class _RecordingFakeCap:
        def isOpened(self) -> bool:
            return False

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _RecordingFakeCv2:
        CAP_FFMPEG = 1900
        CAP_DSHOW = 700
        CAP_PROP_BUFFERSIZE = 38
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54

        def VideoCapture(self, source, *_a, **_kw):
            seen_sources.append(source)
            return _RecordingFakeCap()

        def __getattr__(self, _name):
            return lambda *a, **kw: None

    vid3 = "cred_mask_connect_check"
    d3 = vdir(vid3)
    (d3 / "live").mkdir(parents=True, exist_ok=True)
    job_json3 = d3 / "job.json"
    job_json3.write_text(json.dumps({
        "video_job_id": vid3, "status": "queued", "source_type": "url",
        "source_url": cred_url, "video_fps": 15, "infer_fps": 5,
    }), encoding="utf-8")
    (d3 / "video.log").touch()

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_VIDEO_DRY_RUN", None)
    sys.modules["cv2"] = _RecordingFakeCv2()
    sys.argv = [
        "predict_video_worker.py",
        "--job-json", str(job_json3),
        "--live-dir", str(d3 / "live"),
        "--weight", str(ROOT / PROJ / "runs" / "train" / "train_001" / "weights" / "best.pt"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", cred_url,
        "--video-fps", "15", "--infer-fps", "5",
    ]
    try:
        predict_video_worker.main()
    finally:
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_VIDEO_DRY_RUN"] = orig_dry_run

    check("cred_mask: connection layer received at least one VideoCapture() call", len(seen_sources) >= 1)
    check(
        "cred_mask: connection layer received the RAW credential URL (not masked)",
        all(s == cred_url for s in seen_sources),
    )


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})
    make_fake_train_job("train_001", with_best=True)

    base = f"/api/projects/{PROJ}/video-jobs"

    # --- カメラ一覧（環境依存だが 200 を返す） ---
    r = client.get(f"/api/projects/{PROJ}/cameras")
    check("cameras 200", r.status_code == 200 and "cameras" in r.json())

    body = {
        "video_job_name": "video_001",
        "train_job_id": "train_001",
        "weight_type": "best",
        "camera_index": 0,
        "video_fps": 15,
        "infer_fps": 5,
        "conf": 0.25,
        "iou": 0.7,
        "imgsz": 640,
        "device": "auto",
        "preprocess_mode": "none",
        "overwrite": False,
    }

    # --- 学習ジョブ不在 → 404 ---
    r = client.post(base, json={**body, "train_job_id": "no_such"})
    check("missing train job -> 404", r.status_code == 404)

    # --- weight不在 → 400 ---
    r = client.post(base, json={**body, "weight_type": "last"})
    check("missing weight -> 400", r.status_code == 400)

    # --- infer_fps > video_fps → 400 ---
    r = client.post(base, json={**body, "video_fps": 5, "infer_fps": 10})
    check("infer_fps>video_fps -> 400", r.status_code == 400)

    # --- video_fps 範囲外 → 400 ---
    r = client.post(base, json={**body, "video_fps": 0})
    check("video_fps range -> 400", r.status_code == 400)

    # --- preprocess_mode=latest だが前処理設定なし → 400 ---
    r = client.post(base, json={**body, "preprocess_mode": "latest"})
    check("latest without settings -> 400", r.status_code == 400)

    # --- 不正なジョブ名 → 400 ---
    r = client.post(base, json={**body, "video_job_name": "bad name!"})
    check("invalid name -> 400", r.status_code == 400)

    # --- 正常 → 201 ---
    r = client.post(base, json=body)
    check("start 201", r.status_code == 201)
    res = r.json()
    check("status queued/running", res["status"] in ("queued", "running"))
    check("stream_url shape", res["stream_url"].endswith("/video-jobs/video_001/stream"))

    job_json = ROOT / PROJ / "video" / "video_001" / "job.json"
    check("job.json exists", job_json.exists())

    # --- 同名 overwrite=false → 409 ---
    r = client.post(base, json=body)
    check("duplicate -> 409", r.status_code == 409)

    # --- 合成フレームが出力される ---
    check("frame written", wait_frame("video_001"))

    # --- 取得/一覧 ---
    r = client.get(f"{base}/video_001")
    check("get job 200", r.status_code == 200 and r.json()["video_job_id"] == "video_001")
    r = client.get(base)
    check("list has job", any(j["video_job_id"] == "video_001" for j in r.json()["jobs"]))

    # --- 停止 ---
    r = client.post(f"{base}/video_001/stop")
    check("stop 200", r.status_code == 200 and r.json()["status"] == "stopped")

    # --- 停止後の stream は最終フレームを返して終了 ---
    r = client.get(f"{base}/video_001/stream")
    check("stream 200", r.status_code == 200)
    check("stream content-type", r.headers["content-type"].startswith("multipart/x-mixed-replace"))
    check("stream has jpeg payload", b"image/jpeg" in r.content)

    # --- 存在しないジョブ → 404 ---
    r = client.get(f"{base}/no_job")
    check("missing job -> 404", r.status_code == 404)

    # --- URL機能: バリデーション・URL解決（外部アクセス不要） ---
    test_url_validation_and_resolve()

    # --- URL機能: 認証情報マスク ---
    test_mask_url_credentials()

    # --- URL機能: known_sources.json ---
    test_known_sources()

    # --- overwrite安全性: 実行中ジョブ保護・安全削除 ---
    test_overwrite_protection()
    test_safe_rmtree_rename_failure()

    # --- settings PATCH ---
    test_settings_patch()

    # --- Job作成時のconf/iou/imgsz validationがPATCHと対称であること ---
    test_create_time_validation_symmetry()

    # --- job.json排他制御 ---
    test_job_lock_mutual_exclusion()
    test_settings_lock_no_lost_update()

    # --- URL Job のライフサイクル（作成・解決URL伝播・不正URL・到達不能URL） ---
    test_url_job_lifecycle()

    # --- Checkpoint 3.5: API/UI表示でのcredentialマスク（password平文露出の修正確認） ---
    test_credential_display_masking()

    print("\nALL VIDEO INFERENCE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
