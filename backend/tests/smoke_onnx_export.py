"""ONNXエクスポートの軽量スモークテスト（Issue 027、dry-run）。

実ONNX exportは走らせない。ワーカーは YTS_ONNX_DRY_RUN=1 でダミー model.onnx と
metadata.json を生成し completed にする。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_onnx_export.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_onnx_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_ONNX_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)
PROJ = "onnx_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_train_job(job_id: str, with_best=True, with_last=True) -> None:
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"job_id": job_id, "imgsz": 640, "task": "detect", "status": "completed"}),
        encoding="utf-8",
    )
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"fake-best")
    if with_last:
        (d / "weights" / "last.pt").write_bytes(b"fake-last")


def wait_completed(export_job_id: str) -> str:
    job_json = ROOT / PROJ / "exports" / "onnx" / export_job_id / "job.json"
    final = "?"
    for _ in range(40):
        time.sleep(0.2)
        try:
            final = json.loads(job_json.read_text(encoding="utf-8"))["status"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            continue
        if final in {"completed", "failed"}:
            break
    return final


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})
    make_train_job("train_001")
    make_train_job("train_nolast", with_best=True, with_last=False)

    base = f"/api/projects/{PROJ}/onnx-exports"
    body = {
        "train_job_id": "train_001",
        "weight_type": "best",
        "opset": 12,
        "simplify": True,
        "dynamic": False,
        "half": False,
        "device": "cpu",
        "overwrite": False,
    }

    # --- バリデーション ---
    check("missing train job 404", client.post(base, json={**body, "train_job_id": "no_such"}).status_code == 404)
    check("missing weight 404", client.post(base, json={**body, "train_job_id": "train_nolast", "weight_type": "last"}).status_code == 404)
    check("bad weight_type 400", client.post(base, json={**body, "weight_type": "bogus"}).status_code == 400)
    check("bad opset 400", client.post(base, json={**body, "opset": 99}).status_code == 400)
    check("bad imgsz 400", client.post(base, json={**body, "imgsz": 10}).status_code == 400)
    check("bad device 400", client.post(base, json={**body, "device": "gpu"}).status_code == 400)

    # --- best export 作成 ---
    r = client.post(base, json=body)
    check("start best 201", r.status_code == 201)
    res = r.json()
    check("status queued", res["status"] == "queued")
    check("export_job_id", res["export_job_id"] == "onnx_train_001_best")
    check("export_path", res["export_path"] == "exports/onnx/onnx_train_001_best")

    jid = "onnx_train_001_best"
    job_json = ROOT / PROJ / "exports" / "onnx" / jid / "job.json"
    check("job.json exists", job_json.exists())

    # --- 同名 overwrite=false 409 ---
    check("duplicate 409", client.post(base, json=body).status_code == 409)
    # --- overwrite=true 201 ---
    check("overwrite 201", client.post(base, json={**body, "overwrite": True}).status_code == 201)

    # --- dry-run 完了待ち ---
    check("best dry-run completed", wait_completed(jid) == "completed")

    edir = ROOT / PROJ / "exports" / "onnx" / jid
    check("model.onnx generated", (edir / "model.onnx").exists())
    check("metadata.json generated", (edir / "metadata.json").exists())
    meta = json.loads((edir / "metadata.json").read_text(encoding="utf-8"))
    check("metadata onnx_path", meta["onnx_path"].endswith("model.onnx"))
    check("metadata task detect", meta["task"] == "detect")
    check("metadata classes_path", meta["classes_path"] == "classes.json")

    # --- last export 作成 ---
    r = client.post(base, json={**body, "weight_type": "last"})
    check("start last 201", r.status_code == 201)
    check("last dry-run completed", wait_completed("onnx_train_001_last") == "completed")

    # --- 状態取得 ---
    r = client.get(f"{base}/{jid}")
    check("get status 200", r.status_code == 200 and r.json()["export_job_id"] == jid)
    check("get onnx_path set", r.json()["onnx_path"] is not None)

    # --- 一覧 ---
    r = client.get(base)
    ids = {e["export_job_id"] for e in r.json()["exports"]}
    check("list has both", {"onnx_train_001_best", "onnx_train_001_last"}.issubset(ids))

    # --- ログ ---
    r = client.get(f"{base}/{jid}/logs")
    check("logs 200", r.status_code == 200 and "log" in r.json() and "lines" in r.json())

    # --- ダウンロード ---
    r = client.get(f"{base}/{jid}/download")
    check("download 200", r.status_code == 200)
    check("download content-type", r.headers["content-type"].startswith("application/octet-stream"))
    check("download has bytes", len(r.content) > 0)

    # --- 存在しない export 404 ---
    check("missing export 404", client.get(f"{base}/no_such_export").status_code == 404)
    check("missing download 404", client.get(f"{base}/no_such_export/download").status_code == 404)

    # --- パストラバーサル遮断 ---
    r = client.get(f"{base}/..%2F..%2Fjob/download")
    check("traversal blocked", r.status_code in (400, 404))

    # --- detect/segment: segmentプロジェクトでも壊れない ---
    SEG = "onnx_seg_proj"
    client.post("/api/projects", json={"name": SEG, "task": "segment"})
    client.put(f"/api/projects/{SEG}/classes", json={"names": ["x"]})
    d = ROOT / SEG / "runs" / "train" / "train_001" / "weights"
    d.mkdir(parents=True, exist_ok=True)
    (ROOT / SEG / "runs" / "train" / "train_001" / "job.json").write_text(
        json.dumps({"job_id": "train_001", "imgsz": 640, "task": "segment"}), encoding="utf-8")
    (d / "best.pt").write_bytes(b"seg")
    r = client.post(f"/api/projects/{SEG}/onnx-exports", json=body)
    check("segment export 201", r.status_code == 201)
    check("segment dry-run completed", (lambda: __wait_seg())())

    print("\nALL ONNX EXPORT SMOKE TESTS PASSED")


def __wait_seg() -> bool:
    job_json = ROOT / "onnx_seg_proj" / "exports" / "onnx" / "onnx_train_001_best" / "job.json"
    for _ in range(40):
        time.sleep(0.2)
        try:
            if json.loads(job_json.read_text(encoding="utf-8"))["status"] == "completed":
                return True
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            continue
    return False


if __name__ == "__main__":
    main()
