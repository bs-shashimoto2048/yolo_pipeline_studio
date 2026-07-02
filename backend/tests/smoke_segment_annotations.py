"""segment（polygon）アノテーション保存/読込のスモークテスト（Issue 022）。

detect の bbox 保存が壊れていないことも確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_segment_annotations.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_seg_annot_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def add_image(proj: str, stem: str) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 60, 90)).save(buf, format="JPEG")
    buf.seek(0)
    client.post(
        f"/api/projects/{proj}/images",
        files=[("files", (f"{stem}.jpg", buf.getvalue(), "image/jpeg"))],
    )


def main() -> None:
    # --- segment プロジェクト ---
    proj = "seg_proj"
    r = client.post("/api/projects", json={"name": proj, "task": "segment"})
    check("create segment project 201", r.status_code == 201 and r.json()["task"] == "segment")
    client.put(f"/api/projects/{proj}/classes", json={"names": ["scratch", "dent"]})
    add_image(proj, "img_001")
    base = f"/api/projects/{proj}/images/img_001/annotations"

    # 初期取得は空 + task=segment
    r = client.get(base)
    j = r.json()
    check("GET initial 200", r.status_code == 200)
    check("GET task segment", j["task"] == "segment")
    check("GET empty", j["annotations"] == [])

    poly = {
        "type": "polygon",
        "class_id": 0,
        "points": [
            {"x": 0.41, "y": 0.22},
            {"x": 0.50, "y": 0.24},
            {"x": 0.53, "y": 0.34},
            {"x": 0.44, "y": 0.38},
        ],
        "source": "manual",
    }

    # polygon 保存
    r = client.put(base, json={"annotations": [poly]})
    check("PUT polygon saved", r.status_code == 200 and r.json()["annotation_count"] == 1)
    check("save response task", r.json()["task"] == "segment")

    # 再読込で復元
    r = client.get(base)
    ann = r.json()["annotations"]
    check("reload count 1", len(ann) == 1)
    check("reload type polygon", ann[0]["type"] == "polygon")
    check("reload 4 points", len(ann[0]["points"]) == 4)
    check("reload coord", abs(ann[0]["points"][0]["x"] - 0.41) < 1e-6)

    # YOLO segmentation txt
    label_file = ROOT / proj / "annotations" / "labels" / "img_001.txt"
    check("seg txt exists", label_file.exists())
    tokens = label_file.read_text(encoding="utf-8").strip().split()
    check("seg txt token count 9", len(tokens) == 1 + 4 * 2)
    check("seg txt class_id", tokens[0] == "0")
    check("seg txt 6 decimals", tokens[1] == "0.410000")

    # 点数3未満は400
    r = client.put(base, json={"annotations": [
        {"class_id": 0, "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}]}
    ]})
    check("too few points 400", r.status_code == 400)

    # 座標範囲外は400
    r = client.put(base, json={"annotations": [
        {"class_id": 0, "points": [{"x": 1.5, "y": 0.1}, {"x": 0.2, "y": 0.2}, {"x": 0.3, "y": 0.3}]}
    ]})
    check("coord out of range 400", r.status_code == 400)

    # class_id 不正は400
    r = client.put(base, json={"annotations": [
        {"class_id": 9, "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}, {"x": 0.3, "y": 0.3}]}
    ]})
    check("class_id invalid 400", r.status_code == 400)

    # 空配列も保存できる
    r = client.put(base, json={"annotations": []})
    check("empty saved", r.status_code == 200 and r.json()["annotation_count"] == 0)

    # --- detect プロジェクト（既存bboxが壊れていない） ---
    dproj = "det_proj"
    r = client.post("/api/projects", json={"name": dproj})  # task省略→detect
    check("detect project default task", r.status_code == 201 and r.json()["task"] == "detect")
    client.put(f"/api/projects/{dproj}/classes", json={"names": ["a", "b"]})
    add_image(dproj, "img_001")
    dbase = f"/api/projects/{dproj}/images/img_001/annotations"
    r = client.put(dbase, json={"annotations": [
        {"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.2, "height": 0.1}
    ]})
    check("detect bbox saved", r.status_code == 200 and r.json()["annotation_count"] == 1)
    r = client.get(dbase)
    dj = r.json()
    check("detect task", dj["task"] == "detect")
    check("detect bbox reload", abs(dj["annotations"][0]["x_center"] - 0.5) < 1e-6)

    print("\nALL SEGMENT ANNOTATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
