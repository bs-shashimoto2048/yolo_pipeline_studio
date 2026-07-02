"""画像回転のスモークテスト（Issue 020）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_rot_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402

client = TestClient(app)
PROJ = "rot_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    # raw と processed の両方を用意（640x480）— 回転は両方に反映される
    rawdir = paths.images_dir_for_source(PROJ, "raw")
    rawdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), (10, 20, 30)).save(rawdir / "img_a.jpg", format="JPEG")
    pdir = paths.processed_images_dir(PROJ)
    pdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), (50, 90, 160)).save(pdir / "img_a.jpg", format="JPEG")

    base = f"/api/projects/{PROJ}/selection/images/img_a/rotate"

    # 不正angle → 400
    r = client.post(base, json={"source": "processed", "angle": 45})
    check("bad angle -> 400", r.status_code == 400)

    # 90度回転 → raw / processed 両方が width/height 入れ替わり
    r = client.post(base, json={"source": "processed", "angle": 90})
    check("rotate 200", r.status_code == 200)
    body = r.json()
    check("dims swapped (480x640)", body["width"] == 480 and body["height"] == 640)
    with Image.open(pdir / "img_a.jpg") as im:
        check("processed rotated", im.size == (480, 640))
    with Image.open(rawdir / "img_a.jpg") as im:
        check("raw also rotated", im.size == (480, 640))
    # サムネイル再生成
    check("thumbnail regenerated", (paths.processed_thumbnails_dir(PROJ) / "img_a.jpg").exists())

    # 180度回転 → 元の縦横比へ戻る（480x640 → 640x... ; 180は縦横不変）
    r = client.post(base, json={"source": "processed", "angle": 180})
    check("rotate180 200", r.status_code == 200)
    check("180 keeps dims (480x640)", r.json()["width"] == 480 and r.json()["height"] == 640)

    # 既存ラベルがあると warning
    lbl = paths.labels_dir(PROJ)
    lbl.mkdir(parents=True, exist_ok=True)
    (lbl / "img_a.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    r = client.post(base, json={"source": "processed", "angle": 90})
    check("rotate with label -> warning", r.json().get("warning") is not None)

    # processed が無い画像 → 404
    r = client.post(f"/api/projects/{PROJ}/selection/images/no_img/rotate",
                    json={"source": "processed", "angle": 90})
    check("missing processed image -> 404", r.status_code == 404)

    print("\nALL IMAGE ROTATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
