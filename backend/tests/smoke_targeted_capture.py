"""targeted rare-class capture（Issue #41）の軽量スモークテスト。

実カメラ/production weight/GPUは一切不要（YTS_CAPTURE_DRY_RUN=1で合成フレームを使用）。
検証項目:
  - 既存capture API（target未指定）が従来通り動作すること（後方互換）
  - target/purpose/max_frames付きでセッション作成でき、job.jsonへ反映されること
  - 撮影のたびにframes.jsonへmetadataが記録されること（自動GT化はしないことを確認）
  - max_frames到達で自動停止すること
  - frame review状態の更新（unreviewed→accepted等）
  - candidate manifest（CSV）の出力内容

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_targeted_capture.py
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

_tmp = tempfile.mkdtemp(prefix="yts_targeted_capture_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_CAPTURE_DRY_RUN"] = "1"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "targeted_capture_proj"
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
    last = {}
    while time.time() < deadline:
        r = client.get(f"{base}/{sid}")
        last = r.json()
        if last.get("captured_count", 0) >= at_least:
            return last
        time.sleep(0.2)
    return last


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]})
    base = f"/api/projects/{PROJ}/capture-sessions"

    # --- 後方互換: target/purpose/max_frames を一切指定しない既存クライアント ---
    legacy_body = {
        "session_name": "legacy_session",
        "source_type": "camera",
        "camera_index": 0,
        "video_fps": 10,
        "interval_minutes": None,
        "overwrite": False,
    }
    r = client.post(base, json=legacy_body)
    check("legacy (no target) session create -> 201", r.status_code == 201)
    info = r.json()
    check("legacy session has purpose=None", info.get("purpose") is None)
    check("legacy session has target=None", info.get("target") is None)
    client.post(f"{base}/legacy_session/stop")

    # --- targeted capture: target/purpose/max_frames 指定 ---
    targeted_body = {
        "session_name": "rare_p3_c4_smoke",
        "source_type": "camera",
        "camera_index": 0,
        "video_fps": 10,
        "interval_minutes": None,
        "overwrite": False,
        "purpose": "rare_class_collection",
        "target": {"digit_position": 3, "target_class": "4"},
        "max_frames": 2,
    }
    r = client.post(base, json=targeted_body)
    check("targeted session create -> 201", r.status_code == 201)
    info = r.json()
    check("targeted session purpose reflected", info["purpose"] == "rare_class_collection")
    check("targeted session target reflected", info["target"] == {"digit_position": 3, "target_class": "4"})
    check("targeted session max_frames reflected", info["max_frames"] == 2)

    sid = "rare_p3_c4_smoke"
    check("targeted session reaches running with a frame", wait_frame(sid))

    # --- validation: max_frames < 1 -> 400 ---
    r = client.post(base, json={**targeted_body, "session_name": "bad_max_frames", "max_frames": 0, "overwrite": False})
    check("max_frames < 1 -> 400", r.status_code == 400)

    # --- validation: digit_position < 0 -> 400 ---
    r = client.post(base, json={**targeted_body, "session_name": "bad_position",
                                 "target": {"digit_position": -1, "target_class": "4"}})
    check("target.digit_position < 0 -> 400", r.status_code == 400)

    # --- 撮影: capture_now を2回呼び、max_frames(2)到達で自動停止することを確認 ---
    # 連続要求はワーカーのポーリング周期(0.2秒)次第で immediate responseが
    # "pending" になることがある（既存smoke_capture.pyと同じ既知の挙動）。
    # 実際の反映は wait_captured_count の長めのtimeoutで検証する。
    r = client.post(f"{base}/{sid}/capture")
    check("capture_now #1 -> captured/pending", r.status_code == 200 and r.json()["status"] in ("captured", "pending"))
    time.sleep(1.0)
    r = client.post(f"{base}/{sid}/capture")
    check("capture_now #2 -> captured/pending", r.status_code == 200 and r.json()["status"] in ("captured", "pending"))

    info = wait_captured_count(base, sid, 2)
    check("captured_count == 2", info.get("captured_count") == 2)

    # max_frames到達後、ワーカーが自身をstopped状態にするまで少し待つ
    deadline = time.time() + 10.0
    stopped = False
    while time.time() < deadline:
        r = client.get(f"{base}/{sid}")
        if r.json().get("status") == "stopped":
            stopped = True
            break
        time.sleep(0.2)
    check("session auto-stopped at max_frames", stopped)

    # --- frames.json: GTではなく撮影意図のmetadataが記録されていること ---
    r = client.get(f"{base}/{sid}/frames")
    check("frames list -> 200", r.status_code == 200)
    frames = r.json()["frames"]
    check("frames recorded count == 2", len(frames) == 2)
    for f in frames:
        check(f"frame {f['stem']} target_digit_position == 3", f["target_digit_position"] == 3)
        check(f"frame {f['stem']} target_class == '4'", f["target_class"] == "4")
        check(f"frame {f['stem']} review_status == unreviewed (no auto-GT)", f["review_status"] == "unreviewed")
        check(f"frame {f['stem']} source == session_id (no credential leak)", f["source"] == sid)

    # --- review状態の更新 ---
    target_stem = frames[0]["stem"]
    r = client.patch(f"{base}/{sid}/frames/{target_stem}/review", json={"review_status": "accepted", "note": "clear digit 4"})
    check("review update -> 200", r.status_code == 200)
    check("review update reflects accepted", r.json()["review_status"] == "accepted")
    check("review update reflects note", r.json()["note"] == "clear digit 4")

    r = client.patch(f"{base}/{sid}/frames/{target_stem}/review", json={"review_status": "not_a_real_status"})
    check("invalid review_status -> 400", r.status_code == 400)

    r = client.patch(f"{base}/{sid}/frames/no_such_stem/review", json={"review_status": "accepted"})
    check("review update missing stem -> 404", r.status_code == 404)

    # --- candidate manifest (CSV) export ---
    r = client.get(f"{base}/{sid}/candidate-manifest")
    check("candidate manifest -> 200", r.status_code == 200)
    check("candidate manifest content-type is csv", "csv" in r.headers.get("content-type", ""))
    rows = list(csv.reader(io.StringIO(r.text)))
    check("candidate manifest header", rows[0] == [
        "capture_session_id", "stem", "timestamp", "target_position", "target_class", "review_status",
    ])
    check("candidate manifest has 2 data rows", len(rows) == 3)
    accepted_row = [row for row in rows[1:] if row[1] == target_stem][0]
    check("candidate manifest reflects reviewed status", accepted_row[5] == "accepted")
    check("candidate manifest reflects target_position", accepted_row[3] == "3")
    check("candidate manifest reflects target_class", accepted_row[4] == "4")

    # --- raw画像自体は標準のraw/imagesへ保存されている（既存annotationパイプラインと合流） ---
    raw_dir = ROOT / PROJ / "raw" / "images"
    saved = sorted(p.name for p in raw_dir.glob(f"{sid}_*.jpg"))
    check("raw images saved under raw/images", len(saved) == 2)

    print("\nALL TARGETED CAPTURE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
