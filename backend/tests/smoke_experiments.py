"""実験履歴APIのスモークテスト（Issue 009）。

train job / dataset metadata / results.csv / analysis.json を手で配置し、
集約・欠損耐性・詳細・404 を検証する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_experiments.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_exp_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "exp_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_train_job(job_id: str, dataset_name: str, status: str, with_csv: bool, with_best: bool) -> None:
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id, "dataset_name": dataset_name, "model": "yolov8n.pt",
        "epochs": 50, "imgsz": 640, "batch": 8, "device": "cpu",
        "status": status, "created_at": f"2026-06-29T10:00:0{job_id[-1]}",
        "finished_at": "2026-06-29T10:30:00",
        "best_model_path": f"runs/train/{job_id}/weights/best.pt" if with_best else None,
        "results_csv_path": f"runs/train/{job_id}/results.csv" if with_csv else None,
    }
    write(d / "job.json", json.dumps(job))
    if with_csv:
        write(d / "results.csv",
              "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)\n"
              "1,0.5,0.4,0.6,0.4\n2,0.9234,0.8876,0.9521,0.8123\n")
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"x")
        (d / "weights" / "last.pt").write_bytes(b"x")


def make_dataset(dataset_name: str, train_n: int, val_n: int, classes: int, broken: bool = False) -> None:
    d = ROOT / PROJ / "datasets" / dataset_name
    d.mkdir(parents=True, exist_ok=True)
    if broken:
        write(d / "metadata.json", "{ this is not valid json ]")
        return
    meta = {
        "dataset_name": dataset_name, "seed": 42,
        "train_ratio": 0.8, "val_ratio": 0.2, "test_ratio": 0.0,
        "include_empty_labels": True, "include_unlabeled_images": False,
        "summary": {
            "train_image_count": train_n, "val_image_count": val_n,
            "test_image_count": 0, "total_image_count": train_n + val_n,
            "class_count": classes,
        },
    }
    write(d / "metadata.json", json.dumps(meta))


def make_predict_with_analysis(predict_id: str, train_job_id: str) -> None:
    d = ROOT / PROJ / "predictions" / predict_id
    d.mkdir(parents=True, exist_ok=True)
    write(d / "job.json", json.dumps({
        "predict_job_id": predict_id, "train_job_id": train_job_id,
        "status": "completed", "created_at": "2026-06-29T11:00:00",
        "image_count": 10, "detection_count": 35,
    }))
    analysis = {
        "project_name": PROJ, "predict_job_id": predict_id,
        "iou_threshold": 0.5, "conf_threshold": 0.25,
        "summary": {
            "image_count": 10, "ground_truth_count": 32, "prediction_count": 35,
            "tp_count": 25, "fp_count": 7, "fn_count": 7, "class_mismatch_count": 3,
            "precision": 0.78125, "recall": 0.78125, "f1": 0.78125,
        },
        "class_stats": [], "image_results": [],
    }
    write(d / "analysis.json", json.dumps(analysis))


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b", "c"]})
    base = f"/api/projects/{PROJ}/experiments"

    # --- train job が無い → 空配列で200 ---
    r = client.get(base)
    check("empty -> 200 []", r.status_code == 200 and r.json()["experiments"] == [])

    # --- 実験を構成 ---
    make_dataset("dataset_001", 80, 20, 3)
    make_train_job("train_001", "dataset_001", "completed", with_csv=True, with_best=True)
    make_predict_with_analysis("predict_001", "train_001")

    # failed ジョブ（csv/best 無し、dataset metadata 壊れ）
    make_dataset("dataset_broken", 0, 0, 0, broken=True)
    make_train_job("train_002", "dataset_broken", "failed", with_csv=False, with_best=False)

    # --- 一覧 ---
    r = client.get(base)
    check("list 200", r.status_code == 200)
    exps = {e["experiment_id"]: e for e in r.json()["experiments"]}
    check("two experiments", set(exps.keys()) == {"train_001", "train_002"})

    e1 = exps["train_001"]
    check("completed status", e1["status"] == "completed")
    check("dataset image counts", e1["train_image_count"] == 80 and e1["val_image_count"] == 20)
    check("class_count 3", e1["class_count"] == 3)
    check("eval from csv (last row)", abs(e1["map50"] - 0.9521) < 1e-6 and abs(e1["precision"] - 0.9234) < 1e-6)
    check("best_model_path", e1["best_model_path"] == "runs/train/train_001/weights/best.pt")
    check("latest_analysis present", e1["latest_analysis"] is not None)
    check("latest_analysis values", e1["latest_analysis"]["fp_count"] == 7 and abs(e1["latest_analysis"]["f1"] - 0.78125) < 1e-6)
    check("latest_analysis predict id", e1["latest_analysis"]["predict_job_id"] == "predict_001")

    e2 = exps["train_002"]
    check("failed listed", e2["status"] == "failed")
    check("no csv -> precision null", e2["precision"] is None)
    check("broken dataset -> counts null but no crash", e2["train_image_count"] is None)
    check("no analysis -> null", e2["latest_analysis"] is None)

    # --- 詳細 ---
    r = client.get(f"{base}/train_001")
    check("detail 200", r.status_code == 200)
    det = r.json()
    check("detail train_job", det["train_job"]["job_id"] == "train_001")
    check("detail dataset", det["dataset"]["train_image_count"] == 80)
    check("detail eval has_best", det["evaluation"]["has_best_model"] is True)
    check("detail predictions 1", len(det["predictions"]) == 1)
    check("detail prediction analysis", det["predictions"][0]["analysis"]["tp_count"] == 25)

    # 詳細: csv/analysis 無しでも落ちない
    r = client.get(f"{base}/train_002")
    check("detail train_002 200", r.status_code == 200)
    check("detail eval null-ish", r.json()["evaluation"]["has_results_csv"] is False)

    # --- 存在しない experiment_id → 404 ---
    r = client.get(f"{base}/no_such")
    check("missing -> 404", r.status_code == 404)

    print("\nALL EXPERIMENTS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
