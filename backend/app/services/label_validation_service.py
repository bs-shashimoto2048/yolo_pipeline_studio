"""ラベル品質チェック。

プロジェクト内の画像とYOLOラベルを走査し、学習前に必要な検証を行う。

- error: 学習に致命的な不整合（孤立ラベル・列数不正・class_id不正・座標異常・
  範囲外bbox など）
- warning: 修正候補（未ラベル画像・空ラベル・極端なサイズ・重複bbox・クラス
  偏り など）

画像サイズ取得や一覧は image_service を、クラス定義は class_service を再利用する。
パスはすべて pathlib で組み立てる。
"""

from __future__ import annotations

from pathlib import Path

from ..core import paths
from ..schemas.label_validation import (
    ClassStat,
    LabelIssue,
    LabelValidationResponse,
    ValidationSummary,
)
from . import class_service, image_service, project_service
from .project_service import ProjectError, project_exists

# 判定しきい値（task.md の初期値）
SMALL_AREA_RATIO = 0.0001  # これ未満で極端に小さいbbox / polygon
LARGE_AREA_RATIO = 0.9  # これ超で極端に大きいbbox
DUPLICATE_IOU = 0.95  # 同一class_idでこのIoU以上は重複
IMBALANCE_RATIO = 10  # クラス間件数の最大/最小がこの倍率超で偏り警告
_EPS = 1e-9


