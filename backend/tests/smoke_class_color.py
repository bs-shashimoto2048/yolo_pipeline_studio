"""クラス色のスモークテスト（Issue 011）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_class_color.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_clscolor_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "color_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    base = f"/api/projects/{PROJ}/classes"

    # color 付きで保存
    r = client.put(base, json={"classes": [
        {"name": "ct_h", "color": "#ff4d4f"},
        {"name": "ct_l", "color": "#1677ff"},
    ]})
    check("save with color 200", r.status_code == 200)
    cs = r.json()["classes"]
    check("colors saved", cs[0]["color"] == "#ff4d4f" and cs[1]["color"] == "#1677ff")
    check("ids 0..1", [c["id"] for c in cs] == [0, 1])

    # color 省略 → 自動割当
    r = client.put(base, json={"classes": [
        {"name": "a"}, {"name": "b"}, {"name": "c"},
    ]})
    cs = r.json()["classes"]
    check("auto color assigned", all(c["color"].startswith("#") and len(c["color"]) == 7 for c in cs))

    # color 変更
    r = client.put(base, json={"classes": [
        {"name": "a", "color": "#52c41a"}, {"name": "b"}, {"name": "c"},
    ]})
    check("color edited", r.json()["classes"][0]["color"] == "#52c41a")

    # 不正な color → 400
    r = client.put(base, json={"classes": [{"name": "a", "color": "red"}]})
    check("invalid color -> 400", r.status_code == 400)
    r = client.put(base, json={"classes": [{"name": "a", "color": "#ZZZ"}]})
    check("invalid color2 -> 400", r.status_code == 400)

    # GET で color が返る
    r = client.get(base)
    check("get returns color", all("color" in c for c in r.json()["classes"]))

    # 旧形式 classes.yaml（names: dict）でも読める + color自動補完
    (ROOT / PROJ / "classes.yaml").write_text(
        "names:\n  0: old_a\n  1: old_b\n", encoding="utf-8"
    )
    r = client.get(base)
    cs = r.json()["classes"]
    check("legacy names read", [c["name"] for c in cs] == ["old_a", "old_b"])
    check("legacy color autofilled", all(c["color"].startswith("#") for c in cs))

    print("\nALL CLASS COLOR SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
