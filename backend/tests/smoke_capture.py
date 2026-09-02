"""カメラ/URL撮影機能（プロジェクト準備・画像取り込み）の軽量スモークテスト。

実カメラ/OpenCVは使わない。ワーカーは YTS_CAPTURE_DRY_RUN=1 で合成フレームを
live/latest.jpg に書き出し、撮影要求時は image_service.save_uploads 経由で
raw/images に実際に保存する（保存規約自体は本物のパスを通す）。検証項目:
  - バリデーション（session_name/video_fps/interval_minutes）
  - セッション作成 → job.json 生成 → 合成フレーム出力
  - 「今すぐ撮影」→ raw/images に画像が保存され captured_count が増える
  - interval_minutes による自動撮影
  - 停止後に /stream が最終フレームを1枚返して終了する

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_capture.py
"""

from __future__ import annotations

import json as _json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_capture_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_CAPTURE_DRY_RUN"] = "1"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import capture_service, video_service  # noqa: E402
import capture_worker  # noqa: E402

client = TestClient(app)
PROJ = "capture_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def wait_frame(sid: str) -> bool:
    latest = ROOT / PROJ / "capture" / sid / "live" / "latest.jpg"
    for _ in range(50):
        time.sleep(0.2)
        if latest.exists() and latest.stat().st_size > 0:
            return True
    return False


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


