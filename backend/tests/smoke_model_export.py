"""モデル配布パッケージ出力のスモークテスト（Issue 025）。

実重みは使わず、ダミーの .pt とメタファイルで検証する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_model_export.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_export_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_train_job(proj: str, job_id: str, task: str, dataset_name: str,
                   with_best: bool = True, with_last: bool = True) -> None:
    d = ROOT / proj / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id, "job_name": job_id, "dataset_name": dataset_name,
        "task": task, "model": "yolov8n-seg.pt" if task == "segment" else "yolov8n.pt",
        "epochs": 50, "imgsz": 640, "batch": 8, "device": "cuda", "seed": 42,
        "augmentation_preset": "light", "augmentation_params": {"degrees": 5.0},
        "status": "completed",
    }
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"fake-best-weight")
    if with_last:
        (d / "weights" / "last.pt").write_bytes(b"fake-last-weight")

    # results.csv（評価サマリー用）
    if task == "segment":
        header = "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(M),metrics/recall(M),metrics/mAP50(M),metrics/mAP50-95(M)"
        row = "1,0.91,0.83,0.87,0.76,0.89,0.81,0.85,0.73"
    else:
        header = "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)"
        row = "1,0.916,0.828,0.872,0.761"
    (d / "results.csv").write_text(header + "\n" + row + "\n", encoding="utf-8")


def make_dataset(proj: str, dataset_name: str, task: str) -> None:
    d = ROOT / proj / "datasets" / dataset_name
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "dataset_name": dataset_name, "task": task, "image_source": "processed",
        "summary": {"train_image_count": 80, "val_image_count": 20,
                    "test_image_count": 0, "total_image_count": 100, "class_count": 2},
    }
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def run_for_task(proj: str, task: str) -> None:
    client.post("/api/projects", json={"name": proj, "task": task})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["bolt", "connector"]})
    make_dataset(proj, "dataset_001", task)
    make_train_job(proj, "train_001", task, "dataset_001")

    base = f"/api/projects/{proj}"

    # --- 重みダウンロード ---
    r = client.get(f"{base}/model-export/train_001/best/download")
    check(f"[{task}] download best 200", r.status_code == 200 and r.content == b"fake-best-weight")
    r = client.get(f"{base}/model-export/train_001/last/download")
    check(f"[{task}] download last 200", r.status_code == 200)

    # --- 存在しないモデル / 不正weight ---
    r = client.get(f"{base}/model-export/no_such/best/download")
    check(f"[{task}] missing model 404", r.status_code == 404)
    r = client.get(f"{base}/model-export/train_001/bogus/download")
    check(f"[{task}] bad weight 400", r.status_code == 400)

    # --- 配布パッケージ作成 ---
    r = client.post(f"{base}/model-export/train_001/best/package")
    check(f"[{task}] create package 200", r.status_code == 200)
    res = r.json()
    check(f"[{task}] model_id", res["model_id"] == "train_001:best")
    check(f"[{task}] status completed", res["status"] == "completed")
    pkg_id = res["package_id"]

    expected = {
        "weights/best.pt", "weights/last.pt", "classes.json", "preprocess.json",
        "inference_config.json", "training_config.json", "evaluation_summary.json",
        "dataset_summary.json", "README_model.md", "sample_infer.py",
    }
    check(f"[{task}] response files complete", expected.issubset(set(res["files"])))

    # --- パッケージダウンロード + ZIP検証 ---
    r = client.get(f"{base}/model-packages/{pkg_id}/download")
    check(f"[{task}] download package 200", r.status_code == 200)
    check(f"[{task}] zip content-type", r.headers["content-type"] == "application/zip")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    check(f"[{task}] zip has all files", expected.issubset(names))

    classes_j = json.loads(zf.read("classes.json"))
    check(f"[{task}] classes.json task", classes_j["task"] == task)
    check(f"[{task}] classes.json 2 classes", len(classes_j["classes"]) == 2)
    check(f"[{task}] classes.json fields", classes_j["classes"][0]["name"] == "bolt"
          and "color" in classes_j["classes"][0])

    train_j = json.loads(zf.read("training_config.json"))
    check(f"[{task}] training_config task/model", train_j["task"] == task and train_j["model"])
    check(f"[{task}] training_config dataset", train_j["dataset_name"] == "dataset_001")

    eval_j = json.loads(zf.read("evaluation_summary.json"))
    check(f"[{task}] eval precision_b", eval_j.get("precision_b") is not None)
    if task == "segment":
        check(f"[{task}] eval precision_m", eval_j.get("precision_m") is not None)

    ds_j = json.loads(zf.read("dataset_summary.json"))
    check(f"[{task}] dataset_summary counts", ds_j["train_image_count"] == 80 and ds_j["task"] == task)

    pre_j = json.loads(zf.read("preprocess.json"))
    check(f"[{task}] preprocess.json has applied", "applied" in pre_j)

    infer_j = json.loads(zf.read("inference_config.json"))
    check(f"[{task}] inference_config recommended", infer_j["recommended"]["imgsz"] == 640)

    readme = zf.read("README_model.md").decode("utf-8")
    check(f"[{task}] README mentions task", task in readme)
    sample = zf.read("sample_infer.py").decode("utf-8")
    check(f"[{task}] sample_infer uses YOLO", "from ultralytics import YOLO" in sample)

    # --- 存在しないパッケージ 404 ---
    r = client.get(f"{base}/model-packages/no_such_pkg/download")
    check(f"[{task}] missing package 404", r.status_code == 404)


def main() -> None:
    run_for_task("export_detect", "detect")
    run_for_task("export_segment", "segment")
    print("\nALL MODEL EXPORT SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
