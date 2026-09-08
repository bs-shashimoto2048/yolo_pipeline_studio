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
import time
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


def put_raw(filename: str, img: Image.Image, fmt: str = "PNG", proj: str = PROJ) -> None:
    d = ROOT / proj / "raw" / "images"
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


def run_and_wait(proj: str, payload: dict, timeout: float = 20.0) -> dict:
    """/selection/run を叩いて完了(または失敗)までポーリングし、最終job statusを返す。

    非同期実行（Issue #11 Checkpoint 3）になったため、既存の「同期呼び出しで
    summaryが返る」前提のテストは、開始→ポーリング→完了確認の形に置き換える。
    """
    base = f"/api/projects/{proj}/selection"
    r = client.post(f"{base}/run", json=payload)
    check(f"[{proj}] run start -> 202", r.status_code == 202)
    deadline = time.time() + timeout
    last = r.json()["job"]
    while time.time() < deadline:
        s = client.get(f"{base}/run/status")
        if s.status_code == 200:
            last = s.json()
            if last.get("status") in ("completed", "failed"):
                break
        time.sleep(0.1)
    return last


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

    # 実行（selection未作成 -> mode="full"で正常生成。初回はdiff/fullどちらでも
    # 対象は全件になるが、明示的な完全生成であることを示すためfullを使う）
    job = run_and_wait(PROJ, {
        "source": "raw", "min_width": 320, "min_height": 320,
        "blur_threshold": 80.0, "dark_threshold": 30.0, "bright_threshold": 240.0,
        "detect_duplicates": True, "mode": "full",
    })
    check("run completed", job["status"] == "completed")
    check("selection.json saved", (ROOT / PROJ / "selection" / "selection.json").exists())

    r = client.get(base)
    check("get 200", r.status_code == 200)
    body = r.json()
    summ = body["summary"]
    check("image_count 6", summ["image_count"] == 6)
    check("small detected", summ["small_count"] >= 1)
    check("dark detected", summ["dark_count"] >= 1)
    check("bright detected", summ["bright_count"] >= 1)
    check("blur detected", summ["blur_count"] >= 1)
    check("duplicate detected", summ["duplicate_count"] >= 1)
    check("created_at present", bool(body.get("created_at")))
    check("full run -> all items status_source=auto", all(it["status_source"] == "auto" for it in body["items"]))
    check("freshness: not stale right after run", body["is_stale"] is False)
    check("freshness: current_image_count matches", body["current_image_count"] == 6)
    check("freshness: new/missing are 0", body["new_image_count"] == 0 and body["missing_image_count"] == 0)

    items = {it["image_id"]: it for it in body["items"]}
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

    # 手動更新（サーバー側で必ずstatus_source=manualへ強制されること。Issue #11）
    r = client.put(f"{base}/images/small_001", json={"status": "included", "manual_reason": "使う"})
    check("manual update 200", r.status_code == 200 and r.json()["status"] == "included")
    check("manual update response status_source=manual", r.json()["status_source"] == "manual")
    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("manual reflected", items["small_001"]["status"] == "included")
    check("manual reflected status_source", items["small_001"]["status_source"] == "manual")

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

    # === Issue #11: manual/unknown保持・reset-to-auto・削除reconcile・full正規化・
    #     重複(diff)・二重実行防止・大量規模 ===
    test_diff_preserves_manual_and_unknown_reconciles_deleted()
    test_reset_to_auto()
    test_full_normalizes_everything_to_auto()
    test_duplicate_across_diff()
    test_double_execution_rejected()
    test_legacy_overwrite_compat()
    test_bulk_runtime()
    test_mutation_blocked_during_active_run()

    print("\nALL SELECTION SMOKE TESTS PASSED")


def _sha1_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(data).hexdigest()


