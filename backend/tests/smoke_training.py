"""学習ジョブ基盤の軽量スモークテスト（Issue 005）。

実学習は走らせない。worker は YTS_TRAIN_DRY_RUN=1 で空実行させ、API/job.json/
一覧/ログ取得の疎通だけを確認する。実学習の確認手順は README を参照。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_training.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.mkdtemp(prefix="yts_train_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"  # worker を空実行にする
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.services import training_service  # noqa: E402

client = TestClient(app)
PROJ = "train_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str) -> None:
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


def _wait_for_status(job_json: Path, terminal: set[str], timeout: float = 5.0) -> str:
    """job.json の status が指定の終端状態集合に達するまで待つ（dry-runは高速に終わる）。"""
    deadline = time.time() + timeout
    status = "?"
    while time.time() < deadline:
        try:
            status = json.loads(job_json.read_text(encoding="utf-8")).get("status", "?")
        except (OSError, json.JSONDecodeError):
            status = "?"
        if status in terminal:
            return status
        time.sleep(0.1)
    return status


def _write_fake_job_dir(job_dir: Path, job_id: str, status: str, pid: int | None) -> None:
    """実際に学習プロセスを起動せず、既存ジョブ（job.json/train.log/results.csv/weights）を
    模したディレクトリを作る。上書き保護のテストは実際のUltralytics学習を待つ必要がないため、
    このように成果物だけを直接用意して検証する。
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "weights").mkdir(exist_ok=True)
    (job_dir / "weights" / "last.pt").write_bytes(b"FAKE-WEIGHT-DATA")
    (job_dir / "weights" / "best.pt").write_bytes(b"FAKE-WEIGHT-DATA-BEST")
    (job_dir / "train.log").write_text("[INFO] 学習開始 ...\n", encoding="utf-8")
    (job_dir / "results.csv").write_text("epoch,box_loss\n1,0.5\n", encoding="utf-8")
    job = {
        "job_id": job_id,
        "job_name": job_id,
        "dataset_name": "dataset_001",
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "started_at": "2026-01-01T00:00:01",
        "message": "training" if status in {"queued", "running"} else "completed",
    }
    if pid is not None:
        job["pid"] = pid
    (job_dir / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _snapshot(job_dir: Path) -> dict[str, bytes]:
    """ディレクトリ配下の全ファイルの内容をパスごとに記録する（変更検知用）。"""
    return {
        str(p.relative_to(job_dir)): p.read_bytes()
        for p in job_dir.rglob("*")
        if p.is_file()
    }


def _start_body(job_name: str, overwrite: bool) -> dict:
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
        "overwrite": overwrite,
    }


def test_running_job_overwrite_false() -> None:
    """ケース1: 実行中ジョブ + overwrite=false → 409、ファイル変更なし。"""
    base = f"/api/projects/{PROJ}/train-jobs"
    job_dir = ROOT / PROJ / "runs" / "train" / "guard_running_1"
    _write_fake_job_dir(job_dir, "guard_running_1", status="running", pid=os.getpid())
    before = _snapshot(job_dir)

    r = client.post(base, json=_start_body("guard_running_1", overwrite=False))
    check("case1: running + overwrite=false -> 409", r.status_code == 409)
    check("case1: files unchanged", _snapshot(job_dir) == before)


