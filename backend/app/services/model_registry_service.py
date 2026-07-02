"""モデル管理（レジストリ）。

学習ジョブ配下の best.pt / last.pt を集約して一覧化し、採用モデルを
selected_model.json に参照パスとして保存する。モデルファイルはコピー/移動しない。

評価値・分析値の集約は experiment_service のヘルパを再利用する。
欠損ファイルや破損 selected_model.json があっても一覧APIは落ちない。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..core import paths
from ..schemas.experiment import ExperimentPrediction
from ..schemas.model_registry import (
    ModelDetailResponse,
    ModelItem,
    ModelListResponse,
    SelectedModelResponse,
    SelectModelRequest,
)
from . import experiment_service, training_service
from .project_service import ProjectError, project_exists

_WEIGHT_TYPES = ("best", "last")


class ModelError(Exception):
    pass


class ModelNotFoundError(ModelError):
    """対象が見つからない（404）。"""


class ModelValidationError(ModelError):
    """入力不正・前提未充足（400）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _rel(name: str, train_job_id: str, weight_type: str) -> str:
    return f"runs/train/{train_job_id}/weights/{weight_type}.pt"


def _read_selected(name: str) -> dict | None:
    p = paths.selected_model_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None  # 破損していても落とさない


def _selected_id(name: str) -> str | None:
    sel = _read_selected(name)
    return sel.get("model_id") if sel else None


def _model_item(name: str, tj, weight_type: str, selected_id: str | None) -> ModelItem:
    """1モデル分（train job情報 + 評価 + 最新分析）を構築する。"""
    train_job_id = tj.job_id
    model_id = f"{train_job_id}:{weight_type}"
    wpath = paths.model_weight_path(name, train_job_id, weight_type)
    exists = wpath.exists()
    size = wpath.stat().st_size if exists else None
    created = None
    if exists:
        created = datetime.fromtimestamp(wpath.stat().st_mtime).isoformat(timespec="seconds")

    ev = experiment_service._evaluation(name, train_job_id)
    latest = experiment_service._latest_analysis(name, train_job_id)

    return ModelItem(
        model_id=model_id,
        train_job_id=train_job_id,
        weight_type=weight_type,
        model_path=_rel(name, train_job_id, weight_type),
        exists=exists,
        file_size_bytes=size,
        created_at=created,
        train_status=tj.status,
        dataset_name=tj.dataset_name,
        base_model=tj.model,
        epochs=tj.epochs,
        imgsz=tj.imgsz,
        batch=tj.batch,
        device=tj.device,
        precision=ev.precision if ev else None,
        recall=ev.recall if ev else None,
        map50=ev.map50 if ev else None,
        map50_95=ev.map50_95 if ev else None,
        augmentation_preset=tj.augmentation_preset,
        latest_analysis=latest,
        is_selected=(model_id == selected_id),
    )


def list_models(name: str) -> ModelListResponse:
    _require_project(name)
    selected_id = _selected_id(name)
    try:
        train_jobs = training_service.list_jobs(name).jobs
    except ProjectError:
        raise
    except Exception:  # noqa: BLE001
        train_jobs = []

    models: list[ModelItem] = []
    for tj in train_jobs:
        for wt in _WEIGHT_TYPES:
            models.append(_model_item(name, tj, wt, selected_id))

    return ModelListResponse(
        project_name=name, selected_model_id=selected_id, models=models
    )


def get_model(name: str, train_job_id: str, weight_type: str) -> ModelDetailResponse:
    _require_project(name)
    if weight_type not in _WEIGHT_TYPES:
        raise ModelValidationError("weight_type は best または last です。")
    if not paths.train_job_dir(name, train_job_id).exists():
        raise ModelNotFoundError(f"学習ジョブ '{train_job_id}' が見つかりません。")

    wpath = paths.model_weight_path(name, train_job_id, weight_type)
    exists = wpath.exists()
    size = wpath.stat().st_size if exists else None
    model_id = f"{train_job_id}:{weight_type}"

    try:
        tj = training_service.get_job(name, train_job_id)
    except Exception:  # noqa: BLE001
        tj = None

    evaluation = experiment_service._evaluation(name, train_job_id)
    predictions = []
    for j in experiment_service._predict_jobs_for(name, train_job_id):
        predictions.append(
            ExperimentPrediction(
                predict_job_id=j.predict_job_id,
                status=j.status,
                image_count=j.image_count,
                detection_count=j.detection_count,
                analysis=experiment_service._analysis_brief(name, j.predict_job_id),
            )
        )

    return ModelDetailResponse(
        project_name=name,
        model_id=model_id,
        train_job_id=train_job_id,
        weight_type=weight_type,
        model_path=_rel(name, train_job_id, weight_type),
        exists=exists,
        file_size_bytes=size,
        train_job=tj,
        evaluation=evaluation,
        predictions=predictions,
        is_selected=(model_id == _selected_id(name)),
    )


def set_selected(name: str, req: SelectModelRequest) -> SelectedModelResponse:
    _require_project(name)
    if req.weight_type not in _WEIGHT_TYPES:
        raise ModelValidationError("weight_type は best または last です。")
    if not paths.train_job_dir(name, req.train_job_id).exists():
        raise ModelNotFoundError(f"学習ジョブ '{req.train_job_id}' が見つかりません。")
    wpath = paths.model_weight_path(name, req.train_job_id, req.weight_type)
    if not wpath.exists():
        raise ModelValidationError(
            f"モデルファイルが存在しません: {_rel(name, req.train_job_id, req.weight_type)}"
        )

    model_id = f"{req.train_job_id}:{req.weight_type}"
    selected_at = datetime.now().isoformat(timespec="seconds")
    payload = {
        "model_id": model_id,
        "train_job_id": req.train_job_id,
        "weight_type": req.weight_type,
        "model_path": _rel(name, req.train_job_id, req.weight_type),
        "selected_at": selected_at,
        "memo": req.memo,
    }
    paths.models_dir(name).mkdir(parents=True, exist_ok=True)
    paths.selected_model_path(name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return SelectedModelResponse(project_name=name, selected_model_id=model_id, **{
        k: payload[k] for k in ("train_job_id", "weight_type", "model_path", "selected_at", "memo")
    })


def get_selected(name: str) -> SelectedModelResponse:
    _require_project(name)
    sel = _read_selected(name)
    if not sel or not sel.get("model_id"):
        raise ModelNotFoundError("採用モデルが設定されていません。")
    return SelectedModelResponse(
        project_name=name,
        selected_model_id=sel.get("model_id"),
        train_job_id=sel.get("train_job_id", ""),
        weight_type=sel.get("weight_type", ""),
        model_path=sel.get("model_path", ""),
        selected_at=sel.get("selected_at"),
        memo=sel.get("memo", ""),
    )