def wait_captured_count(sid: str, at_least: int, timeout_s: float = 10.0) -> int:
    base = f"/api/projects/{PROJ}/capture-sessions/{sid}"
    deadline = time.time() + timeout_s
    last = 0
    while time.time() < deadline:
        r = client.get(base)
        if r.status_code == 200:
            last = r.json().get("captured_count", 0)
            if last >= at_least:
                return last
        time.sleep(0.3)
    return last


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})

    base = f"/api/projects/{PROJ}/capture-sessions"
    sources_base = f"/api/projects/{PROJ}/capture-sources"

    # --- 一覧（空） ---
    r = client.get(base)
    check("list empty 200", r.status_code == 200 and r.json()["sessions"] == [])

    # --- 撮影ソース（永続化された定義）のCRUD ---
    r = client.get(sources_base)
    check("sources list empty 200", r.status_code == 200 and r.json()["sources"] == [])

    r = client.post(sources_base, json={"label": "玄関カメラ", "source_type": "camera", "camera_index": 0})
    check("source add 201", r.status_code == 201)
    src = r.json()
    check("source has generated id", src["source_id"] == "src_001")
    check("source label", src["label"] == "玄関カメラ")

    r = client.post(sources_base, json={"label": "屋外URL", "source_type": "url"})
    check("source add without url -> 400", r.status_code == 400)

    r = client.get(sources_base)
    check("sources list has 1", len(r.json()["sources"]) == 1)

    r = client.patch(f"{sources_base}/{src['source_id']}", json={"label": "玄関カメラ(更新)"})
    check("source update 200", r.status_code == 200 and r.json()["label"] == "玄関カメラ(更新)")

    r = client.patch(f"{sources_base}/no_such_source", json={"label": "x"})
    check("source update missing -> 404", r.status_code == 404)

    r = client.delete(f"{sources_base}/{src['source_id']}")
    check("source delete 204", r.status_code == 204)

    r = client.get(sources_base)
    check("sources list empty after delete", r.json()["sources"] == [])

    r = client.delete(f"{sources_base}/{src['source_id']}")
    check("source delete missing -> 404", r.status_code == 404)

    body = {
        "session_name": "capture_001",
        "source_type": "camera",
        "camera_index": 0,
        "video_fps": 10,
        "interval_minutes": None,
        "overwrite": False,
    }

    # --- 不正なセッション名 → 400 ---
    r = client.post(base, json={**body, "session_name": "bad name!"})
    check("invalid name -> 400", r.status_code == 400)

    # --- video_fps 範囲外 → 400 ---
    r = client.post(base, json={**body, "video_fps": 0})
    check("video_fps range -> 400", r.status_code == 400)

    # --- interval_minutes 範囲外 → 400 ---
    r = client.post(base, json={**body, "interval_minutes": 5000})
    check("interval_minutes range -> 400", r.status_code == 400)

    # --- interval_minutes 非整数（1分単位でない）→ 400 ---
    r = client.post(base, json={**body, "interval_minutes": 0.5})
    check("interval_minutes non-integer -> 400", r.status_code == 400)

    # --- 正常 → 201 ---
    r = client.post(base, json=body)
    check("start 201", r.status_code == 201)
    res = r.json()
    check("status queued/running", res["status"] in ("queued", "running"))
    check("stream_url shape", res["stream_url"].endswith("/capture-sessions/capture_001/stream"))

    job_json = ROOT / PROJ / "capture" / "capture_001" / "job.json"
    check("job.json exists", job_json.exists())

    # --- 同名 overwrite=false → 409 ---
    r = client.post(base, json=body)
    check("duplicate -> 409", r.status_code == 409)

    # --- 合成フレームが出力される ---
    check("frame written", wait_frame("capture_001"))

    # --- 都度取得のフレームエンドポイント（ブラウザの同時接続数上限を避けるためのポーリング用） ---
    r = client.get(f"{base}/capture_001/frame")
    check("frame endpoint 200", r.status_code == 200)
    check("frame endpoint content-type", r.headers["content-type"] == "image/jpeg")
    check("frame endpoint has bytes", len(r.content) > 0)

    # --- 実行中セッションのoverwrite保護（Issue #4 Checkpoint 2で追加）。
    #     video_serviceのoverwrite保護と同じ仕様: 実行中は overwrite の値に関わらず
    #     一切変更しない（stale statusでもPID生存中なら実行中扱い）。---
    old_pid = _safe_read_job(job_json).get("pid")
    check("overwrite-protect: pid recorded before test", isinstance(old_pid, int))
    check("overwrite-protect: pid is alive", pid_alive(old_pid))
    job_before = _safe_read_job(job_json)

    r = client.post(base, json={**body, "overwrite": False})
    check("overwrite-protect: active+overwrite=false -> 409", r.status_code == 409)
    check("overwrite-protect: job.json unchanged after overwrite=false attempt", _safe_read_job(job_json) == job_before)

    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite-protect: active+overwrite=true -> 409", r.status_code == 409)
    check("overwrite-protect: job.json unchanged after overwrite=true attempt", _safe_read_job(job_json) == job_before)
    check("overwrite-protect: worker still alive (untouched)", pid_alive(old_pid))

    # --- statusがstale（既知の値以外に更新漏れ）でもPID生存なら実行中扱い -> 409、無変更 ---
    # 注意: "stopped"/"failed"/"completed" は実ワーカー自身の _stopped() が停止合図として
    # 検知してしまうため使えない（video側の test_overwrite_protection と同じ理由）。
    stale = dict(job_before)
    stale["status"] = "unexpected_stale_status"
    job_json.write_text(_json.dumps(stale, ensure_ascii=False, indent=2), encoding="utf-8")
    stale_snapshot = _safe_read_job(job_json)
    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite-protect: stale status but pid alive -> 409", r.status_code == 409)
    check("overwrite-protect: job.json unchanged (stale-status case)", _safe_read_job(job_json) == stale_snapshot)

    # --- 停止して完了させる ---
    r = client.post(f"{base}/capture_001/stop")
    check("overwrite-protect: stop 200", r.status_code == 200)
    check("overwrite-protect: worker pid exits after stop", wait_pid_gone(old_pid))

    # --- 完了済み + PID非生存 + overwrite=true -> 正常に上書き可能 ---
    old_created_at = _safe_read_job(job_json).get("created_at")
    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite-protect: completed+pid dead+overwrite=true -> 201", r.status_code == 201)
    new_job = _safe_read_job(job_json)
    check("overwrite-protect: overwrite produced a new session (created_at changed)", new_job.get("created_at") != old_created_at)
    new_pid = new_job.get("pid")
    check("overwrite-protect: overwrite got a new pid", new_pid is not None and new_pid != old_pid)
    check("overwrite-protect: new instance reached running with a frame", wait_frame("capture_001"))

    # --- 「今すぐ撮影」 ---
    r = client.post(f"{base}/capture_001/capture")
    check("capture now 200", r.status_code == 200)
    cap_res = r.json()
    check("capture status captured/pending", cap_res["status"] in ("captured", "pending"))

    count = wait_captured_count("capture_001", at_least=1)
    check("captured_count >= 1", count >= 1)

    raw_dir = ROOT / PROJ / "raw" / "images"
    saved = list(raw_dir.glob("capture_001_*.jpg")) if raw_dir.exists() else []
    check("captured image saved to raw/images", len(saved) >= 1)

    # --- filename collision handling: 同一秒内に連続撮影しても両方が別ファイルとして
    #     保存されること（image_service.save_uploads の _unique_path に依存する既存の
    #     衝突回避規約が、撮影経由でも機能することの確認。Issue #4 Checkpoint 2） ---
    # ワーカーの撮影処理（保存I/O含む）が完全に一巡してから次の撮影要求を送る
    # （1回のcapture_now呼び出し内で連続要求すると、ワーカー側のポーリング周期
    # （0.2秒間隔）とのタイミング次第で検出が数秒遅れることがあるため、テスト側で
    # 十分な間隔をおく。実運用上「今すぐ撮影」を連打すること自体は許容される操作で、
    # 遅れて確実に反映されること自体は wait_captured_count の長めのtimeoutで検証する）。
    time.sleep(1.0)
    r = client.post(f"{base}/capture_001/capture")
    check("capture now (2nd) 200", r.status_code == 200)
    count2 = wait_captured_count("capture_001", at_least=count + 1, timeout_s=20.0)
    check("captured_count incremented on 2nd capture", count2 >= count + 1)
    saved2 = list(raw_dir.glob("capture_001_*.jpg")) if raw_dir.exists() else []
    check("2nd capture saved as a distinct file (no overwrite)", len(saved2) >= 2)
    check("all captured filenames are unique", len({p.name for p in saved2}) == len(saved2))

    # --- 取得/一覧 ---
    r = client.get(f"{base}/capture_001")
    check("get session 200", r.status_code == 200 and r.json()["session_id"] == "capture_001")
    r = client.get(base)
    check("list has session", any(s["session_id"] == "capture_001" for s in r.json()["sessions"]))

    # --- 停止 ---
    r = client.post(f"{base}/capture_001/stop")
    check("stop 200", r.status_code == 200 and r.json()["status"] == "stopped")

    # --- 停止後の「今すぐ撮影」→ 400（running状態でないため） ---
    r = client.post(f"{base}/capture_001/capture")
    check("capture after stop -> 400", r.status_code == 400)

    # --- 停止後の stream は最終フレームを返して終了 ---
    r = client.get(f"{base}/capture_001/stream")
    check("stream 200", r.status_code == 200)
    check("stream content-type", r.headers["content-type"].startswith("multipart/x-mixed-replace"))
    check("stream has jpeg payload", b"image/jpeg" in r.content)

    # --- 自動撮影（interval_minutes、公開APIは1分単位・1分以上のみ許可） ---
    auto_body = {**body, "session_name": "capture_auto", "interval_minutes": 1}
    r = client.post(base, json=auto_body)
    check("auto session start 201", r.status_code == 201)
    auto_res = r.json()
    next_at_raw = auto_res.get("next_auto_capture_at")
    check("next_auto_capture_at present", bool(next_at_raw))
    if next_at_raw:
        # 壁時計基準（毎分00秒）に揃えるため、実行タイミング次第で0〜60秒の間で変動する。
        diff = (datetime.fromisoformat(next_at_raw) - datetime.now()).total_seconds()
        check("next_auto_capture_at within 0-60s (wall-clock aligned)", 0 <= diff <= 60)
    client.post(f"{base}/capture_auto/stop")

    # --- ワーカーを直接起動し、公開APIの1分下限を経由せず高速に
    #     「次回撮影時刻の初期設定 → 発火 → 再スケジュール」を検証する ---
    test_next_auto_capture_reschedule()

    # --- 存在しないセッション → 404 ---
    r = client.get(f"{base}/no_session")
    check("missing session -> 404", r.status_code == 404)

    # --- Issue #4 Checkpoint 2: 安全性・セキュリティ回帰テスト ---
    test_safe_rmtree_rename_failure()
    test_job_lock_mutual_exclusion()
    test_id_path_traversal_rejection()
    test_malformed_source_input()
    test_credential_masking()
    test_camera_unreachable_still_fails_fast()

    # --- 長時間運用対応（24時間〜数日連続稼働）の回帰テスト ---
    test_no_fixed_time_limit_in_real_worker()
    test_reconnect_recovery()
    test_unrecoverable_exception_marks_failed()
    test_url_initial_connect_wait_then_recovers()
    test_url_stop_during_initial_connect_wait()
    test_stale_auto_capture_slot_is_skipped_then_resumes()

    print("\nALL CAPTURE SMOKE TESTS PASSED")


