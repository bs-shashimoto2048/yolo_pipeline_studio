"""アノテーション（YOLOラベル）の保存・読込。

- 保存先: ``annotations/labels/{image_stem}.txt``
- detect: ``class_id x_center y_center width height``（0〜1 正規化）
- segment: ``class_id x1 y1 x2 y2 ...``（0〜1 正規化、3点以上）
- 空配列も保存可能（ネガティブ画像用に空txtを作成）

プロジェクトの task（detect/segment）に応じて形式を切り替える。1プロジェクトは
どちらか一方に固定され、bboxとpolygonを混在させない。
パスはすべて pathlib で組み立て、OS依存の文字列を直書きしない。
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..core import paths
from ..core.config import settings
from ..schemas.annotation import AnnotationItem, PolygonItem, PolygonPoint
from . import project_service
from .class_service import get_classes
from .project_service import ProjectError, project_exists


class AnnotationError(Exception):
    """アノテーション操作の業務エラー。"""


class AnnotationValidationError(AnnotationError):
    """保存データのバリデーションエラー（HTTP 400相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def resolve_image(name: str, image_id: str) -> Path:
    """image_id（拡張子なしのstem）から実画像ファイルを解決する。

    image_id に拡張子が含まれていた場合も stem として扱う。
    """
    img_dir = paths.raw_images_dir(name)
    if not img_dir.exists():
        raise AnnotationError(f"画像 '{image_id}' が見つかりません。")

    stem = Path(image_id).stem
    # パストラバーサル防止: stem にパス区切りが含まれていたら拒否
    if stem != Path(stem).name or stem in ("", ".", ".."):
        raise AnnotationError("不正な image_id です。")

    for suffix in settings.allowed_image_suffixes:
        candidate = img_dir / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    # 大文字拡張子などに備えて走査でフォールバック
    for p in img_dir.iterdir():
        if p.is_file() and p.stem == stem:
            return p
    raise AnnotationError(f"画像 '{image_id}' が見つかりません。")


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(path.read_bytes())) as im:
            return im.size  # (width, height)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise AnnotationError(f"画像を読み込めません: {path.name}") from e


def _label_path(name: str, stem: str) -> Path:
    return paths.labels_dir(name) / f"{stem}.txt"


def get_annotations(name: str, image_id: str) -> dict:
    """画像のアノテーションを取得する（ラベル未作成なら空配列）。"""
    _require_project(name)
    task = project_service.get_task(name)
    img_path = resolve_image(name, image_id)
    stem = img_path.stem
    width, height = _image_size(img_path)

    annotations: list[dict[str, Any]] = []
    label_path = _label_path(name, stem)
    if label_path.exists():
        if task == "segment":
            annotations = [p.model_dump() for p in _parse_segment_file(label_path)]
        else:
            annotations = [b.model_dump() for b in _parse_bbox_file(label_path)]

    return {
        "image_id": stem,
        "image_name": img_path.name,
        "image_width": width,
        "image_height": height,
        "task": task,
        "annotations": annotations,
    }


# --- 読込（寛容に。壊れた行はスキップ） ---
def _parse_bbox_file(path: Path) -> list[AnnotationItem]:
    items: list[AnnotationItem] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            items.append(
                AnnotationItem(
                    class_id=int(parts[0]),
                    x_center=float(parts[1]),
                    y_center=float(parts[2]),
                    width=float(parts[3]),
                    height=float(parts[4]),
                )
            )
        except ValueError:
            continue
    return items


def _parse_segment_file(path: Path) -> list[PolygonItem]:
    items: list[PolygonItem] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        # class_id + 座標偶数（最低3点=6座標）
        if len(parts) < 7 or (len(parts) - 1) % 2 != 0:
            continue
        try:
            cid = int(parts[0])
            coords = [float(v) for v in parts[1:]]
        except ValueError:
            continue
        pts = [
            PolygonPoint(x=coords[i], y=coords[i + 1])
            for i in range(0, len(coords), 2)
        ]
        if len(pts) < 3:
            continue
        items.append(PolygonItem(class_id=cid, points=pts, source="manual"))
    return items


