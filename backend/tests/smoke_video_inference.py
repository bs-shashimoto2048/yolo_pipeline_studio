"""映像（カメラ）推論基盤の軽量スモークテスト。

実カメラ/Ultralyticsは使わない。ワーカーは YTS_VIDEO_DRY_RUN=1 で合成フレームを
live/latest.jpg に書き出すだけ。検証項目:
  - GET /cameras が 200
  - バリデーション（学習ジョブ不在/weight不在/fps範囲/preprocess_mode）
  - ジョブ作成 → job.json 生成 → 合成フレーム出力
  - ジョブ取得/一覧
  - 停止後に /stream が最終フレームを1枚返して終了する

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_video_inference.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_video_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_VIDEO_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "video_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_fake_train_job(job_id: str, with_best: bool = True) -> None:
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"job_id": job_id, "status": "completed"}), encoding="utf-8"
    )
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"fake-weight")


def wait_frame(vid: str) -> bool:
    latest = ROOT / PROJ / "video" / vid / "live" / "latest.jpg"
    for _ in range(50):
        time.sleep(0.2)
        if latest.exists() and latest.stat().st_size > 0:
            return True
    return False


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})
    make_fake_train_job("train_001", with_best=True)

    base = f"/api/projects/{PROJ}/video-jobs"

    # --- カメラ一覧（環境依存だが 200 を返す） ---
    r = client.get(f"/api/projects/{PROJ}/cameras")
    check("cameras 200", r.status_code == 200 and "cameras" in r.json())

    body = {
        "video_job_name": "video_001",
        "train_job_id": "train_001",
        "weight_type": "best",
        "camera_index": 0,
        "video_fps": 15,
        "infer_fps": 5,
        "conf": 0.25,
        "iou": 0.7,
        "imgsz": 640,
        "device": "auto",
        "preprocess_mode": "none",
        "overwrite": False,
    }

    # --- 学習ジョブ不在 → 404 ---
    r = client.post(base, json={**body, "train_job_id": "no_such"})
    check("missing train job -> 404", r.status_code == 404)

    # --- weight不在 → 400 ---
    r = client.post(base, json={**body, "weight_type": "last"})
    check("missing weight -> 400", r.status_code == 400)

    # --- infer_fps > video_fps → 400 ---
    r = client.post(base, json={**body, "video_fps": 5, "infer_fps": 10})
    check("infer_fps>video_fps -> 400", r.status_code == 400)

    # --- video_fps 範囲外 → 400 ---
    r = client.post(base, json={**body, "video_fps": 0})
    check("video_fps range -> 400", r.status_code == 400)

    # --- preprocess_mode=latest だが前処理設定なし → 400 ---
    r = client.post(base, json={**body, "preprocess_mode": "latest"})
    check("latest without settings -> 400", r.status_code == 400)

    # --- 不正なジョブ名 → 400 ---
    r = client.post(base, json={**body, "video_job_name": "bad name!"})
    check("invalid name -> 400", r.status_code == 400)

    # --- 正常 → 201 ---
    r = client.post(base, json=body)
    check("start 201", r.status_code == 201)
    res = r.json()
    check("status queued/running", res["status"] in ("queued", "running"))
    check("stream_url shape", res["stream_url"].endswith("/video-jobs/video_001/stream"))

    job_json = ROOT / PROJ / "video" / "video_001" / "job.json"
    check("job.json exists", job_json.exists())

    # --- 同名 overwrite=false → 409 ---
    r = client.post(base, json=body)
    check("duplicate -> 409", r.status_code == 409)

    # --- 合成フレームが出力される ---
    check("frame written", wait_frame("video_001"))

    # --- 取得/一覧 ---
    r = client.get(f"{base}/video_001")
    check("get job 200", r.status_code == 200 and r.json()["video_job_id"] == "video_001")
    r = client.get(base)
    check("list has job", any(j["video_job_id"] == "video_001" for j in r.json()["jobs"]))

    # --- 停止 ---
    r = client.post(f"{base}/video_001/stop")
    check("stop 200", r.status_code == 200 and r.json()["status"] == "stopped")

    # --- 停止後の stream は最終フレームを返して終了 ---
    r = client.get(f"{base}/video_001/stream")
    check("stream 200", r.status_code == 200)
    check("stream content-type", r.headers["content-type"].startswith("multipart/x-mixed-replace"))
    check("stream has jpeg payload", b"image/jpeg" in r.content)

    # --- 存在しないジョブ → 404 ---
    r = client.get(f"{base}/no_job")
    check("missing job -> 404", r.status_code == 404)

    print("\nALL VIDEO INFERENCE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
