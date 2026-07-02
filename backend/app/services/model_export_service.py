"""モデル配布パッケージ出力。

学習済みの .pt 重みと、別環境で再利用するために必要なメタ情報（クラス定義・前処理・
推論条件・学習条件・評価結果・データセット情報）＋README＋サンプル推論スクリプトを
1つのZIPにまとめて出力する。ONNX等のエクスポートはこのIssueでは行わない。

パスは pathlib、返す相対パスはPOSIX。ZIPは exports/packages/{package_id}/ に生成。
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from ..core import paths
from ..schemas.model_export import ModelPackageResponse
from . import class_service, evaluation_service, preprocess_service, project_service
from .project_service import ProjectError, project_exists

_WEIGHTS = ("best", "last")
_PKG_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


class ModelExportError(Exception):
    """モデル配布の業務エラー。"""


class ModelExportNotFoundError(ModelExportError):
    """対象が見つからない（404相当）。"""


class ModelExportValidationError(ModelExportError):
    """不正なリクエスト（400相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _read_train_job(name: str, train_job_id: str) -> dict:
    run_dir = paths.train_job_dir(name, train_job_id)
    job_path = run_dir / "job.json"
    if not run_dir.exists() or not job_path.exists():
        raise ModelExportNotFoundError(f"学習ジョブ '{train_job_id}' が見つかりません。")
    try:
        return json.loads(job_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def weight_download_path(name: str, train_job_id: str, weight: str) -> Path:
    """重み(.pt)の実パスを返す（ダウンロード用）。"""
    _require_project(name)
    if weight not in _WEIGHTS:
        raise ModelExportValidationError("weight は best または last です。")
    if not paths.train_job_dir(name, train_job_id).exists():
        raise ModelExportNotFoundError(f"学習ジョブ '{train_job_id}' が見つかりません。")
    wp = paths.model_weight_path(name, train_job_id, weight)
    if not wp.exists():
        raise ModelExportNotFoundError(f"重み '{weight}.pt' が見つかりません。")
    return wp


# ---------------- メタ情報の生成 ----------------
def _classes_json(name: str, task: str) -> dict:
    classes = class_service.get_classes(name)
    return {
        "task": task,
        "classes": [{"id": c.id, "name": c.name, "color": c.color} for c in classes],
    }


def _preprocess_json(name: str) -> dict:
    s = preprocess_service.load_latest_settings(name)
    if s is None:
        return {"applied": False, "note": "前処理は未実行です（raw画像をそのまま使用）。"}
    d = s.model_dump()
    for k in ("job_name", "overwrite", "output_format"):
        d.pop(k, None)
    return {"applied": True, "source": "processed", "exif_transpose": True, **d}


def _training_config_json(job: dict, task: str) -> dict:
    return {
        "task": job.get("task", task),
        "model": job.get("model"),
        "epochs": job.get("epochs"),
        "batch": job.get("batch"),
        "imgsz": job.get("imgsz"),
        "device": job.get("device"),
        "seed": job.get("seed"),
        "augmentation_preset": job.get("augmentation_preset"),
        "augmentation_params": job.get("augmentation_params"),
        "dataset_name": job.get("dataset_name"),
    }


def _evaluation_summary_json(name: str, train_job_id: str, task: str) -> dict:
    out: dict[str, Any] = {"task": task}
    try:
        ev = evaluation_service.get_evaluation(name, train_job_id)
        s = ev.summary
    except Exception:  # noqa: BLE001 - 評価取得失敗でもパッケージ生成は継続
        s = None
    if s is None:
        out["note"] = "評価結果がありません（results.csv 未生成）。"
        return out
    out.update({
        "precision_b": s.precision,
        "recall_b": s.recall,
        "map50_b": s.map50,
        "map50_95_b": s.map50_95,
    })
    if task == "segment":
        out.update({
            "precision_m": s.mask_precision,
            "recall_m": s.mask_recall,
            "map50_m": s.mask_map50,
            "map50_95_m": s.mask_map50_95,
        })
    return out


def _dataset_summary_json(name: str, dataset_name: str | None, task: str) -> dict:
    if not dataset_name:
        return {"note": "データセット情報がありません。"}
    meta_path = paths.dataset_dir(name, dataset_name) / "metadata.json"
    if not meta_path.exists():
        return {"dataset_name": dataset_name, "note": "データセット情報が見つかりません。"}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"dataset_name": dataset_name, "note": "データセット情報の読込に失敗しました。"}
    summary = meta.get("summary", {}) or {}
    return {
        "dataset_name": meta.get("dataset_name", dataset_name),
        "task": meta.get("task", task),
        "image_source": meta.get("image_source"),
        "train_image_count": summary.get("train_image_count", 0),
        "val_image_count": summary.get("val_image_count", 0),
        "test_image_count": summary.get("test_image_count", 0),
        "class_count": summary.get("class_count", 0),
        "use_selection": meta.get("use_selection"),
        "include_review_images": meta.get("include_review_images"),
    }


