"""画像選別。

低品質（小サイズ・暗/明・ブレ）・重複を自動検出して status（included/review）を
selection.json に保存する。自動検出はマーキングのみ（非破壊）で、実際に画像を
取り除きたい場合は `delete_image()` による明示的な削除操作が必要（元に戻せない）。

OpenCV/NumPy は使わず Pillow のみ。ブレはグレースケールの FIND_EDGES 後の
画素分散（ヒストグラムから算出）で近似する。
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from ..core import paths
from ..core.config import settings
from ..schemas.selection import (
    SelectionDeleteResponse,
    SelectionGetResponse,
    SelectionItem,
    SelectionRotateResponse,
    SelectionRunRequest,
    SelectionRunResponse,
    SelectionStatusResponse,
    SelectionStatusUpdate,
    SelectionSummary,
)
from .project_service import ProjectError, project_exists

_VALID_STATUS = {"included", "review"}


class SelectionError(Exception):
    pass


class SelectionNotFoundError(SelectionError):
    """404相当。"""


class SelectionValidationError(SelectionError):
    """400相当。"""


class SelectionConflictError(SelectionError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _hist_stats(hist: list[int]) -> tuple[float, float]:
    """ヒストグラム(256)から (mean, variance) を返す。"""
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
    return mean, var


def _analyze_image(data: bytes) -> tuple[int, int, float, float]:
    """(width, height, brightness_mean, blur_score) を返す。"""
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        gray = im.convert("L")
    brightness_mean, _ = _hist_stats(gray.histogram())
    edges = gray.filter(ImageFilter.FIND_EDGES)
    # FIND_EDGES は画像端で偽のエッジ（高値）を出すため、内側のみで分散を測る
    ew, eh = edges.size
    if ew > 4 and eh > 4:
        edges = edges.crop((2, 2, ew - 2, eh - 2))
    _, blur_score = _hist_stats(edges.histogram())
    return w, h, round(brightness_mean, 2), round(blur_score, 2)


def run(name: str, req: SelectionRunRequest) -> SelectionRunResponse:
    _require_project(name)

    path = paths.selection_path(name)
    if path.exists() and not req.overwrite:
        raise SelectionConflictError(
            "selection.json が既に存在します。overwrite=true で再実行してください。"
        )

    img_dir = paths.images_dir_for_source(name, req.source)
    used_source = "processed" if img_dir == paths.processed_images_dir(name) else "raw"

    files = sorted(
        p for p in img_dir.iterdir()
        if p.is_file() and p.suffix.lower() in settings.allowed_image_suffixes
    ) if img_dir.exists() else []

    items: list[SelectionItem] = []
    hash_first: dict[str, str] = {}  # hash -> 最初の image_id

    for p in files:
        try:
            data = p.read_bytes()
            w, h, brightness, blur = _analyze_image(data)
        except (UnidentifiedImageError, OSError, ValueError):
            continue
        digest = hashlib.sha1(data).hexdigest()
        image_id = p.stem

        warnings: list[str] = []
        reasons: list[str] = []
        duplicate_of: str | None = None

        if w < req.min_width or h < req.min_height:
            warnings.append("small_image")
            reasons.append("画像サイズが小さすぎます")
        if brightness < req.dark_threshold:
            warnings.append("dark_image")
            reasons.append("画像が暗すぎます")
        if brightness > req.bright_threshold:
            warnings.append("bright_image")
            reasons.append("画像が明るすぎます")
        if blur < req.blur_threshold:
            warnings.append("blur_image")
            reasons.append("画像がブレている可能性があります")
        if req.detect_duplicates:
            if digest in hash_first:
                duplicate_of = hash_first[digest]
                warnings.append("duplicate_image")
                reasons.append("重複画像です")
            else:
                hash_first[digest] = image_id

        # status: 警告（重複含む）があれば review（要確認）、無ければ included。
        # 自動検出だけで削除まではしない（削除は利用者が個別に確認して行う破壊的操作）。
        status = "review" if warnings else "included"

        items.append(SelectionItem(
            image_id=image_id, image_name=p.name, source=used_source,
            width=w, height=h, status=status, warnings=warnings, reasons=reasons,
            hash=digest, brightness_mean=brightness, blur_score=blur,
            duplicate_of=duplicate_of,
        ))

    summary = _summarize(items)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": used_source,
        "settings": {
            "min_width": req.min_width, "min_height": req.min_height,
            "blur_threshold": req.blur_threshold, "dark_threshold": req.dark_threshold,
            "bright_threshold": req.bright_threshold, "duplicate_hash": req.detect_duplicates,
        },
        "summary": summary.model_dump(),
        "items": [it.model_dump() for it in items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return SelectionRunResponse(
        project_name=name, source=used_source, summary=summary,
        selection_path="selection/selection.json",
    )


def _summarize(items: list[SelectionItem]) -> SelectionSummary:
    def warned(w: str) -> int:
        return sum(1 for it in items if w in it.warnings)

    return SelectionSummary(
        image_count=len(items),
        included_count=sum(1 for it in items if it.status == "included"),
        excluded_count=sum(1 for it in items if it.status == "excluded"),
        review_count=sum(1 for it in items if it.status == "review"),
        duplicate_count=warned("duplicate_image"),
        small_count=warned("small_image"),
        dark_count=warned("dark_image"),
        bright_count=warned("bright_image"),
        blur_count=warned("blur_image"),
    )


def _load(name: str) -> dict:
    path = paths.selection_path(name)
    if not path.exists():
        raise SelectionNotFoundError("画像選別が未実行です。")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_selection(name: str) -> SelectionGetResponse:
    _require_project(name)
    data = _load(name)
    items = [SelectionItem(**it) for it in data.get("items", [])]
    return SelectionGetResponse(
        project_name=name,
        source=data.get("source", "raw"),
        summary=_summarize(items),
        items=items,
    )


def update_status(name: str, image_id: str, upd: SelectionStatusUpdate) -> SelectionStatusResponse:
    _require_project(name)
    if upd.status not in _VALID_STATUS:
        raise SelectionValidationError("status は included/review のいずれかです（除外は削除操作に置き換えられました）。")
    data = _load(name)
    found = None
    for it in data.get("items", []):
        if it.get("image_id") == image_id:
            it["status"] = upd.status
            it["manual_reason"] = upd.manual_reason
            found = it
            break
    if found is None:
        raise SelectionNotFoundError(f"画像 '{image_id}' が選別結果にありません。")
    # summaryを再計算
    items = [SelectionItem(**it) for it in data["items"]]
    data["summary"] = _summarize(items).model_dump()
    paths.selection_path(name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return SelectionStatusResponse(
        image_id=image_id, status=upd.status, manual_reason=upd.manual_reason
    )


def rotate_image(name: str, image_id: str, source: str, angle: int) -> SelectionRotateResponse:
    """画像を回転保存する。raw と processed の両方（存在する側）に適用し、
    どの表示（選別・前処理・アノテーション）でも向きが一致するようにする。
    processed はプリ生成サムネイルも再生成する。source は無視して両方を回す。
    """
    _require_project(name)
    if angle not in (90, -90, 180):
        raise SelectionValidationError("angle は 90 / -90 / 180 のいずれかです。")

    stem = Path(image_id).stem
    if stem != Path(stem).name:
        raise SelectionValidationError("不正な image_id です。")

    rotated_sources: list[str] = []
    last_w = last_h = 0
    # raw と processed の両方を対象に、存在するファイルを回転
    for src_name in ("raw", "processed"):
        img_dir = paths.images_dir_for_source(name, src_name)
        if not img_dir.exists():
            continue
        target = None
        for p in img_dir.iterdir():
            if p.is_file() and p.stem == stem and p.suffix.lower() in settings.allowed_image_suffixes:
                target = p
                break
        if target is None:
            continue

        fmt = "PNG" if target.suffix.lower() == ".png" else "JPEG"
        with Image.open(target) as im:
            # PILのrotateは反時計回りが正。expand=Trueで枠を広げる。
            # EXIF Orientation を焼き込んでから回すため、保存後は向きが確定する。
            rotated = ImageOps.exif_transpose(im).convert("RGB").rotate(angle, expand=True)
        rotated.save(target, format=fmt)
        rotated_sources.append(src_name)
        last_w, last_h = rotated.width, rotated.height

        # processed はプリ生成サムネイルも再生成
        if src_name == "processed":
            thumbs = paths.processed_thumbnails_dir(name)
            thumbs.mkdir(parents=True, exist_ok=True)
            thumb = rotated.copy()
            thumb.thumbnail((settings.thumbnail_max_size, settings.thumbnail_max_size))
            thumb.save(thumbs / target.name, format=fmt)

    if not rotated_sources:
        raise SelectionNotFoundError(f"画像 '{image_id}' が見つかりません。")

    warning = None
    if paths.labels_dir(name).exists() and any(paths.labels_dir(name).glob("*.txt")):
        warning = (
            "既存ラベルがある状態で画像を回転すると、bbox座標と画像が一致しなくなる可能性があります。"
        )

    return SelectionRotateResponse(
        image_id=stem, source="+".join(rotated_sources), angle=angle,
        width=last_w, height=last_h, warning=warning,
    )


def delete_image(name: str, image_id: str) -> SelectionDeleteResponse:
    """画像を完全に削除する（raw/processed の実画像・サムネイル・アノテーションラベル・
    selection.json 上の該当項目）。

    これまでの「除外(excluded)」は selection.json 上のマーキングのみで非破壊だったが、
    利用者からの明示的な要望により、この削除操作は実ファイルを消去する破壊的操作
    （元に戻せない）にしている。自動検出（重複・低品質等）では削除まで行わず、
    review としてマーキングするだけにとどめ、この関数の呼び出しは常に利用者の
    明示的な操作（削除ボタン押下）に限定すること。
    """
    _require_project(name)
    stem = Path(image_id).stem
    # "." ".." 空文字はいずれも Path(x).name == x を満たしてしまい、単純な
    # 「stem != Path(stem).name」比較だけでは弾けない（pathlibの既知の挙動）。
    # 実際にはこの後 stem を裸のパス片として結合する箇所が無い（必ずファイル名の
    # 比較用途、または f"{stem}.txt" のようにサフィックスを付けてから結合する）ため
    # 現状はディレクトリ脱出には至らないが、意図通りの検証にするため明示的に弾く。
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem:
        raise SelectionValidationError("不正な image_id です。")

    deleted_files: list[str] = []
    failed_files: list[str] = []

    def _try_unlink(p: Path, rel: str) -> None:
        try:
            p.unlink(missing_ok=True)
            deleted_files.append(rel)
        except OSError as e:
            # 他プロセスに開かれている等で削除できなかった場合、ここで例外を
            # 送出して処理を打ち切ると「一部だけ削除された中途半端な状態」を
            # 検知できずに終わってしまう。他の対象の削除は試行を続け、最後に
            # まとめて 409 として報告する。
            failed_files.append(f"{rel}（削除失敗: {e.strerror or e}）")

    for src_name in ("raw", "processed"):
        img_dir = paths.images_dir_for_source(name, src_name)
        if not img_dir.exists():
            continue
        for p in list(img_dir.iterdir()):
            if p.is_file() and p.stem == stem and p.suffix.lower() in settings.allowed_image_suffixes:
                _try_unlink(p, f"{src_name}/images/{p.name}")

    thumbs = paths.processed_thumbnails_dir(name)
    if thumbs.exists():
        for p in list(thumbs.iterdir()):
            if p.is_file() and p.stem == stem:
                _try_unlink(p, f"processed/thumbnails/{p.name}")

    label_path = paths.labels_dir(name) / f"{stem}.txt"
    if label_path.exists():
        _try_unlink(label_path, f"annotations/labels/{label_path.name}")

    if not deleted_files and not failed_files:
        raise SelectionNotFoundError(f"画像 '{image_id}' が見つかりません。")

    if failed_files:
        raise SelectionConflictError(
            "一部のファイルが使用中などの理由で削除できませんでした"
            f"（削除済み: {len(deleted_files)}件 / 失敗: {len(failed_files)}件）: "
            + ", ".join(failed_files)
        )

    # selection.json に該当項目があれば取り除く（無くてもエラーにしない）
    sel_path = paths.selection_path(name)
    if sel_path.exists():
        try:
            data = json.loads(sel_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            data = None
        if data is not None:
            items = data.get("items", [])
            new_items = [it for it in items if it.get("image_id") != stem]
            if len(new_items) != len(items):
                data["items"] = new_items
                data["summary"] = _summarize([SelectionItem(**it) for it in new_items]).model_dump()
                sel_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )

    return SelectionDeleteResponse(image_id=stem, deleted_files=deleted_files)


def load_allowed_stems(name: str, include_review: bool) -> tuple[set[str] | None, str | None]:
    """dataset作成用: 採用する image_id(stem) の集合と warning を返す。

    selection 未実行/破損時は (None, warning) を返し、呼び出し側は全画像対象とする。
    """
    path = paths.selection_path(name)
    if not path.exists():
        return None, "selection.json が無いため、全画像を対象にします。"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None, "selection.json が壊れているため、全画像を対象にします。"
    allowed: set[str] = set()
    for it in data.get("items", []):
        st = it.get("status")
        if st == "included" or (st == "review" and include_review):
            allowed.add(it.get("image_id"))
    return allowed, None
