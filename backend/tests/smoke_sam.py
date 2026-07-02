"""SAM支援アノテーションのスモークテスト（Issue 023、dry-run/mock）。

実SAMモデルはロードしない（YTS_SAM_DRY_RUN=1 で擬似polygonを生成）。
依存未導入エラーは YTS_SAM_SIMULATE_NO_DEP=1 で疑似的に確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_sam.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_sam_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_SAM_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
SEG = "sam_seg_proj"
DET = "sam_det_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def add_image(proj: str, stem: str) -> None:
    d = sum(ord(ch) for ch in stem)
    color = (d % 256, (d * 7) % 256, (d * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(buf, format="JPEG")
    buf.seek(0)
    client.post(
        f"/api/projects/{proj}/images",
        files=[("files", (f"{stem}.jpg", buf.getvalue(), "image/jpeg"))],
    )


def main() -> None:
    client.post("/api/projects", json={"name": SEG, "task": "segment"})
    client.put(f"/api/projects/{SEG}/classes", json={"names": ["scratch", "dent"]})
    add_image(SEG, "img_001")
    client.post("/api/projects", json={"name": DET})  # detect
    client.put(f"/api/projects/{DET}/classes", json={"names": ["a"]})
    add_image(DET, "img_001")

    sbase = f"/api/projects/{SEG}/sam"

    # --- settings GET（デフォルト） ---
    r = client.get(f"{sbase}/settings")
    check("settings GET 200", r.status_code == 200)
    check("default model", r.json()["model"] == "sam2_t.pt")

    # --- settings PUT ---
    good = {"model": "sam_b.pt", "device": "cpu", "polygon_simplify_epsilon": 3.0,
            "min_area": 100, "max_points": 200}
    r = client.put(f"{sbase}/settings", json=good)
    check("settings PUT 200", r.status_code == 200 and r.json()["model"] == "sam_b.pt")
    r = client.get(f"{sbase}/settings")
    check("settings persisted", r.json()["min_area"] == 100)

    # --- 不正 settings ---
    check("bad model 400", client.put(f"{sbase}/settings", json={**good, "model": "x.pt"}).status_code == 400)
    check("bad device 400", client.put(f"{sbase}/settings", json={**good, "device": "gpu"}).status_code == 400)
    check("bad epsilon 400", client.put(f"{sbase}/settings", json={**good, "polygon_simplify_epsilon": 99}).status_code == 400)
    check("bad min_area 400", client.put(f"{sbase}/settings", json={**good, "min_area": 0}).status_code == 400)
    check("bad max_points 400", client.put(f"{sbase}/settings", json={**good, "max_points": 5}).status_code == 400)
    check("bad merge_distance 400", client.put(f"{sbase}/settings", json={**good, "merge_distance_px": 200}).status_code == 400)

    # --- merge設定を保存・取得できる ---
    r = client.put(f"{sbase}/settings", json={**good, "merge_nearby_regions": False, "merge_distance_px": 16})
    check("merge settings PUT 200", r.status_code == 200)
    r = client.get(f"{sbase}/settings")
    check("merge settings persisted", r.json()["merge_nearby_regions"] is False and r.json()["merge_distance_px"] == 16)

    propose_url = f"/api/projects/{SEG}/images/img_001/sam/propose"
    box_prompt = {"type": "box", "box": {"x1": 0.25, "y1": 0.30, "x2": 0.55, "y2": 0.70},
                  "positive_points": [], "negative_points": []}

    # --- detectプロジェクトで propose → 400 ---
    r = client.post(f"/api/projects/{DET}/images/img_001/sam/propose",
                    json={"source": "auto", "class_id": 0, "prompt": box_prompt})
    check("detect propose 400", r.status_code == 400)

    # --- box prompt 正常（mock候補） ---
    r = client.post(propose_url, json={"source": "auto", "class_id": 0, "prompt": box_prompt})
    check("box propose 200", r.status_code == 200)
    cands = r.json()["candidates"]
    check("has candidate", len(cands) >= 1)
    pts = cands[0]["points"]
    check("polygon >=3 points", len(pts) >= 3)
    check("coords in 0..1", all(0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0 for p in pts))

    # --- prompt不足（box無し） → 400 ---
    r = client.post(propose_url, json={"class_id": 0, "prompt": {"type": "box", "positive_points": [], "negative_points": []}})
    check("box missing 400", r.status_code == 400)

    # --- prompt不足（point無し） → 400 ---
    r = client.post(propose_url, json={"class_id": 0, "prompt": {"type": "point", "positive_points": [], "negative_points": []}})
    check("point missing 400", r.status_code == 400)

    # --- box座標範囲外 → 400 ---
    r = client.post(propose_url, json={"class_id": 0, "prompt": {"type": "box", "box": {"x1": -0.1, "y1": 0.3, "x2": 0.5, "y2": 0.7}}})
    check("box out of range 400", r.status_code == 400)

    # --- point座標範囲外 → 400 ---
    r = client.post(propose_url, json={"class_id": 0, "prompt": {"type": "point", "positive_points": [{"x": 1.5, "y": 0.5}]}})
    check("point out of range 400", r.status_code == 400)

    # --- point prompt 正常 ---
    r = client.post(propose_url, json={"class_id": 0, "prompt": {"type": "point", "positive_points": [{"x": 0.5, "y": 0.5}], "negative_points": []}})
    check("point propose 200", r.status_code == 200 and len(r.json()["candidates"]) >= 1)

    # --- min_area未満は候補なし ---
    r = client.post(propose_url, json={
        "class_id": 0, "prompt": box_prompt,
        "settings": {"model": "sam2_t.pt", "device": "auto", "polygon_simplify_epsilon": 2.0,
                     "min_area": 100000, "max_points": 300},
    })
    check("min_area too high -> no candidate", r.status_code == 200 and len(r.json()["candidates"]) == 0)
    check("no-candidate message", r.json()["message"] is not None)

    # --- max_points以下に簡略化 ---
    r = client.post(propose_url, json={
        "class_id": 0, "prompt": box_prompt,
        "settings": {"model": "sam2_t.pt", "device": "auto", "polygon_simplify_epsilon": 2.0,
                     "min_area": 50, "max_points": 10},
    })
    c = r.json()["candidates"][0]
    check("simplified <= max_points", len(c["points"]) <= 10)

    merge_settings = {"model": "sam2_t.pt", "device": "auto", "polygon_simplify_epsilon": 2.0,
                      "min_area": 50, "max_points": 300, "merge_nearby_regions": True,
                      "merge_distance_px": 8}

    # --- 複数positive点で近接領域 → 1候補にマージ ---
    r = client.post(propose_url, json={
        "class_id": 0,
        "prompt": {"type": "point",
                   "positive_points": [{"x": 0.50, "y": 0.50}, {"x": 0.53, "y": 0.50}],
                   "negative_points": []},
        "settings": merge_settings,
    })
    check("near points 200", r.status_code == 200)
    mc = r.json()["candidates"]
    check("near merged into 1", len(mc) == 1)
    check("merged flag true", mc[0]["merged"] is True)
    check("source_mask_count 2", mc[0]["source_mask_count"] == 2)
    check("merged coords 0..1", all(0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0 for p in mc[0]["points"]))
    check("merged points <= max_points", len(mc[0]["points"]) <= merge_settings["max_points"])

    # --- 離れた領域 → 最大領域のみ（1候補） ---
    r = client.post(propose_url, json={
        "class_id": 0,
        "prompt": {"type": "point",
                   "positive_points": [{"x": 0.15, "y": 0.15}, {"x": 0.85, "y": 0.85}],
                   "negative_points": []},
        "settings": merge_settings,
    })
    check("far points 200", r.status_code == 200)
    fc = r.json()["candidates"]
    check("far -> largest only (1)", len(fc) == 1)
    check("far source_mask_count 2", fc[0]["source_mask_count"] == 2)

    # --- 画像が存在しない → 404 ---
    r = client.post(f"/api/projects/{SEG}/images/no_such/sam/propose",
                    json={"class_id": 0, "prompt": box_prompt})
    check("missing image 404", r.status_code == 404)

    # --- SAM依存未導入 friendly error ---
    os.environ["YTS_SAM_SIMULATE_NO_DEP"] = "1"
    try:
        r = client.post(propose_url, json={"class_id": 0, "prompt": box_prompt})
        check("no-dep 400", r.status_code == 400)
        check("no-dep friendly message", "requirements-sam.txt" in r.json()["detail"])
    finally:
        del os.environ["YTS_SAM_SIMULATE_NO_DEP"]

    print("\nALL SAM SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
