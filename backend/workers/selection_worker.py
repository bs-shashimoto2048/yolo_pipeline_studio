"""画像選別（画像選別チェック）の非同期実行ワーカー（別プロセス）。

selection_service.start_run_job から subprocess.Popen で起動される。
7,000枚規模でもFastAPIのリクエスト/レスポンスサイクルをブロックしないよう、
PILによる解析（明度/ブレ判定・重複ハッシュ）はすべてこのワーカー側で行い、
進捗を job.json（--job-json）へ書き戻す（predict_worker.py と同じ
total_count/processed_count方式）。

app パッケージには依存せず、引数で受け取った絶対パスとPillowだけで動作する
（predict_worker.py と同じ自己完結方針）。

mode:
  - diff: 既存 selection.json の items のうち、現在も実ファイルが存在するものは
    一切再解析せずそのまま保持する（manual/unknown の status_source を保護）。
    新規ファイルだけ解析して追加し、削除済み画像（ファイルが無くなったitem）は
    除去する。
  - full: 対象ディレクトリの全ファイルを解析し直し、status_source を全件 auto
    に正規化する（Issue #11 Checkpoint 2 修正指摘）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, UnidentifiedImageError

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
# job.json への書き込み頻度（1枚ごとだと数千枚規模でI/Oが過大になるため間引く）
_PROGRESS_EVERY_N = 25
_PROGRESS_EVERY_SEC = 1.0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _update_job(job_json: Path, **fields: object) -> None:
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.update(fields)
    job_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _hist_stats(hist: list[int]) -> tuple[float, float]:
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
    return mean, var


def _analyze_image(data: bytes) -> tuple[int, int, float, float]:
    """(width, height, brightness_mean, blur_score) を返す。

    selection_service._analyze_image と同一ロジック（reset_to_auto等、単発の
    軽量な再解析はservice側で行うため、そちらにも同じ関数が存在する。
    workerはappパッケージに依存しない自己完結方針のためここに複製している）。
    """
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        gray = im.convert("L")
    brightness_mean, _ = _hist_stats(gray.histogram())
    edges = gray.filter(ImageFilter.FIND_EDGES)
    ew, eh = edges.size
    if ew > 4 and eh > 4:
        edges = edges.crop((2, 2, ew - 2, eh - 2))
    _, blur_score = _hist_stats(edges.histogram())
    return w, h, round(brightness_mean, 2), round(blur_score, 2)


def _list_images(img_dir: Path) -> list[Path]:
    if not img_dir.exists():
        return []
    return sorted(
        p for p in img_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _ALLOWED_SUFFIXES
    )


def _judge(
    w: int, h: int, brightness: float, blur: float,
    min_width: int, min_height: int, blur_threshold: float,
    dark_threshold: float, bright_threshold: float,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    reasons: list[str] = []
    if w < min_width or h < min_height:
        warnings.append("small_image")
        reasons.append("画像サイズが小さすぎます")
    if brightness < dark_threshold:
        warnings.append("dark_image")
        reasons.append("画像が暗すぎます")
    if brightness > bright_threshold:
        warnings.append("bright_image")
        reasons.append("画像が明るすぎます")
    if blur < blur_threshold:
        warnings.append("blur_image")
        reasons.append("画像がブレている可能性があります")
    return warnings, reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--selection-json", required=True)
    ap.add_argument("--img-dir", required=True)
    ap.add_argument("--source", required=True)  # raw | processed（解決済みの表示用ラベル）
    ap.add_argument("--mode", required=True, choices=["diff", "full"])
    ap.add_argument("--min-width", type=int, default=320)
    ap.add_argument("--min-height", type=int, default=320)
    ap.add_argument("--blur-threshold", type=float, default=80.0)
    ap.add_argument("--dark-threshold", type=float, default=30.0)
    ap.add_argument("--bright-threshold", type=float, default=240.0)
    ap.add_argument("--detect-duplicates", action="store_true")
    args = ap.parse_args()

    job_json = Path(args.job_json)
    selection_json = Path(args.selection_json)
    img_dir = Path(args.img_dir)

    files = _list_images(img_dir)
    current_ids = {p.stem: p for p in files}

    # --- diff: 既存itemのうち実ファイルが残っているものだけ保持（manual/unknown保護） ---
    kept_items: list[dict] = []
    if args.mode == "diff" and selection_json.exists():
        try:
            prev = json.loads(selection_json.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            prev = {}
        for it in prev.get("items", []):
            if it.get("image_id") in current_ids:
                kept_items.append(it)
        # 削除済み画像（実ファイルが無くなったitem）は kept_items に含めない
        # ことで自然に除去される（reconcile）。

    kept_ids = {it.get("image_id") for it in kept_items}
    if args.mode == "diff":
        targets = [p for p in files if p.stem not in kept_ids]
    else:
        targets = files  # full: 全件を再解析（status_sourceをautoへ正規化）

    total = len(targets)
    _update_job(
        job_json, status="running", started_at=_now(),
        message=f"解析中… (0/{total})", total_count=total, processed_count=0,
    )
    print(f"[INFO] 画像選別ワーカー開始 mode={args.mode} source={args.source} "
          f"対象={total}件（保持={len(kept_items)}件）")

    # 重複検出用ハッシュマップ。diffでは既存itemの保存済みhashをそのまま再利用し
    # （再デコード不要）、新規ファイルの分だけこのマップへ追加していく。
    hash_first: dict[str, str] = {}
    if args.detect_duplicates:
        for it in kept_items:
            h = it.get("hash")
            if h and h not in hash_first:
                hash_first[h] = it.get("image_id")

    new_items: list[dict] = []
    last_progress_time = time.time()
    try:
        for idx, p in enumerate(targets, 1):
            try:
                data = p.read_bytes()
                w, h, brightness, blur = _analyze_image(data)
            except (UnidentifiedImageError, OSError, ValueError) as e:
                print(f"[WARN] 画像を開けなかったためスキップします: {p.name} ({e!r})")
                continue
            digest = hashlib.sha1(data).hexdigest() if args.detect_duplicates else None
            image_id = p.stem

            warnings, reasons = _judge(
                w, h, brightness, blur,
                args.min_width, args.min_height, args.blur_threshold,
                args.dark_threshold, args.bright_threshold,
            )
            duplicate_of = None
            if args.detect_duplicates and digest is not None:
                if digest in hash_first:
                    duplicate_of = hash_first[digest]
                    warnings.append("duplicate_image")
                    reasons.append("重複画像です")
                else:
                    hash_first[digest] = image_id

            status = "review" if warnings else "included"
            new_items.append({
                "image_id": image_id, "image_name": p.name, "source": args.source,
                "width": w, "height": h, "status": status, "status_source": "auto",
                "warnings": warnings, "reasons": reasons, "hash": digest,
                "brightness_mean": brightness, "blur_score": blur,
                "duplicate_of": duplicate_of, "manual_reason": None,
                "updated_at": _now(),
            })

            now_t = time.time()
            if idx % _PROGRESS_EVERY_N == 0 or (now_t - last_progress_time) >= _PROGRESS_EVERY_SEC or idx == total:
                last_progress_time = now_t
                _update_job(job_json, processed_count=idx, message=f"解析中… ({idx}/{total})")

        items = kept_items + new_items if args.mode == "diff" else new_items

        def _count(pred) -> int:
            return sum(1 for it in items if pred(it))

        summary = {
            "image_count": len(items),
            "included_count": _count(lambda it: it.get("status") == "included"),
            "excluded_count": _count(lambda it: it.get("status") == "excluded"),
            "review_count": _count(lambda it: it.get("status") == "review"),
            "duplicate_count": _count(lambda it: "duplicate_image" in (it.get("warnings") or [])),
            "small_count": _count(lambda it: "small_image" in (it.get("warnings") or [])),
            "dark_count": _count(lambda it: "dark_image" in (it.get("warnings") or [])),
            "bright_count": _count(lambda it: "bright_image" in (it.get("warnings") or [])),
            "blur_count": _count(lambda it: "blur_image" in (it.get("warnings") or [])),
        }
        payload = {
            "created_at": _now(),
            "source": args.source,
            "settings": {
                "min_width": args.min_width, "min_height": args.min_height,
                "blur_threshold": args.blur_threshold, "dark_threshold": args.dark_threshold,
                "bright_threshold": args.bright_threshold, "duplicate_hash": args.detect_duplicates,
            },
            "summary": summary,
            "items": items,
        }
        selection_json.parent.mkdir(parents=True, exist_ok=True)
        tmp = selection_json.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(selection_json)

        _update_job(
            job_json, status="completed", finished_at=_now(), return_code=0,
            message=f"完了（{len(items)}件、うち今回解析{len(new_items)}件）",
            processed_count=total,
        )
        print(f"[INFO] 画像選別ワーカー完了 items={len(items)} 新規解析={len(new_items)}")
        return 0
    except Exception as e:  # noqa: BLE001
        print("[ERROR] 画像選別ワーカーで例外が発生しました:")
        traceback.print_exc()
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message=f"画像選別に失敗しました: {e!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
