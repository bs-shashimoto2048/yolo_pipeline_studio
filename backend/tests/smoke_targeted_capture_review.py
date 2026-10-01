"""targeted capture review workflow（Issue #42）の軽量スモークテスト。

実カメラ/production weight/GPUは一切不要。YTS_CAPTURE_DRY_RUN=1で合成フレームを
使い、既存Issue #41 APIで撮影したframeに対し、本Issueで追加したreview summary・
duplicate audit・target progress・accepted-only manifest exportを検証する。
GTの自動判定はしない（review_statusは常にunreviewedから開始）ことを再確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_targeted_capture_review.py
"""

from __future__ import annotations

import csv
import io
import json as _json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_targeted_review_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_CAPTURE_DRY_RUN"] = "1"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "targeted_review_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def wait_frame(sid: str) -> bool:
    latest = ROOT / PROJ / "capture" / sid / "live" / "latest.jpg"
    for _ in range(50):
        time.sleep(0.2)
        if latest.exists() and latest.stat().st_size > 0:
            return True
    return False


def wait_captured_count(base: str, sid: str, at_least: int, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        r = client.get(f"{base}/{sid}")
        last = r.json()
        if last.get("captured_count", 0) >= at_least:
            return last
        time.sleep(0.2)
    return last


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": [str(i) for i in range(10)]})
    base = f"/api/projects/{PROJ}/capture-sessions"

    # --- 後方互換: target未指定の旧session（frames.json無し）が一覧APIを壊さないこと ---
    legacy_body = {"session_name": "legacy", "source_type": "camera", "camera_index": 0,
                   "video_fps": 10, "interval_minutes": None, "overwrite": False}
    client.post(base, json=legacy_body)
    client.post(f"{base}/legacy/stop")

    # --- targeted session を2つ作る（同じtarget position/classで集計を跨ぐことを確認） ---
    def start_targeted(sid: str, max_frames: int) -> None:
        body = {
            "session_name": sid, "source_type": "camera", "camera_index": 0, "video_fps": 10,
            "interval_minutes": None, "overwrite": False, "purpose": "rare_class_collection",
            "target": {"digit_position": 3, "target_class": "4"}, "max_frames": max_frames,
        }
        r = client.post(base, json=body)
        check(f"{sid} create -> 201", r.status_code == 201)
        check(f"{sid} reaches running with a frame", wait_frame(sid))
        # capture_now の即時応答は "captured"/"pending"/(起動直後のみ)"failed" のいずれも
        # あり得る既知の挙動（既存smoke_capture.pyと同じ理由：ワーカー起動直後は
        # ポーリング周期(0.2秒)とのタイミング次第）。最終的な反映は captured_count の
        # 増加そのもので確認し、即時応答は結果の目安としてのみ扱う。
        for i in range(max_frames):
            before = client.get(f"{base}/{sid}").json().get("captured_count", 0)
            for attempt in range(5):
                client.post(f"{base}/{sid}/capture")
                time.sleep(1.0)
                after = client.get(f"{base}/{sid}").json().get("captured_count", 0)
                if after > before:
                    break
            check(f"{sid} capture #{i + 1} increments captured_count", after > before)
        wait_captured_count(base, sid, max_frames)

    start_targeted("rare_s1", 2)
    start_targeted("rare_s2", 1)

    # --- review summary一覧 ---
    r = client.get(f"/api/projects/{PROJ}/capture-sessions-review-summary")
    check("review summary list -> 200", r.status_code == 200)
    summaries = {s["session_id"]: s for s in r.json()["sessions"]}
    check("legacy session present with purpose=None", summaries["legacy"]["purpose"] is None)
    check("legacy session unreviewed_count == 0 (no frames.json)", summaries["legacy"]["unreviewed_count"] == 0)
    check("rare_s1 captured_count == 2", summaries["rare_s1"]["captured_count"] == 2)
    check("rare_s1 unreviewed_count == 2 (no auto-GT)", summaries["rare_s1"]["unreviewed_count"] == 2)
    check("rare_s2 captured_count == 1", summaries["rare_s2"]["captured_count"] == 1)

    # --- s1の2枚のうち1枚をaccepted、1枚をrejected_ambiguousにする ---
    r = client.get(f"{base}/rare_s1/frames")
    s1_stems = [f["stem"] for f in r.json()["frames"]]
    check("rare_s1 has 2 frames", len(s1_stems) == 2)
    client.patch(f"{base}/rare_s1/frames/{s1_stems[0]}/review", json={"review_status": "accepted"})
    client.patch(f"{base}/rare_s1/frames/{s1_stems[1]}/review", json={"review_status": "rejected_ambiguous"})

    # --- s2の1枚をacceptedにする ---
    r = client.get(f"{base}/rare_s2/frames")
    s2_stems = [f["stem"] for f in r.json()["frames"]]
    client.patch(f"{base}/rare_s2/frames/{s2_stems[0]}/review", json={"review_status": "accepted"})

    # dry-run撮影フレームはどれも低frame_noの単色に近い画像（既存capture_worker.pyの
    # 仕様）で、aHashが互いに近くなりやすい。duplicate-audit監査ロジック自体の正しさを
    # 検証するため、s2側だけ明確に異なる乱数patternへ差し替える（撮影機構のテストは
    # smoke_targeted_capture.py側で別途担保済み、ここではaudit判定の正しさに専念する）。
    import numpy as _np
    import cv2 as _cv2
    s2_raw_path = (ROOT / PROJ / "raw" / "images" / f"{s2_stems[0]}.jpg")
    _rng = _np.random.default_rng(12345)
    _cv2.imwrite(str(s2_raw_path), _rng.integers(0, 256, size=(240, 320, 3), dtype=_np.uint8))

    r = client.get(f"/api/projects/{PROJ}/capture-sessions-review-summary")
    summaries = {s["session_id"]: s for s in r.json()["sessions"]}
    check("rare_s1 accepted_count == 1", summaries["rare_s1"]["accepted_count"] == 1)
    check("rare_s1 rejected_ambiguous_count == 1", summaries["rare_s1"]["rejected_ambiguous_count"] == 1)
    check("rare_s1 unreviewed_count == 0 after review", summaries["rare_s1"]["unreviewed_count"] == 0)

    # --- duplicate audit用の synthetic manifest を用意する(s1の accepted stem と
    #     exact-duplicateなstemをexisting Testとして登録し、監査が検出することを確認) ---
    # stem末尾は "_YYYYMMDD_HHMMSS" 形式でないと audit_dataset_split._parse_ts が
    # timestamp解析不能として比較対象から除外してしまう（near-duplicate判定は
    # timestamp近接が前提のため）。実際のaccepted stemの時刻+10秒を使う。
    from datetime import datetime, timedelta
    raw_dir = ROOT / PROJ / "raw" / "images"
    import shutil
    base_ts = datetime.strptime(s1_stems[0].rsplit("_", 2)[-2] + s1_stems[0].rsplit("_", 2)[-1], "%Y%m%d%H%M%S")
    dup_ts = (base_ts + timedelta(seconds=10)).strftime("%Y%m%d_%H%M%S")
    duplicate_test_stem = f"synthetic_existing_test_{dup_ts}"
    shutil.copy(raw_dir / f"{s1_stems[0]}.jpg", raw_dir / f"{duplicate_test_stem}.jpg")

    # _audit_candidates は manifest_path をrepo_root相対で安全性検証するため、
    # テスト用manifestも一時的にrepo内（backend/tests/配下）へ置き、終了後に必ず削除する。
    manifest_path = _BACKEND_DIR / "tests" / "_scratch_targeted_review_smoke_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_stem", "project", "split", "reading_gt"])
        w.writerow([duplicate_test_stem, PROJ, "test", "0000004"])
        w.writerow(["unrelated_train_stem", PROJ, "train", "0000005"])
    rel_manifest_path = str(manifest_path.relative_to(_REPO_ROOT))

    try:
        r = client.get(f"{base}/rare_s1/duplicate-audit", params={"manifest_path": rel_manifest_path})
        check("duplicate-audit -> 200", r.status_code == 200)
        results = {v["stem"]: v for v in r.json()["results"]}
        check("accepted stem flagged as near_duplicate (exact copy in Test)",
              results[s1_stems[0]]["verdict"] == "near_duplicate")
        check("flagged duplicate split includes test",
              "test" in results[s1_stems[0]]["duplicate_splits"] or "exact_match" in results[s1_stems[0]]["duplicate_splits"])

        # --- manifest_path のpath traversal防止（repo外の絶対パス）を確認 ---
        r = client.get(f"{base}/rare_s1/duplicate-audit",
                       params={"manifest_path": "../../../../../../etc/passwd"})
        check("duplicate-audit rejects path traversal outside repo -> 400", r.status_code == 400)

        # --- target progress (session跨ぎ集計) ---
        r = client.get(f"/api/projects/{PROJ}/targeted-capture-progress",
                        params={"manifest_path": rel_manifest_path, "digit_position": 3, "target_class": "4"})
        check("target progress -> 200", r.status_code == 200)
        prog = r.json()
        check("accepted_total == 2 (s1 + s2)", prog["accepted_total"] == 2)
        check("accepted_flagged_duplicate == 1 (s1's accepted frame is a near-duplicate)",
              prog["accepted_flagged_duplicate"] == 1)
        check("independent_primary == 1", prog["independent_primary"] == 1)
        check("threshold_minimum == 20", prog["threshold_minimum"] == 20)
    finally:
        manifest_path.unlink(missing_ok=True)

    # --- accepted-only candidate manifest export ---
    r = client.get(f"{base}/rare_s1/candidate-manifest", params={"accepted_only": True})
    check("accepted-only manifest -> 200", r.status_code == 200)
    rows = list(csv.reader(io.StringIO(r.text)))
    check("accepted-only manifest has exactly 1 data row", len(rows) == 2)
    check("accepted-only manifest row is the accepted stem", rows[1][1] == s1_stems[0])
    check("accepted-only manifest review_status == accepted", rows[1][5] == "accepted")

    # --- error states: 存在しないsessionのreview操作 ---
    r = client.get(f"{base}/no_such_session/frames")
    check("frames for missing session -> 404", r.status_code == 404)
    r = client.get(f"{base}/no_such_session/duplicate-audit", params={"manifest_path": "data_manifests/does_not_exist.csv"})
    check("duplicate-audit for missing session -> 404", r.status_code == 404)

    print("\nALL TARGETED CAPTURE REVIEW SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
