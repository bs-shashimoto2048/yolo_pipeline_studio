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
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _acquire_job_lock(lock_path: Path, timeout: float = 5.0) -> None:
    """job.json 更新用の簡易ファイルロック（排他生成方式）。

    video_service._acquire_file_lock と同じ方式・同じロックファイル名（job.json.lock）を
    使うことで、FastAPI側（設定PATCH/停止）とワーカー側の read-modify-write を直列化する。
    ワーカーは別プロセスのため video_service を毎回importするより、この小さな
    ロジックだけをここでも持つ方が明快で依存も増えない（_terminate_existing_worker等、
    ワーカー関連コードで既に採用している自己完結スタイルと同じ）。
    """
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except OSError:
            # 通常は FileExistsError（他者がロック保持中）だが、Windowsでは
            # 削除直後の再生成タイミングで PermissionError になることもあるため
            # OSError全体を「今は取れない」として扱い、リトライへ回す。
            if time.time() > deadline:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                deadline = time.time() + timeout
                continue
            time.sleep(0.05)


def _release_job_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        pass


def _update_job(job_json: Path, **fields: object) -> None:
    lock_path = Path(str(job_json) + ".lock")
    _acquire_job_lock(lock_path)
    try:
        try:
            data = json.loads(job_json.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.update(fields)
        job_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        _release_job_lock(lock_path)


def _mask_url_credentials(url: str) -> str:
    """ログ・エラーメッセージ表示用に、URL中の認証情報（user:password@host）をマスクする。

    video_service.mask_url_credentials と同じロジック。ワーカーは接続失敗時など
    video_service を経由しない場面でも表示用マスクを必ず使えるよう、自己完結で持つ。
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if not parsed.password:
        return url
    user = parsed.username or ""
    host = parsed.hostname or ""
    netloc = f"{user}:***@{host}" if user else f"***@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


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


def _open_camera(cv2, source_type: str, source: str):
    """映像ソースを開く。

    - source_type=="camera": ローカルカメラのdevice index。Windowsでは DSHOW を使う。
    - source_type=="url": RTSP/HTTP(MJPEG)等のネットワークストリームURL。FFMPEGバックエンドで開く。
    遅延低減のため、いずれもバッファを最小化する。
    """
    if source_type == "url":
        backend = getattr(cv2, "CAP_FFMPEG", 0)
        cap = cv2.VideoCapture(source, backend) if backend else cv2.VideoCapture(source)
        try:
            # 接続/読み取りが固まった場合に無限待機しないためのタイムアウト（対応バージョンのみ有効）
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
        except Exception:  # noqa: BLE001
            pass
    else:
        backend = getattr(cv2, "CAP_DSHOW", 0)
        index = int(source)
        cap = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 古いフレームを溜めない（遅延・カクつき低減）
    except Exception:  # noqa: BLE001
        pass
    return cap


def _refresh_live_settings(job_json: Path, args: argparse.Namespace) -> bool:
    """job.json の可変設定（FPS・推論パラメータ）を読み直し、args に反映する。

    APIから実行中ジョブの設定変更（video_fps/infer_fps/conf/iou/imgsz/device）を
    受けると job.json のこれらのフィールドが更新される。ワーカーは定期的にこれを
    読み直して即時反映する（カメラ/URL/モデル/前処理は再接続が必要なため対象外）。

    戻り値: video_fps/infer_fps が変化したか（呼び出し側でタイミング計算を再計算する必要がある）。
    """
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    fps_changed = False
    vf, inf = data.get("video_fps"), data.get("infer_fps")
    if isinstance(vf, (int, float)) and isinstance(inf, (int, float)):
        vf = max(1, int(vf))
        inf = max(1, min(vf, int(inf)))
        if vf != args.video_fps or inf != args.infer_fps:
            args.video_fps, args.infer_fps = vf, inf
            fps_changed = True
    if isinstance(data.get("conf"), (int, float)):
        args.conf = float(data["conf"])
    if isinstance(data.get("iou"), (int, float)):
        args.iou = float(data["iou"])
    if isinstance(data.get("imgsz"), (int, float)):
        args.imgsz = int(data["imgsz"])
    if isinstance(data.get("device"), str) and data["device"]:
        args.device = data["device"]
    return fps_changed


def _source_label(source_type: str, source: str) -> str:
    if source_type == "camera":
        return f"カメラ {source}"
    return f"映像URL {_mask_url_credentials(source)}"


def _probe_url(url: str, timeout: float = 4.0) -> str | None:
    """URL映像ソースが開けない場合の追加診断（HTTP到達性/認証状態）。

    cv2.VideoCapture の失敗理由は詳細が分かりにくいため、素のHTTPリクエストで
    ステータスコードだけでも取得し、原因（認証必要/到達不能等）を利用者に示す。
    問題を特定できた場合はその説明文を返し、特定できない/正常だった場合は None。
    """
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "YTS-VideoProbe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout):  # noqa: S310
            return None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return (
                f"HTTP {e.code} {e.reason}: このURLは認証が必要です。"
                "URLに 'http://ユーザー名:パスワード@ホスト/...' の形式で認証情報を埋め込んでください。"
            )
        return f"HTTP {e.code} {e.reason} が返されました。URL・アクセス権を確認してください。"
    except urllib.error.URLError as e:
        return f"接続できません（{e.reason}）。IPアドレス/ポート、ネットワーク到達性（同一LAN/VPN）を確認してください。"
    except Exception as e:  # noqa: BLE001
        return None  # 診断できなければ元のメッセージのみ表示


def _remember_url_source(job_json: Path, backend_dir: str) -> None:
    """接続確立が確認できた時点で、そのURLをプロジェクト単位のURL履歴に直接記録する。

    FastAPI側のポーリング（get_job呼び出し）でも記憶されるが、それはブラウザが
    定期的に状態取得するのに依存するため、ページ再読み込み等でポーリングが
    途切れると記憶されないままになる。接続確立を確認した「このタイミング」で
    確実に記録することで、フロントの状態に依存しない経路を確保する。
    """
    try:
        job_data = json.loads(job_json.read_text(encoding="utf-8-sig"))
        raw_url = job_data.get("source_url")
        if not raw_url:
            return
        sys.path.insert(0, backend_dir)
        from app.services import video_service  # noqa: PLC0415
        video_dir = job_json.parent.parent  # .../video/<vid>/job.json -> .../video
        video_service._remember_source_at(video_dir, job_json.parent.name, raw_url)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] URL履歴の記録に失敗（映像取得自体には影響しません）: {e!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--live-dir", required=True)
    ap.add_argument("--weight", required=True)
    ap.add_argument("--backend-dir", required=True)
    ap.add_argument("--source-type", default="camera")  # camera | url
    ap.add_argument("--source", default="0")  # camera: device index文字列 / url: ストリームURL
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
    print(f"[INFO] 映像推論開始 source_type={args.source_type} "
          f"source={_mask_url_credentials(args.source)} "
          f"video_fps={args.video_fps} infer_fps={args.infer_fps} device={args.device}")

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

    # 初回オープンは数回リトライ（カメラ検出直後などは掴まれていることがある／URLは接続待ち）
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
        _remember_url_source(job_json, args.backend_dir)

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
        last_settings_check = time.time()
        settings_check_interval = 1.0  # FPS・推論設定の即時反映チェック間隔（秒）

        while time.time() < deadline:
            if _stopped(stop_flag, job_json):
                break

            if time.time() - last_settings_check >= settings_check_interval:
                last_settings_check = time.time()
                if _refresh_live_settings(job_json, args):
                    video_interval = 1.0 / max(1, args.video_fps)
                    infer_every = max(1, round(args.video_fps / max(1, args.infer_fps)))
                    max_read_fail = max(10, args.video_fps * 3)
                    next_tick = time.time()
                    print(f"[INFO] FPS設定を反映: video_fps={args.video_fps} infer_fps={args.infer_fps}")
                predict_kwargs = dict(conf=args.conf, iou=args.iou, imgsz=args.imgsz, verbose=False)
                if args.device and args.device != "auto":
                    predict_kwargs["device"] = args.device

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
                    last_annotated = results[0].plot(conf=False)  # BGR ndarray（ラベルは値のみ、信頼度は非表示）
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
