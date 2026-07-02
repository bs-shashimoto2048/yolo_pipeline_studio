"""学習結果評価APIのスモークテスト（Issue 006）。

実学習は走らせず、results.csv や成果物画像を手で配置して解析・配信を検証する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_evaluation.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_eval_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "eval_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def run_dir(job_id: str) -> Path:
    d = ROOT / PROJ / "runs" / "train" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_job(job_id: str, status: str) -> None:
    (run_dir(job_id) / "job.json").write_text(
        json.dumps({"job_id": job_id, "status": status}, ensure_ascii=False),
        encoding="utf-8",
    )


def save_png(path: Path) -> None:
    img = Image.new("RGB", (32, 32), (123, 222, 64))
    img.save(path, format="PNG")


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    base = f"/api/projects/{PROJ}/train-jobs"

    # === completed ジョブ: results.csv（列名に前後空白あり / UTF-8-SIG）===
    d = run_dir("train_001")
    write_job("train_001", "completed")
    # 列名にわざと空白を入れ、BOM付き(utf-8-sig)で保存
    csv_text = (
        " epoch , train/box_loss , train/cls_loss , train/dfl_loss ,"
        " metrics/precision(B) , metrics/recall(B) , metrics/mAP50(B) ,"
        " metrics/mAP50-95(B) , val/box_loss , val/cls_loss , val/dfl_loss \n"
        "1, 1.234, 0.987, 0.85, 0.70, 0.60, 0.75, 0.50, 1.10, 0.95, 0.90\n"
        "\n"  # 空行（無視されること）
        "2, 0.451, 0.233, 0.84, 0.9234, 0.8876, 0.9521, 0.8123, 0.512, 0.301, 0.901\n"
    )
    (d / "results.csv").write_text(csv_text, encoding="utf-8-sig")
    (d / "weights").mkdir(exist_ok=True)
    (d / "weights" / "best.pt").write_bytes(b"x")
    (d / "weights" / "last.pt").write_bytes(b"x")
    save_png(d / "results.png")
    save_png(d / "confusion_matrix.png")

    # --- 評価サマリー ---
    r = client.get(f"{base}/train_001/evaluation")
    check("evaluation 200", r.status_code == 200)
    ev = r.json()
    check("status completed", ev["status"] == "completed")
    check("has_results_csv true", ev["has_results_csv"] is True)
    check("has_best/last", ev["has_best_model"] and ev["has_last_model"])
    s = ev["summary"]
    check("epoch int (last row=2)", s["epoch"] == 2)
    check("precision strip+parse", abs(s["precision"] - 0.9234) < 1e-9)
    check("recall", abs(s["recall"] - 0.8876) < 1e-9)
    check("map50", abs(s["map50"] - 0.9521) < 1e-9)
    check("map50_95", abs(s["map50_95"] - 0.8123) < 1e-9)
    check("train_box_loss", abs(s["train_box_loss"] - 0.451) < 1e-9)
    check("val_box_loss", abs(s["val_box_loss"] - 0.512) < 1e-9)

    # --- artifacts 一覧 ---
    names = [a["name"] for a in ev["artifacts"]]
    check("artifacts has results.png", "results.png" in names)
    check("artifacts has confusion_matrix.png", "confusion_matrix.png" in names)
    check(
        "artifact url shape",
        ev["artifacts"][0]["url"].startswith(
            f"/api/projects/{PROJ}/train-jobs/train_001/artifacts/"
        ),
    )
    check(
        "artifact path posix",
        ev["artifacts"][0]["path"].startswith("runs/train/train_001/"),
    )

    # --- metrics ---
    r = client.get(f"{base}/train_001/metrics")
    check("metrics 200", r.status_code == 200)
    m = r.json()
    check("metrics columns stripped", "epoch" in m["columns"] and "metrics/precision(B)" in m["columns"])
    check("metrics rows skip blank (2 rows)", len(m["rows"]) == 2)
    check("metrics epoch int", m["rows"][0]["epoch"] == 1)
    check("metrics float", abs(m["rows"][0]["train/box_loss"] - 1.234) < 1e-9)

    # --- 画像artifact取得 ---
    r = client.get(f"{base}/train_001/artifacts/results.png")
    check("artifact image 200", r.status_code == 200)
    check("artifact content-type image", r.headers["content-type"].startswith("image/"))

    # --- 存在しないartifact → 404 ---
    r = client.get(f"{base}/train_001/artifacts/nope.png")
    check("missing artifact 404", r.status_code == 404)

    # --- 画像以外の拡張子 → 400 ---
    r = client.get(f"{base}/train_001/artifacts/results.csv")
    check("non-image 400", r.status_code == 400)

    # --- パストラバーサル → 400 または 404 ---
    r = client.get(f"{base}/train_001/artifacts/..%2F..%2Fjob.json")
    check("traversal blocked", r.status_code in (400, 404))
    r = client.get(f"{base}/train_001/artifacts/weights%2Fbest.pt")
    check("subdir blocked", r.status_code in (400, 404))

    # === results.csv が無い場合（running）===
    write_job("train_running", "running")
    r = client.get(f"{base}/train_running/evaluation")
    check("running evaluation 200", r.status_code == 200)
    check("running has_results_csv false", r.json()["has_results_csv"] is False)
    check("running summary null", r.json()["summary"] is None)
    r = client.get(f"{base}/train_running/metrics")
    check("running metrics 200 empty", r.status_code == 200 and r.json()["rows"] == [])

    # === failed ジョブでも評価APIが落ちない ===
    write_job("train_failed", "failed")
    r = client.get(f"{base}/train_failed/evaluation")
    check("failed evaluation 200", r.status_code == 200)
    check("failed status", r.json()["status"] == "failed")

    # === 存在しないジョブ → 404 ===
    r = client.get(f"{base}/no_job/evaluation")
    check("missing job 404", r.status_code == 404)

    print("\nALL EVALUATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
