"""映像推論のselected-model前処理解決のスモークテスト（Issue #19 Checkpoint 2）。

実カメラ/Ultralyticsは使わない。ジョブ起動・解決ロジックは YTS_VIDEO_DRY_RUN=1 で
検証し、実際のROI/前処理適用（crop→resize→grayscale→sharpen）とエラー処理は
predict_video_worker.apply_frame_preprocess を直接importして純粋関数として検証する
（カメラ/モデルなしで実ピクセル処理を確認できるよう、Issue #19でmain()から切り出した）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_video_selected_preprocess.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_video_selected_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_VIDEO_DRY_RUN"] = "1"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas.preprocess import PreprocessSettings  # noqa: E402
from app.services import preprocess_service  # noqa: E402
import predict_video_worker as worker  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_fake_train_job(proj: str, job_id: str) -> None:
    d = ROOT / proj / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({"job_id": job_id, "status": "completed"}), encoding="utf-8")
    (d / "weights" / "best.pt").write_bytes(b"fake-weight")


def read_job(proj: str, vid: str) -> dict:
    p = ROOT / proj / "video" / vid / "job.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def wait_frame(proj: str, vid: str) -> bool:
    latest = ROOT / proj / "video" / vid / "live" / "latest.jpg"
    for _ in range(50):
        time.sleep(0.2)
        if latest.exists() and latest.stat().st_size > 0:
            return True
    return False


def new_project(name: str) -> None:
    r = client.post("/api/projects", json={"name": name})
    check(f"create project {name}", r.status_code in (200, 201))


def set_selected(proj: str, train_job_id: str, conf: float | None, profile: dict | None, memo: str = "") -> None:
    body: dict = {"train_job_id": train_job_id, "weight_type": "best", "memo": memo}
    if conf is not None:
        body["conf"] = conf
    if profile is not None:
        body["preprocess_profile"] = profile
    r = client.put(f"/api/projects/{proj}/models/selected", json=body)
    check(f"set selected model for {proj} -> 200", r.status_code == 200)


SRC004_PROFILE = {
    "roi_enabled": True,
    "roi_x0": 835,
    "roi_y0": 374,
    "roi_x1": 1354,
    "roi_y1": 480,
    "resize_enabled": True,
    "resize_mode": "width",
    "resize_size": 640,
    "grayscale_enabled": True,
    "sharpen_enabled": True,
    "sharpen_strength": 1.0,
}

DIGITAL_PROFILE = {
    "roi_enabled": False,
    "resize_enabled": True,
    "resize_mode": "width",
    "resize_size": 640,
    "grayscale_enabled": True,
    "sharpen_enabled": True,
    "sharpen_strength": 1.0,
}


# ---------------------------------------------------------------------------
# Part A: HTTP経由の resolution / schema 検証（DRY_RUN、resolveロジックのみ確認）
# ---------------------------------------------------------------------------

def test_selected_resolution_src004() -> None:
    proj = "drum_proj"
    new_project(proj)
    make_fake_train_job(proj, "candidate_roi_v3_5")
    set_selected(proj, "candidate_roi_v3_5", 0.25, SRC004_PROFILE)

    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_selected_004",
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "selected", "overwrite": False,
    })
    check("src004 selected job start -> 201", r.status_code == 201)
    check("frame written (dry-run)", wait_frame(proj, "v_selected_004"))
    job = read_job(proj, "v_selected_004")
    check("resolved train_job_id == candidate_roi_v3_5", job.get("train_job_id") == "candidate_roi_v3_5")
    check("resolved conf fallback == 0.25", job.get("conf") == 0.25)
    check("resolution_source all selected_model",
          job.get("resolution_source") == {"train_job_id": "selected_model", "weight_type": "selected_model", "conf": "selected_model"})
    check("resolved_preprocess_profile has ROI", job.get("resolved_preprocess_profile", {}).get("roi_enabled") is True)
    check("processing_order == roi_crop->resize->grayscale->sharpen",
          job.get("processing_order") == ["roi_crop", "resize", "grayscale", "sharpen"])
    client.post(f"/api/projects/{proj}/video-jobs/v_selected_004/stop")


def test_selected_resolution_digital() -> None:
    proj = "digital_proj"
    new_project(proj)
    make_fake_train_job(proj, "production_combined_v2_5z")
    set_selected(proj, "production_combined_v2_5z", 0.6, DIGITAL_PROFILE)

    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_selected_digital",
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "selected", "overwrite": False,
    })
    check("digital selected job start -> 201", r.status_code == 201)
    check("frame written (dry-run)", wait_frame(proj, "v_selected_digital"))
    job = read_job(proj, "v_selected_digital")
    check("resolved conf fallback == 0.6", job.get("conf") == 0.6)
    check("resolved_preprocess_profile ROI off", job.get("resolved_preprocess_profile", {}).get("roi_enabled") is False)
    check("processing_order has no roi_crop", "roi_crop" not in (job.get("processing_order") or []))
    client.post(f"/api/projects/{proj}/video-jobs/v_selected_digital/stop")


def test_explicit_override_beats_selected() -> None:
    proj = "drum_proj"  # 既存プロジェクト（selected=candidate_roi_v3_5/conf0.25）を再利用
    make_fake_train_job(proj, "other_job")
    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_override",
        "train_job_id": "other_job", "weight_type": "best", "conf": 0.9,
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "none", "overwrite": False,
    })
    check("explicit override job start -> 201", r.status_code == 201)
    check("frame written (dry-run)", wait_frame(proj, "v_override"))
    job = read_job(proj, "v_override")
    check("explicit train_job_id wins", job.get("train_job_id") == "other_job")
    check("explicit conf wins", job.get("conf") == 0.9)
    check("resolution_source all request", job.get("resolution_source") == {"train_job_id": "request", "weight_type": "request", "conf": "request"})
    client.post(f"/api/projects/{proj}/video-jobs/v_override/stop")


def test_no_selected_no_request_fails() -> None:
    proj = "no_selected_proj"
    new_project(proj)
    make_fake_train_job(proj, "train_x")
    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_no_selected",
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "none", "overwrite": False,
    })
    check("no train_job_id, no selected -> 400", r.status_code == 400)


def test_selected_mode_without_profile_fails() -> None:
    proj = "no_selected_proj"
    set_selected(proj, "train_x", None, None)  # selectedはあるがpreprocess_profileなし
    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_selected_no_profile",
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "selected", "overwrite": False,
    })
    check("selected mode without preprocess_profile -> 400", r.status_code == 400)


def test_legacy_none_and_latest_regression() -> None:
    proj = "legacy_proj"
    new_project(proj)
    make_fake_train_job(proj, "train_legacy")

    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_legacy_none",
        "train_job_id": "train_legacy", "weight_type": "best", "conf": 0.3,
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "none", "overwrite": False,
    })
    check("legacy none -> 201", r.status_code == 201)
    check("legacy none frame written", wait_frame(proj, "v_legacy_none"))
    job = read_job(proj, "v_legacy_none")
    check("legacy none: no preprocess profile", job.get("resolved_preprocess_profile") is None)
    client.post(f"/api/projects/{proj}/video-jobs/v_legacy_none/stop")

    # latest: 前処理未実行 -> 400（既存挙動）
    r = client.post(f"/api/projects/{proj}/video-jobs", json={
        "video_job_name": "v_legacy_latest_fail",
        "train_job_id": "train_legacy", "weight_type": "best", "conf": 0.3,
        "source_type": "camera", "camera_index": 0,
        "video_fps": 15, "infer_fps": 5, "iou": 0.7, "imgsz": 640, "device": "auto",
        "preprocess_mode": "latest", "overwrite": False,
    })
    check("legacy latest without preprocess run -> 400", r.status_code == 400)


# ---------------------------------------------------------------------------
# Part B: 実ピクセル処理・エラー処理の単体検証（apply_frame_preprocessを直接呼ぶ）
# ---------------------------------------------------------------------------

def _synthetic_frame(w: int, h: int):
    """cv2.VideoCapture.read()相当のBGR ndarrayを合成する。"""
    import cv2
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, 1] = 128  # 緑寄りの適当な絵
    return arr


def test_apply_frame_preprocess_roi_order_and_size() -> None:
    import cv2
    frame = _synthetic_frame(1920, 1080)
    ps = PreprocessSettings(**SRC004_PROFILE)
    out = worker.apply_frame_preprocess(cv2, np, frame, ps, preprocess_service)
    h, w = out.shape[:2]
    check("src004 selected preprocess output width=640", w == 640)
    check("src004 selected preprocess output height=131", h == 131)
    check("processing_order (real) == roi_crop->resize->grayscale->sharpen",
          preprocess_service.processing_order(ps) == ["roi_crop", "resize", "grayscale", "sharpen"])


def test_apply_frame_preprocess_digital_roi_off() -> None:
    import cv2
    frame = _synthetic_frame(1920, 1080)
    ps = PreprocessSettings(**DIGITAL_PROFILE)
    out = worker.apply_frame_preprocess(cv2, np, frame, ps, preprocess_service)
    h, w = out.shape[:2]
    check("digital selected preprocess output width=640", w == 640)
    check("digital selected preprocess ROI off -> full-frame aspect (height=360)", h == 360)
    check("processing_order (real) has no roi_crop", "roi_crop" not in preprocess_service.processing_order(ps))


def test_apply_frame_preprocess_invalid_roi_raises() -> None:
    import cv2
    frame = _synthetic_frame(640, 480)  # ROIが画像サイズを超える小さいframe
    ps = PreprocessSettings(**SRC004_PROFILE)  # roi_x1=1354 > frame width=640
    try:
        worker.apply_frame_preprocess(cv2, np, frame, ps, preprocess_service)
        check("invalid ROI raises PreprocessValidationError (not silent skip)", False)
    except preprocess_service.PreprocessValidationError:
        check("invalid ROI raises PreprocessValidationError (not silent skip)", True)


def test_apply_frame_preprocess_none_passthrough() -> None:
    import cv2
    frame = _synthetic_frame(100, 50)
    out = worker.apply_frame_preprocess(cv2, np, frame, None, preprocess_service)
    check("pre_settings=None -> frame passthrough unchanged", out is frame)


def test_display_frame_not_fed_back_as_inference_input() -> None:
    """live/latest.jpg（annotated display frame）が次の推論入力に再利用されないこと。

    構造的な回帰ガード: ワーカーのメインループが毎回 cap.read() から新規フレームを
    取得しており、latest.jpg (live_dir配下) を読み戻すコードパスが存在しないことを
    ソースレベルで確認する（Issue #19）。
    """
    full_src = (Path(__file__).resolve().parents[1] / "workers" / "predict_video_worker.py").read_text(encoding="utf-8")
    # dry-runブロック（合成フレームのみ）は対象外にし、実推論ループ部分だけを検査する
    src = full_src.split("# --- 実処理 ---", 1)[-1]
    check("worker never re-reads live/latest.jpg as model input",
          "live_dir" not in src.split("model.predict(frame")[0].split("cap.read()")[-1] if "cap.read()" in src else True)
    check("worker calls cap.read() to source each frame", "cap.read()" in src)
    check("worker writes annotated frame only after plot()", src.index("results[0].plot(") < src.index("_atomic_write_jpg_bytes(latest"))


def main() -> None:
    test_selected_resolution_src004()
    test_selected_resolution_digital()
    test_explicit_override_beats_selected()
    test_no_selected_no_request_fails()
    test_selected_mode_without_profile_fails()
    test_legacy_none_and_latest_regression()
    test_apply_frame_preprocess_roi_order_and_size()
    test_apply_frame_preprocess_digital_roi_off()
    test_apply_frame_preprocess_invalid_roi_raises()
    test_apply_frame_preprocess_none_passthrough()
    test_display_frame_not_fed_back_as_inference_input()
    print("\nALL VIDEO SELECTED-PREPROCESS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