# --- detect（bbox）の保存 ---
def _validate_bbox(name: str, annotations: list[AnnotationItem]) -> None:
    valid_ids = {c.id for c in get_classes(name)}
    for i, a in enumerate(annotations):
        prefix = f"annotations[{i}]: "
        if a.class_id not in valid_ids:
            raise AnnotationValidationError(
                f"{prefix}class_id={a.class_id} は classes.yaml に存在しません。"
            )
        for field in ("x_center", "y_center", "width", "height"):
            v = getattr(a, field)
            if not (0.0 <= v <= 1.0):
                raise AnnotationValidationError(
                    f"{prefix}{field}={v} が範囲外です（0〜1）。"
                )
        if a.width <= 0 or a.height <= 0:
            raise AnnotationValidationError(
                f"{prefix}width / height は 0 より大きくしてください。"
            )
        if (
            a.x_center - a.width / 2 < -1e-9
            or a.x_center + a.width / 2 > 1 + 1e-9
            or a.y_center - a.height / 2 < -1e-9
            or a.y_center + a.height / 2 > 1 + 1e-9
        ):
            raise AnnotationValidationError(f"{prefix}bbox が画像範囲外です。")


def _coerce_bbox_items(raw: list[dict[str, Any]]) -> list[AnnotationItem]:
    items: list[AnnotationItem] = []
    for i, d in enumerate(raw):
        try:
            items.append(AnnotationItem(**{k: d[k] for k in (
                "class_id", "x_center", "y_center", "width", "height"
            )}))
        except (KeyError, TypeError, ValueError) as e:
            raise AnnotationValidationError(
                f"annotations[{i}]: bbox形式が不正です（class_id/x_center/y_center/width/height が必要）。"
            ) from e
    return items


# --- segment（polygon）の保存 ---
def _validate_polygons(name: str, polygons: list[PolygonItem]) -> None:
    valid_ids = {c.id for c in get_classes(name)}
    for i, p in enumerate(polygons):
        prefix = f"annotations[{i}]: "
        if p.class_id not in valid_ids:
            raise AnnotationValidationError(
                f"{prefix}class_id={p.class_id} は classes.yaml に存在しません。"
            )
        if len(p.points) < 3:
            raise AnnotationValidationError(
                f"{prefix}polygon は3点以上必要です（現在 {len(p.points)}点）。"
            )
        for pt in p.points:
            for axis, v in (("x", pt.x), ("y", pt.y)):
                if math.isnan(v) or math.isinf(v):
                    raise AnnotationValidationError(
                        f"{prefix}座標に NaN / inf は指定できません。"
                    )
                if not (0.0 <= v <= 1.0):
                    raise AnnotationValidationError(
                        f"{prefix}{axis}={v} が範囲外です（0〜1）。"
                    )


def _coerce_polygon_items(raw: list[dict[str, Any]]) -> list[PolygonItem]:
    items: list[PolygonItem] = []
    for i, d in enumerate(raw):
        try:
            items.append(PolygonItem(**d))
        except (TypeError, ValueError) as e:
            raise AnnotationValidationError(
                f"annotations[{i}]: polygon形式が不正です（class_id/points が必要）。"
            ) from e
    return items


def _write_label(name: str, stem: str, lines: list[str]) -> str:
    label_dir = paths.labels_dir(name)
    label_dir.mkdir(parents=True, exist_ok=True)
    label_path = _label_path(name, stem)
    content = "\n".join(lines) + ("\n" if lines else "")
    label_path.write_text(content, encoding="utf-8")
    return label_path.relative_to(paths.project_dir(name)).as_posix()


def save_annotations(
    name: str, image_id: str, annotations: list[dict[str, Any]]
) -> dict:
    """アノテーションをYOLO txt形式で保存する。空配列も空txtとして保存。"""
    _require_project(name)
    task = project_service.get_task(name)
    img_path = resolve_image(name, image_id)
    stem = img_path.stem

    if task == "segment":
        polygons = _coerce_polygon_items(annotations)
        _validate_polygons(name, polygons)
        lines = [
            f"{p.class_id} "
            + " ".join(f"{c:.6f}" for pt in p.points for c in (pt.x, pt.y))
            for p in polygons
        ]
        rel = _write_label(name, stem, lines)
        return {
            "status": "saved",
            "label_path": rel,
            "annotation_count": len(polygons),
            "task": task,
        }

    # detect（bbox）
    bboxes = _coerce_bbox_items(annotations)
    _validate_bbox(name, bboxes)
    lines = [
        f"{a.class_id} {a.x_center:.6f} {a.y_center:.6f} "
        f"{a.width:.6f} {a.height:.6f}"
        for a in bboxes
    ]
    rel = _write_label(name, stem, lines)
    return {
        "status": "saved",
        "label_path": rel,
        "annotation_count": len(bboxes),
        "task": task,
    }
