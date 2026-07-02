"""segment データセット作成のスモークテスト（Issue 022）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_segment_dataset.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_seg_ds_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)
PROJ = "seg_ds_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def add_image(stem: str) -> None:
    d = sum(ord(ch) for ch in stem)
    color = (d % 256, (d * 7) % 256, (d * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(buf, format="JPEG")
    buf.seek(0)
    client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", (f"{stem}.jpg", buf.getvalue(), "image/jpeg"))],
    )


def save_polygon(stem: str) -> None:
    poly = {
        "type": "polygon", "class_id": 0, "source": "manual",
        "points": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1},
                   {"x": 0.5, "y": 0.5}, {"x": 0.1, "y": 0.5}],
    }
    client.put(
        f"/api/projects/{PROJ}/images/{stem}/annotations",
        json={"annotations": [poly]},
    )


def main() -> None:
    client.post("/api/projects", json={"name": PROJ, "task": "segment"})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["scratch", "dent"]})
    for i in range(4):
        stem = f"img_{i:03d}"
        add_image(stem)
        save_polygon(stem)

    body = {
        "dataset_name": "dataset_001",
        "train_ratio": 0.5,
        "val_ratio": 0.5,
        "test_ratio": 0.0,
        "seed": 42,
        "use_selection": False,
    }
    r = client.post(f"/api/projects/{PROJ}/datasets", json=body)
    check("create dataset 201", r.status_code == 201)
    res = r.json()
    check("response task segment", res["task"] == "segment")

    ds = ROOT / PROJ / "datasets" / "dataset_001"
    check("data.yaml exists", (ds / "data.yaml").exists())

    # labels/train に polygon 形式がコピーされている
    train_labels = list((ds / "labels" / "train").glob("*.txt"))
    check("labels/train has files", len(train_labels) >= 1)
    tokens = train_labels[0].read_text(encoding="utf-8").strip().split()
    check("polygon label copied", len(tokens) >= 7 and (len(tokens) - 1) % 2 == 0)

    # metadata.json に task=segment
    meta = json.loads((ds / "metadata.json").read_text(encoding="utf-8"))
    check("metadata task segment", meta.get("task") == "segment")

    # 一覧にも task が出る
    r = client.get(f"/api/projects/{PROJ}/datasets")
    check("list task segment", r.json()["datasets"][0]["task"] == "segment")

    # --- detect データセット（既存通り動く） ---
    dproj = "det_ds_proj"
    client.post("/api/projects", json={"name": dproj})
    client.put(f"/api/projects/{dproj}/classes", json={"names": ["a"]})
    for i in range(4):
        stem = f"d_{i:03d}"
        buf = io.BytesIO()
        Image.new("RGB", (640, 480), (10 + i * 40, 10, 10)).save(buf, format="JPEG")
        buf.seek(0)
        client.post(f"/api/projects/{dproj}/images",
                    files=[("files", (f"{stem}.jpg", buf.getvalue(), "image/jpeg"))])
        client.put(f"/api/projects/{dproj}/images/{stem}/annotations", json={"annotations": [
            {"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.2, "height": 0.2}
        ]})
    r = client.post(f"/api/projects/{dproj}/datasets", json={
        "dataset_name": "dataset_001", "train_ratio": 0.5, "val_ratio": 0.5,
        "test_ratio": 0.0, "use_selection": False,
    })
    check("detect dataset 201", r.status_code == 201 and r.json()["task"] == "detect")

    print("\nALL SEGMENT DATASET SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
