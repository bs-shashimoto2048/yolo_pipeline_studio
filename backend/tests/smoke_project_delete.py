"""プロジェクト削除のスモークテスト（Issue 020）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_pdel_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core import paths  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    client.post("/api/projects", json={"name": "p_del"})
    check("project dir exists", paths.project_dir("p_del").exists())

    # 削除
    r = client.delete("/api/projects/p_del")
    check("delete 200", r.status_code == 200)
    check("project dir removed", not paths.project_dir("p_del").exists())
    r = client.get("/api/projects")
    check("removed from list", all(p["name"] != "p_del" for p in r.json()))

    # 存在しない → 404
    r = client.delete("/api/projects/no_such")
    check("missing -> 404", r.status_code == 404)

    # 実行中ジョブがある場合 → 409
    client.post("/api/projects", json={"name": "p_busy"})
    d = paths.train_job_dir("p_busy", "train_001")
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({"job_id": "train_001", "status": "running"}), encoding="utf-8")
    r = client.delete("/api/projects/p_busy")
    check("active job -> 409", r.status_code == 409)
    check("busy project kept", paths.project_dir("p_busy").exists())

    # 完了状態にすれば削除可
    (d / "job.json").write_text(json.dumps({"job_id": "train_001", "status": "completed"}), encoding="utf-8")
    r = client.delete("/api/projects/p_busy")
    check("after complete -> 200", r.status_code == 200)

    print("\nALL PROJECT DELETE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