def test_running_job_overwrite_true() -> None:
    """ケース2（今回の障害の直接回帰テスト）: 実行中ジョブ + overwrite=true → 409。

    修正前は、この操作で既存ジョブディレクトリの削除処理が開始され、job.json だけが
    削除されて train.log 等ロック中のファイルは残る、という中途半端な状態が発生した
    （今回の障害そのもの）。修正後は「削除処理そのものが一切開始されない」こと、
    job.json を含む全ファイルが1バイトも変わらないことを確認する。
    """
    base = f"/api/projects/{PROJ}/train-jobs"
    job_dir = ROOT / PROJ / "runs" / "train" / "guard_running_2"
    _write_fake_job_dir(job_dir, "guard_running_2", status="running", pid=os.getpid())
    before = _snapshot(job_dir)

    r = client.post(base, json=_start_body("guard_running_2", overwrite=True))
    check("case2: running + overwrite=true -> 409 (not 201)", r.status_code == 409)
    check("case2: job.json still exists", (job_dir / "job.json").exists())
    check("case2: train.log still exists", (job_dir / "train.log").exists())
    check("case2: results.csv still exists", (job_dir / "results.csv").exists())
    check("case2: weights still exist", (job_dir / "weights" / "last.pt").exists())
    check("case2: no file content changed (1バイトも変わっていない)", _snapshot(job_dir) == before)
    saved = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    check("case2: status still running (誤って上書きされていない)", saved["status"] == "running")


def test_pid_fallback_detects_active_process_with_stale_status() -> None:
    """statusが実行中を示さない値でも、記録済みPIDが生きていれば実行中とみなすこと。

    status文字列だけに依存すると、更新漏れ・クラッシュ等でstatusが古いまま残った
    ケースを見逃す。PIDの生存確認による保険が効いているかを確認する。
    """
    base = f"/api/projects/{PROJ}/train-jobs"
    job_dir = ROOT / PROJ / "runs" / "train" / "guard_pid_fallback"
    # status は意図的に非アクティブな値にしておく（pidだけが実行中の手がかり）。
    _write_fake_job_dir(job_dir, "guard_pid_fallback", status="unknown", pid=os.getpid())
    before = _snapshot(job_dir)

    r = client.post(base, json=_start_body("guard_pid_fallback", overwrite=True))
    check("pid-fallback: stale status but alive PID -> still 409", r.status_code == 409)
    check("pid-fallback: files unchanged", _snapshot(job_dir) == before)


def test_completed_job_overwrite_false() -> None:
    """ケース3: 完了済みジョブ + overwrite=false → 409、変更なし。"""
    base = f"/api/projects/{PROJ}/train-jobs"
    job_dir = ROOT / PROJ / "runs" / "train" / "guard_done_1"
    _write_fake_job_dir(job_dir, "guard_done_1", status="completed", pid=None)
    before = _snapshot(job_dir)

    r = client.post(base, json=_start_body("guard_done_1", overwrite=False))
    check("case3: completed + overwrite=false -> 409", r.status_code == 409)
    check("case3: files unchanged", _snapshot(job_dir) == before)


def test_completed_job_overwrite_true() -> None:
    """ケース4: 完了済みジョブ + overwrite=true → 現行仕様どおり上書き開始できる（201）。"""
    base = f"/api/projects/{PROJ}/train-jobs"
    job_dir = ROOT / PROJ / "runs" / "train" / "guard_done_2"
    _write_fake_job_dir(job_dir, "guard_done_2", status="completed", pid=None)

    r = client.post(base, json=_start_body("guard_done_2", overwrite=True))
    check("case4: completed + overwrite=true -> 201 (仕様: 上書き許可)", r.status_code == 201)
    new_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    check(
        "case4: new job.json written for the overwritten job",
        new_job["status"] in {"queued", "running", "completed"},
    )


def test_rmtree_rename_failure_is_atomic() -> None:
    """ケース5: 削除（リネーム）が失敗した場合、中途半端な状態を作らずエラー終了すること。

    _safe_rmtree はまずゴミ箱名へリネームしてから削除する。リネーム自体が失敗する
    状況（os.rename をモックして再現）では、既存ジョブのファイルに一切触れず
    TrainConflictError（409）になることを確認する。
    """
    base = f"/api/projects/{PROJ}/train-jobs"
    job_dir = ROOT / PROJ / "runs" / "train" / "guard_renamefail"
    _write_fake_job_dir(job_dir, "guard_renamefail", status="completed", pid=None)
    before = _snapshot(job_dir)

    with patch("os.rename", side_effect=OSError("simulated: file in use")):
        r = client.post(base, json=_start_body("guard_renamefail", overwrite=True))
    check("case5: rename failure -> 409 (中途半端な新規開始をしない)", r.status_code == 409)
    check("case5: existing job dir untouched", job_dir.exists())
    check("case5: no partial deletion (1バイトも変わっていない)", _snapshot(job_dir) == before)


