"""映像（カメラ）推論ワーカー（別プロセス）。

OpenCV でカメラを開き、video_fps でキャプチャ、infer_fps（間引き）で推論し、
注釈フレームを live/latest.jpg に原子的に書き出す。FastAPI 側がそれを MJPEG 配信する。

YTS_VIDEO_DRY_RUN=1 のときはカメラ/Ultralyticsを使わず合成フレームを書き出して
プラグイン疎通だけ確認する（テスト用）。
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

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _update_job(job_json: Path, **fields: object) -> None:
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.update(fields)
    job_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _stopped(stop_flag: Path, job_json: Path) -> bool:
    if stop_flag.exists():
        return True
    try:
        st = json.loads(job_json.read_text(encoding="utf-8-sig")).get("status")
        return st in ("stopped", "failed", "completed")
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _atomic_write_jpg_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp.jpg")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, path)
    except OSError:
        # 配信側が読み取り中などで置換に失敗しても次フレームで回復する
        pass


def _open_camera(cv2, index: int):
    """カメラを開く。Windowsでは DSHOW を使い、遅延低減のためバッファを最小化する。"""
    backend = getattr(cv2, "CAP_DSHOW", 0)
    cap = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 古いフレームを溜めない（遅延・カクつき低減）
    except Exception:  # noqa: BLE001
        pass
    return cap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--live-dir", required=True)
    ap.add_argument("--weight", required=True)
    ap.add_argument("--backend-dir", required=True)
    ap.add_argument("--camera-index", type=int, default=0)
    ap.add_argument("--video-fps", type=int, default=15)
    ap.add_argument("--infer-fps", type=int, default=5)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.7)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--preprocess-json", default="")
    args = ap.parse_args()

    job_json = Path(args.job_json)
    live_dir = Path(args.live_dir)
    live_dir.mkdir(parents=True, exist_ok=True)
    latest = live_dir / "latest.jpg"
    stop_flag = live_dir.parent / "stop.flag"
    video_interval = 1.0 / max(1, args.video_fps)
    infer_every = max(1, round(args.video_fps / max(1, args.infer_fps)))

    _update_job(job_json, status="running", started_at=_now(), message="running")
    print(f"[INFO] 映像推論開始 camera={args.camera_index} video_fps={args.video_fps} "
          f"infer_fps={args.infer_fps} device={args.device}")

    # --- dry-run: 合成フレームを書いて停止待ち ---
    if os.environ.get("YTS_VIDEO_DRY_RUN"):
        from PIL import Image  # noqa: PLC0415
        import io as _io
        for n in range(100000):
            if _stopped(stop_flag, job_json):
                break
            buf = _io.BytesIO()
            Image.new("RGB", (320, 240), (30 + n % 40, 60, 120)).save(buf, format="JPEG")
            _atomic_write_jpg_bytes(latest, buf.getvalue())
            time.sleep(0.2)
        _update_job(job_json, status="stopped", finished_at=_now(), message="dry run stopped")
        return 0

    # --- 実処理 ---
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        _update_job(job_json, status="failed", finished_at=_now(),
                    message=f"OpenCV/numpy が読み込めません: {e!r}")
        return 1

    # 前処理設定（任意）
    pre_settings = None
    if args.preprocess_json:
        try:
            sys.path.insert(0, args.backend_dir)
            from app.schemas.preprocess import PreprocessSettings  # noqa: PLC0415
            from app.services import preprocess_service  # noqa: PLC0415
            pre_settings = PreprocessSettings(**json.loads(Path(args.preprocess_json).read_text(encoding="utf-8-sig")))
            _pp = preprocess_service
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 前処理設定の読込に失敗（前処理なしで継続）: {e!r}")
            pre_settings = None

    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        _update_job(job_json, status="failed", finished_at=_now(),
                    message="ultralytics が未導入です（requirements-train.txt を導入してください）")
        print(f"[ERROR] {e!r}")
        return 1

    # 初回オープンは数回リトライ（カメラ検出直後などは掴まれていることがある）
    cap = _open_camera(cv2, args.camera_index)
    for _ in range(5):
        if cap.isOpened():
            break
        try:
            cap.release()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.6)
        cap = _open_camera(cv2, args.camera_index)
    if not cap.isOpened():
        _update_job(job_json, status="failed", finished_at=_now(),
                    message=f"カメラ {args.camera_index} を開けませんでした。接続/使用中（他アプリの占有）を確認してください。")
        return 1

    try:
        model = YOLO(args.weight)
        predict_kwargs = dict(conf=args.conf, iou=args.iou, imgsz=args.imgsz, verbose=False)
        if args.device and args.device != "auto":
            predict_kwargs["device"] = args.device

        frame_no = 0
        last_annotated = None
        deadline = time.time() + 1800  # 安全のため最大30分
        read_fail = 0
        # 約3秒読めなければカメラを開き直す（一時的な切断・ドライバ不調からの自動復帰）
        max_read_fail = max(10, args.video_fps * 3)
        reconnects = 0
        next_tick = time.time()

        while time.time() < deadline:
            if _stopped(stop_flag, job_json):
                break
            ok, frame = cap.read()
            if not ok or frame is None:
                read_fail += 1
                if read_fail >= max_read_fail:
                    reconnects += 1
                    print(f"[WARN] フレーム読み取りが {read_fail} 回連続失敗。カメラを再接続します（{reconnects}回目）。")
                    _update_job(job_json, message=f"カメラ再接続中…（{reconnects}回目）")
                    try:
                        cap.release()
                    except Exception:  # noqa: BLE001
                        pass
                    time.sleep(0.5)
                    cap = _open_camera(cv2, args.camera_index)
                    read_fail = 0
                    if cap.isOpened():
                        _update_job(job_json, status="running", message="running")
                    else:
                        time.sleep(1.0)
                else:
                    time.sleep(video_interval)
                continue
            read_fail = 0

            # 前処理（フレームへ適用）
            if pre_settings is not None:
                try:
                    okj, buf = cv2.imencode(".jpg", frame)
                    if okj:
                        pil = _pp.apply(buf.tobytes(), pre_settings)
                        frame = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
                except Exception:  # noqa: BLE001
                    pass

            if frame_no % infer_every == 0:
                try:
                    results = model.predict(frame, **predict_kwargs)
                    last_annotated = results[0].plot()  # BGR ndarray
                except Exception as e:  # noqa: BLE001
                    print(f"[WARN] 推論に失敗（フレームスキップ）: {e!r}")

            out = last_annotated if last_annotated is not None else frame
            okj, buf = cv2.imencode(".jpg", out)
            if okj:
                _atomic_write_jpg_bytes(latest, buf.tobytes())
            frame_no += 1

            # 目標フレーム時刻までスリープ（推論に時間がかかり遅れた場合は待たずにドロップ）
            next_tick += video_interval
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.time()  # 大きく遅れたら基準をリセット

        if not _stopped(stop_flag, job_json):
            _update_job(job_json, status="completed", finished_at=_now(), message="時間上限で終了")
        else:
            _update_job(job_json, status="stopped", finished_at=_now(), message="stopped")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _update_job(job_json, status="failed", finished_at=_now(), message=f"映像推論失敗: {e!r}")
        return 1
    finally:
        try:
            cap.release()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