def _inference_config_json(task: str, imgsz: Any, apply_pre: bool, include_onnx: bool = False) -> dict:
    return {
        "task": task,
        "recommended": {
            "imgsz": imgsz or 640,
            "conf": 0.25,
            "iou": 0.7,
            "image_source": "processed" if apply_pre else "raw",
            "apply_preprocess": apply_pre,
        },
        "runtime": {
            "pt": {"available": True, "sample": "sample_infer.py"},
            "onnx": {
                "available": include_onnx,
                "sample": "sample_infer_onnx.py" if include_onnx else None,
                "model_path": "weights/model.onnx" if include_onnx else None,
            },
        },
    }


def _onnx_config_json(included: bool, onnx_job: dict, weight: str, task: str) -> dict:
    if not included:
        return {"included": False, "reason": "ONNX export job was not selected."}
    return {
        "included": True,
        "export_job_id": onnx_job.get("export_job_id"),
        "onnx_path": "weights/model.onnx",
        "source_weight_type": weight,
        "task": onnx_job.get("task", task),
        "imgsz": onnx_job.get("imgsz"),
        "opset": onnx_job.get("opset"),
        "simplify": onnx_job.get("simplify"),
        "dynamic": onnx_job.get("dynamic"),
        "half": onnx_job.get("half"),
        "device": onnx_job.get("device"),
        "note": "ONNX Runtimeで利用する場合は、preprocess.json と inference_config.json の条件を合わせてください。",
    }


