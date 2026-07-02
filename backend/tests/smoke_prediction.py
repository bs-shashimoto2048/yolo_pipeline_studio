"""推論ジョブ基盤の軽量スモークテスト（Issue 007）。

実推論は走らせない。ワーカーは YTS_PREDICT_DRY_RUN=1 で空実行し、入力画像を
結果画像にコピー・results.json(検出0件)を生成する。実推論の確認は README を参照。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_prediction.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_predict_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_PREDICT_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "predict_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str) -> None:
    d = sum(ord(ch) for ch in stem)
    color = (d % 256, (d * 7) % 256, (d * 13) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(buf, format="PNG")
    buf.seek(0)
    client.post(
        f"/api/projects/{PROJ}/images",
        files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))],
    )


def make_fake_train_job(job_id: str, with_best: bool = True, with_last: bool = False) -> None:
    d = ROOT / PROJ / "runs" / "train" / job_id
    (d / "weights").mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"job_id": job_id, "status": "completed"}), encoding="utf-8"
    )
    if with_best:
        (d / "weights" / "best.pt").write_bytes(b"fake-weight")
    if with_last:
        (d / "weights" / "last.pt").write_bytes(b"fake-weight")


def wait_completed(predict_job_id: str) -> str:
    job_json = ROOT / PROJ / "predictions" / predict_job_id / "job.json"
    final = "?"
    for _ in range(30):
        time.sleep(0.2)
        final = json.loads(job_json.read_text(encoding="utf-8"))["status"]
        if final in {"completed", "failed"}:
            break
    return final


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["ct_h", "ct_l"]})
    make_image("sample_001")
    make_image("sample_002")
    make_fake_train_job("train_001", with_best=True, with_last=False)

    base = f"/api/projects/{PROJ}/predict-jobs"
    body = {
        "predict_job_name": "predict_001",
        "train_job_id": "train_001",
        "weight_type": "best",
        "source_type": "project_images",
        "image_ids": ["sample_001", "sample_002"],
        "conf": 0.25,
        "iou": 0.7,
        "imgsz": 640,
        "device": "auto",
        "save_txt": True,
        "save_conf": True,
        "overwrite": False,
    }

    # --- train_job_id 不在 → 404 ---
    r = client.post(base, json={**body, "train_job_id": "no_such"})
    check("missing train job -> 404", r.status_code == 404)

    # --- weight_type=last だが last.pt 不在 → 400 ---
    r = client.post(base, json={**body, "weight_type": "last"})
    check("missing weight -> 400", r.status_code == 400)

    # --- image_ids 空 → 400 ---
    r = client.post(base, json={**body, "image_ids": []})
    check("empty image_ids -> 400", r.status_code == 400)

    # --- 指定画像が存在しない → 404 ---
    r = client.post(base, json={**body, "image_ids": ["no_image"]})
    check("missing image -> 404", r.status_code == 404)

    # --- 正常 → 201, job.json 作成 ---
    r = client.post(base, json=body)
    check("start 201", r.status_code == 201)
    res = r.json()
    check("status queued", res["status"] == "queued")
    check("prediction_path", res["prediction_path"] == "predictions/predict_001")
    check("log_path", res["log_path"] == "predictions/predict_001/predict.log")

    job_json = ROOT / PROJ / "predictions" / "predict_001" / "job.json"
    check("job.json exists", job_json.exists())
    saved = json.loads(job_json.read_text(encoding="utf-8"))
    check("job.json image_count 2", saved["image_count"] == 2)

    # --- 同名 overwrite=false → 409 ---
    r = client.post(base, json=body)
    check("duplicate -> 409", r.status_code == 409)

    # --- overwrite=true → 201 ---
    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite -> 201", r.status_code == 201)

    # dry-run worker 完了待ち
    final = wait_completed("predict_001")
    check("dry-run completed", final == "completed")

    # --- 状態取得 ---
    r = client.get(f"{base}/predict_001")
    check("get job 200", r.status_code == 200)
    check("get job id", r.json()["predict_job_id"] == "predict_001")

    # --- 一覧 ---
    r = client.get(base)
    check("list 200", r.status_code == 200)
    check("list has job", any(j["predict_job_id"] == "predict_001" for j in r.json()["jobs"]))

    # --- ログ ---
    r = client.get(f"{base}/predict_001/logs")
    check("logs 200", r.status_code == 200 and "log" in r.json())

    # --- 結果取得 ---
    r = client.get(f"{base}/predict_001/results")
    check("results 200", r.status_code == 200)
    rr = r.json()
    check("results image_count 2", rr["image_count"] == 2)
    check("results detection_count 0 (dry)", rr["detection_count"] == 0)
    check("results has 2 items", len(rr["results"]) == 2)
    first = rr["results"][0]
    check("result has image_name", bool(first["image_name"]))
    check(
        "result_image_url shape",
        first["result_image_url"].startswith(
            f"/api/projects/{PROJ}/predict-jobs/predict_001/images/"
        ),
    )

    # --- 結果画像配信 ---
    img_name = first["image_name"]
    r = client.get(f"{base}/predict_001/images/{img_name}")
    check("result image 200", r.status_code == 200)
    check("result image content-type", r.headers["content-type"].startswith("image/"))

    # --- 非画像 → 400 ---
    r = client.get(f"{base}/predict_001/images/results.json")
    check("non-image -> 400", r.status_code == 400)

    # --- 存在しない画像 → 404 ---
    r = client.get(f"{base}/predict_001/images/nope.png")
    check("missing image -> 404", r.status_code == 404)

    # --- パストラバーサル → 400 または 404 ---
    r = client.get(f"{base}/predict_001/images/..%2F..%2Fjob.json")
    check("traversal blocked", r.status_code in (400, 404))

    # --- 存在しないジョブ → 404 ---
    r = client.get(f"{base}/no_job")
    check("missing job -> 404", r.status_code == 404)

    print("\nALL PREDICTION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
