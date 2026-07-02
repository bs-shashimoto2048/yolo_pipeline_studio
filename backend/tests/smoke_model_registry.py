"""モデル管理APIのスモークテスト（Issue 012）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_model_registry.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_models_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "model_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_train_job(job_id: str, dataset: str, with_best: bool, with_last: bool, with_csv: bool) -> None:
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    write(d / "job.json", json.dumps({
        "job_id": job_id, "dataset_name": dataset, "model": "yolov8n.pt",
        "epochs": 50, "imgsz": 640, "batch": 8, "device": "cpu",
        "status": "completed", "created_at": "2026-06-29T10:00:00",
        "finished_at": "2026-06-29T10:30:00",
    }))
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"x" * 1234)
    if with_last:
        (d / "weights" / "last.pt").write_bytes(b"y" * 999)
    if with_csv:
        write(d / "results.csv",
              "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)\n"
              "2,0.9234,0.8876,0.9521,0.8123\n")


def make_predict_with_analysis(predict_id: str, train_job_id: str) -> None:
    d = ROOT / PROJ / "predictions" / predict_id
    d.mkdir(parents=True, exist_ok=True)
    write(d / "job.json", json.dumps({
        "predict_job_id": predict_id, "train_job_id": train_job_id,
        "status": "completed", "created_at": "2026-06-29T11:00:00",
        "image_count": 10, "detection_count": 35,
    }))
    write(d / "analysis.json", json.dumps({
        "project_name": PROJ, "predict_job_id": predict_id,
        "iou_threshold": 0.5, "conf_threshold": 0.25,
        "summary": {"image_count": 10, "ground_truth_count": 32, "prediction_count": 35,
                    "tp_count": 25, "fp_count": 7, "fn_count": 7, "class_mismatch_count": 3,
                    "precision": 0.78125, "recall": 0.78125, "f1": 0.78125},
        "class_stats": [], "image_results": [],
    }))


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    base = f"/api/projects/{PROJ}/models"

    # train job無し → 空配列で200
    r = client.get(base)
    check("empty -> 200 []", r.status_code == 200 and r.json()["models"] == [])

    # project無し → 404
    r = client.get("/api/projects/no_proj/models")
    check("no project -> 404", r.status_code == 404)

    # モデル構成
    make_train_job("train_001", "dataset_001", with_best=True, with_last=True, with_csv=True)
    make_predict_with_analysis("predict_001", "train_001")
    make_train_job("train_002", "dataset_001", with_best=True, with_last=False, with_csv=False)

    # 一覧
    r = client.get(base)
    check("list 200", r.status_code == 200)
    models = {m["model_id"]: m for m in r.json()["models"]}
    check("4 entries (2 jobs x best/last)", len(models) == 4)
    check("train_001:best exists", models["train_001:best"]["exists"] is True)
    check("train_001:best size", models["train_001:best"]["file_size_bytes"] == 1234)
    check("train_002:last not exists", models["train_002:last"]["exists"] is False)
    check("eval reflected", abs(models["train_001:best"]["map50"] - 0.9521) < 1e-6)
    check("analysis reflected", models["train_001:best"]["latest_analysis"]["fp_count"] == 7)
    check("train_002 no analysis", models["train_002:best"]["latest_analysis"] is None)

    # 詳細
    r = client.get(f"{base}/train_001/best")
    check("detail 200", r.status_code == 200)
    check("detail eval", abs(r.json()["evaluation"]["map50"] - 0.9521) < 1e-6)
    check("detail predictions", len(r.json()["predictions"]) == 1)

    # weight_type 不正 → 400
    r = client.get(f"{base}/train_001/middle")
    check("bad weight_type -> 400", r.status_code == 400)
    # 存在しない train_job → 404
    r = client.get(f"{base}/no_job/best")
    check("missing job detail -> 404", r.status_code == 404)

    # 採用モデル設定
    r = client.put(f"{base}/selected", json={"train_job_id": "train_001", "weight_type": "best", "memo": "mAP高い"})
    check("set selected 200", r.status_code == 200)
    check("selected id", r.json()["selected_model_id"] == "train_001:best")
    check("selected_model.json saved", (ROOT / PROJ / "models" / "selected_model.json").exists())

    # 採用モデル取得
    r = client.get(f"{base}/selected")
    check("get selected 200", r.status_code == 200 and r.json()["memo"] == "mAP高い")

    # 一覧に is_selected 反映
    r = client.get(base)
    ms = {m["model_id"]: m for m in r.json()["models"]}
    check("selected_model_id in list", r.json()["selected_model_id"] == "train_001:best")
    check("is_selected true", ms["train_001:best"]["is_selected"] is True)
    check("others not selected", ms["train_001:last"]["is_selected"] is False)

    # 存在しないモデルファイルの採用 → 400（train_002:last は無い）
    r = client.put(f"{base}/selected", json={"train_job_id": "train_002", "weight_type": "last"})
    check("select missing file -> 400", r.status_code == 400)
    # 存在しない train_job の採用 → 404
    r = client.put(f"{base}/selected", json={"train_job_id": "no_job", "weight_type": "best"})
    check("select missing job -> 404", r.status_code == 404)
    # weight_type 不正 → 400
    r = client.put(f"{base}/selected", json={"train_job_id": "train_001", "weight_type": "x"})
    check("select bad weight -> 400", r.status_code == 400)

    # selected_model.json が壊れていても一覧APIは落ちない
    (ROOT / PROJ / "models" / "selected_model.json").write_text("{ broken json ]", encoding="utf-8")
    r = client.get(base)
    check("broken selected -> list still 200", r.status_code == 200)
    check("broken selected -> selected_model_id null", r.json()["selected_model_id"] is None)

    # モデルファイル欠損でも一覧は落ちない（train_002:last は欠損のまま）
    r = client.get(base)
    check("list robust with missing files", r.status_code == 200 and len(r.json()["models"]) == 4)

    print("\nALL MODEL REGISTRY SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
