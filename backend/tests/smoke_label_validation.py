"""ラベル品質チェックAPIのスモークテスト（Issue 003）。

一時ディレクトリを案件ルートにして実行するので、実データには影響しない。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_label_validation.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_labelval_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "labelval_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str, w: int = 640, h: int = 480) -> None:
    # stem ごとに色を変えて重複ハッシュによるスキップを避ける
    digest = sum(ord(ch) for ch in stem)
    color = (digest % 256, (digest * 7) % 256, (digest * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    buf.seek(0)
    client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))],
    )


def write_label(stem: str, content: str) -> None:
    p = ROOT / PROJ / "annotations" / "labels" / f"{stem}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def validate() -> dict:
    r = client.post(f"/api/projects/{PROJ}/labels/validate")
    assert r.status_code == 200, r.text
    return r.json()


def types_of(issues: list, image_id: str) -> set[str]:
    return {i["type"] for i in issues if i.get("image_id") == image_id}


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["ct_h", "ct_l"]})

    # --- 1) 正常ラベルのみ → error_count == 0 ---
    make_image("good_001")
    write_label("good_001", "0 0.5 0.5 0.2 0.2\n1 0.3 0.3 0.1 0.1\n")
    res = validate()
    check("clean: error_count == 0", res["summary"]["error_count"] == 0)
    check("clean: total_bbox 2", res["summary"]["total_bbox_count"] == 2)
    check("clean: annotated 1", res["summary"]["annotated_image_count"] == 1)
    cs = {c["class_id"]: c for c in res["class_stats"]}
    check("clean: class0 bbox 1", cs[0]["bbox_count"] == 1)

    # --- 2) ラベルなし画像 → warning(missing_label) ---
    make_image("nolabel_001")
    res = validate()
    check(
        "missing_label is warning",
        any(
            i["type"] == "missing_label"
            and i["severity"] == "warning"
            and i["image_id"] == "nolabel_001"
            for i in res["issues"]
        ),
    )
    check("missing_label_count 1", res["summary"]["missing_label_count"] == 1)

    # --- 3) 空ラベル → warning(empty_label) ---
    make_image("empty_001")
    write_label("empty_001", "")
    res = validate()
    check(
        "empty_label is warning",
        any(
            i["type"] == "empty_label"
            and i["severity"] == "warning"
            and i["image_id"] == "empty_001"
            for i in res["issues"]
        ),
    )
    check("empty_label_count 1", res["summary"]["empty_label_image_count"] == 1)

    # --- 4) 孤立ラベル（画像なし） → error(orphan_label) ---
    write_label("orphan_999", "0 0.5 0.5 0.1 0.1\n")
    res = validate()
    check(
        "orphan_label is error",
        any(
            i["type"] == "orphan_label"
            and i["severity"] == "error"
            and i["image_id"] == "orphan_999"
            for i in res["issues"]
        ),
    )
    check("orphan_label_count 1", res["summary"]["orphan_label_count"] == 1)

    # --- 5) class_id範囲外 → error ---
    make_image("badclass_001")
    write_label("badclass_001", "9 0.5 0.5 0.1 0.1\n")
    res = validate()
    check("class_id_not_found error", "class_id_not_found" in types_of(res["issues"], "badclass_001"))

    # --- 6) 座標範囲外 → error ---
    make_image("badcoord_001")
    write_label("badcoord_001", "0 1.5 0.5 0.1 0.1\n")
    res = validate()
    check("coord_out_of_range error", "coord_out_of_range" in types_of(res["issues"], "badcoord_001"))

    # --- 7) width/height 0以下 → error ---
    make_image("badsize_001")
    write_label("badsize_001", "0 0.5 0.5 0.0 0.1\n")
    res = validate()
    check("non_positive_size error", "non_positive_size" in types_of(res["issues"], "badsize_001"))

    # --- 8) bbox画像範囲外 → error ---
    make_image("outside_001")
    write_label("outside_001", "0 0.95 0.5 0.2 0.1\n")
    res = validate()
    check("bbox_out_of_image error", "bbox_out_of_image" in types_of(res["issues"], "outside_001"))

    # --- 9) 列数不正 → error ---
    make_image("cols_001")
    write_label("cols_001", "0 0.5 0.5 0.1\n")
    res = validate()
    check("invalid_column_count error", "invalid_column_count" in types_of(res["issues"], "cols_001"))

    # --- 10) 極端に小さいbbox → warning ---
    make_image("small_001")
    write_label("small_001", "0 0.5 0.5 0.005 0.005\n")  # area=2.5e-5 < 1e-4
    res = validate()
    check("small_bbox warning", "small_bbox" in types_of(res["issues"], "small_001"))

    # --- 11) 極端に大きいbbox → warning ---
    make_image("large_001")
    write_label("large_001", "0 0.5 0.5 1.0 0.95\n")  # area=0.95 > 0.9
    res = validate()
    check("large_bbox warning", "large_bbox" in types_of(res["issues"], "large_001"))

    # --- 12) 重複bbox（同class かつ IoU>=0.95） → warning ---
    make_image("dup_001")
    write_label("dup_001", "0 0.5 0.5 0.2 0.2\n0 0.5 0.5 0.2 0.2\n")
    res = validate()
    check("duplicate_bbox warning", "duplicate_bbox" in types_of(res["issues"], "dup_001"))

    print("\nALL LABEL VALIDATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