def test_diff_preserves_manual_and_unknown_reconciles_deleted() -> None:
    """diff更新が (1)unknown(旧データ)保持 (2)manual保持 (3)新規のみ自動判定
    (4)削除済み画像の除去 を同時に満たすことを確認する（Issue #11 必須検証3,4,6）。
    """
    proj = "sel_diff_proj"
    client.post("/api/projects", json={"name": proj})
    base = f"/api/projects/{proj}/selection"

    put_raw("a.png", checker(400, 400), proj=proj)
    put_raw("b.png", checker(400, 300), proj=proj)
    put_raw("d.png", checker(300, 400), proj=proj)

    # "a" は status_source キーが無い旧形式データとして手で作る（実際の運用で
    # このIssue以前に生成されたselection.jsonを模す）。
    a_bytes = (ROOT / proj / "raw" / "images" / "a.png").read_bytes()
    sel_dir = ROOT / proj / "selection"
    sel_dir.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "created_at": "2026-01-01T00:00:00",
        "source": "raw",
        "settings": {"min_width": 320, "min_height": 320, "blur_threshold": 80.0,
                     "dark_threshold": 30.0, "bright_threshold": 240.0, "duplicate_hash": True},
        "summary": {"image_count": 1, "included_count": 1, "excluded_count": 0, "review_count": 0,
                    "duplicate_count": 0, "small_count": 0, "dark_count": 0, "bright_count": 0, "blur_count": 0},
        "items": [{
            "image_id": "a", "image_name": "a.png", "source": "raw",
            "width": 400, "height": 400, "status": "included",
            "warnings": [], "reasons": [], "hash": _sha1_bytes(a_bytes),
            "brightness_mean": 100.0, "blur_score": 200.0, "duplicate_of": None,
            "manual_reason": None,
            # status_source キーを意図的に含めない（旧データを模す）
        }],
    }
    (sel_dir / "selection.json").write_text(json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # diff実行 その1: b/d が新規として追加される
    job = run_and_wait(proj, {"mode": "diff", "detect_duplicates": True})
    check("diff#1 completed", job["status"] == "completed")
    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("diff#1: legacy 'a' preserved untouched (status)", items["a"]["status"] == "included")
    check("diff#1: legacy 'a' reads as unknown (implicit migration)", items["a"]["status_source"] == "unknown")
    check("diff#1: new 'b' auto-classified", items["b"]["status_source"] == "auto")
    check("diff#1: new 'd' auto-classified", items["d"]["status_source"] == "auto")

    # b を手動で review へ変更（manual化）
    r = client.put(f"{base}/images/b", json={"status": "review", "manual_reason": "確認したい"})
    check("mark b manual -> 200", r.status_code == 200)

    # d.png を（削除APIを使わず）直接ファイルシステムから消す＝reconcile対象を作る
    (ROOT / proj / "raw" / "images" / "d.png").unlink()
    # e.png を新規追加
    put_raw("e.png", checker(400, 500), proj=proj)

    # diff実行 その2: a(unknown)/b(manual)は保護、dは消え、eが新規追加される
    job = run_and_wait(proj, {"mode": "diff", "detect_duplicates": True})
    check("diff#2 completed", job["status"] == "completed")
    r = client.get(base)
    body = r.json()
    items = {it["image_id"]: it for it in body["items"]}
    check("diff#2: 'a' still unknown & untouched", items["a"]["status_source"] == "unknown" and items["a"]["status"] == "included")
    check("diff#2: 'b' still manual & untouched (status stays review)", items["b"]["status_source"] == "manual" and items["b"]["status"] == "review")
    check("diff#2: 'd' removed by reconcile (file deleted outside the API)", "d" not in items)
    check("diff#2: 'e' newly auto-classified", items["e"]["status_source"] == "auto")
    check("diff#2: image_count == 3 (a,b,e)", body["summary"]["image_count"] == 3)
    check("diff#2: freshness matches current files (not stale)", body["is_stale"] is False and body["current_image_count"] == 3)


def test_reset_to_auto() -> None:
    """reset-to-autoで manual/unknown のどちらの画像も単一画像単位でautoへ戻せること
    （Issue #11 必須検証5）。"""
    proj = "sel_diff_proj"  # 直前のテストの続きの状態を使う
    base = f"/api/projects/{proj}/selection"

    r = client.post(f"{base}/images/b/reset-to-auto")
    check("reset-to-auto(manual 'b') -> 200", r.status_code == 200)
    check("reset-to-auto(b) -> status_source auto", r.json()["item"]["status_source"] == "auto")

    r = client.post(f"{base}/images/a/reset-to-auto")
    check("reset-to-auto(unknown 'a') -> 200", r.status_code == 200)
    check("reset-to-auto(a) -> status_source auto", r.json()["item"]["status_source"] == "auto")

    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("after reset: a is auto", items["a"]["status_source"] == "auto")
    check("after reset: b is auto", items["b"]["status_source"] == "auto")

    # 存在しない画像 -> 404
    r = client.post(f"{base}/images/no_such_image/reset-to-auto")
    check("reset-to-auto missing image -> 404", r.status_code == 404)


def test_full_normalizes_everything_to_auto() -> None:
    """full再生成は、直前にmanualへ変更した項目も含め全件autoへ正規化すること
    （Issue #11 必須検証7、Checkpoint 2修正指摘の中核）。"""
    proj = "sel_diff_proj"
    base = f"/api/projects/{proj}/selection"

    # e を手動でincludedへ（現在はauto→manualにしておく）
    r = client.put(f"{base}/images/e", json={"status": "included", "manual_reason": "確認済み"})
    check("mark e manual before full run", r.status_code == 200)
    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}
    check("e is manual before full run", items["e"]["status_source"] == "manual")

    job = run_and_wait(proj, {"mode": "full", "detect_duplicates": True})
    check("full run completed", job["status"] == "completed")
    r = client.get(base)
    body = r.json()
    check(
        "full run normalizes ALL items to status_source=auto (including previously-manual 'e')",
        all(it["status_source"] == "auto" for it in body["items"]),
    )
    check("full run: image_count matches current files", body["summary"]["image_count"] == body["current_image_count"])


