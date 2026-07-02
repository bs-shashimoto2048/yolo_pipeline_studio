"""実験履歴の集約。

MVPでは train_job 1件 = 1実験（experiment_id = train_job_id）。
既存サービス（training / evaluation / prediction / analysis）と metadata.json を
読み取って集約する。欠損・破損ファイルがあってもAPIが落ちないようにする。
"""

from __future__ import annotations

import json

from ..core import paths
from ..schemas.experiment import (
    AnalysisBrief,
    ExperimentDataset,
    ExperimentDetailResponse,
    ExperimentEvaluation,
    ExperimentListItem,
    ExperimentListResponse,
    ExperimentPrediction,
    LatestAnalysis,
)
from ..schemas.training import TrainJobInfo
from . import analysis_service, evaluation_service, prediction_service, training_service
from .project_service import ProjectError, project_exists


class ExperimentNotFoundError(Exception):
    """実験が見つからない（404）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _dataset_meta(name: str, dataset_name: str | None) -> ExperimentDataset | None:
    if not dataset_name:
        return None
    meta_path = paths.dataset_dir(name, dataset_name) / "metadata.json"
    if not meta_path.exists():
        return ExperimentDataset(dataset_name=dataset_name)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        # 破損していても落とさず、名前だけ返す
        return ExperimentDataset(dataset_name=dataset_name)
    summary = meta.get("summary", {}) or {}
    return ExperimentDataset(
        dataset_name=meta.get("dataset_name", dataset_name),
        train_image_count=summary.get("train_image_count"),
        val_image_count=summary.get("val_image_count"),
        test_image_count=summary.get("test_image_count"),
        total_image_count=summary.get("total_image_count"),
        class_count=summary.get("class_count"),
        train_ratio=meta.get("train_ratio"),
        val_ratio=meta.get("val_ratio"),
        test_ratio=meta.get("test_ratio"),
        include_empty_labels=meta.get("include_empty_labels"),
        include_unlabeled_images=meta.get("include_unlabeled_images"),
        seed=meta.get("seed"),
    )


def _evaluation(name: str, train_job_id: str) -> ExperimentEvaluation | None:
    try:
        ev = evaluation_service.get_evaluation(name, train_job_id)
    except Exception:  # noqa: BLE001 - 評価集約は失敗してもAPIを落とさない
        return None
    s = ev.summary
    return ExperimentEvaluation(
        precision=s.precision if s else None,
        recall=s.recall if s else None,
        map50=s.map50 if s else None,
        map50_95=s.map50_95 if s else None,
        train_box_loss=s.train_box_loss if s else None,
        val_box_loss=s.val_box_loss if s else None,
        has_best_model=ev.has_best_model,
        has_last_model=ev.has_last_model,
        has_results_csv=ev.has_results_csv,
    )


def _analysis_brief(name: str, predict_job_id: str) -> AnalysisBrief | None:
    try:
        a = analysis_service.get_saved(name, predict_job_id)
    except Exception:  # noqa: BLE001 - analysis.json 不在/破損でも落とさない
        return None
    s = a.summary
    return AnalysisBrief(
        tp_count=s.tp_count,
        fp_count=s.fp_count,
        fn_count=s.fn_count,
        class_mismatch_count=s.class_mismatch_count,
        precision=s.precision,
        recall=s.recall,
        f1=s.f1,
    )


def _predict_jobs_for(name: str, train_job_id: str):
    try:
        jobs = prediction_service.list_jobs(name).jobs
    except Exception:  # noqa: BLE001
        return []
    return [j for j in jobs if j.train_job_id == train_job_id]


def _latest_analysis(name: str, train_job_id: str) -> LatestAnalysis | None:
    """同じ train_job を使う predict job のうち、analysis.json を持つ最新のもの。"""
    jobs = _predict_jobs_for(name, train_job_id)
    # created_at 降順（None は最後）
    jobs_sorted = sorted(jobs, key=lambda j: (j.created_at or ""), reverse=True)
    for j in jobs_sorted:
        brief = _analysis_brief(name, j.predict_job_id)
        if brief is not None:
            return LatestAnalysis(predict_job_id=j.predict_job_id, **brief.model_dump())
    return None


def list_experiments(name: str) -> ExperimentListResponse:
    _require_project(name)
    try:
        train_jobs = training_service.list_jobs(name).jobs
    except ProjectError:
        raise
    except Exception:  # noqa: BLE001
        train_jobs = []

    experiments: list[ExperimentListItem] = []
    for tj in train_jobs:
        ds = _dataset_meta(name, tj.dataset_name)
        ev = _evaluation(name, tj.job_id)
        latest = _latest_analysis(name, tj.job_id)
        experiments.append(ExperimentListItem(
            experiment_id=tj.job_id,
            train_job_id=tj.job_id,
            status=tj.status,
            dataset_name=tj.dataset_name,
            model=tj.model,
            epochs=tj.epochs,
            imgsz=tj.imgsz,
            batch=tj.batch,
            device=tj.device,
            created_at=tj.created_at,
            finished_at=tj.finished_at,
            train_image_count=ds.train_image_count if ds else None,
            val_image_count=ds.val_image_count if ds else None,
            class_count=ds.class_count if ds else None,
            precision=ev.precision if ev else None,
            recall=ev.recall if ev else None,
            map50=ev.map50 if ev else None,
            map50_95=ev.map50_95 if ev else None,
            best_model_path=tj.best_model_path,
            augmentation_preset=tj.augmentation_preset,
            latest_analysis=latest,
        ))

    return ExperimentListResponse(project_name=name, experiments=experiments)


def get_experiment(name: str, experiment_id: str) -> ExperimentDetailResponse:
    _require_project(name)
    train_job_id = experiment_id
    run_dir = paths.train_job_dir(name, train_job_id)
    if not run_dir.exists():
        raise ExperimentNotFoundError(f"実験 '{experiment_id}' が見つかりません。")

    try:
        tj: TrainJobInfo | None = training_service.get_job(name, train_job_id)
    except Exception:  # noqa: BLE001
        tj = None

    dataset = _dataset_meta(name, tj.dataset_name if tj else None)
    evaluation = _evaluation(name, train_job_id)

    predictions: list[ExperimentPrediction] = []
    for j in _predict_jobs_for(name, train_job_id):
        predictions.append(ExperimentPrediction(
            predict_job_id=j.predict_job_id,
            status=j.status,
            image_count=j.image_count,
            detection_count=j.detection_count,
            analysis=_analysis_brief(name, j.predict_job_id),
        ))

    return ExperimentDetailResponse(
        project_name=name,
        experiment_id=experiment_id,
        train_job=tj,
        dataset=dataset,
        evaluation=evaluation,
        predictions=predictions,
    )
