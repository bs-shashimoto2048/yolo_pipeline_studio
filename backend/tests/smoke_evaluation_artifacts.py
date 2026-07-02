"""評価成果物検出のスモークテスト（Issue 021）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_evart_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402

client = TestClient(app)
PROJ = "evart_proj"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (120, 150, 90)).save(path, format="PNG")


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    run = paths.train_job_dir(PROJ, "train_001")
    run.mkdir(parents=True, exist_ok=True)
    (run / "job.json").write_text(json.dumps({"job_id": "train_001", "status": "completed"}), encoding="utf-8")

    # 成果物を配置（一部は大文字小文字違い）
    png(run / "results.png")
    png(run / "F1_curve.png")
    png(run / "PR_curve.png")
    png(run / "P_curve.png")
    png(run / "R_curve.png")
    png(run / "confusion_matrix.png")
    # weights配下の画像は対象外
    png(run / "weights" / "ignore.png")

    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_001/evaluation")
    check("evaluation 200", r.status_code == 200)
    names = {a["name"] for a in r.json()["artifacts"]}
    check("F1_curve detected", "F1_curve.png" in names)
    check("PR_curve detected", "PR_curve.png" in names)
    check("P_curve detected", "P_curve.png" in names)
    check("R_curve detected", "R_curve.png" in names)
    check("weights image excluded", "ignore.png" not in names)

    # artifact 配信（画像のみ）
    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_001/artifacts/F1_curve.png")
    check("serve F1_curve 200", r.status_code == 200 and r.headers["content-type"].startswith("image/"))
    # 大文字小文字差分でも配信できる
    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_001/artifacts/f1_curve.PNG")
    check("case-insensitive serve", r.status_code == 200)
    # 非画像 → 400
    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_001/artifacts/results.csv")
    check("non-image -> 400", r.status_code == 400)
    # パストラバーサル → 400/404
    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_001/artifacts/..%2Fjob.json")
    check("traversal blocked", r.status_code in (400, 404))
    # 存在しない → 404
    r = client.get(f"/api/projects/{PROJ}/train-jobs/train_001/artifacts/nope.png")
    check("missing -> 404", r.status_code == 404)

    print("\nALL EVALUATION ARTIFACTS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
