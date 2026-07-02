"""学習時オーギュメンテーションのスモークテスト（Issue 013）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_augmentation.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_aug_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ["YTS_TRAIN_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "aug_proj"
ROOT = Path(_tmp)


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def png(seed: int, fmt: str = "PNG") -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (320, 240), (seed % 256, (seed * 7) % 256, (seed * 13) % 256)).save(b, format=fmt)
    return b.getvalue()


def setup_dataset() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["a", "b"]})
    lbl = ROOT / PROJ / "annotations" / "labels"
    lbl.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        stem = f"img_{i:02d}"
        client.post(f"/api/projects/{PROJ}/images",
                    files=[("files", (f"{stem}.png", png(i), "image/png"))])
        (lbl / f"{stem}.txt").write_text(f"{i % 2} 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    r = client.post(f"/api/projects/{PROJ}/datasets",
                    json={"dataset_name": "ds1", "train_ratio": 0.8, "val_ratio": 0.2, "test_ratio": 0.0})
    assert r.status_code == 201, r.text


def main() -> None:
    setup_dataset()
    pbase = f"/api/projects/{PROJ}/augmentation/presets"

    # builtin 一覧
    r = client.get(pbase)
    check("list 200", r.status_code == 200)
    names = {p["name"]: p for p in r.json()["presets"]}
    check("4 builtins", {"none", "light", "standard", "strong"} <= set(names))
    check("builtin flag", names["standard"]["builtin"] is True)
    check("standard params", abs(names["standard"]["params"]["mosaic"] - 1.0) < 1e-9)

    # builtin 詳細
    r = client.get(f"{pbase}/light")
    check("get builtin 200", r.status_code == 200 and r.json()["builtin"] is True)

    # 保存（ユーザープリセット）
    r = client.put(f"{pbase}/my_light", json={
        "description": "自社向け", "params": {"degrees": 3.0, "translate": 0.05, "mosaic": 0.5, "close_mosaic": 10},
    })
    check("save 200", r.status_code == 200 and r.json()["builtin"] is False)
    check("saved file", (ROOT / PROJ / "augmentation" / "presets" / "my_light.json").exists())

    # 詳細
    r = client.get(f"{pbase}/my_light")
    check("get user 200", r.status_code == 200 and r.json()["params"]["degrees"] == 3.0)

    # 範囲外 → 400
    r = client.put(f"{pbase}/bad", json={"params": {"degrees": 999.0}})
    check("degrees out of range -> 400", r.status_code == 400)
    r = client.put(f"{pbase}/bad", json={"params": {"mosaic": 2.0}})
    check("mosaic out of range -> 400", r.status_code == 400)
    r = client.put(f"{pbase}/bad", json={"params": {"close_mosaic": -1}})
    check("close_mosaic negative -> 400", r.status_code == 400)

    # builtin 同名保存 → 409
    r = client.put(f"{pbase}/standard", json={"params": {"degrees": 1.0}})
    check("overwrite builtin -> 409", r.status_code == 409)

    # builtin 削除不可 → 400
    r = client.delete(f"{pbase}/standard")
    check("delete builtin -> 400", r.status_code == 400)

    # 存在しないプリセット → 404
    r = client.get(f"{pbase}/no_such")
    check("missing preset -> 404", r.status_code == 404)

    # ユーザープリセット削除
    r = client.delete(f"{pbase}/my_light")
    check("delete user 200", r.status_code == 200)
    r = client.get(f"{pbase}/my_light")
    check("deleted -> 404", r.status_code == 404)

    # --- 学習ジョブで augmentation_preset 指定 ---
    tbase = f"/api/projects/{PROJ}/train-jobs"
    r = client.post(tbase, json={
        "dataset_name": "ds1", "job_name": "train_aug", "epochs": 1,
        "augmentation_preset": "light",
        "augmentation_params": {"degrees": 7.0},  # 一部上書き
    })
    check("train start 201", r.status_code == 201)
    job_json = ROOT / PROJ / "runs" / "train" / "train_aug" / "job.json"
    saved = json.loads(job_json.read_text(encoding="utf-8"))
    check("job preset saved", saved["augmentation_preset"] == "light")
    check("job params full (14keys)", len(saved["augmentation_params"]) == 14)
    check("override applied", saved["augmentation_params"]["degrees"] == 7.0)
    check("preset value kept", abs(saved["augmentation_params"]["mosaic"] - 0.5) < 1e-9)

    # 未指定 → standard
    r = client.post(tbase, json={"dataset_name": "ds1", "job_name": "train_def", "epochs": 1})
    check("train default 201", r.status_code == 201)
    s2 = json.loads((ROOT / PROJ / "runs" / "train" / "train_def" / "job.json").read_text(encoding="utf-8"))
    check("default preset standard", s2["augmentation_preset"] == "standard")

    # 不正プリセット名指定 → 400
    r = client.post(tbase, json={"dataset_name": "ds1", "job_name": "train_bad", "epochs": 1,
                                 "augmentation_preset": "no_such_preset"})
    check("unknown preset -> 400", r.status_code == 400)

    # dry-run worker 完了待ち（augmentation_params を読めること＝落ちないこと）
    final = "?"
    for _ in range(30):
        time.sleep(0.2)
        final = json.loads(job_json.read_text(encoding="utf-8"))["status"]
        if final in {"completed", "failed"}:
            break
    check("dry-run completed with aug", final == "completed")

    # experiment / model API が augmentation_preset を返す & 落ちない
    r = client.get(f"/api/projects/{PROJ}/experiments")
    exps = {e["experiment_id"]: e for e in r.json()["experiments"]}
    check("experiment has preset", exps["train_aug"]["augmentation_preset"] == "light")

    # best.pt を作って model 一覧（augmentation反映）
    (ROOT / PROJ / "runs" / "train" / "train_aug" / "weights").mkdir(parents=True, exist_ok=True)
    (ROOT / PROJ / "runs" / "train" / "train_aug" / "weights" / "best.pt").write_bytes(b"x")
    r = client.get(f"/api/projects/{PROJ}/models")
    ms = {m["model_id"]: m for m in r.json()["models"]}
    check("model has preset", ms["train_aug:best"]["augmentation_preset"] == "light")

    # 既存job.jsonにaugmentationが無くても落ちない
    legacy = ROOT / PROJ / "runs" / "train" / "train_legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "job.json").write_text(json.dumps({"job_id": "train_legacy", "status": "completed"}), encoding="utf-8")
    r = client.get(f"/api/projects/{PROJ}/experiments")
    check("legacy experiment ok", r.status_code == 200)
    r = client.get(f"/api/projects/{PROJ}/models")
    check("legacy model ok", r.status_code == 200)

    print("\nALL AUGMENTATION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