def _polygon_area(coords: list[float]) -> float:
    """正規化座標の平坦リスト [x1,y1,x2,y2,...] から Shoelace で面積を返す。"""
    xs = coords[0::2]
    ys = coords[1::2]
    n = len(xs)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(area) / 2.0


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """YOLO正規化（中心,幅高さ）形式2つのIoU。"""
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def validate_labels(name: str) -> LabelValidationResponse:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")

    if project_service.get_task(name) == "segment":
        return _validate_segment_labels(name)

    images = image_service.list_images(name)
    classes = class_service.get_classes(name)
    class_ids = {c.id for c in classes}
    labels_dir = paths.labels_dir(name)
    proj_dir = paths.project_dir(name)

    issues: list[LabelIssue] = []
    bbox_count: dict[int, int] = {c.id: 0 for c in classes}
    img_with_class: dict[int, set[str]] = {c.id: set() for c in classes}

    total_bbox = 0
    annotated = 0
    empty_label = 0
    missing = 0

    image_by_stem = {Path(im.filename).stem: im for im in images}

    # --- 画像ごとの検査 ---
    for stem, im in image_by_stem.items():
        label_path = labels_dir / f"{stem}.txt"
        rel = label_path.relative_to(proj_dir).as_posix()

        if not label_path.exists():
            missing += 1
            issues.append(
                LabelIssue(
                    severity="warning",
                    type="missing_label",
                    image_id=stem,
                    image_name=im.filename,
                    message="画像に対応するラベルファイルがありません",
                )
            )
            continue

        # utf-8-sig: 外部ツール由来のBOM付きファイルでも先頭BOMを除去して読む
        lines = label_path.read_text(encoding="utf-8-sig").splitlines()
        content = [(i + 1, ln) for i, ln in enumerate(lines) if ln.strip()]

        if not content:
            empty_label += 1
            issues.append(
                LabelIssue(
                    severity="warning",
                    type="empty_label",
                    image_id=stem,
                    image_name=im.filename,
                    label_path=rel,
                    message="空ラベル（対象物なし画像）です",
                )
            )
            continue

        annotated += 1
        boxes_for_dup: list[tuple[int, float, float, float, float, int]] = []

        for line_no, line in content:
            parts = line.split()

            def add(sev: str, typ: str, msg: str) -> None:
                issues.append(
                    LabelIssue(
                        severity=sev,
                        type=typ,
                        image_id=stem,
                        image_name=im.filename,
                        label_path=rel,
                        line_number=line_no,
                        message=msg,
                    )
                )

            if len(parts) != 5:
                add("error", "invalid_column_count",
                    f"YOLO形式の列数が不正です（{len(parts)}列、5列が必要）")
                continue

            total_bbox += 1

            # class_id（整数のみ許可）
            cid: int | None = None
            try:
                cid = int(parts[0])
            except ValueError:
                add("error", "class_id_not_integer",
                    f"class_id が整数ではありません: '{parts[0]}'")

            # 座標（数値）
            nums: list[float] = []
            numeric_ok = True
            for idx, field in zip(
                range(1, 5), ("x_center", "y_center", "width", "height")
            ):
                try:
                    nums.append(float(parts[idx]))
                except ValueError:
                    numeric_ok = False
                    add("error", "coord_not_numeric",
                        f"{field} が数値ではありません: '{parts[idx]}'")

            if cid is not None and cid not in class_ids:
                add("error", "class_id_not_found",
                    f"class_id={cid} は classes.yaml に存在しません")

            if not numeric_ok:
                continue

            xc, yc, w, h = nums

            if any(not (0.0 <= v <= 1.0) for v in nums):
                add("error", "coord_out_of_range",
                    "x_center/y_center/width/height が 0〜1 の範囲外です")

            if w <= 0 or h <= 0:
                add("error", "non_positive_size",
                    "width/height が 0 以下です")
            else:
                if (
                    xc - w / 2 < -_EPS
                    or xc + w / 2 > 1 + _EPS
                    or yc - h / 2 < -_EPS
                    or yc + h / 2 > 1 + _EPS
                ):
                    add("error", "bbox_out_of_image", "bbox が画像範囲外です")

                area = w * h
                if area < SMALL_AREA_RATIO:
                    add("warning", "small_bbox", "極端に小さいbboxがあります")
                elif area > LARGE_AREA_RATIO:
                    add("warning", "large_bbox", "極端に大きいbboxがあります")

            if cid is not None and cid in class_ids:
                bbox_count[cid] += 1
                img_with_class[cid].add(stem)
                if numeric_ok and w > 0 and h > 0:
                    boxes_for_dup.append((cid, xc, yc, w, h, line_no))

        # 同一画像内の重複bbox（同一class_id かつ IoU>=0.95）
        for i in range(len(boxes_for_dup)):
            for j in range(i + 1, len(boxes_for_dup)):
                bi, bj = boxes_for_dup[i], boxes_for_dup[j]
                if bi[0] == bj[0] and _iou(bi[1:5], bj[1:5]) >= DUPLICATE_IOU:
                    issues.append(
                        LabelIssue(
                            severity="warning",
                            type="duplicate_bbox",
                            image_id=stem,
                            image_name=im.filename,
                            label_path=rel,
                            line_number=bj[5],
                            message=f"重複bboxの可能性があります（{bi[5]}行目と重複）",
                        )
                    )

    # --- 孤立ラベル（ラベルあり・画像なし）と総ラベル数 ---
    label_file_count = 0
    orphan = 0
    if labels_dir.exists():
        for lp in sorted(labels_dir.glob("*.txt")):
            label_file_count += 1
            if lp.stem not in image_by_stem:
                orphan += 1
                issues.append(
                    LabelIssue(
                        severity="error",
                        type="orphan_label",
                        image_id=lp.stem,
                        label_path=lp.relative_to(proj_dir).as_posix(),
                        message="ラベルに対応する画像がありません",
                    )
                )

    # --- クラス別統計 + 偏り警告 ---
    class_stats: list[ClassStat] = []
    for c in classes:
        cnt = bbox_count[c.id]
        class_stats.append(
            ClassStat(
                class_id=c.id,
                class_name=c.name,
                bbox_count=cnt,
                image_count=len(img_with_class[c.id]),
            )
        )
        if cnt == 0:
            issues.append(
                LabelIssue(
                    severity="warning",
                    type="class_zero_count",
                    message=f"クラス '{c.name}'(id={c.id}) のbboxが0件です",
                )
            )

    nonzero = [s.bbox_count for s in class_stats if s.bbox_count > 0]
    if len(nonzero) >= 2 and max(nonzero) > IMBALANCE_RATIO * min(nonzero):
        issues.append(
            LabelIssue(
                severity="warning",
                type="class_imbalance",
                message=(
                    f"クラス間でbbox件数の偏りがあります"
                    f"（最大{max(nonzero)} / 最小{min(nonzero)}）"
                ),
            )
        )

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")

    summary = ValidationSummary(
        image_count=len(images),
        label_file_count=label_file_count,
        annotated_image_count=annotated,
        empty_label_image_count=empty_label,
        missing_label_count=missing,
        orphan_label_count=orphan,
        total_bbox_count=total_bbox,
        error_count=error_count,
        warning_count=warning_count,
    )

    return LabelValidationResponse(
        project_name=name,
        summary=summary,
        class_stats=class_stats,
        issues=issues,
    )


