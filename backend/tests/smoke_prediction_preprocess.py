"""推論時前処理のスモークテスト（Issue 021）。ワーカーは dry-run。"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_predpp_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_PREDICT_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402

client = TestClient(app)
PROJ = "predpp_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str) -> None:
    d = sum(ord(c) for c in stem)
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (d % 256, (d * 7) % 256, (d * 13) % 256)).save(buf, format="PNG")
    buf.seek(0)
    client.post(f"/api/projects/{PROJ}/images", files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))])


def make_train_weight(job_id: str) -> None:
    w = paths.train_job_dir(PROJ, job_id) / "weights"
    w.mkdir(parents=True, exist_ok=True)
    (w / "best.pt").write_bytes(b"x")
    (paths.train_job_dir(PROJ, job_id) / "job.json").write_text(
        json.dumps({"job_id": job_id, "status": "completed"}), encoding="utf-8")


def wait(predict_id: str) -> str:
    jj = paths.predict_job_dir(PROJ, predict_id) / "job.json"
    for _ in range(30):
        time.sleep(0.2)
        st = json.loads(jj.read_text(encoding="utf-8"))["status"]
        if st in ("completed", "failed"):
            return st
    return "?"


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a"]})
    make_image("img_a")
    make_image("img_b")
    make_train_weight("train_001")

    base = f"/api/projects/{PROJ}/predict-jobs"
    body = {
        "predict_job_name": "p_none", "train_job_id": "train_001", "weight_type": "best",
        "source_type": "project_images", "image_ids": ["img_a", "img_b"],
        "conf": 0.25, "iou": 0.7, "imgsz": 640, "device": "auto",
        "save_txt": True, "save_conf": True, "overwrite": False,
    }

    # preprocess_mode=none（既定）
    r = client.post(base, json=body)
    check("none start 201", r.status_code == 201)
    check("none done", wait("p_none") == "completed")
    check("no preprocessed_inputs", not (paths.predict_job_dir(PROJ, "p_none") / "preprocessed_inputs").exists())
    j = json.loads((paths.predict_job_dir(PROJ, "p_none") / "job.json").read_text(encoding="utf-8"))
    check("job none preprocess_mode", j["preprocess_mode"] == "none")

    # latest 未実行時 → 400
    r = client.post(base, json={**body, "predict_job_name": "p_latest1", "preprocess_mode": "latest"})
    check("latest without preprocess -> 400", r.status_code == 400)

    # 前処理を実行（2値化込み）
    r = client.post(f"/api/projects/{PROJ}/preprocess/run", json={
        "output_format": "jpg", "overwrite": True, "resize_enabled": True,
        "resize_mode": "width", "resize_size": 320,
        "binary_enabled": True, "binary_threshold": 128,
    })
    check("preprocess run 200", r.status_code == 200)

    # latest で推論 → preprocessed_inputs が生成
    r = client.post(base, json={**body, "predict_job_name": "p_latest2", "preprocess_mode": "latest"})
    check("latest start 201", r.status_code == 201)
    check("latest done", wait("p_latest2") == "completed")
    pp = paths.predict_job_dir(PROJ, "p_latest2") / "preprocessed_inputs"
    check("preprocessed_inputs created", pp.exists() and any(pp.iterdir()))
    # 前処理が効いている（リサイズ width=320 / 2値化）
    sample = sorted(pp.glob("*"))[0]
    with Image.open(sample) as im:
        check("preprocessed resized width=320", im.size[0] == 320)
        check("preprocessed binarized", {p[1] for p in im.convert("L").getcolors(100000)}.issubset({0, 255}))
    # 元画像・project processed は破壊されない
    check("raw intact", (paths.raw_images_dir(PROJ) / "img_a.png").exists())
    j2 = json.loads((paths.predict_job_dir(PROJ, "p_latest2") / "job.json").read_text(encoding="utf-8"))
    check("job latest preprocess_mode", j2["preprocess_mode"] == "latest")
    res = json.loads((paths.predict_job_dir(PROJ, "p_latest2") / "results.json").read_text(encoding="utf-8"))
    check("results preprocess_mode", res["preprocess_mode"] == "latest")

    print("\nALL PREDICTION PREPROCESS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
