"""同名project同時作成のrace防止スモークテスト（Issue #50で発見・修正した回帰）。

Issue #49で`project_dir(name).mkdir(exist_ok=False)`による原子的排他生成を
導入したが、「project.yamlが無ければ過去の失敗の残骸とみなして自己修復する」
救済ロジックが、mkdir直後〜project.yaml書き込み完了までの間に別リクエストが
来た場合を「過去の残骸」と誤認してしまい、複数リクエストが同名projectを
同時作成できてしまう実害のある回帰を引き起こしていた
（Issue #50で実HTTP経由の同時create_project race testにより実際に検出）。
本テストはこの回帰の固定化テスト。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_project_creation_race.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_project_race_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def test_concurrent_same_name_create_only_one_succeeds() -> None:
    results: list[int | str] = []

    def create(user: str) -> None:
        try:
            r = client.post(
                "/api/projects",
                json={"name": "race_proj", "description": "", "task": "detect"},
                headers={"X-YTS-User-Id": user, "X-YTS-Display-Name": user},
            )
            results.append(r.status_code)
        except Exception as exc:  # noqa: BLE001
            results.append(f"EXCEPTION: {exc!r}")

    threads = [threading.Thread(target=create, args=(f"user-{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    check("all 10 threads completed without dropping", len(results) == 10)
    success = [r for r in results if r == 201]
    conflict = [r for r in results if r == 400]
    check("exactly 1 success (201)", len(success) == 1)
    check("exactly 9 conflicts (400)", len(conflict) == 9)

    r = client.get("/api/projects/race_proj")
    check("project readable after race", r.status_code == 200)
    owner = r.json()["owner_user_id"]
    check("winner owner_user_id is one of the 10 race users",
          owner is not None and owner.startswith("user-"))


def main() -> None:
    test_concurrent_same_name_create_only_one_succeeds()
    print("\nALL PROJECT CREATION RACE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
