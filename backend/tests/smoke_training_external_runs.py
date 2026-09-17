"""job.json が無い外部/直接実行run(Ultralytics直接実行等)を学習ジョブ一覧へ
合成表示する機能のスモークテスト(Issue #14 Checkpoint 2)。

実学習は走らせない。TestClient経由でGET /train-jobs, GET /modelsの挙動のみ確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_training_external_runs.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_ext_train_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "ext_train_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_job_json_run(job_id: str, status: str = "completed", with_best: bool = True) -> None:
    """既存の(アプリの学習API経由で生成された想定の)job.jsonありrun。"""
    d = ROOT / PROJ / "runs" / "train" / job_id
    write(d / "job.json", json.dumps({
        "job_id": job_id, "dataset_name": "ds1", "model": "yolov8n.pt",
        "epochs": 10, "imgsz": 640, "batch": 8, "device": "cpu",
        "status": status, "created_at": "2026-06-29T10:00:00",
    }))
    (d / "weights").mkdir(parents=True, exist_ok=True)
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"x" * 100)


def make_external_run(job_id: str, with_best: bool = False, with_last: bool = False, with_results_csv: bool = False) -> None:
    """job.json無し(Ultralytics直接実行相当)のrun。weightsのみ配置する。"""
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"y" * 200)
    if with_last:
        (d / "weights" / "last.pt").write_bytes(b"z" * 150)
    if with_results_csv:
        write(d / "results.csv",
              "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)\n"
              "1,0.5,0.5,0.5,0.4\n")


def make_broken_job_json_run(job_id: str, with_best: bool = True) -> None:
    """job.jsonは存在するが壊れている(不正JSON)run。"""
    d = ROOT / PROJ / "runs" / "train" / job_id
    write(d / "job.json", "{ this is not valid json ]")
    (d / "weights").mkdir(parents=True, exist_ok=True)
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"w" * 100)


def make_empty_run(job_id: str) -> None:
    """weightsが1つも無い空run(job.jsonも無い)。"""
    d = ROOT / PROJ / "runs" / "train" / job_id
    d.mkdir(parents=True, exist_ok=True)


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})

    # 1. job.jsonありの通常学習runが従来どおり列挙される
    make_job_json_run("normal_job", status="completed", with_best=True)

    # 2. job.jsonなし + best.ptありrunが列挙される
    make_external_run("external_best_only", with_best=True, with_results_csv=True)

    # 3. job.jsonなし + last.ptのみrunが列挙される
    make_external_run("external_last_only", with_last=True)

    # 4. job.jsonなし + weights無しの空runは列挙しない
    make_empty_run("empty_run")

    # 5. 壊れたjob.jsonがあるrunは従来どおり除外される(合成対象にしない)
    make_broken_job_json_run("broken_job", with_best=True)

    r = client.get(f"/api/projects/{PROJ}/train-jobs")
    check("train-jobs 200", r.status_code == 200)
    jobs = {j["job_id"]: j for j in r.json()["jobs"]}

    check("normal_job が列挙される(従来どおり)", "normal_job" in jobs)
    check("normal_job の詳細フィールドが保持される(合成されていない)",
          jobs["normal_job"]["dataset_name"] == "ds1" and jobs["normal_job"]["epochs"] == 10)

    check("external_best_only が列挙される(合成)", "external_best_only" in jobs)
    check("external_best_only status=completed", jobs["external_best_only"]["status"] == "completed")
    check("external_best_only best_model_path設定", jobs["external_best_only"]["best_model_path"] is not None)
    check("external_best_only results_csv_path設定", jobs["external_best_only"]["results_csv_path"] is not None)
    check("external_best_only dataset_name等はNone(詳細情報なしを正直に表現)",
          jobs["external_best_only"]["dataset_name"] is None)

    check("external_last_only が列挙される(合成、last.ptのみでも可)", "external_last_only" in jobs)
    check("external_last_only best_model_pathはNone", jobs["external_last_only"]["best_model_path"] is None)
    check("external_last_only last_model_pathは設定", jobs["external_last_only"]["last_model_path"] is not None)

    check("empty_run は列挙されない(weights無し)", "empty_run" not in jobs)
    check("broken_job は列挙されない(壊れたjob.jsonの既存挙動を維持)", "broken_job" not in jobs)

    check("列挙総数=3(normal_job, external_best_only, external_last_only のみ)", len(jobs) == 3)

    # Models registry側にも反映されること(is_selected等の既存ロジックと合成entryが共存できる)
    r = client.get(f"/api/projects/{PROJ}/models")
    check("models 200", r.status_code == 200)
    model_ids = {m["model_id"] for m in r.json()["models"]}
    check("models一覧にexternal_best_only:bestが含まれる", "external_best_only:best" in model_ids)
    check("models一覧にexternal_last_only:lastが含まれる", "external_last_only:last" in model_ids)
    check("models一覧にempty_run由来のentryは無い",
          not any(mid.startswith("empty_run:") for mid in model_ids))
    check("models一覧にbroken_job由来のentryは無い",
          not any(mid.startswith("broken_job:") for mid in model_ids))

    # selected modelとして外部runを設定し、is_selectedが正しく反映されることを確認
    r = client.put(f"/api/projects/{PROJ}/models/selected", json={
        "train_job_id": "external_best_only", "weight_type": "best", "memo": "",
    })
    check("外部runをselected modelに設定できる 200", r.status_code == 200)

    r = client.get(f"/api/projects/{PROJ}/models")
    models = {m["model_id"]: m for m in r.json()["models"]}
    check("selected_model_idが外部runを指す", r.json()["selected_model_id"] == "external_best_only:best")
    check("is_selected=trueが一覧entryに反映される(誤表示なし)",
          models["external_best_only:best"]["is_selected"] is True)

    print("\nALL TRAINING EXTERNAL-RUN DISCOVERY SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
