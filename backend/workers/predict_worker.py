"""YOLO推論を実行するワーカー（FastAPI本体とは別プロセス）。

prediction_service から subprocess.Popen で起動される。標準出力/標準エラーは
親プロセス側で predict.log にリダイレクトされる。

app パッケージには依存せず、引数で受け取った絶対パスだけで動作する。

環境変数 YTS_PREDICT_DRY_RUN=1 のときは Ultralytics を読み込まず推論も行わず、
入力画像を結果画像としてコピーし results.json（検出0件）を生成して completed に
する（軽量テスト用）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

# 標準出力/標準エラーを UTF-8 に固定（WindowsのCP932による文字化け防止）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

_IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _update_job(job_json: Path, **fields: object) -> None:
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.update(fields)
    job_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _rel_posix(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _input_images(inputs_dir: Path) -> list[Path]:
    return sorted(
        p for p in inputs_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )


def _write_results(
    job_json: Path,
    results_json: Path,
    project_dir: Path,
    results: list[dict],
    detection_count: int,
) -> None:
    job = {}
    try:
        job = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    payload = {
        "predict_job_id": job.get("predict_job_id"),
        "train_job_id": job.get("train_job_id"),
        "weight_type": job.get("weight_type"),
        "preprocess_mode": job.get("preprocess_mode"),
        "created_at": job.get("created_at"),
        "image_count": len(results),
        "detection_count": detection_count,
        "results": results,
    }
    results_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--inputs-dir", required=True)
    ap.add_argument("--predict-dir", required=True)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--weight", required=True)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.7)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--save-txt", action="store_true")
    ap.add_argument("--save-conf", action="store_true")
    args = ap.parse_args()

    job_json = Path(args.job_json)
    inputs_dir = Path(args.inputs_dir)
    predict_dir = Path(args.predict_dir)
    project_dir = Path(args.project_dir)
    weight = Path(args.weight)
    out_images = predict_dir / "outputs" / "images"
    out_images.mkdir(parents=True, exist_ok=True)
    results_json = predict_dir / "results.json"

    # 1) running
    _update_job(job_json, status="running", started_at=_now(), message="predicting")
    print(f"[INFO] 推論開始 weight={weight.name} conf={args.conf} iou={args.iou} "
          f"imgsz={args.imgsz} device={args.device}")

    # 2) モデル存在確認
    if not weight.exists():
        print(f"[ERROR] モデルが見つかりません: {weight}")
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message="モデルファイルが見つかりません")
        return 1

    # dry-run: 入力画像を結果画像としてコピーし、検出0件の results.json を生成
    if os.environ.get("YTS_PREDICT_DRY_RUN"):
        print("[INFO] DRY RUN: Ultralytics を読み込まず推論をスキップします。")
        results = []
        for img in _input_images(inputs_dir):
            shutil.copy2(img, out_images / img.name)
            results.append({
                "image_id": img.stem,
                "image_name": img.name,
                "result_image_path": _rel_posix(out_images / img.name, project_dir),
                "detections": [],
            })
        _write_results(job_json, results_json, project_dir, results, 0)
        _update_job(job_json, status="completed", finished_at=_now(), return_code=0,
                    message="dry run completed", image_count=len(results),
                    detection_count=0)
        return 0

    # 3) Ultralytics 読み込み
    try:
        from ultralytics import YOLO
    except Exception as e:  # noqa: BLE001
        print("[ERROR] ultralytics を読み込めませんでした。")
        print("        requirements-train.txt を導入してください:")
        print("        pip install -r requirements-train.txt")
        print(f"        詳細: {e!r}")
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message="ultralytics が未導入です（requirements-train.txt を導入してください）")
        return 1

    # 4) 推論実行
    try:
        model = YOLO(str(weight))
        kwargs = dict(
            source=str(inputs_dir),
            conf=args.conf,
            iou=args.iou,
            imgsz=args.imgsz,
            save=True,
            save_txt=args.save_txt,
            save_conf=args.save_conf,
            project=str(predict_dir),
            name="outputs",
            exist_ok=True,
        )
        if args.device and args.device != "auto":
            kwargs["device"] = args.device

        preds = model.predict(**kwargs)

        results = []
        detection_count = 0
        for r in preds:
            src_path = Path(r.path)
            image_name = src_path.name
            save_dir = Path(r.save_dir)
            saved = save_dir / image_name
            # Ultralyticsは save_dir 直下に注釈画像を保存するので images/ へ移動
            if saved.exists() and saved.resolve() != (out_images / image_name).resolve():
                shutil.move(str(saved), str(out_images / image_name))

            detections = []
            boxes = getattr(r, "boxes", None)
            names = getattr(r, "names", {}) or {}
            if boxes is not None and len(boxes) > 0:
                xywhn = boxes.xywhn.tolist()
                cls = boxes.cls.tolist()
                conf = boxes.conf.tolist()
                for (xc, yc, w, h), c, cf in zip(xywhn, cls, conf):
                    cid = int(c)
                    detections.append({
                        "class_id": cid,
                        "class_name": names.get(cid, str(cid)),
                        "confidence": float(cf),
                        "x_center": float(xc),
                        "y_center": float(yc),
                        "width": float(w),
                        "height": float(h),
                    })
            detection_count += len(detections)
            results.append({
                "image_id": src_path.stem,
                "image_name": image_name,
                "result_image_path": _rel_posix(out_images / image_name, project_dir),
                "detections": detections,
            })

        _write_results(job_json, results_json, project_dir, results, detection_count)
        _update_job(job_json, status="completed", finished_at=_now(), return_code=0,
                    message="completed", image_count=len(results),
                    detection_count=detection_count)
        print(f"[INFO] 推論完了: 画像 {len(results)} 件 / 検出 {detection_count} 件")
        return 0
    except Exception as e:  # noqa: BLE001
        print("[ERROR] 推論中に例外が発生しました:")
        traceback.print_exc()
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message=f"推論失敗: {e!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
