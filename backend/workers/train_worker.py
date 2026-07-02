"""YOLO学習を実行するワーカー（FastAPI本体とは別プロセス）。

training_service から subprocess.Popen で起動される。標準出力/標準エラーは
親プロセス側で train.log にリダイレクトされる。

app パッケージには依存せず、引数で受け取った絶対パスだけで動作する
（独立スクリプトとして起動できるようにするため）。

環境変数 YTS_TRAIN_DRY_RUN=1 のときは Ultralytics を読み込まず学習も行わず、
プラグイン疎通確認用に completed にする（軽量テスト用）。
"""

from __future__ import annotations

import argparse
import json
import os
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


def _summarize_error(text: str) -> str:
    """例外/ログ文字列から分かりやすいエラー要約を作る。"""
    low = text.lower()
    if "images not found" in low or "missing path" in low:
        return "data.yaml の画像パスが見つかりません。データセットを再作成してください。"
    if "cuda out of memory" in low:
        return "GPUメモリ不足です。batch を下げるか imgsz を小さくしてください。"
    if "no module named 'ultralytics'" in low:
        return "ultralytics が未導入です。requirements-train.txt または Windows GPU 導入手順を確認してください。"
    if "no module named 'torch'" in low:
        return "torch が未導入です。requirements-train.txt または Windows GPU 導入手順を確認してください。"
    if "cuda is not available" in low or "torch not compiled with cuda" in low:
        return "CUDAが利用できません。CUDA対応PyTorchが入っているか確認してください。"
    return f"学習失敗: {text[:200]}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _update_job(job_json: Path, **fields: object) -> None:
    """job.json を読み込み、指定フィールドを更新して書き戻す。"""
    try:
        # utf-8-sig: 万一BOM付きで書かれていてもjob_id等を失わないように
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.update(fields)
    job_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _rel_posix(path: Path, base: Path) -> str | None:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--data-yaml", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    job_json = Path(args.job_json)
    data_yaml = Path(args.data_yaml)
    run_dir = Path(args.run_dir)
    project_dir = Path(args.project_dir)

    # 1) data.yaml の確認
    if not data_yaml.exists():
        print(f"[ERROR] data.yaml が見つかりません: {data_yaml}")
        _update_job(
            job_json,
            status="failed",
            finished_at=_now(),
            return_code=1,
            message="data.yaml が見つかりません",
        )
        return 1

    # job.json から学習時オーギュメンテーション設定を読む（後方互換: 無ければ空）
    aug_params: dict = {}
    try:
        _job = json.loads(job_json.read_text(encoding="utf-8-sig"))
        aug_params = _job.get("augmentation_params") or {}
    except (FileNotFoundError, json.JSONDecodeError):
        aug_params = {}

    # 2) running へ更新
    _update_job(job_json, status="running", started_at=_now(), message="training")
    print(f"[INFO] 学習開始 model={args.model} epochs={args.epochs} "
          f"imgsz={args.imgsz} batch={args.batch} device={args.device}")

    # 軽量テスト用 dry-run
    if os.environ.get("YTS_TRAIN_DRY_RUN"):
        print("[INFO] DRY RUN: Ultralytics を読み込まず学習をスキップします。")
        _update_job(
            job_json,
            status="completed",
            finished_at=_now(),
            return_code=0,
            message="dry run completed",
        )
        return 0

    # 2.5) data.yaml の train/val 実在を検証（Ultralyticsに渡す前に防御）
    try:
        import yaml  # noqa: PLC0415
        dy = yaml.safe_load(data_yaml.read_text(encoding="utf-8-sig")) or {}
        base = Path(dy.get("path") or data_yaml.parent)
        if not base.is_absolute():
            base = (data_yaml.parent / base).resolve()
        train_dir = base / dy.get("train", "images/train")
        val_dir = base / dy.get("val", "images/val")
        missing = None
        if not train_dir.exists():
            missing = f"train パスが存在しません: {train_dir.as_posix()}"
        elif not val_dir.exists():
            missing = f"val パスが存在しません: {val_dir.as_posix()}"
        if missing:
            print(f"[ERROR] data.yaml の {missing}")
            _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                        message=f"data.yaml の {missing}。データセットを再作成してください。")
            return 1
    except Exception as e:  # noqa: BLE001 - 検証自体の失敗は致命的ではないので継続
        print(f"[WARN] data.yaml 事前検証に失敗（続行）: {e!r}")

    # 3) Ultralytics 読み込み（未導入なら分かりやすく失敗）
    try:
        from ultralytics import YOLO
    except Exception as e:  # noqa: BLE001
        print("[ERROR] ultralytics を読み込めませんでした。")
        print("        requirements-train.txt を導入してください:")
        print("        pip install -r requirements-train.txt")
        print(f"        詳細: {e!r}")
        _update_job(
            job_json,
            status="failed",
            finished_at=_now(),
            return_code=1,
            message="ultralytics が未導入です（requirements-train.txt を導入してください）",
        )
        return 1

    # 4) 学習実行
    try:
        model = YOLO(args.model)
        train_kwargs = dict(
            data=str(data_yaml),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            workers=args.workers,
            patience=args.patience,
            seed=args.seed,
            project=str(run_dir.parent),
            name=run_dir.name,
            exist_ok=True,  # job.json/train.log を置いた同一ディレクトリへ出力する
            plots=True,  # F1/PR/P/R curve・confusion_matrix 等の成果物を生成
            val=True,
        )
        # device=="auto" は Ultralytics に任せる（引数を渡さない）
        if args.device and args.device != "auto":
            train_kwargs["device"] = args.device

        # 学習時オーギュメンテーション（degrees / mosaic / hsv_* など）を反映
        if aug_params:
            train_kwargs.update(aug_params)

        model.train(**train_kwargs)

        # 5) 結果パスの収集
        best = run_dir / "weights" / "best.pt"
        last = run_dir / "weights" / "last.pt"
        results = run_dir / "results.csv"
        _update_job(
            job_json,
            status="completed",
            finished_at=_now(),
            return_code=0,
            best_model_path=_rel_posix(best, project_dir) if best.exists() else None,
            last_model_path=_rel_posix(last, project_dir) if last.exists() else None,
            results_csv_path=_rel_posix(results, project_dir) if results.exists() else None,
            message="completed",
        )
        print("[INFO] 学習が完了しました。")
        return 0
    except Exception as e:  # noqa: BLE001
        print("[ERROR] 学習中に例外が発生しました:")
        traceback.print_exc()
        _update_job(
            job_json,
            status="failed",
            finished_at=_now(),
            return_code=1,
            message=_summarize_error(f"{e!r} {e}"),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
