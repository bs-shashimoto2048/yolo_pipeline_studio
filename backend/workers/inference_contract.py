"""Production inference contract の共通定数・observabilityヘルパ（Issue #29）。

predict_worker.py / predict_video_worker.py の両方が、job.json へ記録する
observability metadata（contract version・pinned args・model identity・SHA256）を
ここへ一本化する。`production-inference-contract-v1` という文字列や pinned args の値を
複数箇所へ直書きしないための唯一の定義元。

predict_worker.py は「app パッケージに依存しない」設計方針（同ファイル冒頭のdocstring
参照）のため、本モジュールも標準ライブラリのみに依存する。worker はサブプロセスとして
`python <script path>` で起動されるため、スクリプト自身のディレクトリ（このファイルと
同じ backend/workers/）が自動的に sys.path へ入り、`import inference_contract` できる。

注意: ここで定義する PINNED_ARGS は observability metadata（記録用の値）としてのみ使う。
predict_worker.py / predict_video_worker.py が実際に model.predict() へ渡す
kwargs = dict(rect=True, ...) の**リテラル記述はそのまま維持する**（Issue #25/#26/#27の
smoke_inference_contract.py がソース文字列を直接検査しているため、リテラルを
本モジュール参照へ置き換えると既存の回帰テストが壊れる）。値の一致は
backend/tests/smoke_inference_observability.py で別途検証する。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "production-inference-contract-v1"

# predict_worker.py / predict_video_worker.py の kwargs = dict(...) リテラルと
# 同値であることが前提（Issue #25/#26で実測確認済み）。この値自体を書き換える場合は
# 対応するworkerのリテラルも同時に変更し、docs/PRODUCTION_INFERENCE_CONTRACT.md の
# contract version bump手順に従うこと。
PINNED_ARGS: dict[str, Any] = {
    "rect": True,
    "max_det": 300,
    "agnostic_nms": False,
    "augment": False,
    "batch": 1,
    "quantize": None,
}


def sha256_file(path: Path) -> str | None:
    """weight fileの実バイト列からSHA256を計算する（毎frameではなくjob開始時1回想定）。"""
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ultralytics_version() -> str | None:
    try:
        import ultralytics  # noqa: PLC0415

        return str(getattr(ultralytics, "__version__", None))
    except Exception:  # noqa: BLE001
        return None


def torch_version() -> str | None:
    try:
        import torch  # noqa: PLC0415

        return str(getattr(torch, "__version__", None))
    except Exception:  # noqa: BLE001
        return None


def resolve_model_identity(job_json: Path, weight: Path) -> dict[str, Any]:
    """job.json の train_job_id/weight_type と、weight fileの実SHA256からmodel identityを構築する。

    model_path は個人ユーザー名等を含む絶対パスを避け、model_registry_service._rel() と
    同じ project-relative 形式（例: "runs/train/<train_job_id>/weights/<weight_type>.pt"）にする。
    train_job_id/weight_typeが不明（job.json読込不可等）な場合は model_path も None とし、
    存在しないパスを捏造しない。
    """
    try:
        job = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        job = {}
    train_job_id = job.get("train_job_id")
    weight_type = job.get("weight_type")
    model_path = (
        f"runs/train/{train_job_id}/weights/{weight_type}.pt"
        if train_job_id and weight_type
        else None
    )
    return {
        "train_job_id": train_job_id,
        "weight_type": weight_type,
        "model_path": model_path,
        "sha256": sha256_file(weight),
    }


def build_resolved_args(
    *,
    conf: float,
    iou: float,
    imgsz: int,
    requested_device: str,
    runtime_device: str | None = None,
) -> dict[str, Any]:
    """production contractのpinned args + runtime値（conf/iou/imgsz/device）を1つの辞書にまとめる。

    runtime_device は「実際に使用されたdevice」（Ultralytics解決後の値）。取得できない場合は
    推測せず None のままにする（呼び出し側で判明した時点で更新する）。
    """
    args: dict[str, Any] = dict(PINNED_ARGS)
    args.update(
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        requested_device=requested_device,
        runtime_device=runtime_device,
    )
    return args


def build_contract(
    job_json: Path,
    weight: Path,
    *,
    conf: float,
    iou: float,
    imgsz: int,
    requested_device: str,
    runtime_device: str | None = None,
) -> dict[str, Any]:
    """job.json へ記録する inference_contract 全体（画像predict用の完全形）を構築する。

    映像ワーカーは戻り値の "resolved_args" を "initial_resolved_args"/"current_resolved_args"
    へ分割して使う（live settings refreshでconf/iou/imgsz/deviceが動的に変わるため）。
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "ultralytics_version": ultralytics_version(),
        "torch_version": torch_version(),
        "model": resolve_model_identity(job_json, weight),
        "resolved_args": build_resolved_args(
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            requested_device=requested_device,
            runtime_device=runtime_device,
        ),
    }
