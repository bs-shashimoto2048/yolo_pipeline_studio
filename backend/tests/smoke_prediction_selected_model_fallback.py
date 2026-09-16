"""採用モデル（selected model）拡張とpredict jobのフォールバック解決のスモークテスト
（Issue #1 Checkpoint 5AE）。

実推論は走らせない（YTS_PREDICT_DRY_RUN=1）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_prediction_selected_model_fallback.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_predfallback_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_PREDICT_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "predfallback_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str, proj: str = PROJ) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (1, 2, 3)).save(buf, format="PNG")
    buf.seek(0)
    client.post(f"/api/projects/{proj}/images",
                files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))])


def make_fake_train_job(job_id: str, proj: str = PROJ, with_best: bool = True, with_last: bool = True) -> None:
    d = ROOT / proj / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({"job_id": job_id, "status": "completed"}), encoding="utf-8")
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"fake-best")
    if with_last:
        (d / "weights" / "last.pt").write_bytes(b"fake-last")


def wait_completed(proj: str, predict_job_id: str) -> str:
    job_json = ROOT / proj / "predictions" / predict_job_id / "job.json"
    final = "?"
    for _ in range(30):
        time.sleep(0.2)
        final = json.loads(job_json.read_text(encoding="utf-8"))["status"]
        if final in {"completed", "failed"}:
            break
    return final


def read_job(proj: str, predict_job_id: str) -> dict:
    return json.loads((ROOT / proj / "predictions" / predict_job_id / "job.json").read_text(encoding="utf-8"))


def test_legacy_selected_model_json_still_readable() -> None:
    """conf/preprocess_profileキーを持たない旧形式selected_model.jsonが読み込めること。"""
    proj = "legacy_selected"
    client.post("/api/projects", json={"name": proj})
    make_fake_train_job("train_001", proj=proj)

    models_dir = ROOT / proj / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "model_id": "train_001:best", "train_job_id": "train_001", "weight_type": "best",
        "model_path": "runs/train/train_001/weights/best.pt",
        "selected_at": "2026-06-29T10:00:00", "memo": "旧形式",
    }
    (models_dir / "selected_model.json").write_text(json.dumps(legacy_payload), encoding="utf-8")

    r = client.get(f"/api/projects/{proj}/models/selected")
    check("legacy selected -> 200", r.status_code == 200)
    body = r.json()
    check("legacy conf is None", body["conf"] is None)
    check("legacy preprocess_profile is None", body["preprocess_profile"] is None)
    check("legacy memo維持", body["memo"] == "旧形式")


def test_new_selected_model_conf_preprocess_roundtrip() -> None:
    """conf/preprocess_profileを含む新形式の読み書き。"""
    proj = "new_selected"
    client.post("/api/projects", json={"name": proj})
    make_fake_train_job("train_roi", proj=proj)

    profile = {
        "roi_enabled": True, "roi_x0": 835, "roi_y0": 374, "roi_x1": 1354, "roi_y1": 480,
        "resize_enabled": True, "resize_mode": "width", "resize_size": 640,
        "grayscale_enabled": True, "sharpen_enabled": True, "sharpen_strength": 1.0,
    }
    r = client.put(f"/api/projects/{proj}/models/selected", json={
        "train_job_id": "train_roi", "weight_type": "best", "memo": "src004 ROI candidate",
        "conf": 0.25, "preprocess_profile": profile,
    })
    check("set selected with conf/profile -> 200", r.status_code == 200)
    check("response conf", r.json()["conf"] == 0.25)
    check("response preprocess_profile", r.json()["preprocess_profile"]["roi_enabled"] is True)

    r = client.get(f"/api/projects/{proj}/models/selected")
    check("get selected -> 200", r.status_code == 200)
    check("get conf", r.json()["conf"] == 0.25)
    check("get preprocess_profile roi coords", r.json()["preprocess_profile"]["roi_x1"] == 1354)

    on_disk = json.loads((ROOT / proj / "models" / "selected_model.json").read_text(encoding="utf-8"))
    check("on-disk conf", on_disk["conf"] == 0.25)
    check("on-disk preprocess_profile", on_disk["preprocess_profile"]["roi_enabled"] is True)


def test_priority_request_over_selected_over_default() -> None:
    """train_job_id/weight_type/conf: request明示値 > selected model > 安全なdefault。"""
    proj = "priority_proj"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("img1", proj=proj)
    make_fake_train_job("train_A", proj=proj, with_best=True, with_last=True)
    make_fake_train_job("train_B", proj=proj, with_best=True, with_last=False)

    # selected modelなし・request全指定 -> requestがそのまま使われる
    r = client.post(f"/api/projects/{proj}/predict-jobs", json={
        "predict_job_name": "p_explicit", "train_job_id": "train_A", "weight_type": "last",
        "source_type": "project_images", "image_ids": ["img1"], "conf": 0.5,
    })
    check("explicit request -> 201", r.status_code == 201)
    wait_completed(proj, "p_explicit")
    job = read_job(proj, "p_explicit")
    check("explicit train_job_id", job["train_job_id"] == "train_A")
    check("explicit weight_type", job["weight_type"] == "last")
    check("explicit conf", job["conf"] == 0.5)
    check("resolution_source all request", job["resolution_source"] == {
        "train_job_id": "request", "weight_type": "request", "conf": "request",
    })

    # selected modelを設定 -> train_job_id/weight_type/conf省略時にそちらへフォールバック
    client.put(f"/api/projects/{proj}/models/selected", json={
        "train_job_id": "train_B", "weight_type": "best", "conf": 0.6,
    })
    r = client.post(f"/api/projects/{proj}/predict-jobs", json={
        "predict_job_name": "p_selected", "source_type": "project_images", "image_ids": ["img1"],
    })
    check("omit all -> falls back to selected -> 201", r.status_code == 201)
    wait_completed(proj, "p_selected")
    job = read_job(proj, "p_selected")
    check("selected train_job_id", job["train_job_id"] == "train_B")
    check("selected weight_type", job["weight_type"] == "best")
    check("selected conf", job["conf"] == 0.6)
    check("resolution_source all selected_model", job["resolution_source"] == {
        "train_job_id": "selected_model", "weight_type": "selected_model", "conf": "selected_model",
    })

    # requestでconfだけ明示 -> confはrequest優先、train_job_id/weight_typeはselectedのまま
    r = client.post(f"/api/projects/{proj}/predict-jobs", json={
        "predict_job_name": "p_mixed", "source_type": "project_images", "image_ids": ["img1"], "conf": 0.9,
    })
    check("mixed override -> 201", r.status_code == 201)
    wait_completed(proj, "p_mixed")
    job = read_job(proj, "p_mixed")
    check("mixed train_job_id from selected", job["train_job_id"] == "train_B")
    check("mixed conf from request", job["conf"] == 0.9)
    check("resolution_source mixed", job["resolution_source"]["conf"] == "request"
          and job["resolution_source"]["train_job_id"] == "selected_model")


def test_default_fallback_when_nothing_set() -> None:
    """selected modelも無い状態でconf省略 -> 安全なdefault(0.25)。train_job_id省略は明示エラー。"""
    proj = "default_fallback_proj"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("img1", proj=proj)
    make_fake_train_job("train_only", proj=proj, with_best=True, with_last=False)

    # train_job_id省略・selectedも無し -> 明示エラー(400)、旧挙動(必須)と互換
    r = client.post(f"/api/projects/{proj}/predict-jobs", json={
        "predict_job_name": "p_no_model", "source_type": "project_images", "image_ids": ["img1"],
    })
    check("no train_job_id and no selected -> 400", r.status_code == 400)

    # train_job_idのみ指定、weight_type/conf省略 -> weight_type='best', conf=0.25(安全なdefault)
    r = client.post(f"/api/projects/{proj}/predict-jobs", json={
        "predict_job_name": "p_default", "train_job_id": "train_only",
        "source_type": "project_images", "image_ids": ["img1"],
    })
    check("train_job_id only -> 201", r.status_code == 201)
    wait_completed(proj, "p_default")
    job = read_job(proj, "p_default")
    check("default weight_type=best", job["weight_type"] == "best")
    check("default conf=0.25", job["conf"] == 0.25)
    check("resolution_source default", job["resolution_source"]["weight_type"] == "default"
          and job["resolution_source"]["conf"] == "default")


def test_selected_model_resolves_correct_weight_path() -> None:
    """selected modelフォールバックで、実際に存在するweightファイルのパスへ解決されること。"""
    proj = "weight_path_proj"
    client.post("/api/projects", json={"name": proj})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a"]})
    make_image("img1", proj=proj)
    make_fake_train_job("train_X", proj=proj, with_best=True, with_last=True)
    client.put(f"/api/projects/{proj}/models/selected", json={"train_job_id": "train_X", "weight_type": "last"})

    r = client.post(f"/api/projects/{proj}/predict-jobs", json={
        "predict_job_name": "p_weightpath", "source_type": "project_images", "image_ids": ["img1"],
    })
    check("selected weight resolve -> 201", r.status_code == 201)
    wait_completed(proj, "p_weightpath")
    expected = ROOT / proj / "runs" / "train" / "train_X" / "weights" / "last.pt"
    check("weightファイル実在", expected.exists())
    job = read_job(proj, "p_weightpath")
    check("job記録もlastを指す", job["weight_type"] == "last" and job["train_job_id"] == "train_X")


def main() -> None:
    test_legacy_selected_model_json_still_readable()
    test_new_selected_model_conf_preprocess_roundtrip()
    test_priority_request_over_selected_over_default()
    test_default_fallback_when_nothing_set()
    test_selected_model_resolves_correct_weight_path()
    print("\nALL PREDICTION SELECTED-MODEL FALLBACK SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
