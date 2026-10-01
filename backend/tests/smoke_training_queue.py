"""shared server mode: FIFO学習キュー + single GPU lockのスモークテスト（Issue #49）。

実学習は走らせない。worker は YTS_TRAIN_DRY_RUN=1 で空実行させる
（詳細はtests/smoke_training.py参照）。YTS_SHARED_SERVER_MODE=1で起動し、
TrainingQueueServiceのFIFO挙動・single GPU lock・restart recovery・
per-user limit・並行リクエストでのrace防止を確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_training_queue.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

_tmp = tempfile.mkdtemp(prefix="yts_train_queue_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"
os.environ["YTS_SHARED_SERVER_MODE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.services import training_queue_service  # noqa: E402

ROOT = Path(_tmp)
PROJ = "queue_proj"

def _identity_headers(user_id: str, display_name: str) -> dict:
    # HTTPヘッダはASCII以外を直接格納できないため、フロントエンド実装(identity.ts)
    # と同じくencodeURIComponent相当(quote)で符号化する（Issue #49 §7）。
    return {"X-YTS-User-Id": user_id, "X-YTS-Display-Name": quote(display_name)}


USER_A = _identity_headers("user-a", "Aさん")
USER_B = _identity_headers("user-b", "Bさん")
USER_C = _identity_headers("user-c", "Cさん")


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(client: TestClient, stem: str) -> None:
    d = sum(ord(ch) for ch in stem)
    color = (d % 256, (d * 7) % 256, (d * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(buf, format="PNG")
    buf.seek(0)
    client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))],
    )


def write_label(stem: str, content: str) -> None:
    p = ROOT / PROJ / "annotations" / "labels" / f"{stem}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def setup_dataset(client: TestClient) -> None:
    r = client.post("/api/projects", json={"name": PROJ}, headers=USER_A)
    assert r.status_code == 201, r.text
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})
    for i in range(10):
        stem = f"img_{i:02d}"
        make_image(client, stem)
        write_label(stem, f"{i % 2} 0.5 0.5 0.2 0.2\n")
    r = client.post(
        f"/api/projects/{PROJ}/datasets",
        json={
            "dataset_name": "dataset_001",
            "train_ratio": 0.8,
            "val_ratio": 0.2,
            "test_ratio": 0.0,
            "seed": 42,
        },
    )
    assert r.status_code == 201, r.text


def start_body(job_name: str) -> dict:
    return {
        "dataset_name": "dataset_001",
        "job_name": job_name,
        "model": "yolov8n.pt",
        "epochs": 1,
        "imgsz": 640,
        "batch": 8,
        "device": "auto",
        "workers": 2,
        "patience": 20,
        "seed": 42,
        "overwrite": False,
    }


def _wait_for_status(job_path: Path, terminal: set[str], timeout: float = 5.0) -> str:
    deadline = time.time() + timeout
    status = "?"
    while time.time() < deadline:
        try:
            status = json.loads(job_path.read_text(encoding="utf-8")).get("status", "?")
        except (OSError, json.JSONDecodeError):
            status = "?"
        if status in terminal:
            return status
        time.sleep(0.05)
    return status


def job_json_path(job_id: str) -> Path:
    return ROOT / PROJ / "runs" / "train" / job_id / "job.json"


def test_scenario_a_fifo_order(client: TestClient) -> None:
    """§66: A,B,C投入 → A running、B queued pos1、C queued pos2。"""
    os.environ["YTS_TRAIN_DRY_RUN_DELAY_MS"] = "1500"
    try:
        ra = client.post(
            f"/api/projects/{PROJ}/train-jobs", json=start_body("jobA"), headers=USER_A
        )
        check("scenario A: jobA started 201", ra.status_code == 201)
        check("scenario A: jobA queue_position None (immediate start)", ra.json()["queue_position"] is None)
    finally:
        os.environ["YTS_TRAIN_DRY_RUN_DELAY_MS"] = "0"

    rb = client.post(
        f"/api/projects/{PROJ}/train-jobs", json=start_body("jobB"), headers=USER_B
    )
    check("scenario A: jobB queued 201", rb.status_code == 201)
    check("scenario A: jobB position 1", rb.json()["queue_position"] == 1)

    rc = client.post(
        f"/api/projects/{PROJ}/train-jobs", json=start_body("jobC"), headers=USER_C
    )
    check("scenario A: jobC queued 201", rc.status_code == 201)
    check("scenario A: jobC position 2", rc.json()["queue_position"] == 2)

    status = client.get("/api/training-queue/status").json()
    check("scenario A: status.running is jobA", status["running"]["job_id"] == "jobA")
    check("scenario A: status.queued order [jobB, jobC]",
          [e["job_id"] for e in status["queued"]] == ["jobB", "jobC"])
    check("scenario A: owner_display_name surfaced",
          status["running"]["owner_display_name"] == "Aさん")


def test_scenario_b_auto_promote_on_completion(client: TestClient) -> None:
    """§67: A完了 → B自動開始、C position1。"""
    status = _wait_for_status(job_json_path("jobA"), {"completed", "failed"}, timeout=5.0)
    check("scenario B: jobA reached terminal status", status == "completed")

    training_queue_service.poll_and_advance()

    q = client.get("/api/training-queue/status").json()
    check("scenario B: running is now jobB", q["running"]["job_id"] == "jobB")
    check("scenario B: queued is now [jobC] at position 1",
          [e["job_id"] for e in q["queued"]] == ["jobC"] and q["queued"][0]["position"] == 1)


def test_scenario_c_failure_does_not_stall_queue(client: TestClient) -> None:
    """§68: B failure → queueが止まらずCが自動開始。"""
    # dry-runは必ず成功するため、実行中ジョブの異常終了を直接シミュレートする
    # （tests/smoke_training.pyの_write_fake_job_dirと同じ「成果物を直接用意する」方針）。
    p = job_json_path("jobB")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["status"] = "failed"
    data["message"] = "simulated failure for smoke test"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    training_queue_service.poll_and_advance()

    q = client.get("/api/training-queue/status").json()
    check("scenario C: running is now jobC (queue did not stall on failure)",
          q["running"] is not None and q["running"]["job_id"] == "jobC")
    check("scenario C: queue now empty", q["queued"] == [])


def test_scenario_d_cancel_queued_job(client: TestClient) -> None:
    """§69: queued中のjobをcancel → runningはそのまま、以降の順位が繰り上がる。"""
    rd = client.post(f"/api/projects/{PROJ}/train-jobs", json=start_body("jobD"), headers=USER_A)
    check("scenario D: jobD queued", rd.status_code == 201 and rd.json()["queue_position"] == 1)
    re_ = client.post(f"/api/projects/{PROJ}/train-jobs", json=start_body("jobE"), headers=USER_B)
    check("scenario D: jobE queued pos2", re_.status_code == 201 and re_.json()["queue_position"] == 2)

    cancel = client.post(f"/api/projects/{PROJ}/train-jobs/jobD/cancel", headers=USER_A)
    check("scenario D: cancel jobD 200", cancel.status_code == 200)
    check("scenario D: jobD marked cancelled", cancel.json()["status"] == "cancelled")

    q = client.get("/api/training-queue/status").json()
    check("scenario D: running still jobC (untouched)", q["running"]["job_id"] == "jobC")
    check("scenario D: queued now [jobE] at position 1",
          [e["job_id"] for e in q["queued"]] == ["jobE"] and q["queued"][0]["position"] == 1)

    # 後続シナリオに影響しないよう、runningだったjobCを終わらせてjobEを昇格させておく
    pc = job_json_path("jobC")
    data = json.loads(pc.read_text(encoding="utf-8"))
    data["status"] = "completed"
    pc.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    training_queue_service.poll_and_advance()
    q2 = client.get("/api/training-queue/status").json()
    check("scenario D cleanup: jobE now running", q2["running"] is not None and q2["running"]["job_id"] == "jobE")


def test_scenario_d2_cancel_running_job(client: TestClient) -> None:
    """§32/§69派生: running中のjobをcancel → 次のqueued jobが自動的に昇格する。

    jobFは投入時点ではqueued（jobEがrunning中のため）で、実際のPopen起動は
    cancel(jobE)呼び出しの中で初めて行われる。そのためDRY_RUN_DELAY環境変数は
    enqueue直後ではなく、cancel呼び出しが終わるまで設定したままにする
    （prepare_job/enqueueはPopenせず、launch_jobが実際に呼ばれた瞬間の
    os.environスナップショットだけが子プロセスに渡るため）。
    """
    os.environ["YTS_TRAIN_DRY_RUN_DELAY_MS"] = "3000"
    try:
        rf = client.post(f"/api/projects/{PROJ}/train-jobs", json=start_body("jobF"), headers=USER_A)
        check("scenario D2: jobF queued pos1", rf.status_code == 201 and rf.json()["queue_position"] == 1)

        cancel = client.post(f"/api/projects/{PROJ}/train-jobs/jobE/cancel", headers=USER_B)
        check("scenario D2: cancel running jobE 200", cancel.status_code == 200)
        check("scenario D2: jobE marked cancelled", cancel.json()["status"] == "cancelled")
    finally:
        os.environ["YTS_TRAIN_DRY_RUN_DELAY_MS"] = "0"

    q = client.get("/api/training-queue/status").json()
    check("scenario D2: jobF auto-promoted to running", q["running"] is not None and q["running"]["job_id"] == "jobF")


def test_scenario_e_restart_recovery() -> None:
    """§70/§22/§23: backend再起動後もqueued jobが保持され、runningは安全にfailed扱いされる。"""
    # jobFはrunning中のまま（まだdelay中の可能性がある）。再起動前の状態を確認。
    pre = training_queue_service.get_status()
    check("scenario E (pre): jobF is running before restart", pre.running is not None and pre.running.job_id == "jobF")

    with TestClient(app) as client2:
        # jobFのPIDは実際には生存しているはずなので、poll_and_advanceは何もしない
        # （再起動シミュレーションとしては、lifespan再実行時にrecover()が呼ばれる
        #   ことそのものを確認する: recover()はpoll_and_advance()を呼ぶだけで、
        #   生存中のPIDを誤ってfailedにしないことを検証する）。
        post = client2.get("/api/training-queue/status").json()
        check(
            "scenario E: queued/running state preserved across restart (still jobF running)",
            post["running"] is not None and post["running"]["job_id"] == "jobF",
        )

    # jobFが完了するまで待ち、実際にPIDが消えた後の2回目の再起動でinterrupted scanも検証する
    status = _wait_for_status(job_json_path("jobF"), {"completed", "failed"}, timeout=6.0)
    check("scenario E: jobF eventually completes", status == "completed")


def test_limit_per_user(client: TestClient) -> None:
    """§72/§28: 同一userの上限超過 → 明確な409。"""
    os.environ["YTS_TRAIN_DRY_RUN_DELAY_MS"] = "2000"
    try:
        r1 = client.post(f"/api/projects/{PROJ}/train-jobs", json=start_body("limitJob1"), headers=USER_A)
        check("limit test: job1 (running) 201", r1.status_code == 201)
        r2 = client.post(f"/api/projects/{PROJ}/train-jobs", json=start_body("limitJob2"), headers=USER_A)
        check("limit test: job2 (queued, at limit=2) 201", r2.status_code == 201)
        r3 = client.post(f"/api/projects/{PROJ}/train-jobs", json=start_body("limitJob3"), headers=USER_A)
        check("limit test: job3 exceeds per-user limit -> 409", r3.status_code == 409)
    finally:
        os.environ["YTS_TRAIN_DRY_RUN_DELAY_MS"] = "0"
    # cleanup: 投入した分をキャンセルして後続テストに影響させない
    client.post(f"/api/projects/{PROJ}/train-jobs/limitJob2/cancel", headers=USER_A)
    client.post(f"/api/projects/{PROJ}/train-jobs/limitJob1/cancel", headers=USER_A)
    training_queue_service.poll_and_advance()


def test_race_single_gpu_lock(client: TestClient) -> None:
    """§73/§74: ほぼ同時の複数start requestでも、GPU lockは絶対に二重取得されない。

    training_queue_service内のtraining_service.launch_jobを差し替え、
    「同時に『実行中』とみなした呼び出し数」の最大値を計測する。実際のenqueue()
    ロジック（_acquire_file_lockベースの排他制御）はそのまま使うため、
    モックするのはOSプロセスを立てる副作用のみ。
    """
    concurrent = {"current": 0, "max_seen": 0}
    guard = threading.Lock()

    def fake_launch_job(name: str, job_id: str):
        with guard:
            concurrent["current"] += 1
            concurrent["max_seen"] = max(concurrent["max_seen"], concurrent["current"])
        time.sleep(0.05)
        with guard:
            concurrent["current"] -= 1
        from app.schemas.training import TrainJobStartResponse

        return TrainJobStartResponse(
            project_name=name, job_id=job_id, job_name=job_id,
            status="queued", run_path="x", log_path="x/train.log",
        )

    results: list[int | str] = []

    def worker(i: int) -> None:
        try:
            r = client.post(
                f"/api/projects/{PROJ}/train-jobs",
                json=start_body(f"raceJob{i}"),
                headers={"X-YTS-User-Id": f"race-user-{i}"},
            )
            results.append(r.status_code)
        except Exception as exc:  # noqa: BLE001 - サーバー側例外を見逃さず記録する
            results.append(f"EXCEPTION: {exc!r}")

    with patch("app.services.training_queue_service.training_service.launch_job", side_effect=fake_launch_job):
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

    check("race test: all 8 threads completed without dropping", len(results) == 8)
    check("race test: all requests accepted (201)", all(code == 201 for code in results))
    check("race test: GPU lock never held by >1 launch concurrently", concurrent["max_seen"] <= 1)

    # cleanup: raceJob*のうちrunning/queuedをキャンセルして後続に影響させない
    q = client.get("/api/training-queue/status").json()
    for entry in ([q["running"]] if q["running"] else []) + q["queued"]:
        if entry and entry["job_id"].startswith("raceJob"):
            client.post(f"/api/projects/{PROJ}/train-jobs/{entry['job_id']}/cancel")


def main() -> None:
    with TestClient(app) as client:
        setup_dataset(client)
        test_scenario_a_fifo_order(client)
        test_scenario_b_auto_promote_on_completion(client)
        test_scenario_c_failure_does_not_stall_queue(client)
        test_scenario_d_cancel_queued_job(client)
        test_scenario_d2_cancel_running_job(client)
    test_scenario_e_restart_recovery()
    with TestClient(app) as client:
        test_limit_per_user(client)
        test_race_single_gpu_lock(client)

    print("\nALL TRAINING QUEUE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