def _safe_read_job(job_json: Path) -> dict:
    """job.json を読む（ワーカーが書き込み中の瞬間と重なってもクラッシュしない）。"""
    try:
        return _json.loads(job_json.read_text(encoding="utf-8-sig")) if job_json.exists() else {}
    except (OSError, _json.JSONDecodeError):
        return {}


def test_next_auto_capture_reschedule() -> None:
    """ワーカーの next_auto_capture_at 初期設定・発火・再スケジュールを高速に検証する。

    公開APIは interval_minutes を1分以上に制限しているため、ここではワーカーを
    直接起動して短い間隔（6秒）で高速に確認する（ワーカー自体は下限を課さない）。
    """
    sid = "reschedule_test"
    sdir = ROOT / PROJ / "capture" / sid
    (sdir / "live").mkdir(parents=True, exist_ok=True)
    job_json = sdir / "job.json"
    job_json.write_text(_json.dumps({"session_id": sid, "status": "queued", "captured_count": 0}), encoding="utf-8")

    backend_dir = Path(__file__).resolve().parents[1]
    worker = backend_dir / "workers" / "capture_worker.py"
    proc = subprocess.Popen([
        sys.executable, str(worker),
        "--job-json", str(job_json),
        "--live-dir", str(sdir / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(backend_dir),
        "--source-type", "camera", "--source", "0",
        "--video-fps", "10", "--interval-minutes", "0.1",
    ], env=os.environ.copy())

    try:
        first_at = None
        for _ in range(20):
            time.sleep(0.2)
            data = _safe_read_job(job_json)
            first_at = data.get("next_auto_capture_at")
            if first_at:
                break
        check("next_auto_capture_at set at start", bool(first_at))

        second_at = None
        for _ in range(60):
            time.sleep(0.3)
            data = _safe_read_job(job_json)
            if (data.get("captured_count") or 0) >= 1:
                second_at = data.get("next_auto_capture_at")
                break
        check("auto-captured (direct worker)", second_at is not None)
        check("next_auto_capture_at reset after firing", bool(second_at) and second_at != first_at)
    finally:
        (sdir / "stop.flag").write_text("stop", encoding="utf-8")
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_safe_rmtree_rename_failure() -> None:
    """安全削除（rename→delete）でrenameが失敗した場合、既存セッションを一切変更しないこと。

    video_service.test_safe_rmtree_rename_failure と同じ考え方（capture_service は
    video_service._safe_rmtree をそのまま再利用しているため、同じ os.rename をpatchする）。
    """
    base = f"/api/projects/{PROJ}/capture-sessions"
    body = {
        "session_name": "rmtree_fail",
        "source_type": "camera",
        "camera_index": 0,
        "video_fps": 10,
        "interval_minutes": None,
        "overwrite": False,
    }
    r = client.post(base, json=body)
    check("rmtree_fail: start 201", r.status_code == 201)
    check("rmtree_fail: frame written", wait_frame("rmtree_fail"))
    sdir = ROOT / PROJ / "capture" / "rmtree_fail"
    job_json = sdir / "job.json"
    old_pid = _safe_read_job(job_json).get("pid")
    r = client.post(f"{base}/rmtree_fail/stop")
    check("rmtree_fail: stop 200", r.status_code == 200)
    # API側は即座に status=stopped を書くが、ワーカー自身も停止検知後に自分の
    # finished_at/messageで job.json を更新する（非同期）。両方の更新が完了して
    # 安定するまで待ってからスナップショットを取る（ワーカーpidの終了で判定する）。
    check("rmtree_fail: worker pid exits after stop", wait_pid_gone(old_pid))
    job_before = _safe_read_job(job_json)
    log_path = sdir / "capture.log"
    log_before = log_path.read_bytes() if log_path.exists() else b""
    check("rmtree_fail: session not active before test", not capture_service._is_session_active(sdir))

    orig_rename = video_service.os.rename

    def _boom(*_a, **_kw):
        raise OSError("simulated: rename failed (file in use)")

    video_service.os.rename = _boom
    try:
        r = client.post(base, json={**body, "overwrite": True})
        check("rmtree_fail: overwrite -> 409 when rename fails", r.status_code == 409)
        check("rmtree_fail: job.json unchanged", _safe_read_job(job_json) == job_before)
        check(
            "rmtree_fail: capture.log unchanged",
            (log_path.read_bytes() if log_path.exists() else b"") == log_before,
        )
        check("rmtree_fail: directory still exists (not partially deleted)", sdir.exists())
    finally:
        video_service.os.rename = orig_rename

    r = client.post(base, json={**body, "overwrite": True})
    check("rmtree_fail: overwrite succeeds after unpatch", r.status_code == 201)
    client.post(f"{base}/rmtree_fail/stop")


def test_job_lock_mutual_exclusion() -> None:
    """capture_service の job.json ロックが実際に排他できていること、かつ
    video_service（ワーカー側 _update_job が使う lock）と同じパス規約を使っていること。
    """
    lock_path = ROOT / PROJ / "capture" / "lock_test" / "job.json.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        lock_path.unlink()

    intervals: list[tuple[float, float, int]] = []
    guard = threading.Lock()

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

    check("capture lock: all 5 threads recorded", len(intervals) == 5)
    intervals.sort()
    overlap = any(intervals[i][1] > intervals[i + 1][0] for i in range(len(intervals) - 1))
    check("capture lock: no overlapping lock holds (mutual exclusion works)", not overlap)

    job_json_path = capture_service._job_json_path(PROJ, "lock_path_check")
    check(
        "capture lock: capture_service and worker(_update_job) use the same lock path convention",
        str(capture_service._job_lock_path(PROJ, "lock_path_check")) == str(job_json_path) + ".lock",
    )


def test_id_path_traversal_rejection() -> None:
    """session_id/source_id の形式検証（Issue #4 Checkpoint 2）。

    実在しない・不正な形式のIDに対して、パストラバーサル目的のアクセスを含め
    一貫して404（存在しないものと同じ扱い）を返すこと。
    """
    base = f"/api/projects/{PROJ}/capture-sessions"
    sources_base = f"/api/projects/{PROJ}/capture-sources"
    # "/" を含む値やパスセグメント単独の".."はHTTPクライアント側でURL正規化されて
    # 別ルートに解決されてしまうため（本テストの対象外）、それ以外の「許可文字以外を
    # 含む」形式違反を代表として使う。
    bad_ids = ["bad name!", "a..b", "id;rm", "id$(x)"]

    for bad in bad_ids:
        r = client.get(f"{base}/{bad}")
        check(f"traversal: get session '{bad}' -> 404", r.status_code == 404)
        r = client.post(f"{base}/{bad}/stop")
        check(f"traversal: stop session '{bad}' -> 404", r.status_code == 404)
        r = client.post(f"{base}/{bad}/capture")
        check(f"traversal: capture '{bad}' -> 404", r.status_code == 404)
        r = client.get(f"{base}/{bad}/frame")
        check(f"traversal: frame '{bad}' -> 404", r.status_code == 404)
        r = client.patch(f"{sources_base}/{bad}", json={"label": "x"})
        check(f"traversal: update source '{bad}' -> 404", r.status_code == 404)
        r = client.delete(f"{sources_base}/{bad}")
        check(f"traversal: delete source '{bad}' -> 404", r.status_code == 404)


def test_malformed_source_input() -> None:
    """撮影ソース定義CRUDの異常系・重複入力の仕様確認（Issue #4 Checkpoint 2）。"""
    sources_base = f"/api/projects/{PROJ}/capture-sources"

    r = client.post(sources_base, json={"label": "無効種別", "source_type": "ftp", "camera_index": 0})
    check("malformed: invalid source_type -> 400", r.status_code == 400)

    r = client.post(sources_base, json={"label": "負のindex", "source_type": "camera", "camera_index": -1})
    check("malformed: negative camera_index -> 400", r.status_code == 400)

    r = client.post(sources_base, json={"label": "", "source_type": "camera", "camera_index": 0})
    check("malformed: empty label -> 400", r.status_code == 400)

    # --- 重複ラベルは現行仕様として許可される（source_idで一意に区別されるため） ---
    r1 = client.post(sources_base, json={"label": "重複名", "source_type": "camera", "camera_index": 1})
    check("duplicate label: 1st add 201", r1.status_code == 201)
    r2 = client.post(sources_base, json={"label": "重複名", "source_type": "camera", "camera_index": 2})
    check("duplicate label: 2nd add 201 (allowed by current spec)", r2.status_code == 201)
    check(
        "duplicate label: distinct source_id assigned",
        r1.json()["source_id"] != r2.json()["source_id"],
    )

    sid1, sid2 = r1.json()["source_id"], r2.json()["source_id"]
    r = client.patch(f"{sources_base}/{sid1}", json={"source_type": "ftp"})
    check("malformed: update invalid source_type -> 400", r.status_code == 400)
    r = client.patch(f"{sources_base}/{sid1}", json={"camera_index": -1})
    check("malformed: update negative camera_index -> 400", r.status_code == 400)

    client.delete(f"{sources_base}/{sid1}")
    client.delete(f"{sources_base}/{sid2}")


def test_credential_masking() -> None:
    """Capture API応答・known_sources表示でpasswordが平文露出しないこと（Issue #4 Checkpoint 2）。

    Issue #3 Checkpoint 3.5でVideo側に導入したmasking(video_service.mask_url_credentials)
    と同じ考え方をCapture側にも適用したことの回帰テスト。
    """
    sources_base = f"/api/projects/{PROJ}/capture-sources"
    base = f"/api/projects/{PROJ}/capture-sessions"
    cred_url = "http://admin:secret123@192.168.1.10/mjpg/video.mjpg"

    # --- 撮影ソース定義: masked_source_url にpasswordが含まれず、source_url(raw)は編集用に維持 ---
    r = client.post(sources_base, json={"label": "認証URL", "source_type": "url", "source_url": cred_url})
    check("cred_mask: source add 201", r.status_code == 201)
    src = r.json()
    check("cred_mask: source raw source_url kept for edit-form reuse", src["source_url"] == cred_url)
    check("cred_mask: source masked_source_url has no plaintext password", "secret123" not in (src["masked_source_url"] or ""))
    check("cred_mask: source masked_source_url masked", "***" in (src["masked_source_url"] or ""))

    r = client.get(sources_base)
    listed = next(s for s in r.json()["sources"] if s["source_id"] == src["source_id"])
    check("cred_mask: list response masked_source_url has no plaintext password", "secret123" not in (listed["masked_source_url"] or ""))
    client.delete(f"{sources_base}/{src['source_id']}")

    # --- 撮影セッション: source_url/resolved_source_url がAPI応答でマスクされること ---
    vid = "cred_mask_session"
    r = client.post(base, json={
        "session_name": vid, "source_type": "url", "source_url": cred_url,
        "video_fps": 10, "interval_minutes": None, "overwrite": False,
    })
    check("cred_mask: session create 201", r.status_code == 201)
    created = r.json()
    check("cred_mask: session create response source_url has no plaintext password", "secret123" not in created["source_url"])
    check("cred_mask: session create response source_url masked", "***" in created["source_url"])

    check("cred_mask: frame written", wait_frame(vid))
    r = client.get(f"{base}/{vid}")
    fetched = r.json()
    check("cred_mask: session GET response source_url has no plaintext password", "secret123" not in fetched["source_url"])

    # --- サーバー内部（job.json）はrawのまま保持し、接続処理自体は壊れないこと ---
    raw_job = _safe_read_job(ROOT / PROJ / "capture" / vid / "job.json")
    check("cred_mask: job.json keeps raw source_url (needed for actual connection)", raw_job.get("source_url") == cred_url)

    # --- known_sources（Video側と共有）にも masked_url が付与され、passwordが含まれないこと ---
    r = client.get(f"/api/projects/{PROJ}/video-sources")
    check("cred_mask: known_sources list 200", r.status_code == 200)
    entry = next((s for s in r.json()["sources"] if s["url"] == cred_url), None)
    check("cred_mask: known_sources kept raw url for reconnect", entry is not None)
    check("cred_mask: known_sources masked_url has no plaintext password", "secret123" not in (entry or {}).get("masked_url", ""))

    client.post(f"{base}/{vid}/stop")


def test_camera_unreachable_still_fails_fast() -> None:
    """camera（ローカルカメラ）は、URLと異なり従来どおり数回のリトライで見切りを
    つけ failed として早期にユーザーへ通知すること（起動時接続待ちの無期限化は
    URLソースのみが対象で、camera側の既存仕様には影響しないことの回帰確認）。
    """
    vid = "cap_camera_unreachable"
    d = ROOT / PROJ / "capture" / vid
    (d / "live").mkdir(parents=True, exist_ok=True)
    job_json = d / "job.json"
    job_json.write_text(_json.dumps({
        "session_id": vid, "status": "queued", "source_type": "camera",
        "camera_index": 0, "video_fps": 10, "captured_count": 0,
    }), encoding="utf-8")
    (d / "capture.log").touch()

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
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_CAPTURE_DRY_RUN", None)  # 実処理（open失敗パス）を通す
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "capture_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(d / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "camera",
        "--source", "0",
        "--video-fps", "10", "--interval-minutes", "0",
    ]
    try:
        rc = capture_worker.main()
    finally:
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_CAPTURE_DRY_RUN"] = orig_dry_run

    check("camera unreachable -> main() returns failure (1)", rc == 1)
    final = _safe_read_job(job_json)
    check("camera unreachable ends in failed (unlike url, no infinite wait)", final.get("status") == "failed")


