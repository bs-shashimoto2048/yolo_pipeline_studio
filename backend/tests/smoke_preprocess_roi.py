"""前処理の固定ROI機能のスモークテスト（Issue #1 Checkpoint 5AE）。

- ROI無効時: 既存の前処理出力（回帰）が変わらないこと
- ROI有効時: crop境界・出力サイズ・処理順（roi_crop -> resize -> grayscale -> ... -> sharpen）
- 不正ROI（構造的不正・画像サイズ超過）が明示エラーになること（silent clampしない）

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_preprocess_roi.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_roi_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.services import preprocess_service  # noqa: E402
from app.schemas.preprocess import PreprocessSettings  # noqa: E402

client = TestClient(app)
PROJ = "roi_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str, w: int, h: int, proj: str = PROJ) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    buf.seek(0)
    client.post(f"/api/projects/{proj}/images",
                files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))])


def run(body: dict, proj: str = PROJ):
    return client.post(f"/api/projects/{proj}/preprocess/run", json=body)


def proc_dir(proj: str = PROJ) -> Path:
    return ROOT / proj / "processed" / "images"


def test_roi_disabled_regression() -> None:
    """ROI無効（既定）では、ROI関連コード追加前と出力が変わらないこと。"""
    proj = "roi_regress"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("img", 800, 600, proj=proj)

    r = run({
        "job_name": "p1", "output_format": "jpg",
        "grayscale_enabled": True, "sharpen_enabled": True, "sharpen_strength": 1.0,
        "resize_enabled": True, "resize_mode": "width", "resize_size": 640,
    }, proj=proj)
    check("regression run 200", r.status_code == 200)
    with Image.open(proc_dir(proj) / "img.jpg") as im:
        check("regression size width=640, aspect維持", im.size == (640, 480))

    meta = json.loads((ROOT / proj / "processed" / "metadata.json").read_text(encoding="utf-8"))
    check("regression processing_order", meta["processing_order"] == ["grayscale", "sharpen", "resize"])
    check("roi_enabled既定False", meta["settings"]["roi_enabled"] is False)


def test_roi_enabled_crop_and_order() -> None:
    proj = "roi_enabled"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("img", 1920, 1080, proj=proj)

    body = {
        "job_name": "p1", "output_format": "jpg",
        "roi_enabled": True, "roi_x0": 835, "roi_y0": 374, "roi_x1": 1354, "roi_y1": 480,
        "resize_enabled": True, "resize_mode": "width", "resize_size": 640,
        "grayscale_enabled": True,
        "sharpen_enabled": True, "sharpen_strength": 1.0,
    }
    r = run(body, proj=proj)
    check("roi run 200", r.status_code == 200)

    with Image.open(proc_dir(proj) / "img.jpg") as im:
        expected_h = round((480 - 374) * 640 / (1354 - 835))
        check(f"roi crop寸法519x106->width640 resize後サイズ 640x{expected_h}", im.size == (640, expected_h))

    meta = json.loads((ROOT / proj / "processed" / "metadata.json").read_text(encoding="utf-8"))
    check("roi processing_order = crop->resize->grayscale->sharpen",
          meta["processing_order"] == ["roi_crop", "resize", "grayscale", "sharpen"])

    # apply()（推論前処理相当）でも同じ変換になること
    with Image.open(ROOT / proj / "raw" / "images" / "img.png") as im:
        raw_bytes = io.BytesIO()
        im.save(raw_bytes, format="PNG")
    settings = PreprocessSettings(**body)
    out = preprocess_service.apply(raw_bytes.getvalue(), settings)
    check("apply()も同一処理順・同一出力サイズ", out.size == (640, expected_h))


def test_invalid_roi_structural() -> None:
    """構造的に不正なROI設定は明示エラー（400）。silent clampしない。"""
    proj = "roi_invalid_struct"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("img", 640, 480, proj=proj)

    # x0 >= x1
    r = run({"job_name": "p1", "roi_enabled": True, "roi_x0": 100, "roi_y0": 10, "roi_x1": 50, "roi_y1": 60}, proj=proj)
    check("roi x0>=x1 -> 400", r.status_code == 400)

    # 座標一部欠落
    r = run({"job_name": "p2", "roi_enabled": True, "roi_x0": 10, "roi_y0": 10, "roi_x1": 100}, proj=proj)
    check("roi座標欠落 -> 400", r.status_code == 400)


def test_invalid_roi_out_of_image_bounds() -> None:
    """ROIが実画像サイズを超える場合は明示エラー（400）。silent clampしない。"""
    proj = "roi_invalid_bounds"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("small", 100, 100, proj=proj)

    r = run({"job_name": "p1", "roi_enabled": True, "roi_x0": 0, "roi_y0": 0, "roi_x1": 200, "roi_y1": 50}, proj=proj)
    check("roi範囲が画像幅超過 -> 400", r.status_code == 400)


def main() -> None:
    test_roi_disabled_regression()
    test_roi_enabled_crop_and_order()
    test_invalid_roi_structural()
    test_invalid_roi_out_of_image_bounds()
    print("\nALL PREPROCESS ROI SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
