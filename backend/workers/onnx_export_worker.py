"""YOLO(.pt) → ONNX エクスポートを実行するワーカー（FastAPI本体とは別プロセス）。

onnx_export_service から subprocess.Popen で起動される。標準出力/標準エラーは
親プロセス側で export.log にリダイレクトされる。app パッケージには依存しない。

環境変数 YTS_ONNX_DRY_RUN=1 のときは Ultralytics を読み込まず、ダミーの model.onnx と
metadata.json を作って completed にする（軽量テスト用）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def _summarize_error(text: str) -> str:
    low = text.lower()
    if "no module named 'ultralytics'" in low:
        return "ultralytics が未導入です。requirements-train.txt または Windows GPU 導入手順を確認してください。"
    if "no module named 'torch'" in low:
        return "torch が未導入です。requirements-train.txt または Windows GPU 導入手順を確認してください。"
    if "onnx" in low and ("no module named" in low or "not installed" in low or "requires" in low):
        return "ONNX関連の依存が不足しています（onnx / onnxruntime / onnxslim）。requirements-train.txt を確認してください。"
    if "out of memory" in low:
        return "GPUメモリ不足です。device=cpu または half=false を試してください。"
    if "no such file" in low or "not exist" in low:
        return "対象の重みファイルが存在しません。学習ジョブまたはweight_typeを確認してください。"
    return f"ONNXエクスポート失敗: {text[:200]}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _update_job(job_json: Path, **fields: object) -> None:
    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.update(fields)
    job_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _rel_posix(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_metadata(export_dir: Path, job: dict, project_dir: Path, onnx_path: Path,
                    source_weight_rel: str, preprocess_required: bool) -> None:
    meta = {
        "export_job_id": job.get("export_job_id"),
        "project_name": job.get("project_name"),
        "train_job_id": job.get("train_job_id"),
        "weight_type": job.get("weight_type"),
        "task": job.get("task"),
        "source_weight_path": source_weight_rel,
        "onnx_path": _rel_posix(onnx_path, project_dir),
        "imgsz": job.get("imgsz"),
        "opset": job.get("opset"),
        "simplify": job.get("simplify"),
        "dynamic": job.get("dynamic"),
        "half": job.get("half"),
        "device": job.get("device"),
        "created_at": job.get("created_at"),
        "finished_at": _now(),
        "classes_path": "classes.json",
        "preprocess_required": preprocess_required,
    }
    (export_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-json", required=True)
    ap.add_argument("--weight", required=True)
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--opset", type=int, default=12)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--task", default="detect")
    ap.add_argument("--source-weight-rel", default="")
    ap.add_argument("--preprocess-required", default="0")
    ap.add_argument("--simplify", action="store_true")
    ap.add_argument("--dynamic", action="store_true")
    ap.add_argument("--half", action="store_true")
    args = ap.parse_args()

    job_json = Path(args.job_json)
    weight = Path(args.weight)
    export_dir = Path(args.export_dir)
    project_dir = Path(args.project_dir)
    onnx_out = export_dir / "model.onnx"
    preprocess_required = args.preprocess_required == "1"

    _update_job(job_json, status="running", started_at=_now(), message="exporting")
    print(f"[INFO] ONNXエクスポート開始 weight={weight.name} imgsz={args.imgsz} "
          f"opset={args.opset} simplify={args.simplify} dynamic={args.dynamic} "
          f"half={args.half} device={args.device}")

    try:
        job = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        job = {}

    if not weight.exists():
        print(f"[ERROR] 重みが見つかりません: {weight}")
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message="対象の重みファイルが存在しません。学習ジョブまたはweight_typeを確認してください。")
        return 1

    # 軽量テスト用 dry-run
    if os.environ.get("YTS_ONNX_DRY_RUN"):
        print("[INFO] DRY RUN: Ultralytics を読み込まず、ダミー model.onnx を生成します。")
        onnx_out.write_bytes(b"ONNXDRYRUN\x00dummy")
        _write_metadata(export_dir, job, project_dir, onnx_out, args.source_weight_rel, preprocess_required)
        _update_job(job_json, status="completed", finished_at=_now(), return_code=0,
                    onnx_path=_rel_posix(onnx_out, project_dir), message="dry run completed")
        print("[INFO] DRY RUN 完了。")
        return 0

    # Ultralytics 読み込み
    try:
        from ultralytics import YOLO
    except Exception as e:  # noqa: BLE001
        print("[ERROR] ultralytics を読み込めませんでした。requirements-train.txt を導入してください。")
        print(f"        詳細: {e!r}")
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message="ultralytics が未導入です（requirements-train.txt を導入してください）")
        return 1

    try:
        model = YOLO(str(weight))
        export_kwargs = dict(
            format="onnx",
            imgsz=args.imgsz,
            opset=args.opset,
            simplify=args.simplify,
            dynamic=args.dynamic,
            half=args.half,
        )
        if args.device and args.device != "auto":
            export_kwargs["device"] = args.device

        exported = model.export(**export_kwargs)

        # 生成された .onnx を export_dir/model.onnx へコピー
        exported_path = Path(str(exported)) if exported else None
        if exported_path and exported_path.exists():
            if exported_path.resolve() != onnx_out.resolve():
                import shutil  # noqa: PLC0415
                shutil.copy2(exported_path, onnx_out)
        else:
            # export() が戻り値を返さない版に備え、weight隣の .onnx を探す
            cand = weight.with_suffix(".onnx")
            if cand.exists():
                import shutil  # noqa: PLC0415
                shutil.copy2(cand, onnx_out)

        if not onnx_out.exists():
            raise RuntimeError("ONNXファイルの生成を確認できませんでした。")

        _write_metadata(export_dir, job, project_dir, onnx_out, args.source_weight_rel, preprocess_required)
        _update_job(job_json, status="completed", finished_at=_now(), return_code=0,
                    onnx_path=_rel_posix(onnx_out, project_dir), message="completed")
        print("[INFO] ONNXエクスポートが完了しました。")
        return 0
    except Exception as e:  # noqa: BLE001
        print("[ERROR] ONNXエクスポート中に例外が発生しました:")
        traceback.print_exc()
        _update_job(job_json, status="failed", finished_at=_now(), return_code=1,
                    message=_summarize_error(f"{e!r} {e}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