def test_url_initial_connect_wait_then_recovers() -> None:
    """URLソースが起動直後は接続できない場合の挙動（今回追加した必須修正）。

    - 起動直後に接続できなくても failed にはならず running のまま
      「接続待機中…」として待ち続けること
    - 接続待機中もCPUを浪費する高速リトライにはならず、backoffで再試行すること
      （このテスト自体は待ち時間そのものの長さまでは検証しない。挙動の存在確認）
    - その後URLが復旧すると接続に成功し running/running へ戻ること
    - 復旧後、自動撮影（interval）が正常に開始されること
    """
    from PIL import Image  # noqa: PLC0415
    import io as _io  # noqa: PLC0415

    sid = "url_connect_wait_test"
    sdir = ROOT / PROJ / "capture" / sid
    (sdir / "live").mkdir(parents=True, exist_ok=True)
    job_json = sdir / "job.json"
    job_json.write_text(_json.dumps({"session_id": sid, "status": "queued", "captured_count": 0}), encoding="utf-8")
    (sdir / "capture.log").touch()

    # 起動直後の数回（VideoCapture呼び出し）は isOpened()=False（接続失敗）を返し、
    # それ以降は正常に開けて読めるキャプチャを返す（＝しばらくしてURLが復旧する想定）。
    state = {"opens": 0, "frame_no": 0}

    class _UnopenableCap:
        def isOpened(self) -> bool:
            return False

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _WorkingCap:
        def isOpened(self) -> bool:
            return True

        def read(self):
            state["frame_no"] += 1
            return True, f"frame-{state['frame_no']}"

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _JpegBuf:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def tobytes(self) -> bytes:
            return self._data

    class _FakeCv2:
        CAP_FFMPEG = 1900
        CAP_DSHOW = 700
        CAP_PROP_BUFFERSIZE = 38
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54

        def VideoCapture(self, *_a, **_kw):
            state["opens"] += 1
            # 最初の3回（初回オープン+2回の待機中リトライ）は接続できない状態を再現する。
            return _UnopenableCap() if state["opens"] <= 3 else _WorkingCap()

        def imencode(self, _ext, _frame):
            buf = _io.BytesIO()
            Image.new("RGB", (320, 240), (20 + state["frame_no"] % 200, 70, 130)).save(buf, format="JPEG")
            return True, _JpegBuf(buf.getvalue())

        def __getattr__(self, _name):
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_CAPTURE_DRY_RUN", None)
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "capture_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(sdir / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", "http://127.0.0.1:9/connect-wait-fake",
        # interval-minutesは公開APIの1分下限を経由しない直接起動なので、短い値で
        # 自動撮影の開始まで高速に確認できる。
        "--video-fps", "20", "--interval-minutes", "0.03",
    ]

    result_holder: dict[str, int] = {}

    def _run() -> None:
        result_holder["rc"] = capture_worker.main()

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    try:
        # --- (1)(2) 起動直後は接続できず、failedにはならず「接続待機中」のままであること ---
        saw_waiting = False
        for _ in range(150):  # 最大約15秒
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if "接続待機中" in (data.get("message") or ""):
                saw_waiting = True
                if data.get("status") == "failed":
                    break
            if data.get("status") == "failed":
                break
        check("url connect-wait: message shows waiting for initial connection", saw_waiting)
        check(
            "url connect-wait: status is running (not failed) while waiting to connect",
            _safe_read_job(job_json).get("status") == "running",
        )
        check("url connect-wait: worker thread still alive while waiting", th.is_alive())

        # --- (4)(5) URLが復旧すると接続に成功し running へ戻ること ---
        # interval_secondsが短いテスト設定では、接続成功直後の壁時計スロットに
        # 極めて近いタイミングで自動撮影が発火し、message が "running" から
        # 撮影成功メッセージへ一瞬で遷移することがある（ポーリング間隔0.1秒では
        # その一瞬の "running" 文字列そのものを取り逃す可能性がある）。ここでは
        # 「接続待機中」から抜けて running のまま（＝failed/stoppedになっていない）
        # ことをもって復旧の確認とする（自動撮影の実際の発火は次の確認で見る）。
        connected = False
        for _ in range(100):
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if data.get("status") == "running" and "接続待機中" not in (data.get("message") or ""):
                connected = True
                break
        check("url connect-wait: connects and returns to running once source recovers", connected)

        # --- (6) 復旧後、自動撮影(interval)が開始されること ---
        auto_captured = False
        for _ in range(150):  # 最大約15秒（壁時計基準アライメント分の待ちを含む）
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if (data.get("captured_count") or 0) >= 1:
                auto_captured = True
                break
        check("url connect-wait: auto capture starts after recovering", auto_captured)
    finally:
        (sdir / "stop.flag").write_text("stop", encoding="utf-8")
        th.join(timeout=15)
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_CAPTURE_DRY_RUN"] = orig_dry_run

    check("url connect-wait: worker thread exited after stop", not th.is_alive())
    check("url connect-wait: main() returned success (0) on normal stop", result_holder.get("rc") == 0)
    check("url connect-wait: final status is stopped (not failed)", _safe_read_job(job_json).get("status") == "stopped")


