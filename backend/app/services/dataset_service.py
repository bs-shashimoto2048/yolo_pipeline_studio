"""YOLOデータセット作成。

プロジェクトの raw/images と annotations/labels、classes.yaml をもとに、
Ultralytics YOLO で学習可能なデータセット（images/labels の train/val/test 分割
＋ data.yaml）を生成する。学習やUltralyticsの導入はこのIssueでは行わない。

- 元画像・元ラベルは読むだけで、コピー先のみ書き込む（破壊しない）。
- コピーは shutil、パス組み立ては pathlib。返却する相対パスはPOSIX区切り。
"""

from __future__ import annotations

import json
import random
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from ..core import paths
from ..schemas.dataset import (
    DatasetCreate,
    DatasetCreateResponse,
    DatasetListItem,
    DatasetListResponse,
    DatasetSummary,
)
from . import (
    class_service,
    image_service,
    label_validation_service,
    project_service,
    selection_service,
)
from .project_service import ProjectError, project_exists

_RATIO_EPS = 1e-6
_SPLITS = ("train", "val", "test")


class DatasetError(Exception):
    """データセット作成の業務エラー。"""


class DatasetValidationError(DatasetError):
    """事前チェック失敗（HTTP 400相当）。"""


class DatasetConflictError(DatasetError):
    """同名データセットの衝突（HTTP 409相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _select_images(
    name: str, include_empty_labels: bool, include_unlabeled_images: bool,
    image_source: str = "auto", allowed_stems: set[str] | None = None,
) -> list[tuple[Path, Path | None]]:
    """対象画像を選別する。

    返り値: (画像パス, ラベルパス or None) のリスト。
    ラベルパスが None の画像は、コピー時に空txtを作成する（未ラベル取り込み時）。
    list_images は filename 昇順なので、選別結果も決定的な順序になる。
    image_source: auto/raw/processed（autoはprocessedがあればprocessed）。
    allowed_stems: 指定時、stemがこの集合に含まれる画像のみ対象（画像選別の反映）。
    """
    images = image_service.list_images(name, image_source)
    img_dir = paths.images_dir_for_source(name, image_source)
    labels_dir = paths.labels_dir(name)

    selected: list[tuple[Path, Path | None]] = []
    for im in images:
        if allowed_stems is not None and Path(im.filename).stem not in allowed_stems:
            continue
        img_path = img_dir / im.filename
        label_path = labels_dir / f"{Path(im.filename).stem}.txt"
        if label_path.exists():
            is_empty = label_path.read_text(encoding="utf-8-sig").strip() == ""
            if is_empty:
                if include_empty_labels:
                    selected.append((img_path, label_path))
            else:
                selected.append((img_path, label_path))
        else:
            if include_unlabeled_images:
                selected.append((img_path, None))
    return selected


def _split(
    items: list[tuple[Path, Path | None]],
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> dict[str, list[tuple[Path, Path | None]]]:
    """seed固定でシャッフルし、比率で train/val/test に分割する。"""
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)

    n = len(shuffled)
    n_test = int(n * test_ratio)
    n_val = int(n * val_ratio)
    n_train = n - n_val - n_test  # 端数は train に寄せる

    return {
        "train": shuffled[:n_train],
        "val": shuffled[n_train : n_train + n_val],
        "test": shuffled[n_train + n_val :],
    }


def create_dataset(name: str, req: DatasetCreate) -> DatasetCreateResponse:
    _require_project(name)

    if not paths.is_valid_project_name(req.dataset_name):
        raise DatasetValidationError(
            "dataset_name は英数・アンダースコア・ハイフンのみ使用できます。"
        )

    # 比率の合計チェック
    total_ratio = req.train_ratio + req.val_ratio + req.test_ratio
    if abs(total_ratio - 1.0) > _RATIO_EPS:
        raise DatasetValidationError(
            f"train/val/test の比率合計は 1.0 にしてください（現在 {total_ratio}）。"
        )

    # --- 事前チェック ---
    if not paths.classes_yaml(name).exists():
        raise DatasetValidationError("classes.yaml が存在しません。")
    classes = class_service.get_classes(name)
    if len(classes) == 0:
        raise DatasetValidationError("クラスが定義されていません。")

    report = label_validation_service.validate_labels(name)
    if report.summary.error_count > 0:
        raise DatasetValidationError(
            f"ラベル品質チェックで error が {report.summary.error_count} 件あります。"
            "先に修正してください。"
        )

    # 画像選別（selection.json）の反映
    allowed_stems = None
    selection_warning = None
    if req.use_selection:
        allowed_stems, selection_warning = selection_service.load_allowed_stems(
            name, req.include_review_images
        )

    selected = _select_images(
        name, req.include_empty_labels, req.include_unlabeled_images,
        req.image_source, allowed_stems,
    )
    if len(selected) == 0:
        raise DatasetValidationError("対象画像が0枚です。")

    # 解決された実ソース（auto→raw/processed）
    resolved_dir = paths.images_dir_for_source(name, req.image_source)
    used_source = "processed" if resolved_dir == paths.processed_images_dir(name) else "raw"
    warning = None
    if used_source == "processed" and paths.labels_dir(name).exists() and any(
        paths.labels_dir(name).glob("*.txt")
    ):
        warning = (
            "processed画像を使用しています。raw画像に対してアノテーション済みの場合、"
            "前処理で見た目やサイズが変わっているとラベルがズレる可能性があります。"
        )
    # 選別未実行/破損の警告を結合
    if selection_warning:
        warning = f"{warning} {selection_warning}" if warning else selection_warning

    splits = _split(
        selected, req.train_ratio, req.val_ratio, req.test_ratio, req.seed
    )
    if len(splits["val"]) == 0:
        raise DatasetValidationError(
            "val画像数が0です。val_ratio または画像枚数を見直してください。"
        )

    # --- overwrite 制御 ---
    ds_dir = paths.dataset_dir(name, req.dataset_name)
    if ds_dir.exists():
        if not req.overwrite:
            raise DatasetConflictError(
                f"データセット '{req.dataset_name}' は既に存在します。"
            )
        shutil.rmtree(ds_dir)

    # --- フォルダ作成 + コピー ---
    for split in _SPLITS:
        (ds_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (ds_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    for split in _SPLITS:
        img_out = ds_dir / "images" / split
        lbl_out = ds_dir / "labels" / split
        for img_path, label_path in splits[split]:
            shutil.copy2(img_path, img_out / img_path.name)
            target_label = lbl_out / f"{img_path.stem}.txt"
            if label_path is not None:
                shutil.copy2(label_path, target_label)
            else:
                # 未ラベル取り込み時は空txtを作成
                target_label.write_text("", encoding="utf-8")

    # --- data.yaml 生成 ---
    # path はデータセットの絶対パス（POSIX）。Ultralyticsは相対pathを datasets_dir
    # 設定基準で解決してしまうため、絶対パスにして確実に images/labels を参照させる。
    data_yaml = {
        "path": ds_dir.resolve().as_posix(),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {c.id: c.name for c in classes},
    }
    with (ds_dir / "data.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml, f, allow_unicode=True, sort_keys=False)

    summary = DatasetSummary(
        train_image_count=len(splits["train"]),
        val_image_count=len(splits["val"]),
        test_image_count=len(splits["test"]),
        total_image_count=len(selected),
        class_count=len(classes),
    )

    # --- メタデータ保存 ---
    task = project_service.get_task(name)
    metadata = {
        "dataset_name": req.dataset_name,
        "task": task,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "seed": req.seed,
        "train_ratio": req.train_ratio,
        "val_ratio": req.val_ratio,
        "test_ratio": req.test_ratio,
        "include_empty_labels": req.include_empty_labels,
        "include_unlabeled_images": req.include_unlabeled_images,
        "image_source": used_source,
        "summary": summary.model_dump(),
    }
    with (ds_dir / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    rel_dir = ds_dir.relative_to(paths.project_dir(name)).as_posix()
    return DatasetCreateResponse(
        project_name=name,
        dataset_name=req.dataset_name,
        dataset_path=rel_dir,
        summary=summary,
        data_yaml_path=f"{rel_dir}/data.yaml",
        image_source=used_source,
        task=task,
        warning=warning,
    )


def list_datasets(name: str) -> DatasetListResponse:
    _require_project(name)
    root = paths.datasets_dir(name)
    items: list[DatasetListItem] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            meta_path = child / "metadata.json"
            rel_dir = child.relative_to(paths.project_dir(name)).as_posix()
            meta: dict = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            summary = meta.get("summary", {}) or {}
            items.append(
                DatasetListItem(
                    dataset_name=meta.get("dataset_name", child.name),
                    dataset_path=rel_dir,
                    created_at=meta.get("created_at"),
                    train_image_count=summary.get("train_image_count", 0),
                    val_image_count=summary.get("val_image_count", 0),
                    test_image_count=summary.get("test_image_count", 0),
                    class_count=summary.get("class_count", 0),
                    task=meta.get("task", "detect"),
                    data_yaml_path=f"{rel_dir}/data.yaml",
                )
            )
    return DatasetListResponse(project_name=name, datasets=items)
