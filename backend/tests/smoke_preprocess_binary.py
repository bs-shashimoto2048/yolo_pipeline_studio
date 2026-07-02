"""前処理2値化のスモークテスト（Issue 021）。"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_bin_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402

client = TestClient(app)
PROJ = "bin_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def put_gradient(stem: str) -> None:
    d = paths.raw_images_dir(PROJ)
    d.mkdir(parents=True, exist_ok=True)
    im = Image.new("L", (256, 64))
    px = im.load()
    for x in range(256):
        for y in range(64):
            px[x, y] = x  # 左→右で 0..255 のグラデーション
    im.convert("RGB").save(d / f"{stem}.png", format="PNG")


def colors_of(path: Path) -> set:
    with Image.open(path) as im:
        return {p[1] for p in im.convert("L").getcolors(maxcolors=100000)}


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    put_gradient("g")
    base = f"/api/projects/{PROJ}/preprocess"

    # binary threshold=128（非反転）→ ほぼ 0 と 255 のみ
    r = client.post(f"{base}/run", json={"output_format": "png", "overwrite": True,
                                         "binary_enabled": True, "binary_threshold": 128, "binary_invert": False})
    check("run 200", r.status_code == 200)
    out = ROOT / PROJ / "processed" / "images" / "g.png"
    vals = colors_of(out)
    check("only black/white", vals.issubset({0, 255}))
    check("both present", 0 in vals and 255 in vals)

    # threshold が効く: 大きいthresholdなら白(255)ピクセルが減る
    with Image.open(out) as im:
        white_128 = sum(1 for p in im.convert("L").getdata() if p == 255)
    r = client.post(f"{base}/run", json={"output_format": "png", "overwrite": True,
                                         "binary_enabled": True, "binary_threshold": 200, "binary_invert": False})
    with Image.open(out) as im:
        white_200 = sum(1 for p in im.convert("L").getdata() if p == 255)
    check("higher threshold -> less white", white_200 < white_128)

    # invert が効く（同じ threshold=200 で invert すると白黒が反転＝白の数が変わる）
    r = client.post(f"{base}/run", json={"output_format": "png", "overwrite": True,
                                         "binary_enabled": True, "binary_threshold": 200, "binary_invert": True})
    with Image.open(out) as im:
        white_inv200 = sum(1 for p in im.convert("L").getdata() if p == 255)
    check("invert flips white count", white_inv200 != white_200)

    # threshold 範囲外 → 400
    r = client.post(f"{base}/run", json={"binary_enabled": True, "binary_threshold": 300})
    check("threshold out of range -> 400", r.status_code == 400)

    # metadata に binary 設定が保存される
    meta = json.loads((ROOT / PROJ / "processed" / "metadata.json").read_text(encoding="utf-8"))
    check("metadata has binary", meta["settings"]["binary_enabled"] is True)

    # preview にも反映される
    r = client.post(f"{base}/preview", json={"output_format": "png", "binary_enabled": True,
                                             "binary_threshold": 128}, params={"image_id": "g"})
    check("preview 200", r.status_code == 200)
    pv = ROOT / PROJ / "processed" / "preview" / "g.png"
    check("preview binary applied", colors_of(pv).issubset({0, 255}))

    print("\nALL PREPROCESS BINARY SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