def test_url_stop_during_initial_connect_wait() -> None:
    """(3) URLソースが起動直後から一度も接続できないままでも、stop要求には
    速やかに応答して終了できること（failedにもハングにもならない）。
    """
    sid = "url_connect_wait_stop_test"
    sdir = ROOT / PROJ / "capture" / sid
    (sdir / "live").mkdir(parents=True, exist_ok=True)
    job_json = sdir / "job.json"
    job_json.write_text(_json.dumps({"session_id": sid, "status": "queued", "captured_count": 0}), encoding="utf-8")
    (sdir / "capture.log").touch()

    class _NeverOpensCap:
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
            return _NeverOpensCap()

        def __getattr__(self, _name):
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_CAPTURE_DRY_RUN", None)
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "capture_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(sdir / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", "http://127.0.0.1:9/never-opens",
        "--video-fps", "20", "--interval-minutes", "0",
    ]

    result_holder: dict[str, int] = {}

    def _run() -> None:
        result_holder["rc"] = capture_worker.main()

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    try:
        # 接続待機状態に入るまで少し待ってから、停止要求を出す。
        entered_waiting = False
        for _ in range(50):
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if "接続待機中" in (data.get("message") or ""):
                entered_waiting = True
                break
        check("url connect-wait stop: entered waiting state before stop request", entered_waiting)
    finally:
        (sdir / "stop.flag").write_text("stop", encoding="utf-8")

    # backoffの途中でも速やかに（数秒程度で）終了できること
    # （_interruptible_sleep によりbackoff中でも0.5秒刻みで停止要求を確認する）。
    joined_in_time = True
    th.join(timeout=10)
    if th.is_alive():
        joined_in_time = False
    check("url connect-wait stop: worker exits promptly during connect-wait backoff", joined_in_time)
    check("url connect-wait stop: main() returned success (0)", result_holder.get("rc") == 0)
    final = _safe_read_job(job_json)
    check("url connect-wait stop: final status is stopped (not failed)", final.get("status") == "stopped")


