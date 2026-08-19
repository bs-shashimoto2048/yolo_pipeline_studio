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
from unittest.mock import patch

_tmp = tempfile.mkdtemp(prefix="yts_sel_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.services import selection_service  # noqa: E402
from app.services.selection_service import SelectionValidationError  # noqa: E402

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
    # 重複2枚目は review（自動検出だけでは削除しない。要確認として残す）
    dup_item = items["dup_001"]
    ok_item = items["ok_001"]
    # どちらが先かはファイル名順（dup_001 < ok_001）なので dup_001 が先＝originalになる
    review_dup = dup_item if dup_item["status"] == "review" else ok_item
    check("duplicate 2nd -> review", review_dup["status"] == "review" and "duplicate_image" in review_dup["warnings"])
    check("ok included", items["ok_001"]["status"] in ("included", "review"))  # 片方がreview

    # 手動更新
    r = client.put(f"{base}/images/small_001", json={"status": "included", "manual_reason": "使う"})
    check("manual update 200", r.status_code == 200 and r.json()["status"] == "included")
    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("manual reflected", items["small_001"]["status"] == "included")

    # 不正status → 400
    r = client.put(f"{base}/images/small_001", json={"status": "bad"})
    check("bad status -> 400", r.status_code == 400)
    # excluded は削除操作に置き換えられたため、もはや有効な手動statusではない → 400
    r = client.put(f"{base}/images/small_001", json={"status": "excluded"})
    check("excluded status rejected -> 400", r.status_code == 400)
    # 存在しない画像 → 404
    r = client.put(f"{base}/images/no_img", json={"status": "included"})
    check("missing image -> 404", r.status_code == 404)

    # === 削除（実ファイルを完全に消す破壊的操作） ===
    lbl_dir = ROOT / PROJ / "annotations" / "labels"
    lbl_dir.mkdir(parents=True, exist_ok=True)
    (lbl_dir / "blur_001.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    raw_path = ROOT / PROJ / "raw" / "images" / "blur_001.png"
    check("raw file exists before delete", raw_path.exists())

    r = client.delete(f"{base}/images/blur_001")
    check("delete 200", r.status_code == 200)
    del_res = r.json()
    check("delete reports raw file", any("raw/images/blur_001.png" == f for f in del_res["deleted_files"]))
    check("delete reports label file", any("annotations/labels/blur_001.txt" == f for f in del_res["deleted_files"]))
    check("raw file actually removed", not raw_path.exists())
    check("label file actually removed", not (lbl_dir / "blur_001.txt").exists())

    r = client.get(base)
    remaining_ids = {it["image_id"] for it in r.json()["items"]}
    check("deleted image removed from selection.json", "blur_001" not in remaining_ids)
    check("image_count decreased", r.json()["summary"]["image_count"] == 5)

    # 削除済み画像を再度削除 → 404
    r = client.delete(f"{base}/images/blur_001")
    check("delete missing -> 404", r.status_code == 404)

    # 他の画像には一切影響がないこと（削除したのは blur_001 のみ）
    dark_raw = ROOT / PROJ / "raw" / "images" / "dark_001.png"
    check("other image untouched (raw)", dark_raw.exists())
    r = client.get(base)
    items_after = {it["image_id"]: it for it in r.json()["items"]}
    check("other image untouched (selection.json)", "dark_001" in items_after)

    # === 削除: 不正な image_id（パストラバーサル等）は実際にファイルを消さず 400 ===
    # HTTP経由だと ".." や "." はURL正規化で別ルートに解決されてしまい、
    # このエンドポイントへ literal な ".." が到達するかはクライアント実装依存のため、
    # サービス関数を直接呼んでバリデーションそのものを検証する。
    for bad_id in ("..", ".", ""):
        try:
            selection_service.delete_image(PROJ, bad_id)
            check(f"delete rejects {bad_id!r}", False)
        except SelectionValidationError:
            check(f"delete rejects {bad_id!r} -> ValidationError", True)

    # プロジェクト外を指せない・意図しないファイルへ影響しないことの確認:
    # ".." 等を渡しても、プロジェクト外は元よりプロジェクト内のいかなるファイルも
    # 削除されていないこと（raw/labels の枚数が変化していない）。
    raw_count_before = len(list((ROOT / PROJ / "raw" / "images").iterdir()))
    lbl_count_before = len(list((ROOT / PROJ / "annotations" / "labels").iterdir()))
    for bad_id in ("..", ".", "", "../../etc/passwd", "..%2Fetc%2Fpasswd"):
        try:
            selection_service.delete_image(PROJ, bad_id)
        except Exception:  # noqa: BLE001 - 例外の種類は問わず、副作用だけ見る
            pass
    check(
        "no raw files removed by traversal-like ids",
        len(list((ROOT / PROJ / "raw" / "images").iterdir())) == raw_count_before,
    )
    check(
        "no label files removed by traversal-like ids",
        len(list((ROOT / PROJ / "annotations" / "labels").iterdir())) == lbl_count_before,
    )

    # === 削除: 一部ファイルの削除に失敗した場合、409になり中途半端な状態を隠さないこと ===
    # dark_001 のラベルを削除対象として用意し、raw画像の unlink だけを失敗させる。
    (lbl_dir / "dark_001.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    dark_raw_path = ROOT / PROJ / "raw" / "images" / "dark_001.png"
    check("dark_001 raw exists before partial-failure test", dark_raw_path.exists())

    real_unlink = Path.unlink

    def _flaky_unlink(self: Path, missing_ok: bool = False):
        if self.name == "dark_001.png":
            raise PermissionError(13, "simulated: file in use")
        return real_unlink(self, missing_ok=missing_ok)

    with patch.object(Path, "unlink", _flaky_unlink):
        r = client.delete(f"{base}/images/dark_001")
    check("partial failure -> 409 (not 200/500)", r.status_code == 409)
    check("failed raw file NOT deleted (no partial silent loss)", dark_raw_path.exists())
    check(
        "other target (label) still deleted despite raw failure",
        not (lbl_dir / "dark_001.txt").exists(),
    )

    # 失敗した分は実体が残っているので、再度（モックなしで）削除すれば正常に完了する
    r = client.delete(f"{base}/images/dark_001")
    check("retry after transient failure -> 200", r.status_code == 200)
    check("dark_001 raw removed on retry", not dark_raw_path.exists())

    # === dataset 連携 ===
    # ラベルを残りの画像に付与（blur_001/dark_001は上で削除済みのため対象外）
    lbl = ROOT / PROJ / "annotations" / "labels"
    lbl.mkdir(parents=True, exist_ok=True)
    for stem in ["ok_001", "small_001", "bright_001", "dup_001"]:
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
