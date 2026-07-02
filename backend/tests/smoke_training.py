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

_tmp = tempfile.mkdtemp(prefix="yts_train_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"  # worker を空実行にする
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

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

    # --- overwrite=true → 201 ---
    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite -> 201", r.status_code == 201)

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
    final = "?"
    for _ in range(20):
        time.sleep(0.2)
        data = json.loads(job_json.read_text(encoding="utf-8"))
        final = data["status"]
        if final in {"completed", "failed"}:
            break
    print(f"   (dry-run worker final status: {final})")

    print("\nALL TRAINING SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
