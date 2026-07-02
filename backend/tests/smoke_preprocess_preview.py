"""前処理プレビュー & 新リサイズ仕様のスモークテスト（Issue 020）。"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_prev_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402

client = TestClient(app)
PROJ = "prev_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def put_raw(stem: str, w: int, h: int) -> None:
    d = paths.raw_images_dir(PROJ)
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (100, 120, 140)).save(d / f"{stem}.png", format="PNG")


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    put_raw("img_a", 1280, 720)

    base = f"/api/projects/{PROJ}/preprocess"

    # --- preview: resize_mode=width ---
    body = {"output_format": "jpg", "resize_enabled": True, "resize_mode": "width", "resize_size": 640}
    r = client.post(f"{base}/preview", json=body, params={"image_id": "img_a"})
    check("preview 200", r.status_code == 200)
    pv = r.json()
    check("before dims", pv["before_width"] == 1280 and pv["before_height"] == 720)
    # width=640 → 高さはアスペクト比 720*640/1280 = 360
    check("after width=640", pv["after_width"] == 640)
    check("after height=360 (aspect)", pv["after_height"] == 360)
    check("preview saved", (ROOT / PROJ / "processed" / "preview" / "img_a.jpg").exists())
    # processed本体は更新されない
    check("processed not created by preview", not (ROOT / PROJ / "processed" / "images").exists())
    # raw非破壊
    with Image.open(paths.raw_images_dir(PROJ) / "img_a.png") as im:
        check("raw intact", im.size == (1280, 720))

    # preview画像配信
    r = client.get(f"{base}/preview-image/img_a.jpg")
    check("preview-image 200", r.status_code == 200 and r.headers["content-type"].startswith("image/"))

    # --- preview: resize_mode=height ---
    body = {"output_format": "jpg", "resize_enabled": True, "resize_mode": "height", "resize_size": 360}
    r = client.post(f"{base}/preview", json=body, params={"image_id": "img_a"})
    pv = r.json()
    check("height mode after height=360", pv["after_height"] == 360)
    check("height mode after width=640 (aspect)", pv["after_width"] == 640)

    # --- 範囲外 → 400 ---
    r = client.post(f"{base}/preview", json={"resize_enabled": True, "resize_mode": "width", "resize_size": 10000})
    check("resize_size out of range -> 400", r.status_code == 400)
    r = client.post(f"{base}/preview", json={"resize_enabled": True, "resize_mode": "diagonal", "resize_size": 640})
    check("bad resize_mode -> 400", r.status_code == 400)

    # --- run: resize_mode=width で本処理 ---
    r = client.post(f"{base}/run", json={"output_format": "jpg", "overwrite": True,
                                         "resize_enabled": True, "resize_mode": "width", "resize_size": 320})
    check("run 200", r.status_code == 200)
    with Image.open(ROOT / PROJ / "processed" / "images" / "img_a.jpg") as im:
        check("run width=320 aspect height=180", im.size == (320, 180))

    print("\nALL PREPROCESS PREVIEW SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
