"""レポート出力のスモークテスト（Issue 016）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_reports.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_rep_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "rep_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    # ほぼ空のプロジェクト（selection/preprocess/dataset/model 未実行）
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})
    base = f"/api/projects/{PROJ}/reports"

    # 空に近いプロジェクトでも markdown 生成できる（未実行データで落ちない）
    r = client.post(base, json={"report_name": "report_001", "format": "markdown"})
    check("markdown 201", r.status_code == 201)
    res = r.json()
    check("markdown_path set", res["markdown_path"] == "reports/report_001.md")
    check("json_path set", res["json_path"] == "reports/report_001.json")
    check("md file exists", (ROOT / PROJ / "reports" / "report_001.md").exists())
    check("json file exists", (ROOT / PROJ / "reports" / "report_001.json").exists())
    check("latest_report saved", (ROOT / PROJ / "reports" / "latest_report.json").exists())

    # json のみ
    r = client.post(base, json={"report_name": "report_json", "format": "json"})
    check("json 201", r.status_code == 201)
    check("json-only no md path", r.json()["markdown_path"] is None)

    # both
    r = client.post(base, json={"report_name": "report_both", "format": "both"})
    check("both 201", r.status_code == 201 and r.json()["markdown_path"] is not None)

    # 不正 format → 400
    r = client.post(base, json={"report_name": "bad", "format": "pdf"})
    check("bad format -> 400", r.status_code == 400)

    # 一覧
    r = client.get(base)
    check("list 200", r.status_code == 200)
    ids = {x["report_id"] for x in r.json()["reports"]}
    check("list has reports", {"report_001", "report_json", "report_both"} <= ids)
    check("latest excluded from list", "latest_report" not in ids)

    # 詳細
    r = client.get(f"{base}/report_001")
    check("detail 200", r.status_code == 200)
    content = r.json()["content"]
    check("detail has overview", content["project_overview"]["project_name"] == PROJ)
    check("detail selection 未実行", content["selection"]["status"] == "未実行")
    check("detail preprocess 未実行", content["preprocess"]["status"] == "未実行")
    check("detail selected_model None", content["selected_model"] is None)
    check("detail improvements", len(content["improvement_suggestions"]) >= 1)
    check("detail classes", len(content["classes"]) == 2)

    # ダウンロード（markdown / json）
    r = client.get(f"{base}/report_both/download", params={"format": "markdown"})
    check("download md 200", r.status_code == 200 and r.headers["content-type"].startswith("text/markdown"))
    r = client.get(f"{base}/report_both/download", params={"format": "json"})
    check("download json 200", r.status_code == 200)

    # json-only レポートの markdown download は 404
    r = client.get(f"{base}/report_json/download", params={"format": "markdown"})
    check("md download missing -> 404", r.status_code == 404)

    # 存在しない report_id → 404
    r = client.get(f"{base}/no_such")
    check("missing report -> 404", r.status_code == 404)

    # パストラバーサル系 → 400 または 404
    r = client.get(f"{base}/..%2F..%2Fproject")
    check("traversal -> 400/404", r.status_code in (400, 404))

    print("\nALL REPORTS SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