def test_duplicate_across_diff() -> None:
    """diffモードでも重複検出が (a)既存同士 (b)新規同士 (c)新規と既存 の
    いずれのパターンでも機能すること（Issue #11 必須検証8）。"""
    proj = "sel_dup_diff_proj"
    client.post("/api/projects", json={"name": proj})
    base = f"/api/projects/{proj}/selection"

    put_raw("orig1.png", checker(400, 400), proj=proj)
    put_raw("orig2.png", checker(410, 410), proj=proj)
    job = run_and_wait(proj, {"mode": "full", "detect_duplicates": True})
    check("dup-diff: initial full run completed", job["status"] == "completed")

    # 新規: dup_of_orig1(既存と同一バイト) / newA・newB(新規同士で重複)
    put_raw("orig1.png", checker(400, 400), proj=proj)  # 上書きではなく同一内容の別名で複製
    (ROOT / proj / "raw" / "images" / "dup_of_orig1.png").write_bytes(
        (ROOT / proj / "raw" / "images" / "orig1.png").read_bytes()
    )
    checker(500, 500).save(ROOT / proj / "raw" / "images" / "newA.png", format="PNG")
    (ROOT / proj / "raw" / "images" / "newB.png").write_bytes(
        (ROOT / proj / "raw" / "images" / "newA.png").read_bytes()
    )

    job = run_and_wait(proj, {"mode": "diff", "detect_duplicates": True})
    check("dup-diff: diff run completed", job["status"] == "completed")
    r = client.get(base)
    items = {it["image_id"]: it for it in r.json()["items"]}

    check("dup vs existing: dup_of_orig1 flagged duplicate of orig1",
          items["dup_of_orig1"]["duplicate_of"] == "orig1" and "duplicate_image" in items["dup_of_orig1"]["warnings"])
    check("existing orig1 untouched (still not flagged as the duplicate side)",
          items["orig1"]["duplicate_of"] is None)
    newer_is_dup = items["newB"] if items["newB"]["duplicate_of"] == "newA" else items["newA"]
    check("new vs new: one of newA/newB flagged as duplicate of the other",
          newer_is_dup["duplicate_of"] in ("newA", "newB"))


