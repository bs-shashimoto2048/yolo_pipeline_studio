"""カメラ/URL映像のプレビュー表示＋静止画撮影ワーカー（別プロセス）。

プロジェクト準備（画像取り込み）段階では学習済みモデルがまだ無いため、
`predict_video_worker.py`（YOLO推論を伴う映像テスト）とは別に、推論なしで
軽量にプレビュー＋撮影だけを行う。カメラ/URLのオープン・再接続ロジックは
`predict_video_worker.py` の関数をそのまま再利用し、実装の重複を避けている。

- video_fps でプレビューフレームを live/latest.jpg に書き出す（FastAPI側がMJPEG配信）。
- capture.flag が置かれたら次フレームを raw/images へ保存し、flagを削除してjob.jsonを更新する。
- interval_minutes（>0）が設定されていれば、その間隔で自動的に同様の保存を行う。
- 撮影画像は image_service.save_uploads 経由で保存し、重複/破損チェック・
  ファイル名正規化を既存の画像取り込みと完全に同じ規約にする。
- 停止は stop.flag。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from predict_video_worker import (  # noqa: E402
    _atomic_write_jpg_bytes,
    _now,
    _open_camera,
    _probe_url,
    _source_label,
    _stopped,
    _update_job,
)


def _iso_at(epoch: float | None) -> str | None:
    """epoch秒（time.time()系）をISO文字列へ変換する（フロント側でカウントダウン表示に使う）。"""
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds") if epoch is not None else None


def _next_aligned_epoch(interval_seconds: float, now: float) -> float:
    """次回自動撮影のepoch秒を「壁時計基準」で計算する。

    同じ間隔の複数ソースが、開始タイミングに関わらず同じ絶対時刻（UNIX epochの
    interval_seconds区切り、例: 5分間隔なら毎時00分・05分・10分…）で発火するように
    することで、中央の一斉トリガー機構なしに複数ソースの同時撮影を実現する
    （capture_service.next_aligned_time と同じ考え方）。
    """
    if interval_seconds <= 0:
        return now
    return (now // interval_seconds + 1) * interval_seconds


def _remember_url_source_shared(job_json: Path, backend_dir: str) -> None:
    """接続確立が確認できた時点で、URLをプロジェクト共通のURL履歴へ記録する。

    known_sources.json は `projects/<name>/video/` 配下（映像推論テストと共有）。
    job_json は `projects/<name>/capture/<sid>/job.json` なので、プロジェクト直下から
    たどり直す（capture/ ではなく video/ を明示的に指すため2階層分の単純な遡上では不可）。
    """
    try:
        job_data = json.loads(job_json.read_text(encoding="utf-8-sig"))
        raw_url = job_data.get("source_url")
        if not raw_url:
            return
        sys.path.insert(0, backend_dir)
        from app.services import video_service  # noqa: PLC0415
        project_dir = job_json.parents[2]  # .../projects/<name>/capture/<sid>/job.json -> .../projects/<name>
        video_dir = project_dir / "video"
        video_service._remember_source_at(video_dir, job_json.parent.name, raw_url)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] URL履歴の記録に失敗（撮影自体には影響しません）: {e!r}")


def _save_captured_frame(job_json: Path, backend_dir: str, raw_images_dir: Path, frame, cv2) -> tuple[str | None, str | None]:
    """フレームを image_service.save_uploads 経由で raw/images に保存する。

    既存の画像取り込み（フォルダ一括取り込み・個別アップロード）と同じ
    拡張子/重複(SHA1)/破損(PIL検証)チェック・ファイル名正規化を通すことで、
    撮影画像も後続の画像選別・アノテーション工程にそのまま合流できるようにする。

    戻り値: (保存されたファイル名 or None, 失敗時のメッセージ or None)
    """
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return None, "フレームのJPEGエンコードに失敗しました。"
    try:
        sys.path.insert(0, backend_dir)
        from app.services import image_service  # noqa: PLC0415
        project_name = job_json.parents[2].name
        session_id = job_json.parent.name
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{session_id}_{ts}.jpg"
        result = image_service.save_uploads(project_name, [(filename, buf.tobytes())])
        if not result.results:
            return None, "保存結果が空でした。"
        item = result.results[0]
        if item.status == "added" and item.stored_name:
            return item.stored_name, None
        return None, f"保存されませんでした（{item.status}: {item.detail}）"
    except Exception as e:  # noqa: BLE001
        return None, f"保存に失敗しました: {e!r}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--live-dir", required=True)
    ap.add_argument("--raw-images-dir", required=True)
    ap.add_argument("--backend-dir", required=True)
    ap.add_argument("--source-type", default="camera")  # camera | url
    ap.add_argument("--source", default="0")
    ap.add_argument("--video-fps", type=int, default=10)
    ap.add_argument("--interval-minutes", type=float, default=0.0)  # 0以下なら手動撮影のみ
    args = ap.parse_args()

    job_json = Path(args.job_json)
    live_dir = Path(args.live_dir)
    live_dir.mkdir(parents=True, exist_ok=True)
    raw_images_dir = Path(args.raw_images_dir)
    latest = live_dir / "latest.jpg"
    stop_flag = live_dir.parent / "stop.flag"
    capture_flag = live_dir.parent / "capture.flag"
    video_interval = 1.0 / max(1, args.video_fps)

    _update_job(job_json, status="running", started_at=_now(), message="running")
    print(f"[INFO] 撮影セッション開始 source_type={args.source_type} source={args.source} "
          f"video_fps={args.video_fps} interval_minutes={args.interval_minutes}")

    # --- dry-run: 合成フレームで疎通確認（テスト用、カメラ/ネットワーク不要） ---
    if os.environ.get("YTS_CAPTURE_DRY_RUN"):
        from PIL import Image  # noqa: PLC0415
        import io as _io  # noqa: PLC0415
        import numpy as _np  # noqa: PLC0415

        class _DryCap:
            def isOpened(self) -> bool:
                return True

            def read(self):
                arr = _np.full((240, 320, 3), 80, dtype=_np.uint8)
                return True, arr

            def release(self) -> None:
                pass

        cv2 = None  # noqa: N806 - imencode の代わりに PIL を使うためダミー
        cap = _DryCap()
        interval_seconds = args.interval_minutes * 60.0 if args.interval_minutes and args.interval_minutes > 0 else 0.0
        next_auto_capture = _next_aligned_epoch(interval_seconds, time.time()) if interval_seconds > 0 else None
        _update_job(job_json, next_auto_capture_at=_iso_at(next_auto_capture))
        captured_count = 0
        deadline = time.time() + 60
        frame_no = 0
        while time.time() < deadline:
            if _stopped(stop_flag, job_json):
                break
            # 実カメラのフレームは撮影ごとに微妙に変化するため、重複排除(SHA1)で
            # 弾かれないよう色を変えて疑似的な変化を再現する（predict_video_worker.py の
            # dry-runと同様のパターン）。
            buf = _io.BytesIO()
            Image.new("RGB", (320, 240), (30 + frame_no % 200, 60, 120)).save(buf, format="JPEG")
            frame_no += 1
            _atomic_write_jpg_bytes(latest, buf.getvalue())

            do_capture = capture_flag.exists()
            if do_capture:
                try:
                    capture_flag.unlink()
                except OSError:
                    pass
            if next_auto_capture is not None and time.time() >= next_auto_capture:
                do_capture = True
                next_auto_capture = _next_aligned_epoch(interval_seconds, time.time())
                _update_job(job_json, next_auto_capture_at=_iso_at(next_auto_capture))
            if do_capture:
                try:
                    sys.path.insert(0, args.backend_dir)
                    from app.services import image_service  # noqa: PLC0415
                    project_name = job_json.parents[2].name
                    session_id = job_json.parent.name
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{session_id}_{ts}.jpg"
                    result = image_service.save_uploads(project_name, [(filename, buf.getvalue())])
                    item = result.results[0] if result.results else None
                    if item and item.status == "added" and item.stored_name:
                        captured_count += 1
                        _update_job(job_json, captured_count=captured_count, last_captured_at=_now(),
                                    last_captured_filename=item.stored_name,
                                    message=f"{captured_count}枚撮影済み（最新: {item.stored_name}, dry-run）")
                    elif item:
                        # 実処理側(_save_captured_frame)と同様、addedにならなかった場合も
                        # 原因をログへ残す（以前は無条件に無視され、原因不明のまま撮影枚数が
                        # 増えないという不具合が判明した。Issue #4 Checkpoint 2）。
                        print(f"[WARN] dry-run撮影が保存されませんでした（{item.status}: {item.detail}）")
                    else:
                        print("[WARN] dry-run撮影の保存結果が空でした。")
                except Exception as e:  # noqa: BLE001
                    print(f"[WARN] dry-run撮影に失敗: {e!r}")
            time.sleep(0.2)
        _update_job(job_json, status="stopped", finished_at=_now(), message="dry run stopped")
        return 0

    try:
        import cv2  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        _update_job(job_json, status="failed", finished_at=_now(),
                    message=f"OpenCV が読み込めません: {e!r}")
        return 1

    cap = _open_camera(cv2, args.source_type, args.source)
    for _ in range(5):
        if cap.isOpened():
            break
        try:
            cap.release()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.6)
        cap = _open_camera(cv2, args.source_type, args.source)
    if not cap.isOpened():
        label = _source_label(args.source_type, args.source)
        if args.source_type == "camera":
            hint = "接続/使用中（他アプリの占有）を確認してください。"
        else:
            hint = _probe_url(args.source) or (
                "URLが正しいか、ネットワークカメラに到達できるか（同一LAN/認証不要か）を確認してください。"
            )
        _update_job(job_json, status="failed", finished_at=_now(),
                    message=f"{label} を開けませんでした。{hint}")
        return 1

    if args.source_type == "url":
        _remember_url_source_shared(job_json, args.backend_dir)

    read_fail = 0
    max_read_fail = max(10, args.video_fps * 3)
    reconnects = 0
    deadline = time.time() + 3600 * 6  # 撮影は長時間の運用も想定し上限6時間
    next_tick = time.time()
    interval_seconds = args.interval_minutes * 60.0 if args.interval_minutes and args.interval_minutes > 0 else 0.0
    next_auto_capture = _next_aligned_epoch(interval_seconds, time.time()) if interval_seconds > 0 else None
    _update_job(job_json, next_auto_capture_at=_iso_at(next_auto_capture))
    captured_count = int((json.loads(job_json.read_text(encoding="utf-8-sig")) or {}).get("captured_count") or 0)

    try:
        while time.time() < deadline:
            if _stopped(stop_flag, job_json):
                break
            ok, frame = cap.read()
            if not ok or frame is None:
                read_fail += 1
                if read_fail >= max_read_fail:
                    reconnects += 1
                    label = _source_label(args.source_type, args.source)
                    print(f"[WARN] フレーム読み取りが {read_fail} 回連続失敗。{label} を再接続します（{reconnects}回目）。")
                    _update_job(job_json, message=f"再接続中…（{reconnects}回目）")
                    try:
                        cap.release()
                    except Exception:  # noqa: BLE001
                        pass
                    time.sleep(0.5)
                    cap = _open_camera(cv2, args.source_type, args.source)
                    read_fail = 0
                    if cap.isOpened():
                        _update_job(job_json, status="running", message="running")
                    else:
                        time.sleep(1.0)
                else:
                    time.sleep(video_interval)
                continue
            read_fail = 0

            okj, buf = cv2.imencode(".jpg", frame)
            if okj:
                _atomic_write_jpg_bytes(latest, buf.tobytes())

            do_capture = False
            if capture_flag.exists():
                do_capture = True
                try:
                    capture_flag.unlink()
                except OSError:
                    pass
            if next_auto_capture is not None and time.time() >= next_auto_capture:
                do_capture = True
                next_auto_capture = _next_aligned_epoch(interval_seconds, time.time())
                _update_job(job_json, next_auto_capture_at=_iso_at(next_auto_capture))

            if do_capture:
                filename, err = _save_captured_frame(job_json, args.backend_dir, raw_images_dir, frame, cv2)
                if filename:
                    captured_count += 1
                    _update_job(
                        job_json,
                        captured_count=captured_count,
                        last_captured_at=_now(),
                        last_captured_filename=filename,
                        message=f"{captured_count}枚撮影済み（最新: {filename}）",
                    )
                    print(f"[INFO] 撮影しました: {filename}")
                else:
                    print(f"[WARN] 撮影に失敗しました: {err}")

            next_tick += video_interval
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.time()

        if not _stopped(stop_flag, job_json):
            _update_job(job_json, status="completed", finished_at=_now(), message="時間上限で終了")
        else:
            _update_job(job_json, status="stopped", finished_at=_now(), message="stopped")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _update_job(job_json, status="failed", finished_at=_now(), message=f"撮影セッション失敗: {e!r}")
        return 1
    finally:
        try:
            cap.release()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
