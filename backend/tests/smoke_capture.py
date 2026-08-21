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
    test_unreachable_url_capture()

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


def test_unreachable_url_capture() -> None:
    """到達不能URLでは、リトライを使い切った上で failed になり、残骸を残さず終了すること
    （video側 test_url_job_lifecycle の到達不能URLケースと同じ手法。capture_worker.py用）。
    """
    vid = "cap_url_unreachable"
    d = ROOT / PROJ / "capture" / vid
    (d / "live").mkdir(parents=True, exist_ok=True)
    job_json = d / "job.json"
    job_json.write_text(_json.dumps({
        "session_id": vid, "status": "queued", "source_type": "url",
        "source_url": "http://127.0.0.1:1/unreachable", "video_fps": 10,
        "captured_count": 0,
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
        "--source-type", "url",
        "--source", "http://127.0.0.1:1/unreachable",
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

    check("cap_url: unreachable url -> main() returns failure (1)", rc == 1)
    final = _safe_read_job(job_json)
    check("cap_url: unreachable url ends in failed", final.get("status") == "failed")
    check("cap_url: main() returned (no hang / no residue)", True)


if __name__ == "__main__":
    main()