def _resolve_onnx(name: str, train_job_id: str, weight: str, onnx_export_job_id: str | None):
    """同梱するONNX export jobを検証し、(model.onnxパス, jobdict) を返す。"""
    if not onnx_export_job_id:
        raise ModelExportValidationError("onnx_export_job_id を指定してください。")
    if not paths.is_valid_project_name(onnx_export_job_id):
        raise ModelExportValidationError("不正な onnx_export_job_id です。")
    edir = paths.onnx_export_dir(name, onnx_export_job_id)
    job_path = edir / "job.json"
    if not job_path.exists():
        raise ModelExportNotFoundError(f"ONNXエクスポート '{onnx_export_job_id}' が見つかりません。")
    try:
        ojob = json.loads(job_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        ojob = {}
    if ojob.get("status") != "completed":
        raise ModelExportValidationError(
            "指定されたONNXエクスポートは完了していません（status が completed ではありません）。"
        )
    onnx_file = edir / "model.onnx"
    if not onnx_file.exists():
        raise ModelExportValidationError("指定されたONNXエクスポートに model.onnx が存在しません。")
    if ojob.get("train_job_id") != train_job_id:
        raise ModelExportValidationError(
            "指定されたONNXエクスポートは、このモデルの学習ジョブに対応していません。"
        )
    if ojob.get("weight_type") != weight:
        raise ModelExportValidationError(
            f"指定されたONNXエクスポートは、このモデルの{weight}重みに対応していません。"
        )
    return onnx_file, ojob


def _readme_md(name, train_job_id, weight, task, classes_j, pre_j, train_j, eval_j, ds_j, infer_j,
               include_onnx: bool = False) -> str:
    cls_lines = "\n".join(
        f"| {c['id']} | {c['name']} | {c['color']} |" for c in classes_j["classes"]
    ) or "| - | (クラス未定義) | - |"
    rec = infer_j["recommended"]
    pre_note = (
        "前処理は不要（raw画像のまま）。"
        if not pre_j.get("applied")
        else "学習時と同じ前処理を推論前に適用してください（下記 preprocess.json 参照）。"
    )
    ev_lines = []
    if "note" not in eval_j:
        ev_lines.append(f"- Box: precision {eval_j.get('precision_b')} / recall {eval_j.get('recall_b')} "
                        f"/ mAP50 {eval_j.get('map50_b')} / mAP50-95 {eval_j.get('map50_95_b')}")
        if task == "segment":
            ev_lines.append(f"- Mask: precision {eval_j.get('precision_m')} / recall {eval_j.get('recall_m')} "
                            f"/ mAP50 {eval_j.get('map50_m')} / mAP50-95 {eval_j.get('map50_95_m')}")
    else:
        ev_lines.append(f"- {eval_j['note']}")
    onnx_section = _onnx_readme_section(include_onnx, task)
    return f"""# モデル配布パッケージ: {name} / {train_job_id} ({weight}.pt)

- **タスク種別**: {task}（{"物体検出(bbox)" if task == "detect" else "セグメンテーション(polygon)"}）
- **モデル**: {train_j.get('model')}
- **学習ジョブ**: {train_job_id}
- **重み**: weights/{weight}.pt

## クラス一覧

| id | name | color |
| -- | ---- | ----- |
{cls_lines}

## 入力画像サイズ / 推奨推論パラメータ

- imgsz: {rec['imgsz']}
- conf: {rec['conf']}
- iou: {rec['iou']}
- image_source: {rec['image_source']}
- apply_preprocess: {rec['apply_preprocess']}

## 必要な前処理

{pre_note}

## 学習条件

- model: {train_j.get('model')} / epochs: {train_j.get('epochs')} / batch: {train_j.get('batch')} / imgsz: {train_j.get('imgsz')}
- device: {train_j.get('device')} / seed: {train_j.get('seed')}
- augmentation_preset: {train_j.get('augmentation_preset')}
- dataset: {ds_j.get('dataset_name')}（train {ds_j.get('train_image_count')} / val {ds_j.get('val_image_count')} / test {ds_j.get('test_image_count')}）

## 評価結果

{chr(10).join(ev_lines)}

## 使い方

1. `pip install ultralytics`（GPUを使う場合は CUDA対応 PyTorch を先に導入）
2. `python sample_infer.py`（`sample.jpg` を用意するか source を書き換え）
3. 各種 *.json に前処理・推論条件・クラス定義・評価・データセット情報が入っています。

## 注意点

- 推論精度を再現するには、学習時と同じ前処理・imgsz を合わせてください。
- クラスIDと名称は classes.json を正としてください。
{onnx_section}
"""


def _onnx_readme_section(include_onnx: bool, task: str) -> str:
    if not include_onnx:
        return (
            "\n## ONNX\n\n"
            "このパッケージにはONNXモデルは含まれていません。\n"
            "アプリのモデル管理画面からONNXエクスポートを実行した後、ONNX同梱パッケージを作成してください。\n"
        )
    seg_note = (
        "\nセグメンテーションモデルの場合は、mask出力の後処理も必要です。\n"
        if task == "segment" else ""
    )
    return (
        "\n## ONNX Runtimeでの利用\n\n"
        "このパッケージには `weights/model.onnx` が含まれています。\n\n"
        "### セットアップ\n\n"
        "```bash\n"
        "pip install -r requirements-infer.txt\n"
        "```\n\n"
        "### サンプル実行\n\n"
        "```bash\n"
        "python sample_infer_onnx.py\n"
        "```\n\n"
        "`sample.jpg` を同じフォルダに配置して実行してください。\n\n"
        "### 注意\n\n"
        "このサンプルはONNX Runtimeでモデルを読み込み、推論を実行する最小例です。\n"
        "YOLOの検出結果を実際に描画するには、NMSなどの後処理が必要です。\n"
        f"{seg_note}"
        "GPUでONNX Runtimeを使う場合は、環境に合わせて onnxruntime-gpu を検討してください。\n"
    )


def _requirements_infer_txt() -> str:
    return (
        "# ONNX Runtime 推論用（CPU版）。GPUを使う場合は環境に合わせて onnxruntime-gpu を検討。\n"
        "onnxruntime\n"
        "numpy\n"
        "Pillow\n"
    )


def _sample_infer_onnx_py() -> str:
    return '''"""最小推論サンプル（ONNX Runtime）。

使い方:
    pip install -r requirements-infer.txt
    python sample_infer_onnx.py   # 同じフォルダに sample.jpg を置く

このサンプルは ONNX Runtime でモデルを読み込み、推論を実行する最小例です。
YOLO の bbox / mask を実際に描画するには、NMS や mask 後処理が必要です
（Ultralyticsのバージョン・export設定・detect/segmentで出力形状が異なる場合があります）。
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
import onnxruntime as ort


BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "weights" / "model.onnx"
CLASSES_PATH = BASE_DIR / "classes.json"
PREPROCESS_PATH = BASE_DIR / "preprocess.json"
INFERENCE_CONFIG_PATH = BASE_DIR / "inference_config.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def apply_preprocess(image: Image.Image, preprocess: dict) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")

    if preprocess.get("resize_enabled"):
        mode = preprocess.get("resize_mode", "width")
        size = int(preprocess.get("resize_size", 640))
        w, h = image.size
        if mode == "height":
            new_h = size
            new_w = int(w * (new_h / h))
        else:
            new_w = size
            new_h = int(h * (new_w / w))
        image = image.resize((new_w, new_h))

    if preprocess.get("grayscale_enabled"):
        image = image.convert("L").convert("RGB")

    if preprocess.get("binary_enabled"):
        threshold = int(preprocess.get("binary_threshold", 128))
        invert = bool(preprocess.get("binary_invert", False))
        gray = image.convert("L")
        if invert:
            binary = gray.point(lambda p: 255 if p < threshold else 0)
        else:
            binary = gray.point(lambda p: 255 if p >= threshold else 0)
        image = binary.convert("RGB")

    return image


def letterbox_to_square(image: Image.Image, size: int) -> Image.Image:
    w, h = image.size
    scale = min(size / w, size / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = image.resize((nw, nh))
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def to_tensor(image: Image.Image) -> np.ndarray:
    arr = np.asarray(image).astype(np.float32) / 255.0
    arr = np.transpose(arr, (2, 0, 1))
    return np.expand_dims(arr, axis=0)


def main():
    image_path = BASE_DIR / "sample.jpg"
    if not image_path.exists():
        raise FileNotFoundError("sample.jpg をこのフォルダに置いてから実行してください。")

    classes = load_json(CLASSES_PATH)
    preprocess = load_json(PREPROCESS_PATH)
    inference_config = load_json(INFERENCE_CONFIG_PATH)
    imgsz = int(inference_config.get("recommended", {}).get("imgsz", 640))

    image = Image.open(image_path)
    image = apply_preprocess(image, preprocess)
    image = letterbox_to_square(image, imgsz)
    tensor = to_tensor(image)

    session = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})

    print("Classes:", classes.get("classes"))
    print("Input:", input_name, tensor.shape)
    print("Output count:", len(outputs))
    for i, out in enumerate(outputs):
        print(f"Output[{i}] shape:", getattr(out, "shape", None))

    print()
    print("注意: これはONNX Runtimeでの推論実行の最小例です。")
    print("bbox/maskの描画には NMS や mask 後処理が必要です。")


if __name__ == "__main__":
    main()
'''


def _sample_infer_py(weight: str, task: str, rec: dict, apply_pre: bool) -> str:
    pre_block = ""
    if apply_pre:
        pre_block = (
            "# preprocess.json に学習時の前処理設定が入っています。\n"
            "# 精度を合わせるには、推論前に同じ前処理（リサイズ/グレースケール等）を適用してください。\n"
        )
    return f'''"""最小推論サンプル（Ultralytics YOLO）。

使い方:
    pip install ultralytics
    python sample_infer.py   # 同じフォルダに sample.jpg を置くか source を変更

task: {task}
"""

from ultralytics import YOLO

{pre_block}model = YOLO("weights/{weight}.pt")
results = model.predict(
    source="sample.jpg",
    imgsz={rec['imgsz']},
    conf={rec['conf']},
    iou={rec['iou']},
)

for r in results:
    print(r.boxes if r.boxes is not None else r)
    # segment の場合は r.masks に輪郭情報が入ります
'''


def _sanitize(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", part)


def create_package(
    name: str,
    train_job_id: str,
    weight: str,
    include_onnx: bool = False,
    onnx_export_job_id: str | None = None,
) -> ModelPackageResponse:
    _require_project(name)
    if weight not in _WEIGHTS:
        raise ModelExportValidationError("weight は best または last です。")
    job = _read_train_job(name, train_job_id)
    weight_file = paths.model_weight_path(name, train_job_id, weight)
    if not weight_file.exists():
        raise ModelExportNotFoundError(f"重み '{weight}.pt' が見つかりません。")

    # ONNX同梱の検証（任意）
    onnx_file = None
    onnx_job: dict = {}
    if include_onnx:
        onnx_file, onnx_job = _resolve_onnx(name, train_job_id, weight, onnx_export_job_id)

    task = project_service.get_task(name)
    apply_pre = preprocess_service.load_latest_settings(name) is not None

    classes_j = _classes_json(name, task)
    pre_j = _preprocess_json(name)
    train_j = _training_config_json(job, task)
    eval_j = _evaluation_summary_json(name, train_job_id, task)
    ds_j = _dataset_summary_json(name, job.get("dataset_name"), task)
    infer_j = _inference_config_json(task, job.get("imgsz"), apply_pre, include_onnx)
    onnx_j = _onnx_config_json(include_onnx, onnx_job, weight, task)
    readme = _readme_md(name, train_job_id, weight, task, classes_j, pre_j, train_j, eval_j, ds_j, infer_j, include_onnx)
    sample = _sample_infer_py(weight, task, infer_j["recommended"], apply_pre)

    package_id = _sanitize(f"{train_job_id}__{weight}")
    pkg_dir = paths.package_dir(name, package_id)
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir, ignore_errors=True)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    zip_name = f"model_package_{_sanitize(name)}_{_sanitize(train_job_id)}_{weight}.zip"
    zip_path = pkg_dir / zip_name

    files: list[str] = []

    def dump(d: dict) -> str:
        return json.dumps(d, ensure_ascii=False, indent=2)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 重み（存在するものを両方入れる）
        best = paths.model_weight_path(name, train_job_id, "best")
        last = paths.model_weight_path(name, train_job_id, "last")
        if best.exists():
            zf.write(best, "weights/best.pt")
            files.append("weights/best.pt")
        if last.exists():
            zf.write(last, "weights/last.pt")
            files.append("weights/last.pt")
        # ONNX（同梱時のみ）
        if include_onnx and onnx_file is not None:
            zf.write(onnx_file, "weights/model.onnx")
            files.append("weights/model.onnx")
        # メタ情報
        meta_files = [
            ("classes.json", dump(classes_j)),
            ("preprocess.json", dump(pre_j)),
            ("inference_config.json", dump(infer_j)),
            ("onnx_config.json", dump(onnx_j)),
            ("training_config.json", dump(train_j)),
            ("evaluation_summary.json", dump(eval_j)),
            ("dataset_summary.json", dump(ds_j)),
            ("README_model.md", readme),
            ("sample_infer.py", sample),
        ]
        if include_onnx:
            meta_files.append(("sample_infer_onnx.py", _sample_infer_onnx_py()))
            meta_files.append(("requirements-infer.txt", _requirements_infer_txt()))
        for fname, content in meta_files:
            zf.writestr(fname, content)
            files.append(fname)

    rel = zip_path.relative_to(paths.project_dir(name)).as_posix()
    return ModelPackageResponse(
        project_name=name,
        model_id=f"{train_job_id}:{weight}",
        package_id=package_id,
        status="completed",
        zip_path=rel,
        files=files,
    )


def package_zip_path(name: str, package_id: str) -> Path:
    """配布パッケージZIPの実パスを返す（ダウンロード用）。"""
    _require_project(name)
    if not _PKG_ID_RE.match(package_id) or package_id in ("", ".", ".."):
        raise ModelExportValidationError("不正な package_id です。")
    pkg_dir = paths.package_dir(name, package_id)
    if not pkg_dir.exists():
        raise ModelExportNotFoundError(f"パッケージ '{package_id}' が見つかりません。")
    zips = sorted(pkg_dir.glob("*.zip"))
    if not zips:
        raise ModelExportNotFoundError(f"パッケージ '{package_id}' のZIPが見つかりません。")
    return zips[0]
