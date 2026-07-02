"""アノテーション保存/読込APIのスモークテスト（Issue 002）。

一時ディレクトリを案件ルートにして実行するので、実データには影響しない。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_annotations.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

# 一時ディレクトリを案件ルートに（import 前に設定）
_tmp = tempfile.mkdtemp(prefix="yts_annot_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp

# backend ディレクトリを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "annot_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def setup() -> str:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["ct_h", "ct_l"]})
    buf = io.BytesIO()
    Image.new("RGB", (1280, 720), (10, 20, 30)).save(buf, format="JPEG")
    buf.seek(0)
    client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", ("sample_001.jpg", buf.getvalue(), "image/jpeg"))],
    )
    return f"/api/projects/{PROJ}/images/sample_001/annotations"


def main() -> None:
    base = setup()
    label_file = (
        Path(_tmp) / PROJ / "annotations" / "labels" / "sample_001.txt"
    )

    # 初期取得は空
    r = client.get(base)
    check("GET initial 200", r.status_code == 200)
    j = r.json()
    check("GET dims 1280x720", j["image_width"] == 1280 and j["image_height"] == 720)
    check("GET image_name", j["image_name"] == "sample_001.jpg")
    check("GET empty", j["annotations"] == [])

    # 空アノテーションを保存できる（空txt作成）
    r = client.put(base, json={"annotations": []})
    check("PUT empty saved", r.status_code == 200 and r.json()["annotation_count"] == 0)
    check(
        "label_path posix",
        r.json()["label_path"] == "annotations/labels/sample_001.txt",
    )
    check("empty txt exists", label_file.exists())
    check("empty txt content empty", label_file.read_text(encoding="utf-8") == "")

    # 1件のbboxを保存できる
    r = client.put(
        base,
        json={
            "annotations": [
                {
                    "class_id": 0,
                    "x_center": 0.512345,
                    "y_center": 0.433210,
                    "width": 0.120000,
                    "height": 0.088000,
                }
            ]
        },
    )
    check("PUT one saved", r.status_code == 200 and r.json()["annotation_count"] == 1)

    # 複数bboxを保存できる
    r = client.put(
        base,
        json={
            "annotations": [
                {"class_id": 0, "x_center": 0.5, "y_center": 0.4, "width": 0.12, "height": 0.088},
                {"class_id": 1, "x_center": 0.2311, "y_center": 0.612, "width": 0.05, "height": 0.07},
            ]
        },
    )
    check("PUT multi saved", r.json()["annotation_count"] == 2)

    # 保存したbboxを再読込できる
    r = client.get(base)
    ann = r.json()["annotations"]
    check("reload count 2", len(ann) == 2)
    check(
        "reload values",
        abs(ann[0]["x_center"] - 0.5) < 1e-6 and ann[1]["class_id"] == 1,
    )

    # txt が YOLO形式
    lines = label_file.read_text(encoding="utf-8").strip().splitlines()
    check("txt 2 lines", len(lines) == 2)
    check(
        "txt format",
        lines[0].split()[0] == "0" and len(lines[0].split()) == 5,
    )

    # class_id 範囲外は400
    r = client.put(
        base,
        json={"annotations": [
            {"class_id": 9, "x_center": 0.5, "y_center": 0.5, "width": 0.1, "height": 0.1}
        ]},
    )
    check("class_id out of range 400", r.status_code == 400)

    # 座標範囲外は400
    r = client.put(
        base,
        json={"annotations": [
            {"class_id": 0, "x_center": 1.5, "y_center": 0.5, "width": 0.1, "height": 0.1}
        ]},
    )
    check("coord out of range 400", r.status_code == 400)

    # width/height が0以下は400
    r = client.put(
        base,
        json={"annotations": [
            {"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.0, "height": 0.1}
        ]},
    )
    check("width<=0 400", r.status_code == 400)

    # bbox が画像範囲外は400
    r = client.put(
        base,
        json={"annotations": [
            {"class_id": 0, "x_center": 0.95, "y_center": 0.5, "width": 0.2, "height": 0.1}
        ]},
    )
    check("bbox outside image 400", r.status_code == 400)

    # 存在しない画像は404
    r = client.get(f"/api/projects/{PROJ}/images/no_such/annotations")
    check("missing image 404", r.status_code == 404)

    print("\nALL ANNOTATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
