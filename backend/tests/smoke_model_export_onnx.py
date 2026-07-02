"""ONNX同梱モデル配布パッケージのスモークテスト（Issue 028）。

ONNX export は YTS_ONNX_DRY_RUN=1 でダミー生成し、それを配布パッケージへ同梱する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_model_export_onnx.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_pkg_onnx_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_ONNX_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_train_job(proj: str, job_id: str, task: str) -> None:
    d = ROOT / proj / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"job_id": job_id, "imgsz": 640, "task": task, "dataset_name": "dataset_001",
                    "model": "yolov8n-seg.pt" if task == "segment" else "yolov8n.pt"}),
        encoding="utf-8",
    )
    (d / "weights" / "best.pt").write_bytes(b"best")
    (d / "weights" / "last.pt").write_bytes(b"last")


def wait_onnx(proj: str, jid: str) -> str:
    p = ROOT / proj / "exports" / "onnx" / jid / "job.json"
    for _ in range(40):
        time.sleep(0.2)
        try:
            st = json.loads(p.read_text(encoding="utf-8"))["status"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            continue
        if st in ("completed", "failed"):
            return st
    return "?"


def craft_onnx(proj: str, jid: str, status: str, train_job_id: str, weight_type: str, with_onnx: bool) -> None:
    d = ROOT / proj / "exports" / "onnx" / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({
        "export_job_id": jid, "status": status, "train_job_id": train_job_id,
        "weight_type": weight_type, "task": "detect", "imgsz": 640, "opset": 12,
        "simplify": True, "dynamic": False, "half": False, "device": "cpu",
    }), encoding="utf-8")
    if with_onnx:
        (d / "model.onnx").write_bytes(b"onnx-bytes")


def create_onnx_export(proj: str, train_job_id: str, weight: str) -> str:
    r = client.post(f"/api/projects/{proj}/onnx-exports", json={
        "train_job_id": train_job_id, "weight_type": weight, "opset": 12,
        "simplify": True, "dynamic": False, "half": False, "device": "cpu",
    })
    assert r.status_code == 201, r.text
    jid = r.json()["export_job_id"]
    assert wait_onnx(proj, jid) == "completed"
    return jid


def zip_names(content: bytes) -> set:
    return set(zipfile.ZipFile(io.BytesIO(content)).namelist())


def run_for_task(proj: str, task: str) -> None:
    client.post("/api/projects", json={"name": proj, "task": task})
    client.put(f"/api/projects/{proj}/classes", json={"names": ["a", "b"]})
    make_train_job(proj, "train_001", task)
    make_train_job(proj, "train_002", task)

    pkg_url = f"/api/projects/{proj}/model-export/train_001/best/package"
    dl = lambda pid: client.get(f"/api/projects/{proj}/model-packages/{pid}/download")  # noqa: E731

    # --- include_onnx=false（従来通り） ---
    r = client.post(pkg_url, json={"include_onnx": False})
    check(f"[{task}] pkg no-onnx 200", r.status_code == 200)
    names = zip_names(dl(r.json()["package_id"]).content)
    check(f"[{task}] no model.onnx", "weights/model.onnx" not in names)
    check(f"[{task}] no sample_infer_onnx", "sample_infer_onnx.py" not in names)
    check(f"[{task}] onnx_config present", "onnx_config.json" in names)
    zf = zipfile.ZipFile(io.BytesIO(dl(r.json()["package_id"]).content))
    oc = json.loads(zf.read("onnx_config.json"))
    check(f"[{task}] onnx_config included false", oc["included"] is False)

    # --- 完了ONNX exportを作って同梱 ---
    onnx_best = create_onnx_export(proj, "train_001", "best")
    r = client.post(pkg_url, json={"include_onnx": True, "onnx_export_job_id": onnx_best})
    check(f"[{task}] pkg with-onnx 200", r.status_code == 200)
    files = set(r.json()["files"])
    check(f"[{task}] response has model.onnx", "weights/model.onnx" in files)
    zf = zipfile.ZipFile(io.BytesIO(dl(r.json()["package_id"]).content))
    names = set(zf.namelist())
    for f in ("weights/model.onnx", "onnx_config.json", "sample_infer_onnx.py", "requirements-infer.txt"):
        check(f"[{task}] zip has {f}", f in names)
    oc = json.loads(zf.read("onnx_config.json"))
    check(f"[{task}] onnx_config included true", oc["included"] is True and oc["source_weight_type"] == "best")
    ic = json.loads(zf.read("inference_config.json"))
    check(f"[{task}] inference runtime.onnx available", ic["runtime"]["onnx"]["available"] is True)
    check(f"[{task}] inference runtime.pt sample", ic["runtime"]["pt"]["sample"] == "sample_infer.py")
    readme = zf.read("README_model.md").decode("utf-8")
    check(f"[{task}] README has ONNX section", "ONNX Runtime" in readme)
    reqs = zf.read("requirements-infer.txt").decode("utf-8")
    check(f"[{task}] requirements-infer has onnxruntime", "onnxruntime" in reqs)
    sample = zf.read("sample_infer_onnx.py").decode("utf-8")
    check(f"[{task}] sample_infer_onnx uses ort", "onnxruntime" in sample and "InferenceSession" in sample)

    # --- 不正指定 ---
    check(f"[{task}] missing onnx job 404", client.post(pkg_url, json={"include_onnx": True, "onnx_export_job_id": "no_such"}).status_code == 404)

    craft_onnx(proj, "onnx_running", "running", "train_001", "best", True)
    check(f"[{task}] uncompleted 400", client.post(pkg_url, json={"include_onnx": True, "onnx_export_job_id": "onnx_running"}).status_code == 400)

    craft_onnx(proj, "onnx_wrong_train", "completed", "train_002", "best", True)
    check(f"[{task}] wrong train_job 400", client.post(pkg_url, json={"include_onnx": True, "onnx_export_job_id": "onnx_wrong_train"}).status_code == 400)

    craft_onnx(proj, "onnx_wrong_weight", "completed", "train_001", "last", True)
    check(f"[{task}] wrong weight 400", client.post(pkg_url, json={"include_onnx": True, "onnx_export_job_id": "onnx_wrong_weight"}).status_code == 400)

    craft_onnx(proj, "onnx_no_file", "completed", "train_001", "best", False)
    check(f"[{task}] missing model.onnx 400", client.post(pkg_url, json={"include_onnx": True, "onnx_export_job_id": "onnx_no_file"}).status_code == 400)


def main() -> None:
    run_for_task("pkg_onnx_detect", "detect")
    run_for_task("pkg_onnx_segment", "segment")
    print("\nALL MODEL EXPORT ONNX SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