def _validate_segment_labels(name: str) -> LabelValidationResponse:
    """segment（YOLO polygon）ラベルの品質チェック。"""
    images = image_service.list_images(name)
    classes = class_service.get_classes(name)
    class_ids = {c.id for c in classes}
    labels_dir = paths.labels_dir(name)
    proj_dir = paths.project_dir(name)

    issues: list[LabelIssue] = []
    poly_count: dict[int, int] = {c.id: 0 for c in classes}
    img_with_class: dict[int, set[str]] = {c.id: set() for c in classes}

    total_poly = 0
    annotated = 0
    empty_label = 0
    missing = 0

    image_by_stem = {Path(im.filename).stem: im for im in images}

    for stem, im in image_by_stem.items():
        label_path = labels_dir / f"{stem}.txt"
        rel = label_path.relative_to(proj_dir).as_posix()

        if not label_path.exists():
            missing += 1
            issues.append(LabelIssue(
                severity="warning", type="missing_label", image_id=stem,
                image_name=im.filename,
                message="画像に対応するラベルファイルがありません",
            ))
            continue

        lines = label_path.read_text(encoding="utf-8-sig").splitlines()
        content = [(i + 1, ln) for i, ln in enumerate(lines) if ln.strip()]
        if not content:
            empty_label += 1
            issues.append(LabelIssue(
                severity="warning", type="empty_label", image_id=stem,
                image_name=im.filename, label_path=rel,
                message="空ラベル（対象物なし画像）です",
            ))
            continue

        annotated += 1
        for line_no, line in content:
            parts = line.split()

            def add(sev: str, typ: str, msg: str) -> None:
                issues.append(LabelIssue(
                    severity=sev, type=typ, image_id=stem, image_name=im.filename,
                    label_path=rel, line_number=line_no, message=msg,
                ))

            if len(parts) < 3:
                add("error", "invalid_column_count",
                    f"列数が不足しています（{len(parts)}列、class_id + 座標が必要）")
                continue

            total_poly += 1

            cid: int | None = None
            try:
                cid = int(parts[0])
            except ValueError:
                add("error", "class_id_not_integer",
                    f"class_id が整数ではありません: '{parts[0]}'")

            coord_tokens = parts[1:]
            coords: list[float] = []
            numeric_ok = True
            for tok in coord_tokens:
                try:
                    coords.append(float(tok))
                except ValueError:
                    numeric_ok = False
            if not numeric_ok:
                add("error", "coord_not_numeric", "座標に数値でない値があります")

            if len(coord_tokens) % 2 != 0:
                add("error", "odd_coord_count", "座標数が奇数です（x,yの対で指定してください）")

            n_points = len(coord_tokens) // 2
            if n_points < 3:
                add("error", "too_few_points",
                    f"polygon は3点以上必要です（現在 {n_points}点）")

            if cid is not None and cid not in class_ids:
                add("error", "class_id_not_found",
                    f"class_id={cid} は classes.yaml に存在しません")

            if numeric_ok and any(not (0.0 <= v <= 1.0) for v in coords):
                add("error", "coord_out_of_range", "座標が 0〜1 の範囲外です")

            if numeric_ok and len(coords) % 2 == 0 and n_points >= 3:
                area = _polygon_area(coords)
                if area < SMALL_AREA_RATIO:
                    add("warning", "small_polygon", "極端に小さいpolygonがあります")

            if cid is not None and cid in class_ids and n_points >= 3:
                poly_count[cid] += 1
                img_with_class[cid].add(stem)

    # 孤立ラベル
    label_file_count = 0
    orphan = 0
    if labels_dir.exists():
        for lp in sorted(labels_dir.glob("*.txt")):
            label_file_count += 1
            if lp.stem not in image_by_stem:
                orphan += 1
                issues.append(LabelIssue(
                    severity="error", type="orphan_label", image_id=lp.stem,
                    label_path=lp.relative_to(proj_dir).as_posix(),
                    message="ラベルに対応する画像がありません",
                ))

    # クラス別統計 + 偏り
    class_stats: list[ClassStat] = []
    for c in classes:
        cnt = poly_count[c.id]
        class_stats.append(ClassStat(
            class_id=c.id, class_name=c.name,
            bbox_count=cnt, image_count=len(img_with_class[c.id]),
        ))
        if cnt == 0:
            issues.append(LabelIssue(
                severity="warning", type="class_zero_count",
                message=f"クラス '{c.name}'(id={c.id}) のpolygonが0件です",
            ))

    nonzero = [s.bbox_count for s in class_stats if s.bbox_count > 0]
    if len(nonzero) >= 2 and max(nonzero) > IMBALANCE_RATIO * min(nonzero):
        issues.append(LabelIssue(
            severity="warning", type="class_imbalance",
            message=(f"クラス間でpolygon件数の偏りがあります"
                     f"（最大{max(nonzero)} / 最小{min(nonzero)}）"),
        ))

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")

    summary = ValidationSummary(
        image_count=len(images),
        label_file_count=label_file_count,
        annotated_image_count=annotated,
        empty_label_image_count=empty_label,
        missing_label_count=missing,
        orphan_label_count=orphan,
        total_bbox_count=total_poly,
        error_count=error_count,
        warning_count=warning_count,
    )

    return LabelValidationResponse(
        project_name=name,
        summary=summary,
        class_stats=class_stats,
        issues=issues,
    )