def test_double_execution_rejected() -> None:
    """既にrunジョブが実行中(かつPID生存)の間は、新たなrun開始を409で拒否すること
    （Issue #11 必須検証10）。実際のタイミング競合を待たず、決定的に検証するため、
    実行中を装うjob.json（生存が保証されている自分自身のPID）を直接書き込む。
    """
    import os as _os

    proj = "sel_lock_proj"
    client.post("/api/projects", json={"name": proj})
    base = f"/api/projects/{proj}/selection"
    sel_dir = ROOT / proj / "selection"
    sel_dir.mkdir(parents=True, exist_ok=True)
    fake_job = {
        "status": "running", "mode": "diff", "source": "raw", "message": "解析中…",
        "total_count": 100, "processed_count": 1,
        "created_at": "2026-01-01T00:00:00", "started_at": "2026-01-01T00:00:00",
        "finished_at": None, "return_code": None, "pid": _os.getpid(),
    }
    (sel_dir / "run_job.json").write_text(json.dumps(fake_job, ensure_ascii=False, indent=2), encoding="utf-8")

    r = client.post(f"{base}/run", json={"mode": "diff"})
    check("run while another job is 'running' (alive pid) -> 409", r.status_code == 409)

    # PIDが死んでいる場合は実行中とみなさず、正常に開始できること
    fake_job["pid"] = 999999999  # 通常存在しないPID
    (sel_dir / "run_job.json").write_text(json.dumps(fake_job, ensure_ascii=False, indent=2), encoding="utf-8")
    job = run_and_wait(proj, {"mode": "diff"})
    check("run allowed once stale job's pid is dead", job["status"] == "completed")


def test_legacy_overwrite_compat() -> None:
    """mode省略時、旧overwriteフィールドが後方互換として解決されること
    （Checkpoint 2修正指摘: overwriteを即削除せず互換層を設ける）。"""
    proj = "sel_overwrite_compat_proj"
    client.post("/api/projects", json={"name": proj})
    base = f"/api/projects/{proj}/selection"
    put_raw("x.png", checker(400, 400), proj=proj)

    # overwrite=false かつ未作成 -> 旧仕様どおり全件作成（=full相当）で成功
    job = run_and_wait(proj, {"overwrite": False})
    check("legacy overwrite=false on first run -> completed (full-equivalent)", job["status"] == "completed")
    check("legacy overwrite=false resolved to full", job["mode"] == "full")

    # overwrite=false かつ既存 -> 旧仕様どおり409（衝突）
    r = client.post(f"{base}/run", json={"overwrite": False})
    check("legacy overwrite=false with existing selection -> 409", r.status_code == 409)

    # overwrite=true -> full として実行できる
    job = run_and_wait(proj, {"overwrite": True})
    check("legacy overwrite=true -> completed", job["status"] == "completed")
    check("legacy overwrite=true resolved to full", job["mode"] == "full")

    # 不正なmode文字列 -> 400
    r = client.post(f"{base}/run", json={"mode": "bogus"})
    check("invalid mode -> 400", r.status_code == 400)


def test_bulk_runtime() -> None:
    """数千枚規模のdisposable test projectで、非同期実行が同期HTTPをブロックせず
    完走し、進捗が更新され、安定して完了することを確認する（Issue #11 必須検証14）。

    projects/meter 等の実プロジェクトには一切触れない、このスモークテスト専用の
    一時プロジェクトのみを対象にする。
    """
    import time as _time

    proj = "sel_bulk_proj"
    client.post("/api/projects", json={"name": proj})
    img_dir = ROOT / proj / "raw" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    N = 3000
    base_img = checker(64, 64)
    buf = io.BytesIO()
    base_img.save(buf, format="PNG")
    base_bytes = buf.getvalue()
    t0 = _time.time()
    for i in range(N):
        (img_dir / f"bulk_{i:05d}.png").write_bytes(base_bytes)
    gen_elapsed = _time.time() - t0

    base = f"/api/projects/{proj}/selection"
    t0 = _time.time()
    r = client.post(f"{base}/run", json={"mode": "full", "detect_duplicates": True})
    check("bulk: run start -> 202 (does not block on HTTP)", r.status_code == 202)
    start_elapsed = _time.time() - t0
    check("bulk: POST /run itself returns immediately (<2s, not proportional to N)", start_elapsed < 2.0)

    # 進捗が実際に更新されていくことを確認する
    saw_partial_progress = False
    job = r.json()["job"]
    deadline = _time.time() + 180.0
    while _time.time() < deadline:
        s = client.get(f"{base}/run/status")
        job = s.json()
        if 0 < job.get("processed_count", 0) < job.get("total_count", 0):
            saw_partial_progress = True
        if job.get("status") in ("completed", "failed"):
            break
        _time.sleep(0.2)
    total_elapsed = _time.time() - t0

    check("bulk: job completed (not failed)", job.get("status") == "completed")
    check("bulk: total_count == N", job.get("total_count") == N)
    check("bulk: processed_count == N at completion", job.get("processed_count") == N)
    check("bulk: progress was observed advancing mid-run", saw_partial_progress)

    r = client.get(base)
    body = r.json()
    check("bulk: image_count == N", body["summary"]["image_count"] == N)
    check("bulk: not stale after full run", body["is_stale"] is False)
    print(f"[bulk] N={N} file_gen={gen_elapsed:.1f}s run_total={total_elapsed:.1f}s "
          f"(job started in {start_elapsed:.2f}s)")


