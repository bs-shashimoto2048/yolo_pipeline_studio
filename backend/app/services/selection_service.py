"""画像選別。

低品質（小サイズ・暗/明・ブレ）・重複を自動検出して status（included/review）を
selection.json に保存する。自動検出はマーキングのみ（非破壊）で、実際に画像を
取り除きたい場合は `delete_image()` による明示的な削除操作が必要（元に戻せない）。

OpenCV/NumPy は使わず Pillow のみ。ブレはグレースケールの FIND_EDGES 後の
画素分散（ヒストグラムから算出）で近似する。

画像選別の実行（PILによる全件/差分解析）は7,000枚規模になり得るため、FastAPIの
リクエスト/レスポンスサイクルをブロックしないよう `backend/workers/selection_worker.py`
を subprocess.Popen で起動し、`run_job.json` のポーリングで進捗・完了を確認する
（capture/predict等の既存ジョブパターンと同じ方式。Issue #11 Checkpoint 3）。
このモジュール内の `_analyze_image` は、reset_to_auto（単一画像の再解析）でのみ
同期的に使う軽量処理として残している。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from ..core import paths
from ..core.config import settings
from ..schemas.selection import (
    SelectionDeleteResponse,
    SelectionGetResponse,
    SelectionItem,
    SelectionJobStatus,
    SelectionRotateResponse,
    SelectionRunRequest,
    SelectionRunResponse,
    SelectionStatusResponse,
    SelectionStatusUpdate,
    SelectionSummary,
)
from . import video_service
from .project_service import ProjectError, project_exists

_VALID_STATUS = {"included", "review"}
_WORKER = Path(__file__).resolve().parents[2] / "workers" / "selection_worker.py"


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


def _resolve_mode(name: str, req: SelectionRunRequest) -> str:
    """mode（正式仕様）と overwrite（非推奨・後方互換）を解決する。

    - mode が明示されていればそれを最優先で使う。
    - mode 未指定の場合のみ overwrite を見る（旧クライアント向け互換層）:
        overwrite=true  -> "full"（旧仕様: 無条件に全件再生成）
        overwrite=false/未指定かつ selection.json 未作成 -> "full"（旧仕様: 初回作成は常に全件）
        overwrite=false かつ selection.json 既存 -> 旧仕様どおり衝突エラー（409）
    """
    if req.mode in ("diff", "full"):
        return req.mode
    if req.mode is not None:
        raise SelectionValidationError("mode は 'diff' または 'full' です。")
    # --- 互換層: overwrite ---
    exists = paths.selection_path(name).exists()
    if req.overwrite:
        return "full"
    if exists:
        raise SelectionConflictError(
            "selection.json が既に存在します。mode='diff'（差分更新）または "
            "mode='full'（完全再生成）を指定してください（overwrite=trueは非推奨の互換指定です）。"
        )
    return "full"


def _read_job(name: str) -> dict | None:
    p = paths.selection_job_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _job_status_from_dict(data: dict | None) -> SelectionJobStatus:
    data = data or {}
    return SelectionJobStatus(
        status=data.get("status", "unknown"),
        mode=data.get("mode"),
        source=data.get("source"),
        message=data.get("message"),
        total_count=int(data.get("total_count") or 0),
        processed_count=int(data.get("processed_count") or 0),
        created_at=data.get("created_at"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        return_code=data.get("return_code"),
    )


def _is_run_job_active(name: str) -> bool:
    """既に実行中のrunジョブがあるか（二重実行防止用）。

    statusがrunning/queuedでも、記録済みPIDが既に死んでいれば実行中とはみなさない
    （capture_service._is_session_active と同じ考え方。異常終了で更新が漏れた
    ジョブがいつまでも「実行中」扱いになり続けるのを防ぐ）。
    """
    data = _read_job(name)
    if data is None:
        return False
    if data.get("status") not in ("queued", "running"):
        return False
    pid = data.get("pid")
    if isinstance(pid, int) and not video_service._pid_alive(pid):
        return False
    return True


def _guard_no_active_run(name: str) -> None:
    """selection_worker（diff/full）が実行中の間、selection.json や解析対象画像を
    書き換えるAPI（update_status/reset_to_auto/delete_image/rotate_image）を
    409で拒否する（Issue #11 追加対応: mutation競合対策）。

    ワーカーは selection.json を「最後にまとめて一括書き込み（tmp→replace）」
    するため、実行中に他の経路がファイルを書き換えると、ワーカー完了時の
    上書きでその変更が消える、または画像本体が変わることで解析結果と実ファイルが
    食い違う（rotate等）といった競合が起こり得る。複雑なロック基盤を新設する
    かわりに、既に二重実行防止で使っている `_is_run_job_active` をそのまま
    再利用し、シンプルに「実行中は書き込み系APIを止める」方針にする。
    """
    if _is_run_job_active(name):
        raise SelectionConflictError(
            "画像選別の実行（差分更新/完全再生成）が進行中のため、この操作は今は行えません。"
            "完了までお待ちください。"
        )


def start_run_job(name: str, req: SelectionRunRequest) -> SelectionRunResponse:
    """画像選別の実行を非同期ジョブとして開始する（7,000枚規模でもHTTPをブロックしない）。

    実際のPIL解析は backend/workers/selection_worker.py が別プロセスで行う。
    ここでは対象ディレクトリ・対象件数（total_count）だけ軽量に確定させ、
    ジョブを起動して即座に返す。
    """
    _require_project(name)
    mode = _resolve_mode(name, req)

    if _is_run_job_active(name):
        raise SelectionConflictError("画像選別は既に実行中です。完了までお待ちください。")

    img_dir = paths.images_dir_for_source(name, req.source)
    used_source = "processed" if img_dir == paths.processed_images_dir(name) else "raw"
    files = sorted(
        p for p in img_dir.iterdir()
        if p.is_file() and p.suffix.lower() in settings.allowed_image_suffixes
    ) if img_dir.exists() else []

    if mode == "diff" and paths.selection_path(name).exists():
        try:
            prev = json.loads(paths.selection_path(name).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            prev = {}
        existing_ids = {it.get("image_id") for it in prev.get("items", [])}
        total = sum(1 for p in files if p.stem not in existing_ids)
    else:
        total = len(files)

    job_path = paths.selection_job_path(name)
    lock_path = Path(str(job_path) + ".lock")
    now = datetime.now().isoformat(timespec="seconds")
    job = {
        "status": "queued", "mode": mode, "source": used_source,
        "message": "queued", "total_count": total, "processed_count": 0,
        "created_at": now, "started_at": None, "finished_at": None, "return_code": None,
    }
    video_service._acquire_file_lock(lock_path)
    try:
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        video_service._release_file_lock(lock_path)

    log_path = paths.selection_log_path(name)
    log_path.touch()
    cmd = [
        sys.executable, str(_WORKER),
        "--job-json", str(job_path),
        "--selection-json", str(paths.selection_path(name)),
        "--img-dir", str(img_dir),
        "--source", used_source,
        "--mode", mode,
        "--min-width", str(req.min_width),
        "--min-height", str(req.min_height),
        "--blur-threshold", str(req.blur_threshold),
        "--dark-threshold", str(req.dark_threshold),
        "--bright-threshold", str(req.bright_threshold),
    ]
    if req.detect_duplicates:
        cmd.append("--detect-duplicates")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_f = log_path.open("a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, env=env)
    finally:
        log_f.close()

    video_service._acquire_file_lock(lock_path)
    try:
        current = _read_job(name) or job
        current["pid"] = proc.pid
        job_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        video_service._release_file_lock(lock_path)

    return SelectionRunResponse(
        project_name=name, selection_path="selection/selection.json",
        job=_job_status_from_dict(current),
    )


def get_run_job_status(name: str) -> SelectionJobStatus:
    _require_project(name)
    data = _read_job(name)
    if data is None:
        raise SelectionNotFoundError("画像選別はまだ一度も実行されていません。")
    return _job_status_from_dict(data)


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


def _freshness(name: str, source: str, existing_ids: set[str]) -> tuple[int, int, int, bool]:
    """(current_image_count, new_image_count, missing_image_count, is_stale) を、
    PILデコードを伴わない軽量なディレクトリ走査のみで算出する。

    比較対象は selection.json に記録済みの source（前回runで実際に使われた
    raw/processed）。"auto"を毎回再解決すると、raw/processedの枚数次第で
    比較対象そのものが揺れてしまい鮮度判定が安定しないため、記録済みの
    resolved sourceを使う。
    """
    img_dir = paths.images_dir_for_source(name, source)
    current_ids = {
        p.stem for p in img_dir.iterdir()
        if p.is_file() and p.suffix.lower() in settings.allowed_image_suffixes
    } if img_dir.exists() else set()
    new_count = len(current_ids - existing_ids)
    missing_count = len(existing_ids - current_ids)
    return len(current_ids), new_count, missing_count, (new_count > 0 or missing_count > 0)


def get_selection(name: str) -> SelectionGetResponse:
    _require_project(name)
    data = _load(name)
    items = [SelectionItem(**it) for it in data.get("items", [])]
    source = data.get("source", "raw")
    existing_ids = {it.image_id for it in items}
    current_count, new_count, missing_count, is_stale = _freshness(name, source, existing_ids)
    job_data = _read_job(name)
    return SelectionGetResponse(
        project_name=name,
        source=source,
        created_at=data.get("created_at"),
        summary=_summarize(items),
        items=items,
        current_image_count=current_count,
        new_image_count=new_count,
        missing_image_count=missing_count,
        is_stale=is_stale,
        job=_job_status_from_dict(job_data) if job_data is not None else None,
    )


def update_status(name: str, image_id: str, upd: SelectionStatusUpdate) -> SelectionStatusResponse:
    _require_project(name)
    _guard_no_active_run(name)
    if upd.status not in _VALID_STATUS:
        raise SelectionValidationError("status は included/review のいずれかです（除外は削除操作に置き換えられました）。")
    data = _load(name)
    found = None
    for it in data.get("items", []):
        if it.get("image_id") == image_id:
            it["status"] = upd.status
            # UI操作を経由したstatus変更は必ずmanualとして記録する（Issue #11）。
            # 以前は manual_reason の有無でしか手動変更を推測できず、かつ
            # フロントは manual_reason を渡さないため実質常にnullになり、
            # 自動判定と手動判定を信頼して区別できないという問題があった。
            it["status_source"] = "manual"
            it["manual_reason"] = upd.manual_reason
            it["updated_at"] = datetime.now().isoformat(timespec="seconds")
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
        image_id=image_id, status=upd.status, status_source="manual",
        manual_reason=upd.manual_reason,
    )


def reset_to_auto(name: str, image_id: str) -> SelectionItem:
    """manual/unknown な単一画像の判定を、現在の閾値で再解析した自動判定へ戻す。

    全体を`full`で再実行しなくても、個別の画像だけ「自動判定に戻す」ための
    軽量なエスケープハッチ（Issue #11 Checkpoint 2/3）。対象1枚だけをPILで
    再解析するため、7,000枚規模でも同期処理のままで問題ない。
    """
    _require_project(name)
    _guard_no_active_run(name)
    data = _load(name)
    items = data.get("items", [])
    idx = next((i for i, it in enumerate(items) if it.get("image_id") == image_id), None)
    if idx is None:
        raise SelectionNotFoundError(f"画像 '{image_id}' が選別結果にありません。")
    it = items[idx]

    source = data.get("source", "raw")
    img_dir = paths.images_dir_for_source(name, source)
    target = None
    if img_dir.exists():
        target = next(
            (p for p in img_dir.iterdir()
             if p.is_file() and p.stem == image_id and p.suffix.lower() in settings.allowed_image_suffixes),
            None,
        )
    if target is None:
        raise SelectionNotFoundError(f"画像 '{image_id}' の実ファイルが見つかりません。")

    settings_used = data.get("settings", {})
    min_width = settings_used.get("min_width", 320)
    min_height = settings_used.get("min_height", 320)
    blur_threshold = settings_used.get("blur_threshold", 80.0)
    dark_threshold = settings_used.get("dark_threshold", 30.0)
    bright_threshold = settings_used.get("bright_threshold", 240.0)
    detect_duplicates = settings_used.get("duplicate_hash", True)

    try:
        raw_bytes = target.read_bytes()
        w, h, brightness, blur = _analyze_image(raw_bytes)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise SelectionValidationError(f"画像を解析できませんでした: {e!r}") from e

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

    duplicate_of = None
    if detect_duplicates:
        digest = hashlib.sha1(raw_bytes).hexdigest()
        for other in items:
            if other is it:
                continue
            if other.get("hash") == digest:
                duplicate_of = other.get("image_id")
                warnings.append("duplicate_image")
                reasons.append("重複画像です")
                break
    else:
        digest = it.get("hash")

    status = "review" if warnings else "included"
    it.update(
        status=status, status_source="auto", warnings=warnings, reasons=reasons,
        hash=digest, brightness_mean=brightness, blur_score=blur,
        duplicate_of=duplicate_of, manual_reason=None,
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )

    all_items = [SelectionItem(**x) for x in items]
    data["summary"] = _summarize(all_items).model_dump()
    paths.selection_path(name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return SelectionItem(**it)


def rotate_image(name: str, image_id: str, source: str, angle: int) -> SelectionRotateResponse:
    """画像を回転保存する。raw と processed の両方（存在する側）に適用し、
    どの表示（選別・前処理・アノテーション）でも向きが一致するようにする。
    processed はプリ生成サムネイルも再生成する。source は無視して両方を回す。
    """
    _require_project(name)
    # runningジョブが同じ画像ファイルをPILで読み込み中に本体を書き換えると、
    # 解析結果（selection.json）と実ファイルの内容が食い違うため拒否する。
    _guard_no_active_run(name)
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
    # selection.json を書き換えるため、実行中のrunと同様に競合対象として保護する。
    _guard_no_active_run(name)
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
