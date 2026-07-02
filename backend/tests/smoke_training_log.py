"""学習ログ整形・data.yaml絶対パス・学習前検証のスモークテスト（Issue 018）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_training_log.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_tlog_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
import yaml  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402
from app.services import log_utils  # noqa: E402

client = TestClient(app)
PROJ = "tlog_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def make_image(stem: str) -> None:
    d = sum(ord(c) for c in stem)
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (d % 256, (d * 7) % 256, (d * 13) % 256)).save(buf, format="PNG")
    buf.seek(0)
    client.post(f"/api/projects/{PROJ}/images",
                files=[("files", (f"{stem}.png", buf.getvalue(), "image/png"))])


def main() -> None:
    # --- log_utils 単体 ---
    check("strip_ansi removes color", log_utils.strip_ansi("\x1b[34m\x1b[1mengine\x1b[0m x") == "engine x")
    check("classify error", log_utils.classify_line("Traceback (most recent call last):") == "error")
    check("classify info", log_utils.classify_line("[INFO] 学習開始") == "info")
    check("summary images not found",
          log_utils.error_summary("Dataset images not found, missing path X") is not None
          and "画像パス" in log_utils.error_summary("images not found missing path X"))
    check("summary cuda oom",
          "GPUメモリ" in (log_utils.error_summary("torch.cuda.OutOfMemoryError: CUDA out of memory") or ""))
    check("summary no ultralytics",
          "ultralytics" in (log_utils.error_summary("ModuleNotFoundError: No module named 'ultralytics'") or ""))
    check("summary cuda unavailable",
          "CUDA" in (log_utils.error_summary("AssertionError: CUDA is not available") or ""))

    # --- セットアップ ---
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a"]})
    for i in range(4):
        stem = f"img_{i:02d}"
        make_image(stem)
        p = paths.labels_dir(PROJ) / f"{stem}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    r = client.post(f"/api/projects/{PROJ}/datasets", json={
        "dataset_name": "ds1", "train_ratio": 0.5, "val_ratio": 0.5, "test_ratio": 0.0,
        "use_selection": False,
    })
    check("dataset created", r.status_code == 201)

    # --- data.yaml の path が絶対パスPOSIX ---
    ds_dir = paths.dataset_dir(PROJ, "ds1")
    dy = yaml.safe_load((ds_dir / "data.yaml").read_text(encoding="utf-8"))
    check("data.yaml path absolute posix", dy["path"] == ds_dir.resolve().as_posix())
    check("data.yaml train rel", dy["train"] == "images/train")

    # --- logs API: ANSI除去・日本語・CP932混入・lines・error_summary ---
    run_dir = paths.train_job_dir(PROJ, "train_log")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "job.json").write_text(json.dumps({"job_id": "train_log", "status": "failed",
                                                  "message": "x"}), encoding="utf-8")
    log_bytes = (
        "\x1b[34m\x1b[1m[INFO] 学習開始 model=yolov8n.pt\x1b[0m\n".encode("utf-8")
        + "[INFO] 日本語ログ テスト\n".encode("utf-8")
        + b"\x93\xfa\x96{\x8c\xea\n"  # CP932の不正バイト（utf-8として壊れている）
        + "Dataset images not found, missing path C:/x/images/val\n".encode("utf-8")
    )
    (run_dir / "train.log").write_bytes(log_bytes)

    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_log/logs")
    check("logs 200", r.status_code == 200)
    body = r.json()
    check("no ANSI in log", "\x1b[" not in body["log"])
    check("japanese readable", "学習開始" in body["log"] and "日本語ログ" in body["log"])
    check("lines present", len(body["lines"]) >= 3)
    check("has error line", any(l["level"] == "error" for l in body["lines"]))
    check("has info line", any(l["level"] == "info" for l in body["lines"]))
    check("error_summary set", body["error_summary"] is not None and "画像パス" in body["error_summary"])

    # --- 学習前検証: val パス不正で 400 ---
    import shutil
    shutil.rmtree(ds_dir / "images" / "val")
    r = client.post(f"/api/projects/{PROJ}/train-jobs", json={
        "dataset_name": "ds1", "job_name": "train_bad", "epochs": 1, "device": "cpu",
    })
    check("missing val path -> 400", r.status_code == 400)
    check("400 message mentions val", "val" in r.json()["detail"])

    print("\nALL TRAINING LOG SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
