"""誤検出分析APIのスモークテスト（Issue 008）。

推論結果(results.json)と正解ラベルを手で配置し、TP/FP/FN/class_mismatch の
判定・しきい値・保存/再取得・各種エラーを検証する（実推論は不要）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_analysis.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_analysis_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "ana_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def write_label(stem: str, content: str) -> None:
    p = ROOT / PROJ / "annotations" / "labels" / f"{stem}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def make_predict_job(job_id: str, status: str, results: dict | None) -> None:
    d = ROOT / PROJ / "predictions" / job_id
    (d / "outputs" / "images").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"predict_job_id": job_id, "status": status}), encoding="utf-8"
    )
    if results is not None:
        (d / "results.json").write_text(json.dumps(results), encoding="utf-8")


def det(cid, conf, x, y, w, h):
    return {"class_id": cid, "class_name": None, "confidence": conf,
            "x_center": x, "y_center": y, "width": w, "height": h}


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["ct_h", "ct_l"]})

    # === predict_001: TP/FP/FN/class_mismatch/conf-filter/duplicate ===
    # GT: class0@(0.5,0.5), class1@(0.2,0.2), class0@(0.8,0.8)
    write_label("sample_001", "0 0.5 0.5 0.2 0.2\n1 0.2 0.2 0.1 0.1\n0 0.8 0.8 0.1 0.1\n")
    res_001 = {
        "results": [{
            "image_id": "sample_001",
            "image_name": "sample_001.jpg",
            "detections": [
                det(0, 0.90, 0.50, 0.50, 0.20, 0.20),   # TP (GT0)
                det(0, 0.80, 0.51, 0.50, 0.20, 0.20),   # FP (GT0 重複)
                det(0, 0.90, 0.10, 0.10, 0.05, 0.05),   # FP (重なりなし)
                det(1, 0.70, 0.80, 0.80, 0.10, 0.10),   # class_mismatch (GT2はclass0)
                det(0, 0.10, 0.95, 0.95, 0.02, 0.02),   # conf<0.25 → 除外
            ],
        }],
    }
    make_predict_job("predict_001", "completed", res_001)

    base = f"/api/projects/{PROJ}/predict-jobs/predict_001/analysis"
    r = client.post(base, json={"iou_threshold": 0.5, "conf_threshold": 0.25})
    check("analysis 200", r.status_code == 200)
    a = r.json()
    s = a["summary"]
    check("gt_count 3", s["ground_truth_count"] == 3)
    check("prediction_count 4 (conf filter)", s["prediction_count"] == 4)
    check("TP 1", s["tp_count"] == 1)
    check("FP 2", s["fp_count"] == 2)
    check("FN 2", s["fn_count"] == 2)
    check("class_mismatch 1", s["class_mismatch_count"] == 1)
    check("precision 1/3", abs(s["precision"] - 1 / 3) < 1e-4)
    check("recall 1/3", abs(s["recall"] - 1 / 3) < 1e-4)

    # duplicate FP は GTと重なる（iou>0 の fp item が存在）
    items = a["image_results"][0]["items"]
    dup_fp = [it for it in items if it["type"] == "fp" and it["iou"] is not None and it["iou"] > 0]
    check("duplicate FP recorded (1 TP, rest FP)", len(dup_fp) == 1)
    check("class_mismatch item has gt_class", any(
        it["type"] == "class_mismatch" and it["gt_class_id"] == 0 for it in items))

    # analysis.json 保存
    check("analysis.json saved", (ROOT / PROJ / "predictions" / "predict_001" / "analysis.json").exists())

    # GET 再取得
    r = client.get(base)
    check("GET analysis 200", r.status_code == 200)
    check("GET same tp", r.json()["summary"]["tp_count"] == 1)

    # === IoUしきい値で判定が変わる（predict_002）===
    write_label("sample_002", "0 0.5 0.5 0.2 0.2\n")
    res_002 = {"results": [{
        "image_id": "sample_002", "image_name": "sample_002.jpg",
        "detections": [det(0, 0.9, 0.58, 0.50, 0.20, 0.20)],  # IoU≈0.43
    }]}
    make_predict_job("predict_002", "completed", res_002)
    b2 = f"/api/projects/{PROJ}/predict-jobs/predict_002/analysis"

    r = client.post(b2, json={"iou_threshold": 0.5, "conf_threshold": 0.25})
    check("iou0.5 -> TP0/FP1", r.json()["summary"]["tp_count"] == 0 and r.json()["summary"]["fp_count"] == 1)
    r = client.post(b2, json={"iou_threshold": 0.4, "conf_threshold": 0.25})
    check("iou0.4 -> TP1/FP0", r.json()["summary"]["tp_count"] == 1 and r.json()["summary"]["fp_count"] == 0)

    # === running / failed → 400 ===
    make_predict_job("predict_run", "running", None)
    r = client.post(f"/api/projects/{PROJ}/predict-jobs/predict_run/analysis", json={})
    check("running -> 400", r.status_code == 400)
    make_predict_job("predict_fail", "failed", None)
    r = client.post(f"/api/projects/{PROJ}/predict-jobs/predict_fail/analysis", json={})
    check("failed -> 400", r.status_code == 400)

    # === results.json なし（completed）→ 400 ===
    make_predict_job("predict_nores", "completed", None)
    r = client.post(f"/api/projects/{PROJ}/predict-jobs/predict_nores/analysis", json={})
    check("no results.json -> 400/404", r.status_code in (400, 404))

    # === しきい値範囲外 → 400 ===
    r = client.post(base, json={"iou_threshold": 1.5, "conf_threshold": 0.25})
    check("iou out of range -> 400", r.status_code == 400)
    r = client.post(base, json={"iou_threshold": 0.5, "conf_threshold": -0.1})
    check("conf out of range -> 400", r.status_code == 400)

    # === 不正な正解ラベル → 400 ===
    write_label("sample_bad", "0 0.5 0.5 0.2\n")  # 4列
    res_bad = {"results": [{"image_id": "sample_bad", "image_name": "sample_bad.jpg",
                            "detections": [det(0, 0.9, 0.5, 0.5, 0.2, 0.2)]}]}
    make_predict_job("predict_bad", "completed", res_bad)
    r = client.post(f"/api/projects/{PROJ}/predict-jobs/predict_bad/analysis", json={})
    check("invalid GT label -> 400", r.status_code == 400)

    # === 存在しないジョブ → 404 ===
    r = client.post(f"/api/projects/{PROJ}/predict-jobs/no_job/analysis", json={})
    check("missing job -> 404", r.status_code == 404)
    r = client.get(f"/api/projects/{PROJ}/predict-jobs/predict_002/analysis")
    check("GET existing 200", r.status_code == 200)
    r = client.get(f"/api/projects/{PROJ}/predict-jobs/predict_run/analysis")
    check("GET without analysis -> 404", r.status_code == 404)

    print("\nALL ANALYSIS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
