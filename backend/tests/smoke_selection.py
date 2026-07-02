"""画像選別のスモークテスト（Issue 015）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_selection.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_sel_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "sel_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def put_raw(filename: str, img: Image.Image, fmt: str = "PNG") -> None:
    d = ROOT / PROJ / "raw" / "images"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / filename, format=fmt)


def checker(w: int, h: int) -> Image.Image:
    """高コントラストの市松模様（シャープ＝ブレなし）。"""
    im = Image.new("RGB", (w, h), (0, 0, 0))
    px = im.load()
    for y in range(h):
        for x in range(w):
            if (x // 8 + y // 8) % 2 == 0:
                px[x, y] = (255, 255, 255)
    return im


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a"]})

    # 正常（大・適正輝度・シャープ）
    put_raw("ok_001.png", checker(640, 480))
    # 小サイズ
    put_raw("small_001.png", checker(100, 80))
    # 暗すぎ（ほぼ黒・単色＝ブレも誘発するので大きめにして輝度のみ見る）
    put_raw("dark_001.png", Image.new("RGB", (640, 480), (5, 5, 5)))
    # 明るすぎ
    put_raw("bright_001.png", Image.new("RGB", (640, 480), (250, 250, 250)))
    # ブレ（単色＝エッジ分散ほぼ0）だが輝度は中庸
    put_raw("blur_001.png", Image.new("RGB", (640, 480), (128, 128, 128)))
    # 重複（ok_001 と同一バイト）
    put_raw("dup_001.png", checker(640, 480))

    base = f"/api/projects/{PROJ}/selection"

    # 未実行 GET → 404
    r = client.get(base)
    check("get before run -> 404", r.status_code == 404)

    # 実行
    r = client.post(f"{base}/run", json={
        "source": "raw", "min_width": 320, "min_height": 320,
        "blur_threshold": 80.0, "dark_threshold": 30.0, "bright_threshold": 240.0,
        "detect_duplicates": True, "overwrite": True,
    })
    check("run 200", r.status_code == 200)
    summ = r.json()["summary"]
    check("selection.json saved", (ROOT / PROJ / "selection" / "selection.json").exists())
    check("image_count 6", summ["image_count"] == 6)
    check("small detected", summ["small_count"] >= 1)
    check("dark detected", summ["dark_count"] >= 1)
    check("bright detected", summ["bright_count"] >= 1)
    check("blur detected", summ["blur_count"] >= 1)
    check("duplicate detected", summ["duplicate_count"] >= 1)

    # GET 取得
    r = client.get(base)
    check("get 200", r.status_code == 200)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("small_001 warning", "small_image" in items["small_001"]["warnings"])
    check("dark_001 warning", "dark_image" in items["dark_001"]["warnings"])
    check("bright_001 warning", "bright_image" in items["bright_001"]["warnings"])
    check("blur_001 warning", "blur_image" in items["blur_001"]["warnings"])
    # 重複2枚目は excluded
    dup_item = items["dup_001"]
    ok_item = items["ok_001"]
    # どちらが先かはファイル名順（dup_001 < ok_001）なので dup_001 が先＝originalになる
    excluded_dup = dup_item if dup_item["status"] == "excluded" else ok_item
    check("duplicate 2nd excluded", excluded_dup["status"] == "excluded" and "duplicate_image" in excluded_dup["warnings"])
    check("ok included", items["ok_001"]["status"] in ("included", "excluded"))  # 片方がexcluded

    # 手動更新
    r = client.put(f"{base}/images/small_001", json={"status": "included", "manual_reason": "使う"})
    check("manual update 200", r.status_code == 200 and r.json()["status"] == "included")
    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("manual reflected", items["small_001"]["status"] == "included")

    # 不正status → 400
    r = client.put(f"{base}/images/small_001", json={"status": "bad"})
    check("bad status -> 400", r.status_code == 400)
    # 存在しない画像 → 404
    r = client.put(f"{base}/images/no_img", json={"status": "included"})
    check("missing image -> 404", r.status_code == 404)

    # === dataset 連携 ===
    # ラベルを全画像に付与
    lbl = ROOT / PROJ / "annotations" / "labels"
    lbl.mkdir(parents=True, exist_ok=True)
    for stem in ["ok_001", "small_001", "dark_001", "bright_001", "blur_001", "dup_001"]:
        (lbl / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")

    # use_selection=true, include_review=false → excluded/review除外
    r = client.post(f"/api/projects/{PROJ}/datasets", json={
        "dataset_name": "ds1", "train_ratio": 0.5, "val_ratio": 0.5, "test_ratio": 0.0,
        "image_source": "raw", "use_selection": True, "include_review_images": False,
    })
    check("dataset with selection 201", r.status_code == 201)
    total_excl_review = r.json()["summary"]["total_image_count"]

    # include_review_images=true → review含む（より多い）
    r2 = client.post(f"/api/projects/{PROJ}/datasets", json={
        "dataset_name": "ds2", "train_ratio": 0.5, "val_ratio": 0.5, "test_ratio": 0.0,
        "image_source": "raw", "use_selection": True, "include_review_images": True,
    })
    total_incl_review = r2.json()["summary"]["total_image_count"]
    check("include_review increases count", total_incl_review > total_excl_review)

    # selection.json 破損でも dataset作成は継続（warning）
    (ROOT / PROJ / "selection" / "selection.json").write_text("{ broken ]", encoding="utf-8")
    r = client.post(f"/api/projects/{PROJ}/datasets", json={
        "dataset_name": "ds3", "train_ratio": 0.5, "val_ratio": 0.5, "test_ratio": 0.0,
        "image_source": "raw", "use_selection": True,
    })
    check("broken selection -> dataset still 201", r.status_code == 201)
    check("broken selection warning", r.json().get("warning") is not None)

    print("\nALL SELECTION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