def test_no_fixed_time_limit_in_real_worker() -> None:
    """実運用パス（YTS_CAPTURE_DRY_RUN未設定時）に固定時間の終了条件（旧: 6時間）が
    存在しないことをソースから確認する。

    実際に24時間〜数日待って確認することはできないため、静的検査で代替する
    （ループ・再接続はモック可能な構成のため、動的な挙動は他のテスト関数で検証する）。
    """
    src = (Path(__file__).resolve().parents[1] / "workers" / "capture_worker.py").read_text(encoding="utf-8")
    check("no fixed 6h deadline (3600 * 6) left in source", "3600 * 6" not in src.replace(" ", ""))
    check("real-run loop uses 'while True' (time-based deadline removed)", "while True:" in src)
    # dry-run（テスト用）の60秒制限はテスト用途として維持されていること
    check("dry-run's 60s time limit is still present (test-only, intentionally kept)",
          "deadline = time.time() + 60" in src)


def test_reconnect_recovery() -> None:
    """URL/カメラの一時的な切断からの再接続シナリオ（長時間運用対応の核心）。

    実カメラ/ネットワークは使わず、cv2 モジュール全体をフェイクに差し替えて
    「最初のオープンは成功するがフレーム読み取りが続けて失敗する（＝一時的な
    通信断）→ ワーカーが再接続 → 再オープンしたキャプチャは正常にフレームを
    返す（＝復旧）」という時系列をシミュレートする。

    確認する内容:
      - フレーム読み取り失敗が続くと再接続（message に「再接続中」）を試みること
      - その間 status は failed/stopped にならず running のままであること
        （一時的な通信断だけでセッションを終了しない）
      - 再接続成功後は status/message が running に戻ること
      - worker プロセス（スレッド）自体は生き続けており、再接続後も撮影が
        正常に行えること
      - 最終的にユーザーの停止要求（stop.flag）で正常に stopped 終了すること
    """
    from PIL import Image  # noqa: PLC0415
    import io as _io  # noqa: PLC0415

    sid = "reconnect_test"
    sdir = ROOT / PROJ / "capture" / sid
    (sdir / "live").mkdir(parents=True, exist_ok=True)
    job_json = sdir / "job.json"
    job_json.write_text(_json.dumps({"session_id": sid, "status": "queued", "captured_count": 0}), encoding="utf-8")
    (sdir / "capture.log").touch()

    state = {"opens": 0, "frame_no": 0}

    class _StallingCap:
        """最初に開かれるキャプチャ。開けてはいるが、フレームは一切読めない
        （一時的な通信断・ストリーム停止を模す）。"""

        def isOpened(self) -> bool:
            return True

        def read(self):
            return False, None

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _WorkingCap:
        """再接続後に開かれるキャプチャ。以後は常にフレームを返す（＝復旧）。"""

        def isOpened(self) -> bool:
            return True

        def read(self):
            state["frame_no"] += 1
            return True, f"frame-{state['frame_no']}"

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _JpegBuf:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def tobytes(self) -> bytes:
            return self._data

    class _FakeCv2:
        CAP_FFMPEG = 1900
        CAP_DSHOW = 700
        CAP_PROP_BUFFERSIZE = 38
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54

        def VideoCapture(self, *_a, **_kw):
            state["opens"] += 1
            # 1回目のオープン（初回接続）は「開けるが読めない」キャプチャ、
            # 2回目以降（再接続）は「正常に読める」キャプチャを返す。
            return _StallingCap() if state["opens"] == 1 else _WorkingCap()

        def imencode(self, _ext, _frame):
            # 実際のフレーム内容は解釈しない（read()側で完全に制御しているため）。
            # image_service.save_uploads のPIL検証を通す必要があるので、
            # 有効なJPEGバイト列だけは本物を生成する（撮影ごとに色を変えて
            # SHA1重複チェックに弾かれないようにする）。
            buf = _io.BytesIO()
            Image.new("RGB", (320, 240), (10 + state["frame_no"] % 200, 40, 90)).save(buf, format="JPEG")
            return True, _JpegBuf(buf.getvalue())

        def __getattr__(self, _name):
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_CAPTURE_DRY_RUN", None)  # 実処理（読み取り/再接続パス）を通す
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "capture_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(sdir / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", "http://127.0.0.1:9/reconnect-fake",
        # video_fps=20 -> max_read_fail=max(10, 20*3)=60、video_interval=0.05秒。
        # 60回連続失敗にかかる時間は約3秒で、テストとして十分速い。
        "--video-fps", "20", "--interval-minutes", "0",
    ]

    result_holder: dict[str, int] = {}

    def _run() -> None:
        result_holder["rc"] = capture_worker.main()

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    try:
        # --- フレーム取得失敗が続き、再接続中メッセージが出ること ---
        saw_reconnecting = False
        for _ in range(150):  # 最大約15秒待つ
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if "再接続中" in (data.get("message") or ""):
                saw_reconnecting = True
                break
        check("reconnect: message shows reconnecting after read failures", saw_reconnecting)
        check(
            "reconnect: status stays running during reconnect (not failed/stopped)",
            _safe_read_job(job_json).get("status") == "running",
        )
        check("reconnect: worker thread still alive during reconnect", th.is_alive())

        # --- 再接続成功後、status/message が running に戻ること ---
        recovered = False
        for _ in range(100):
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if data.get("status") == "running" and data.get("message") == "running":
                recovered = True
                break
        check("reconnect: status/message return to running after reconnect succeeds", recovered)
        check("reconnect: worker thread still alive after recovery (session not terminated)", th.is_alive())

        # --- 復旧後、実際に撮影ができること（見た目だけでなく機能的に復旧している確認） ---
        (sdir / "capture.flag").write_text("capture", encoding="utf-8")
        captured = False
        for _ in range(100):
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if (data.get("captured_count") or 0) >= 1:
                captured = True
                break
        check("reconnect: capture succeeds after reconnect recovery", captured)
    finally:
        (sdir / "stop.flag").write_text("stop", encoding="utf-8")
        th.join(timeout=15)
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_CAPTURE_DRY_RUN"] = orig_dry_run

    check("reconnect: worker thread exited after stop request", not th.is_alive())
    check("reconnect: main() returned success (0) on normal stop", result_holder.get("rc") == 0)
    final = _safe_read_job(job_json)
    check(
        "reconnect: final status is stopped (temporary disconnect did not end the session)",
        final.get("status") == "stopped",
    )


