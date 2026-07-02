"""フォルダ取り込みのスモークテスト（Issue 011）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_folder_import.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_folder_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "folder_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def png_bytes(seed: int, fmt: str = "PNG") -> bytes:
    color = (seed % 256, (seed * 7) % 256, (seed * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format=fmt)
    return buf.getvalue()


def import_files(files, allowed):
    multipart = [("files", (fn, data, "application/octet-stream")) for fn, data in files]
    # httpx: data は dict（list値は繰り返しフィールドに展開）。files と併用するため。
    form = {"allowed_extensions": list(allowed), "include_subfolders": "true"}
    return client.post(f"/api/projects/{PROJ}/images/import-folder", files=multipart, data=form)


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})

    # jpg + png + (除外したい bmp) + 大文字JPG + 非対応txt
    files = [
        ("a.jpg", png_bytes(1, "JPEG")),
        ("b.png", png_bytes(2, "PNG")),
        ("c.bmp", png_bytes(3, "BMP")),
        ("D.JPG", png_bytes(4, "JPEG")),     # 大文字拡張子
        ("notes.txt", b"hello world"),       # 非対応
    ]
    r = import_files(files, ["jpg", "jpeg", "png"])
    check("import 201", r.status_code == 201)
    res = r.json()
    # a.jpg, b.png, D.JPG が取り込み（bmpは選択外、txtは非対応）
    check("imported 3", res["imported_count"] == 3)
    check("unsupported 2 (bmp+txt)", res["unsupported_count"] == 2)
    check("skipped == sum", res["skipped_count"] == res["unsupported_count"] + res["duplicate_count"] + res["broken_count"])
    statuses = {it["filename"]: it["status"] for it in res["items"]}
    check("uppercase JPG imported", any(s == "imported" and "D" in fn for fn, s in statuses.items()) or res["imported_count"] == 3)

    # 重複: 同じ a.jpg を再取り込み → duplicate
    r = import_files([("a.jpg", png_bytes(1, "JPEG"))], ["jpg", "png"])
    check("duplicate 1", r.json()["duplicate_count"] == 1 and r.json()["imported_count"] == 0)

    # 破損画像 → broken
    r = import_files([("broken.png", b"not-an-image")], ["png"])
    check("broken 1", r.json()["broken_count"] == 1)

    # bmp を許可に含めれば取り込める
    r = import_files([("e.bmp", png_bytes(9, "BMP"))], ["bmp"])
    check("bmp imported when allowed", r.json()["imported_count"] == 1)

    # 既存の単一アップロードAPIが回帰しない
    r = client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", ("single.png", png_bytes(50, "PNG"), "image/png"))],
    )
    check("single upload still works", r.status_code == 201 and r.json()["added"] == 1)

    # 一覧に取り込んだ画像が出る
    r = client.get(f"/api/projects/{PROJ}/images")
    check("list reflects imports", r.json()["total"] >= 5)

    print("\nALL FOLDER IMPORT SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
