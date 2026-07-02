"""データセット作成APIのスモークテスト（Issue 004）。

一時ディレクトリを案件ルートにして実行するので、実データには影響しない。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_dataset_builder.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="yts_dataset_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PROJ = "ds_proj"
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


def ds_path(*parts: str) -> Path:
    return ROOT / PROJ / "datasets" / Path(*parts)


def main() -> None:
    client.post("/api/projects", json={"name": PROJ})
    client.put(f"/api/projects/{PROJ}/classes", json={"names": ["ct_h", "ct_l"]})

    # ラベル付き画像 10枚
    for i in range(10):
        stem = f"img_{i:02d}"
        make_image(stem)
        cid = i % 2
        write_label(stem, f"{cid} 0.5 0.5 0.2 0.2\n")
    # 空ラベル画像 2枚
    for i in range(2):
        stem = f"empty_{i:02d}"
        make_image(stem)
        write_label(stem, "")
    # 未ラベル画像 2枚
    for i in range(2):
        make_image(f"nolabel_{i:02d}")

    base = f"/api/projects/{PROJ}/datasets"

    # --- 1) 正常作成（include_empty_labels=true, unlabeled=false 既定）---
    body = {
        "dataset_name": "dataset_001",
        "train_ratio": 0.8,
        "val_ratio": 0.2,
        "test_ratio": 0.0,
        "seed": 42,
        "include_empty_labels": True,
        "include_unlabeled_images": False,
    }
    r = client.post(base, json=body)
    check("create 201", r.status_code == 201)
    res = r.json()
    s = res["summary"]
    # 対象=ラベル付き10 + 空2 = 12（未ラベルは除外）
    check("total 12 (empty含む/unlabeled除外)", s["total_image_count"] == 12)
    check("train+val=total", s["train_image_count"] + s["val_image_count"] == 12)
    check("val>0", s["val_image_count"] > 0)
    check("class_count 2", s["class_count"] == 2)
    check("dataset_path posix", res["dataset_path"] == "datasets/dataset_001")
    check("data_yaml_path", res["data_yaml_path"] == "datasets/dataset_001/data.yaml")

    # --- 2) data.yaml と フォルダ生成確認 ---
    check("data.yaml exists", ds_path("dataset_001", "data.yaml").exists())
    check("images/train", ds_path("dataset_001", "images", "train").is_dir())
    check("images/val", ds_path("dataset_001", "images", "val").is_dir())
    check("labels/train", ds_path("dataset_001", "labels", "train").is_dir())
    check("labels/val", ds_path("dataset_001", "labels", "val").is_dir())

    import yaml

    dy = yaml.safe_load(ds_path("dataset_001", "data.yaml").read_text(encoding="utf-8"))
    check("yaml train path", dy["train"] == "images/train")
    check("yaml val path", dy["val"] == "images/val")
    check("yaml names", dy["names"] == {0: "ct_h", 1: "ct_l"})
    # Issue 018: path はデータセットの絶対パス(POSIX)
    check("yaml path absolute posix",
          dy["path"] == ds_path("dataset_001").resolve().as_posix())

    # --- 3) 画像とラベルの対応維持 ---
    def stems(split: str, kind: str) -> set[str]:
        d = ds_path("dataset_001", kind, split)
        return {p.stem for p in d.iterdir() if p.is_file()}

    for split in ("train", "val"):
        check(
            f"{split} image-label correspondence",
            stems(split, "images") == stems(split, "labels"),
        )

    # 元データ非破壊（raw/images と annotations/labels が残っている）
    raw_count = sum(1 for _ in (ROOT / PROJ / "raw" / "images").iterdir())
    check("raw images intact (14)", raw_count == 14)

    # --- 4) 空ラベルが含まれている（labels内に空txtが存在）---
    all_label_files = list(
        (ds_path("dataset_001", "labels", "train").glob("*.txt"))
    ) + list(ds_path("dataset_001", "labels", "val").glob("*.txt"))
    has_empty = any(p.read_text(encoding="utf-8").strip() == "" for p in all_label_files)
    check("empty label included", has_empty)

    # --- 5) ラベルなし画像は除外（empty_/img_ のみ、nolabel_ は無い）---
    img_stems = stems("train", "images") | stems("val", "images")
    check("unlabeled excluded", not any(s.startswith("nolabel_") for s in img_stems))
    check("selected stems count 12", len(img_stems) == 12)

    # --- 6) overwrite=false 同名 → 409 ---
    r = client.post(base, json=body)
    check("duplicate 409", r.status_code == 409)

    # --- 7) overwrite=true → 再作成 ---
    r = client.post(base, json={**body, "overwrite": True})
    check("overwrite 201", r.status_code == 201)

    # --- 8) seed固定で分割再現 ---
    train_a = stems("train", "images")
    client.post(base, json={**body, "overwrite": True})
    train_b = stems("train", "images")
    check("seed reproducible split", train_a == train_b)

    # --- 9) error_count>0 で 400（不正ラベルを追加）---
    make_image("bad_img")
    write_label("bad_img", "9 0.5 0.5 0.2 0.2\n")  # class_id 9 は未定義 → error
    r = client.post(base, json={**body, "dataset_name": "dataset_bad"})
    check("error_count>0 -> 400", r.status_code == 400)

    # --- 10) 一覧取得 ---
    r = client.get(base)
    check("list 200", r.status_code == 200)
    lst = r.json()
    check("list has dataset_001", any(d["dataset_name"] == "dataset_001" for d in lst["datasets"]))
    d0 = next(d for d in lst["datasets"] if d["dataset_name"] == "dataset_001")
    check("list created_at present", bool(d0["created_at"]))
    check("list counts", d0["train_image_count"] + d0["val_image_count"] == 12)

    print("\nALL DATASET BUILDER SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
