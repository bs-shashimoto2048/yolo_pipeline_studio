"""segment ラベル品質チェックのスモークテスト（Issue 022）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_segment_label_validation.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_seg_lv_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)
PROJ = "seg_lv_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def add_image(stem: str) -> None:
    d = sum(ord(ch) for ch in stem)
    color = (d % 256, (d * 7) % 256, (d * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(buf, format="JPEG")
    buf.seek(0)
    client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", (f"{stem}.jpg", buf.getvalue(), "image/jpeg"))],
    )


def write_label(stem: str, content: str) -> None:
    d = ROOT / PROJ / "annotations" / "labels"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.txt").write_text(content + "\n", encoding="utf-8")


def main() -> None:
    client.post("/api/projects", json={"name": PROJ, "task": "segment"})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})

    cases = {
        "img_ok": "0 0.10 0.10 0.50 0.10 0.50 0.50 0.10 0.50",  # 正常4点
        "img_few": "0 0.10 0.10 0.20 0.20",                     # 2点 → too_few
        "img_odd": "0 0.10 0.10 0.20 0.20 0.30",                # 座標奇数
        "img_oor": "0 1.50 0.10 0.50 0.10 0.50 0.50",           # 範囲外
        "img_badcls": "9 0.10 0.10 0.50 0.10 0.50 0.50",        # class_id不正
        "img_small": "0 0.100 0.100 0.101 0.100 0.100 0.101",   # 極小 → warning
    }
    for stem, content in cases.items():
        add_image(stem)
        write_label(stem, content)
    add_image("img_missing")  # ラベルなし → missing warning

    r = client.post(f"/api/projects/{PROJ}/labels/validate")
    check("validate 200", r.status_code == 200)
    res = r.json()
    types = {i["type"] for i in res["issues"]}
    by_image: dict[str, set] = {}
    for i in res["issues"]:
        by_image.setdefault(i.get("image_id") or "", set()).add(i["type"])

    check("too_few_points error", "too_few_points" in types)
    check("odd_coord_count error", "odd_coord_count" in types)
    check("coord_out_of_range error", "coord_out_of_range" in types)
    check("class_id_not_found error", "class_id_not_found" in types)
    check("small_polygon warning", "small_polygon" in types)
    check("missing_label warning", "missing_label" in types)
    check("error_count > 0", res["summary"]["error_count"] > 0)

    # 正常polygonにはエラーが無い
    check("img_ok no error", "img_ok" not in by_image or not (by_image["img_ok"] & {
        "too_few_points", "odd_coord_count", "coord_out_of_range",
        "class_id_not_found", "invalid_column_count", "coord_not_numeric",
    }))

    # クラス別統計が返る
    check("class_stats present", len(res["class_stats"]) == 2)

    print("\nALL SEGMENT LABEL VALIDATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
