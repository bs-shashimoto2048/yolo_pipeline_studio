"""segment 学習ジョブのスモークテスト（Issue 022、dry-run）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_segment_training.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_seg_train_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)
PROJ = "seg_train_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def setup_dataset() -> None:
    client.post("/api/projects", json={"name": PROJ, "task": "segment"})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["scratch"]})
    for i in range(4):
        stem = f"img_{i:03d}"
        buf = io.BytesIO()
        Image.new("RGB", (640, 480), (30 + i * 40, 60, 90)).save(buf, format="JPEG")
        buf.seek(0)
        client.post(f"/api/projects/{PROJ}/images",
                    files=[("files", (f"{stem}.jpg", buf.getvalue(), "image/jpeg"))])
        client.put(f"/api/projects/{PROJ}/images/{stem}/annotations", json={"annotations": [
            {"type": "polygon", "class_id": 0, "source": "manual",
             "points": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}]}
        ]})
    client.post(f"/api/projects/{PROJ}/datasets", json={
        "dataset_name": "dataset_001", "train_ratio": 0.5, "val_ratio": 0.5,
        "test_ratio": 0.0, "use_selection": False,
    })


def wait_completed(job_id: str) -> str:
    job_json = ROOT / PROJ / "runs" / "train" / job_id / "job.json"
    final = "?"
    for _ in range(30):
        time.sleep(0.2)
        final = json.loads(job_json.read_text(encoding="utf-8"))["status"]
        if final in {"completed", "failed"}:
            break
    return final


def main() -> None:
    setup_dataset()
    base = f"/api/projects/{PROJ}/train-jobs"

    # task 未指定 → プロジェクト task=segment を採用
    r = client.post(base, json={
        "dataset_name": "dataset_001", "job_name": "train_seg_001",
        "model": "yolov8n-seg.pt", "epochs": 1,
    })
    check("start 201", r.status_code == 201)

    # job.json に task=segment が保存される
    job_json = ROOT / PROJ / "runs" / "train" / "train_seg_001" / "job.json"
    saved = json.loads(job_json.read_text(encoding="utf-8"))
    check("job.json task segment", saved["task"] == "segment")
    check("job.json model seg", saved["model"] == "yolov8n-seg.pt")

    # dry-run で completed
    check("dry-run completed", wait_completed("train_seg_001") == "completed")

    # 取得APIで task が返る
    r = client.get(f"{base}/train_seg_001")
    check("get job task", r.status_code == 200 and r.json()["task"] == "segment")

    # 明示 task=detect も指定できる（上書き）
    r = client.post(base, json={
        "dataset_name": "dataset_001", "job_name": "train_det_x",
        "task": "detect", "model": "yolov8n.pt", "epochs": 1,
    })
    check("explicit detect task 201", r.status_code == 201)
    saved2 = json.loads((ROOT / PROJ / "runs" / "train" / "train_det_x" / "job.json").read_text(encoding="utf-8"))
    check("explicit task detect saved", saved2["task"] == "detect")

    # 不正 task は 400
    r = client.post(base, json={
        "dataset_name": "dataset_001", "job_name": "train_bad",
        "task": "bogus", "model": "yolov8n.pt",
    })
    check("invalid task 400", r.status_code == 400)

    print("\nALL SEGMENT TRAINING SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
