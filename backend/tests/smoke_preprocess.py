"""前処理のスモークテスト（Issue 014）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_preprocess.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_pre_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "pre_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str, w: int, h: int, fmt: str = "PNG") -> None:
    d = sum(ord(c) for c in stem)
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (d % 256, (d * 7) % 256, (d * 13) % 256)).save(buf, format=fmt)
    buf.seek(0)
    client.post(f"/api/projects/{PROJ}/images",
                files=[("files", (f"{stem}.{ 'png' if fmt=='PNG' else 'jpg'}", buf.getvalue(), "image/png"))])


def run(body: dict):
    return client.post(f"/api/projects/{PROJ}/preprocess/run", json=body)


def proc_dir() -> Path:
    return ROOT / PROJ / "processed" / "images"


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a"]})
    make_image("img_a", 1280, 720)
    make_image("img_b", 800, 600)

    raw_before = sorted(p.name for p in (ROOT / PROJ / "raw" / "images").iterdir())

    # --- resize + aspect + padding ---
    r = run({"job_name": "p1", "output_format": "jpg", "resize_enabled": True,
             "resize_width": 640, "resize_height": 640, "keep_aspect_ratio": True, "padding": True})
    check("run 200", r.status_code == 200)
    res = r.json()
    check("processed_count 2", res["processed_count"] == 2)
    check("processed_dir posix", res["processed_dir"] == "processed/images")

    # raw 非破壊
    raw_after = sorted(p.name for p in (ROOT / PROJ / "raw" / "images").iterdir())
    check("raw intact", raw_before == raw_after)

    # 出力jpg & padding で 640x640
    files = sorted(proc_dir().glob("*"))
    check("output jpg ext", all(p.suffix == ".jpg" for p in files))
    with Image.open(files[0]) as im:
        check("padded to 640x640", im.size == (640, 640))

    # metadata.json
    meta = json.loads((ROOT / PROJ / "processed" / "metadata.json").read_text(encoding="utf-8"))
    check("metadata items", len(meta["items"]) == 2)
    check("metadata settings", meta["settings"]["resize_enabled"] is True)

    # overwrite=false → 409
    r = run({"job_name": "p2", "resize_enabled": False})
    check("overwrite false -> 409", r.status_code == 409)

    # overwrite=true で再作成（output_format png）
    r = run({"job_name": "p3", "overwrite": True, "output_format": "png", "resize_enabled": False})
    check("overwrite true 200", r.status_code == 200)
    files = sorted(proc_dir().glob("*"))
    check("output png ext", all(p.suffix == ".png" for p in files))
    # resize 無効なので元サイズ維持
    with Image.open(proc_dir() / "img_a.png") as im:
        check("no resize keeps size", im.size == (1280, 720))

    # resize keep_aspect=false で厳密サイズ
    r = run({"job_name": "p4", "overwrite": True, "output_format": "jpg",
             "resize_enabled": True, "resize_width": 320, "resize_height": 200, "keep_aspect_ratio": False})
    check("exact resize 200", r.status_code == 200)
    with Image.open(proc_dir() / "img_a.jpg") as im:
        check("exact 320x200", im.size == (320, 200))

    # 明るさ・コントラスト・グレースケール・CLAHE が動作（落ちない＆出力生成）
    for label, body in [
        ("brightness", {"job_name": "b", "overwrite": True, "brightness_enabled": True, "brightness": 40}),
        ("contrast", {"job_name": "c", "overwrite": True, "contrast_enabled": True, "contrast": 1.8}),
        ("grayscale", {"job_name": "g", "overwrite": True, "grayscale_enabled": True}),
        ("clahe", {"job_name": "cl", "overwrite": True, "clahe_enabled": True, "clahe_clip_limit": 2.0, "clahe_tile_grid_size": 8}),
        ("sharpen", {"job_name": "sh", "overwrite": True, "sharpen_enabled": True, "sharpen_strength": 1.5}),
    ]:
        r = run(body)
        check(f"{label} 200", r.status_code == 200 and r.json()["processed_count"] == 2)

    # GET /preprocess
    r = client.get(f"/api/projects/{PROJ}/preprocess")
    check("info 200", r.status_code == 200)
    check("has_processed", r.json()["has_processed_images"] is True)

    # images?source=auto → processed 優先
    r = client.get(f"/api/projects/{PROJ}/images", params={"source": "auto"})
    autonames = sorted(i["filename"] for i in r.json()["images"])
    check("auto -> processed (jpg)", all(n.endswith(".jpg") for n in autonames))
    r = client.get(f"/api/projects/{PROJ}/images", params={"source": "raw"})
    rawnames = sorted(i["filename"] for i in r.json()["images"])
    check("raw -> png", all(n.endswith(".png") for n in rawnames))

    # 既存ラベルがある状態で前処理 → warning
    (ROOT / PROJ / "annotations" / "labels").mkdir(parents=True, exist_ok=True)
    (ROOT / PROJ / "annotations" / "labels" / "img_a.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    r = run({"job_name": "w", "overwrite": True, "resize_enabled": False})
    check("warning returned", r.json().get("warning") is not None)

    # dataset 作成で image_source=processed を選べる
    r = client.post(f"/api/projects/{PROJ}/datasets", json={
        "dataset_name": "ds_proc", "train_ratio": 0.5, "val_ratio": 0.5, "test_ratio": 0.0,
        "image_source": "processed", "include_empty_labels": True, "include_unlabeled_images": True,
    })
    check("dataset processed 201", r.status_code == 201)
    check("dataset used processed", r.json()["image_source"] == "processed")

    print("\nALL PREPROCESS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
