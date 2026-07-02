"""画像取り込み・一覧・サムネイル生成。

task.md「6. 画像取り込み機能」の土台:
- 対応形式チェック (jpg/jpeg/png/bmp)
- ファイル名正規化（日本語・空白を避ける）
- ハッシュ値による重複検出
- 破損画像チェック
- 解像度チェック（小さすぎる画像を警告）
- サムネイル表示
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..core import paths
from ..core.config import settings
from ..schemas.image import (
    FolderImportResponse,
    ImageInfo,
    ImportItem,
    UploadResponse,
    UploadResultItem,
)
from .project_service import ProjectError, project_exists

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def normalize_filename(filename: str) -> str:
    """日本語・空白を避けた安全なファイル名へ正規化する。"""
    stem = Path(filename).stem
    suffix = Path(filename).suffix.lower()
    # NFKD で分解し ASCII 化できない文字は落とす
    ascii_stem = (
        unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    )
    ascii_stem = _SAFE_NAME_RE.sub("_", ascii_stem).strip("._-")
    if not ascii_stem:
        ascii_stem = "image"
    return f"{ascii_stem}{suffix}"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _existing_hashes(img_dir: Path) -> set[str]:
    hashes: set[str] = set()
    for p in img_dir.iterdir():
        if p.is_file():
            hashes.add(_sha1(p.read_bytes()))
    return hashes


def _unique_path(img_dir: Path, filename: str) -> Path:
    """同名衝突時に連番を付与してユニークなパスを返す。"""
    candidate = img_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    i = 1
    while True:
        candidate = img_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def save_uploads(name: str, files: list[tuple[str, bytes]]) -> UploadResponse:
    """アップロードされた画像を検証・重複排除して保存する。

    files: (元ファイル名, バイト列) のリスト
    """
    _require_project(name)
    img_dir = paths.raw_images_dir(name)
    img_dir.mkdir(parents=True, exist_ok=True)

    existing = _existing_hashes(img_dir)
    results: list[UploadResultItem] = []
    added = 0
    skipped = 0

    for original_name, data in files:
        suffix = Path(original_name).suffix.lower()
        if suffix not in settings.allowed_image_suffixes:
            results.append(
                UploadResultItem(
                    original_name=original_name,
                    status="unsupported",
                    detail=f"非対応形式: {suffix}",
                )
            )
            skipped += 1
            continue

        digest = _sha1(data)
        if digest in existing:
            results.append(
                UploadResultItem(
                    original_name=original_name,
                    status="duplicate",
                    detail="同一ハッシュの画像が既に存在します。",
                )
            )
            skipped += 1
            continue

        # 破損チェック
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except (UnidentifiedImageError, OSError, ValueError):
            results.append(
                UploadResultItem(
                    original_name=original_name,
                    status="corrupt",
                    detail="画像として読み込めませんでした。",
                )
            )
            skipped += 1
            continue

        safe_name = normalize_filename(original_name)
        target = _unique_path(img_dir, safe_name)
        target.write_bytes(data)
        existing.add(digest)
        added += 1
        results.append(
            UploadResultItem(
                original_name=original_name,
                stored_name=target.name,
                status="added",
            )
        )

    return UploadResponse(results=results, added=added, skipped=skipped)


def import_folder(
    name: str,
    files: list[tuple[str, bytes]],
    allowed_extensions: list[str] | None = None,
) -> FolderImportResponse:
    """フォルダ取り込み。許可拡張子で絞り、重複/破損を除外して保存する。

    バックエンド側でも必ず拡張子を再チェックする（API直叩き・想定外混入対策）。
    allowed_extensions はマスター（settings.allowed_image_suffixes）の範囲に制限する。
    """
    _require_project(name)
    img_dir = paths.raw_images_dir(name)
    img_dir.mkdir(parents=True, exist_ok=True)

    master = {e.lower() for e in settings.allowed_image_suffixes}
    if allowed_extensions:
        allowed = {
            (e if e.startswith(".") else f".{e}").lower()
            for e in allowed_extensions
        } & master
    else:
        allowed = master
    if not allowed:
        allowed = master

    existing = _existing_hashes(img_dir)
    items: list[ImportItem] = []
    imported = duplicate = broken = unsupported = 0

    for original_name, data in files:
        # 大文字拡張子も許可（lowerで比較）
        suffix = Path(original_name).suffix.lower()
        if suffix not in allowed:
            unsupported += 1
            items.append(ImportItem(
                filename=original_name, status="unsupported",
                detail=f"対象外の拡張子: {suffix}",
            ))
            continue

        digest = _sha1(data)
        if digest in existing:
            duplicate += 1
            items.append(ImportItem(
                filename=original_name, status="duplicate", hash=digest,
                detail="同一ハッシュの画像が既に存在します。",
            ))
            continue

        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            with Image.open(io.BytesIO(data)) as im2:
                w, h = im2.size
        except (UnidentifiedImageError, OSError, ValueError):
            broken += 1
            items.append(ImportItem(
                filename=original_name, status="broken",
                detail="画像として読み込めませんでした。",
            ))
            continue

        safe_name = normalize_filename(original_name)
        target = _unique_path(img_dir, safe_name)
        target.write_bytes(data)
        existing.add(digest)
        imported += 1
        items.append(ImportItem(
            filename=target.name, status="imported",
            width=w, height=h, hash=digest,
        ))

    return FolderImportResponse(
        project_name=name,
        imported_count=imported,
        skipped_count=duplicate + broken + unsupported,
        duplicate_count=duplicate,
        broken_count=broken,
        unsupported_count=unsupported,
        items=items,
    )


def list_images(name: str, source: str = "raw") -> list[ImageInfo]:
    """登録画像の一覧をメタ情報付きで返す。

    source: raw / processed / auto（autoはprocessedがあればprocessed）。
    """
    _require_project(name)
    img_dir = paths.images_dir_for_source(name, source)
    lbl_dir = paths.labels_dir(name)
    if not img_dir.exists():
        return []

    infos: list[ImageInfo] = []
    for p in sorted(img_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in settings.allowed_image_suffixes:
            continue
        try:
            data = p.read_bytes()
            with Image.open(io.BytesIO(data)) as im:
                # EXIF Orientation を反映した実表示サイズを返す
                im = ImageOps.exif_transpose(im)
                w, h = im.size
        except (UnidentifiedImageError, OSError, ValueError):
            # 壊れた画像はスキップ（一覧では出さない）
            continue

        label_path = lbl_dir / f"{p.stem}.txt"
        low_res = min(w, h) < settings.min_resolution_warn
        infos.append(
            ImageInfo(
                filename=p.name,
                width=w,
                height=h,
                size_bytes=len(data),
                sha1=_sha1(data),
                has_label=label_path.exists(),
                low_resolution=low_res,
            )
        )
    return infos


def image_path(name: str, filename: str, source: str = "raw") -> Path:
    """安全に画像の実パスを返す（パストラバーサル防止）。"""
    _require_project(name)
    img_dir = paths.images_dir_for_source(name, source)
    target = (img_dir / filename).resolve()
    if img_dir.resolve() not in target.parents:
        raise ProjectError("不正なファイルパスです。")
    if not target.exists():
        raise ProjectError(f"画像 '{filename}' が見つかりません。")
    return target


def make_thumbnail(name: str, filename: str, source: str = "raw") -> bytes:
    """サムネイル（PNG）を生成して返す。EXIF Orientation を反映する。"""
    src = image_path(name, filename, source)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((settings.thumbnail_max_size, settings.thumbnail_max_size))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    return buf.getvalue()