def test_mutation_blocked_during_active_run() -> None:
    """selection run（diff/full）が実行中の間、selection.json や解析対象画像を
    書き換えるAPI（update_status/reset_to_auto/delete_image/rotate_image）を
    409で拒否し、run終了後は通常どおり成功することを確認する
    （Issue #11 追加対応: active run中のmutation競合対策）。

    実際のタイミング競合を待たず決定的に検証するため、二重実行防止テストと
    同じ手法（生存が保証されている自分自身のPIDを持つ、実行中を装う
    run_job.jsonを直接書き込む）を用いる。
    """
    import os as _os

    proj = "sel_mutation_guard_proj"
    client.post("/api/projects", json={"name": proj})
    base = f"/api/projects/{proj}/selection"

    put_raw("m1.png", checker(400, 400), proj=proj)
    put_raw("m2.png", checker(410, 410), proj=proj)
    job = run_and_wait(proj, {"mode": "full", "detect_duplicates": True})
    check("mutation-guard: initial full run completed", job["status"] == "completed")

    sel_dir = ROOT / proj / "selection"
    run_job_path = sel_dir / "run_job.json"

    def _mark_running() -> None:
        fake_job = {
            "status": "running", "mode": "diff", "source": "raw", "message": "解析中…",
            "total_count": 100, "processed_count": 1,
            "created_at": "2026-01-01T00:00:00", "started_at": "2026-01-01T00:00:00",
            "finished_at": None, "return_code": None, "pid": _os.getpid(),
        }
        run_job_path.write_text(json.dumps(fake_job, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mark_completed() -> None:
        data = json.loads(run_job_path.read_text(encoding="utf-8-sig"))
        data["status"] = "completed"
        data["finished_at"] = "2026-01-01T00:00:01"
        run_job_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 1. active中: update_status -> 409 ---
    _mark_running()
    r = client.put(f"{base}/images/m1", json={"status": "review", "manual_reason": "x"})
    check("mutation-guard: update_status during active run -> 409", r.status_code == 409)

    # --- 2. active中: reset_to_auto -> 409 ---
    r = client.post(f"{base}/images/m1/reset-to-auto")
    check("mutation-guard: reset_to_auto during active run -> 409", r.status_code == 409)

    # --- 3. active中: delete_image -> 409 ---
    r = client.delete(f"{base}/images/m2")
    check("mutation-guard: delete_image during active run -> 409", r.status_code == 409)
    check("mutation-guard: m2 file NOT deleted while blocked", (ROOT / proj / "raw" / "images" / "m2.png").exists())

    # --- 4. active中: rotate_image -> 409 ---
    r = client.post(f"{base}/images/m1/rotate", json={"source": "raw", "angle": 90})
    check("mutation-guard: rotate_image during active run -> 409", r.status_code == 409)

    # --- 5. run終了後は各操作が通常どおり成功すること ---
    _mark_completed()
    r = client.put(f"{base}/images/m1", json={"status": "review", "manual_reason": "x"})
    check("mutation-guard: update_status after run completes -> 200", r.status_code == 200)
    r = client.post(f"{base}/images/m1/reset-to-auto")
    check("mutation-guard: reset_to_auto after run completes -> 200", r.status_code == 200)
    r = client.post(f"{base}/images/m1/rotate", json={"source": "raw", "angle": 90})
    check("mutation-guard: rotate_image after run completes -> 200", r.status_code == 200)
    r = client.delete(f"{base}/images/m2")
    check("mutation-guard: delete_image after run completes -> 200", r.status_code == 200)
    check("mutation-guard: m2 file actually deleted after run completes", not (ROOT / proj / "raw" / "images" / "m2.png").exists())


if __name__ == "__main__":
    main()