def test_unrecoverable_exception_marks_failed() -> None:
    """一時的な読み取り失敗（再接続で回復可能）とは異なり、想定外の例外
    （例: フレームのエンコード処理そのものの失敗）が起きた場合は「回復不能な例外」
    として扱われ、stopped ではなく failed として job.json が確定すること。
    """
    sid = "unrecoverable_test"
    sdir = ROOT / PROJ / "capture" / sid
    (sdir / "live").mkdir(parents=True, exist_ok=True)
    job_json = sdir / "job.json"
    job_json.write_text(_json.dumps({"session_id": sid, "status": "queued", "captured_count": 0}), encoding="utf-8")
    (sdir / "capture.log").touch()

    class _OkCap:
        def isOpened(self) -> bool:
            return True

        def read(self):
            return True, "frame"

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
            return _OkCap()

        def imencode(self, _ext, _frame):
            # cap.read() 自体の失敗（再接続で回復すべき一時的な不調）とは異なり、
            # ループ内の他の処理で起きる想定外の例外を模す（回復不能な例外）。
            raise RuntimeError("simulated unrecoverable encode failure")

        def __getattr__(self, _name):
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_CAPTURE_DRY_RUN", None)
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "capture_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(sdir / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", "http://127.0.0.1:9/boom",
        "--video-fps", "10", "--interval-minutes", "0",
    ]
    try:
        rc = capture_worker.main()
    finally:
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_CAPTURE_DRY_RUN"] = orig_dry_run

    check("unrecoverable: main() returns failure (1)", rc == 1)
    final = _safe_read_job(job_json)
    check("unrecoverable: status is failed (not stopped)", final.get("status") == "failed")
    check("unrecoverable: message mentions the failure", bool(final.get("message")))
    check("unrecoverable: finished_at is set", bool(final.get("finished_at")))