def setup_dataset() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["ct_h", "ct_l"]})
    for i in range(10):
        stem = f"img_{i:02d}"
        make_image(stem)
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


def main() -> None:
    setup_dataset()
    base = f"/api/projects/{PROJ}/train-jobs"

    body = {
        "dataset_name": "dataset_001",
        "job_name": "train_001",
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

    # --- dataset が存在しない → 404 ---
    r = client.post(base, json={**body, "dataset_name": "no_such"})
    check("missing dataset -> 404", r.status_code == 404)

    # --- data.yaml がない → 400 ---
    empty_ds = ROOT / PROJ / "datasets" / "empty_ds" / "images" / "train"
    empty_ds.mkdir(parents=True, exist_ok=True)
    r = client.post(base, json={**body, "dataset_name": "empty_ds"})
    check("missing data.yaml -> 400", r.status_code == 400)

    # --- 正常入力 → 201, job.json 作成 ---
    r = client.post(base, json=body)
    check("start 201", r.status_code == 201)
    res = r.json()
    check("status queued", res["status"] == "queued")
    check("run_path posix", res["run_path"] == "runs/train/train_001")
    check("log_path posix", res["log_path"] == "runs/train/train_001/train.log")

    job_json = ROOT / PROJ / "runs" / "train" / "train_001" / "job.json"
    check("job.json exists", job_json.exists())
    saved = json.loads(job_json.read_text(encoding="utf-8"))
    check("job.json fields", saved["job_id"] == "train_001" and saved["epochs"] == 1)
    check(
        "job.json status valid",
        saved["status"] in {"queued", "running", "completed", "failed"},
    )

    # --- 同名 overwrite=false → 409 ---
    r = client.post(base, json=body)
    check("duplicate -> 409", r.status_code == 409)

    # dry-run worker が completed になるまで待つ（実行中のジョブへ overwrite すると
    # 今回の再発防止修正により 409 になるため、"完了済みジョブへのoverwrite" を
    # 確実にテストするには先に completed であることを保証する必要がある）。
    _wait_for_status(job_json, {"completed", "failed"})

    # --- overwrite=true（完了済みジョブへの上書き）→ 201 ---
    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite (completed job) -> 201", r.status_code == 201)

    # --- 状態取得 ---
    r = client.get(f"{base}/train_001")
    check("get job 200", r.status_code == 200)
    check("get job id", r.json()["job_id"] == "train_001")

    # --- 一覧 ---
    r = client.get(base)
    check("list 200", r.status_code == 200)
    check("list has job", any(j["job_id"] == "train_001" for j in r.json()["jobs"]))

    # --- ログ取得 ---
    r = client.get(f"{base}/train_001/logs")
    check("logs 200", r.status_code == 200)
    check("logs has field", "log" in r.json())

    # --- 存在しないジョブ → 404 ---
    r = client.get(f"{base}/no_job")
    check("missing job -> 404", r.status_code == 404)

    # dry-run worker が完了するのを少し待って状態を確認（任意・参考）
    final = _wait_for_status(job_json, {"completed", "failed"})
    print(f"   (dry-run worker final status: {final})")

    # --- 実行中ジョブの上書き保護（今回の障害の再発防止テスト） ---
    test_running_job_overwrite_false()
    test_running_job_overwrite_true()
    test_pid_fallback_detects_active_process_with_stale_status()
    test_completed_job_overwrite_false()
    test_completed_job_overwrite_true()
    test_rmtree_rename_failure_is_atomic()

    print("\nALL TRAINING SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
