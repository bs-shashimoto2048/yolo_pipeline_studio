"""前処理（アノテーション前工程）。

raw/images を破壊せず processed/images に出力する。OpenCVは使わず Pillow のみで
実装（requirements を増やさない方針）。CLAHE は LAB の L チャンネルに対する
タイル別ヒストグラム均等化＋クリップで近似する。

処理順: グレースケール → 明るさ/コントラスト → CLAHE → シャープ化 → リサイズ。
"""

from __future__ import annotations

import io
import json
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from ..core import paths
from ..core.config import settings
from ..schemas.preprocess import (
    PreprocessInfoResponse,
    PreprocessPreviewResponse,
    PreprocessRunResponse,
    PreprocessSettings,
)
from . import image_service
from .project_service import ProjectError, project_exists

_PAD_COLORS = {"black": (0, 0, 0), "white": (255, 255, 255), "gray": (128, 128, 128)}
_THUMB = 256


class PreprocessError(Exception):
    pass


class PreprocessValidationError(PreprocessError):
    """400相当。"""


class PreprocessConflictError(PreprocessError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _validate_resize(s: PreprocessSettings) -> None:
    if s.resize_enabled and s.resize_mode is not None:
        if s.resize_mode not in ("width", "height"):
            raise PreprocessValidationError("resize_mode は width または height です。")
        if not (32 <= s.resize_size <= 4096):
            raise PreprocessValidationError("resize_size は 32〜4096 で指定してください。")
    if s.binary_enabled and not (0 <= s.binary_threshold <= 255):
        raise PreprocessValidationError("binary_threshold は 0〜255 で指定してください。")


# ---- 画像処理ヘルパ（Pillow） ----

def _apply_brightness_contrast(img: Image.Image, contrast: float, brightness: float) -> Image.Image:
    def f(i: int) -> int:
        v = i * contrast + brightness
        return 0 if v < 0 else 255 if v > 255 else int(v)

    return img.point(f)


def _clahe_lut(hist: list[int], clip_limit: float, npix: int) -> list[int]:
    clip = max(1, int(clip_limit * npix / 256))
    clipped = [min(h, clip) for h in hist]
    excess = sum(h - c for h, c in zip(hist, clipped))
    add = excess // 256
    clipped = [c + add for c in clipped]
    total = sum(clipped) or 1
    lut: list[int] = []
    cum = 0
    for c in clipped:
        cum += c
        lut.append(round(255 * cum / total))
    return lut


def _clahe_channel(l_img: Image.Image, clip_limit: float, grid: int) -> Image.Image:
    w, h = l_img.size
    grid = max(1, grid)
    out = l_img.copy()
    for gy in range(grid):
        for gx in range(grid):
            x0, y0 = gx * (w // grid), gy * (h // grid)
            x1 = w if gx == grid - 1 else (gx + 1) * (w // grid)
            y1 = h if gy == grid - 1 else (gy + 1) * (h // grid)
            if x1 <= x0 or y1 <= y0:
                continue
            tile = l_img.crop((x0, y0, x1, y1))
            lut = _clahe_lut(tile.histogram(), clip_limit, (x1 - x0) * (y1 - y0))
            out.paste(tile.point(lut), (x0, y0))
    return out


def _apply_clahe(img: Image.Image, clip_limit: float, grid: int) -> Image.Image:
    lab = img.convert("LAB")
    l, a, b = lab.split()
    l2 = _clahe_channel(l, clip_limit, grid)
    return Image.merge("LAB", (l2, a, b)).convert("RGB")


def _apply_resize_legacy(img: Image.Image, w: int, h: int, keep: bool, pad: bool, color: str) -> Image.Image:
    if not keep:
        return img.resize((w, h))
    scale = min(w / img.width, h / img.height)
    nw, nh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    resized = img.resize((nw, nh))
    if not pad:
        return resized
    canvas = Image.new("RGB", (w, h), _PAD_COLORS.get(color, (0, 0, 0)))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def _apply_resize_mode(img: Image.Image, mode: str, size: int) -> Image.Image:
    """新仕様: width/height の一方を size px に、他方はアスペクト比維持で自動計算。"""
    size = int(_clamp(size, 32, 4096))
    if mode == "height":
        nh = size
        nw = max(1, round(img.width * size / img.height))
    else:  # width（既定）
        nw = size
        nh = max(1, round(img.height * size / img.width))
    return img.resize((nw, nh))


def _process_one(data: bytes, s: PreprocessSettings) -> Image.Image:
    # EXIF Orientation を反映してから処理（縦横の向きを保持）
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")

    if s.grayscale_enabled:
        img = img.convert("L").convert("RGB")
    if s.binary_enabled:
        # 2値化は内部的にグレースケール化してから白黒変換（グレースケールOFFでも実施）
        thr = int(_clamp(s.binary_threshold, 0, 255))
        gray = img.convert("L")
        if s.binary_invert:
            binary = gray.point(lambda p, t=thr: 255 if p < t else 0)
        else:
            binary = gray.point(lambda p, t=thr: 255 if p >= t else 0)
        img = binary.convert("RGB")
    if s.brightness_enabled or s.contrast_enabled:
        contrast = _clamp(s.contrast, 0.5, 3.0) if s.contrast_enabled else 1.0
        brightness = _clamp(s.brightness, -100.0, 100.0) if s.brightness_enabled else 0.0
        img = _apply_brightness_contrast(img, contrast, brightness)
    if s.clahe_enabled:
        img = _apply_clahe(
            img, _clamp(s.clahe_clip_limit, 1.0, 10.0),
            int(_clamp(s.clahe_tile_grid_size, 4, 16)),
        )
    if s.sharpen_enabled:
        strength = _clamp(s.sharpen_strength, 0.0, 3.0)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=int(strength * 100), threshold=2))
    if s.resize_enabled:
        if s.resize_mode in ("width", "height"):
            img = _apply_resize_mode(img, s.resize_mode, s.resize_size)
        else:
            # 旧仕様（後方互換）
            img = _apply_resize_legacy(
                img, max(1, s.resize_width), max(1, s.resize_height),
                s.keep_aspect_ratio, s.padding, s.padding_color,
            )
    return img


# ---- 実行 ----

def run(name: str, s: PreprocessSettings) -> PreprocessRunResponse:
    _require_project(name)
    if not paths.is_valid_project_name(s.job_name):
        raise PreprocessValidationError(
            "job_name は英数・アンダースコア・ハイフンのみです。"
        )
    _validate_resize(s)
    out_fmt = s.output_format.lower()
    if out_fmt not in ("jpg", "jpeg", "png"):
        raise PreprocessValidationError("output_format は jpg または png です。")
    ext = ".png" if out_fmt == "png" else ".jpg"
    pil_fmt = "PNG" if ext == ".png" else "JPEG"

    proc_root = paths.project_dir(name) / "processed"
    proc_images = paths.processed_images_dir(name)
    if proc_images.exists() and any(proc_images.iterdir()):
        if not s.overwrite:
            raise PreprocessConflictError(
                "processed/images が既に存在します。overwrite=true で再作成してください。"
            )
        # 既存processedを削除して再作成
        if proc_root.exists():
            shutil.rmtree(proc_root)

    proc_images.mkdir(parents=True, exist_ok=True)
    proc_thumbs = paths.processed_thumbnails_dir(name)
    proc_thumbs.mkdir(parents=True, exist_ok=True)

    raw_dir = paths.raw_images_dir(name)
    raw_files = sorted(
        p for p in raw_dir.iterdir()
        if raw_dir.exists() and p.is_file() and p.suffix.lower() in settings.allowed_image_suffixes
    ) if raw_dir.exists() else []

    items = []
    processed = 0
    skipped = 0
    for src in raw_files:
        try:
            data = src.read_bytes()
            with Image.open(io.BytesIO(data)) as probe:
                sw, sh = probe.size
            result = _process_one(data, s)
        except (UnidentifiedImageError, OSError, ValueError):
            skipped += 1
            continue

        out_name = f"{src.stem}{ext}"
        result.save(proc_images / out_name, format=pil_fmt)

        thumb = result.copy()
        thumb.thumbnail((_THUMB, _THUMB))
        thumb.save(proc_thumbs / out_name, format=pil_fmt)

        items.append({
            "source_filename": src.name,
            "processed_filename": out_name,
            "source_width": sw,
            "source_height": sh,
            "processed_width": result.width,
            "processed_height": result.height,
        })
        processed += 1

    metadata = {
        "job_name": s.job_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "raw/images",
        "output": "processed/images",
        "input_count": len(raw_files),
        "processed_count": processed,
        "skipped_count": skipped,
        "settings": s.model_dump(),
        "items": items,
    }
    paths.processed_metadata_path(name).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    warning = None
    lbl_dir = paths.labels_dir(name)
    if lbl_dir.exists() and any(lbl_dir.glob("*.txt")):
        warning = (
            "既存の annotations/labels が存在します。前処理後の画像と既存ラベルの"
            "整合性が崩れる可能性があります（ラベル座標の自動変換は行いません）。"
        )

    return PreprocessRunResponse(
        project_name=name,
        job_name=s.job_name,
        status="completed",
        input_count=len(raw_files),
        processed_count=processed,
        skipped_count=skipped,
        processed_dir="processed/images",
        metadata_path="processed/metadata.json",
        warning=warning,
    )


def preview(name: str, image_id: str | None, s: PreprocessSettings) -> PreprocessPreviewResponse:
    """設定を1枚に適用したプレビューを生成（processed/preview に保存、本体は更新しない）。"""
    _require_project(name)
    _validate_resize(s)

    # 対象画像（指定なければ raw の先頭）
    raw = image_service.list_images(name, "raw")
    if not raw:
        raise PreprocessValidationError("raw/images に画像がありません。")
    target = None
    if image_id:
        for im in raw:
            if Path(im.filename).stem == Path(image_id).stem:
                target = im
                break
        if target is None:
            raise PreprocessValidationError(f"画像 '{image_id}' が見つかりません。")
    else:
        target = raw[0]

    src = paths.raw_images_dir(name) / target.filename
    data = src.read_bytes()
    with Image.open(io.BytesIO(data)) as probe:
        bw, bh = ImageOps.exif_transpose(probe).size

    out_fmt = (s.output_format or "jpg").lower()
    ext = ".png" if out_fmt == "png" else ".jpg"
    pil_fmt = "PNG" if ext == ".png" else "JPEG"

    # プレビューは表示確認が目的なので、大きい画像は作業用に縮小してから処理する
    # （CPU負荷と転送量を抑え、即時反映を可能にする）。
    # 寸法に影響する処理はリサイズのみで、リサイズは入力サイズに依存せず出力寸法を
    # 決めるため、縮小しても After の表示寸法は正しく保たれる。
    PREVIEW_MAX = 900
    work_data = data
    if max(bw, bh) > PREVIEW_MAX:
        with Image.open(io.BytesIO(data)) as im0:
            im0 = ImageOps.exif_transpose(im0)
            im0.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
            buf = io.BytesIO()
            im0.convert("RGB").save(buf, format="JPEG", quality=88)
            work_data = buf.getvalue()

    result = _process_one(work_data, s)

    pdir = paths.processed_preview_dir(name)
    pdir.mkdir(parents=True, exist_ok=True)
    stem = Path(target.filename).stem
    out_name = f"{stem}{ext}"
    result.save(pdir / out_name, format=pil_fmt)

    # After の表示寸法: リサイズ有効時は出力寸法（入力サイズに依存しない）、
    # リサイズ無効時は寸法が変わらないため元画像の寸法を返す（作業用縮小の影響を排除）。
    if s.resize_enabled:
        aw, ah = result.width, result.height
    else:
        aw, ah = bw, bh

    return PreprocessPreviewResponse(
        project_name=name,
        image_id=stem,
        before_url=f"/api/projects/{name}/images/{target.filename}?source=raw",
        preview_url=f"/api/projects/{name}/preprocess/preview-image/{out_name}",
        before_width=bw,
        before_height=bh,
        after_width=aw,
        after_height=ah,
    )


def preview_image_path(name: str, filename: str) -> Path:
    """プレビューキャッシュ画像の実パスを安全に返す。"""
    _require_project(name)
    if filename != Path(filename).name or filename in ("", ".", ".."):
        raise PreprocessValidationError("不正なファイル名です。")
    pdir = paths.processed_preview_dir(name).resolve()
    target = (pdir / filename).resolve()
    if pdir not in target.parents or not target.is_file():
        raise PreprocessValidationError("プレビュー画像が見つかりません。")
    return target


def apply(data: bytes, s: PreprocessSettings) -> Image.Image:
    """画像バイト列に前処理設定を適用した PIL.Image を返す（推論前処理等で再利用）。"""
    return _process_one(data, s)


def load_latest_settings(name: str) -> PreprocessSettings | None:
    """processed/metadata.json から最新の前処理設定を復元する。無ければ None。"""
    meta_path = paths.processed_metadata_path(name)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    settings = data.get("settings")
    if not settings:
        return None
    try:
        return PreprocessSettings(**settings)
    except Exception:  # noqa: BLE001
        return None


def get_info(name: str) -> PreprocessInfoResponse:
    _require_project(name)
    proc_images = paths.processed_images_dir(name)
    count = 0
    if proc_images.exists():
        count = sum(
            1 for p in proc_images.iterdir()
            if p.is_file() and p.suffix.lower() in settings.allowed_image_suffixes
        )
    metadata = None
    meta_path = paths.processed_metadata_path(name)
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            metadata = None
    return PreprocessInfoResponse(
        project_name=name,
        has_processed_images=count > 0,
        processed_count=count,
        processed_dir="processed/images",
        metadata=metadata,
    )
