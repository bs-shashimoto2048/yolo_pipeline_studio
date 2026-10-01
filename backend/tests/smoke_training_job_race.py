"""同名training job(job_name)同時投入のrace防止スモークテスト（Issue #50で発見・修正）。

training_service.prepare_job()の「run_dir.exists()チェック→run_dir.mkdir()」が
check-then-actでTOCTOU脆弱だった（project_serviceの同名project衝突と同じ根本
原因）。実HTTP経由での二重クリック/race testにより実際に再現を確認した
（GILの影響で再現確率は低いが、ゼロではない潜在バグ）。本テストはこの回帰の
固定化テスト。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_training_job_race.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_train_job_race_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "race_train_proj"
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


def write_label(stem: str, content: str) -> None:
    p = ROOT / PROJ / "annotations" / "labels" / f"{stem}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def setup_dataset() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a"]})
    for i in range(10):
        stem = f"img_{i:02d}"
        make_image(stem)
        write_label(stem, "0 0.5 0.5 0.2 0.2\n")
    r = client.post(
        f"/api/projects/{PROJ}/datasets",
        json={"dataset_name": "ds_001", "train_ratio": 0.8, "val_ratio": 0.2, "test_ratio": 0.0, "seed": 42},
    )
    assert r.status_code == 201, r.text


def test_concurrent_same_job_name_only_one_succeeds() -> None:
    results: list[int | str] = []

    def submit() -> None:
        try:
            r = client.post(
                f"/api/projects/{PROJ}/train-jobs",
                json={
                    "dataset_name": "ds_001", "job_name": "race_job", "model": "yolov8n.pt",
                    "epochs": 1, "imgsz": 640, "batch": 8, "device": "auto",
                    "workers": 2, "patience": 20, "seed": 42, "overwrite": False,
                },
            )
            results.append(r.status_code)
        except Exception as exc:  # noqa: BLE001
            results.append(f"EXCEPTION: {exc!r}")

    threads = [threading.Thread(target=submit) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    check("all 10 threads completed without dropping", len(results) == 10)
    success = [r for r in results if r == 201]
    conflict = [r for r in results if r == 409]
    check("exactly 1 success (201)", len(success) == 1)
    check("exactly 9 conflicts (409)", len(conflict) == 9)

    r = client.get(f"/api/projects/{PROJ}/train-jobs/race_job")
    check("job readable after race", r.status_code == 200)


def main() -> None:
    setup_dataset()
    test_concurrent_same_job_name_only_one_succeeds()
    print("\nALL TRAINING JOB RACE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