def test_stale_auto_capture_slot_is_skipped_then_resumes() -> None:
    """stale-skip（自動撮影スロットの遅延許容 max(5秒, video_interval*5)）が、

    - 通信断で本当に長く遅延したスロットは追いかけ撮影しない（既存の目的）
    - かつ、通常運転レベルの遅延では撮影を不必要にスキップしない（今回の確認事項）

    の両方を満たしていることを確認する。

    通信断シナリオ: 読み取りが連続失敗する状態（cap.isOpened()はTrueだがread()が
    失敗し続ける）を意図的に約10秒間（許容誤差5秒を明確に超える長さ）継続させ、
    その間に自動撮影スロット（interval=2秒）が複数回過ぎるようにする。復旧直後に
    その間の失敗したスロットをまとめて追いかけ撮影していないこと（復旧直後の
    captured_countが0のまま）、かつその後の正規スロットでは通常どおり撮影が
    再開すること（captured_countが増える）を確認する。
    """
    from PIL import Image  # noqa: PLC0415
    import io as _io  # noqa: PLC0415

    sid = "stale_skip_test"
    sdir = ROOT / PROJ / "capture" / sid
    (sdir / "live").mkdir(parents=True, exist_ok=True)
    job_json = sdir / "job.json"
    job_json.write_text(_json.dumps({"session_id": sid, "status": "queued", "captured_count": 0}), encoding="utf-8")
    (sdir / "capture.log").touch()

    state = {"opens": 0, "frame_no": 0}

    class _StallingCap:
        """開けはするが読めない（通信断シミュレーション）。"""

        def isOpened(self) -> bool:
            return True

        def read(self):
            return False, None

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _WorkingCap:
        def isOpened(self) -> bool:
            return True

        def read(self):
            state["frame_no"] += 1
            return True, f"frame-{state['frame_no']}"

        def set(self, *_a, **_kw) -> bool:
            return True

        def release(self) -> None:
            pass

    class _JpegBuf:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def tobytes(self) -> bytes:
            return self._data

    class _FakeCv2:
        CAP_FFMPEG = 1900
        CAP_DSHOW = 700
        CAP_PROP_BUFFERSIZE = 38
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54

        def VideoCapture(self, *_a, **_kw):
            state["opens"] += 1
            # 初回オープン+再接続2回分（計3回）は「開けるが読めない」状態を維持し、
            # 通信断を約9〜10秒（許容誤差5秒を明確に超える長さ）継続させる。
            # 4回目のオープン（3回目の再接続）で復旧する。
            return _StallingCap() if state["opens"] <= 3 else _WorkingCap()

        def imencode(self, _ext, _frame):
            buf = _io.BytesIO()
            Image.new("RGB", (320, 240), (5 + state["frame_no"] % 200, 100, 150)).save(buf, format="JPEG")
            return True, _JpegBuf(buf.getvalue())

        def __getattr__(self, _name):
            return lambda *a, **kw: None

    orig_argv = sys.argv
    orig_cv2 = sys.modules.get("cv2")
    orig_dry_run = os.environ.pop("YTS_CAPTURE_DRY_RUN", None)
    sys.modules["cv2"] = _FakeCv2()
    sys.argv = [
        "capture_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(sdir / "live"),
        "--raw-images-dir", str(ROOT / PROJ / "raw" / "images"),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "url",
        "--source", "http://127.0.0.1:9/stale-skip-fake",
        # video_fps=20 -> max_read_fail=60, video_interval=0.05秒 -> 1回の通信断
        # サイクルは約3秒（60*0.05）。3サイクル分＝約9秒の通信断を作る。
        # interval-minutes=2/60（=2秒）の自動撮影スロットが、その約9秒の間に
        # 複数回過ぎるようにする。
        "--video-fps", "20", "--interval-minutes", str(2 / 60),
    ]

    result_holder: dict[str, int] = {}

    def _run() -> None:
        result_holder["rc"] = capture_worker.main()

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    try:
        # --- まず本当に通信断（再接続中）状態へ入ったことを確認する ---
        # ("running"状態は通信断の前後どちらでも観測され得るため、"再接続中"を
        #  経由したことを先に確認しないと、通信断が起きる前の状態を誤って
        #  「復旧した」と判定してしまう（実際にこの誤判定が起きたため修正した）。
        saw_reconnecting = False
        for _ in range(150):  # 最大約15秒
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if "再接続中" in (data.get("message") or ""):
                saw_reconnecting = True
                break
        check("stale-skip: enters reconnecting state (outage simulated)", saw_reconnecting)

        # --- 再接続中の状態を経由した後、実際に復旧する（running に戻る）まで待つ ---
        recovered = False
        for _ in range(200):  # 最大約20秒（3回のstalling openサイクル分を待てる）
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if data.get("status") == "running" and "再接続中" not in (data.get("message") or ""):
                recovered = True
                break
        check("stale-skip: worker recovers from the simulated outage", recovered)

        # --- 復旧した直後は、通信断中に過ぎたスロットを追いかけ撮影していないこと ---
        just_after_recovery = _safe_read_job(job_json)
        check(
            "stale-skip: no catch-up capture for the stale slot right after recovery",
            (just_after_recovery.get("captured_count") or 0) == 0,
        )

        # --- その後の正規スロットでは、通常どおり撮影が再開すること（撮影を
        #     不必要にスキップし続けているのではないことの確認） ---
        resumed = False
        for _ in range(150):  # 最大約15秒（次の2秒スロット到来を十分待てる）
            time.sleep(0.1)
            data = _safe_read_job(job_json)
            if (data.get("captured_count") or 0) >= 1:
                resumed = True
                break
        check("stale-skip: normal auto capture resumes at the next regular slot", resumed)
    finally:
        (sdir / "stop.flag").write_text("stop", encoding="utf-8")
        th.join(timeout=15)
        sys.argv = orig_argv
        if orig_cv2 is not None:
            sys.modules["cv2"] = orig_cv2
        else:
            sys.modules.pop("cv2", None)
        if orig_dry_run is not None:
            os.environ["YTS_CAPTURE_DRY_RUN"] = orig_dry_run

    check("stale-skip: worker thread exited after stop", not th.is_alive())
    check("stale-skip: main() returned success (0) on normal stop", result_holder.get("rc") == 0)


if __name__ == "__main__":
    main()
