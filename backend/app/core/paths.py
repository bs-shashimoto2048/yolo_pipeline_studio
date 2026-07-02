"""プロジェクトのフォルダ構成を一元管理する。

task.md「画面1：プロジェクト管理 / プロジェクト構成例」に従い、案件ごとに
raw / annotations / reviewed / datasets / preprocess / augment / runs /
predictions / reports などのフォルダを生成・参照する。
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import settings

# プロジェクト名として許可する文字（英数・アンダースコア・ハイフン）
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 案件直下に作るサブディレクトリ一覧
PROJECT_SUBDIRS: tuple[str, ...] = (
    "raw/images",
    "annotations/labels",
    "reviewed/images",
    "reviewed/labels",
    "datasets",
    "preprocess",
    "augment",
    "runs",
    "predictions",
    "reports",
)


def is_valid_project_name(name: str) -> bool:
    """プロジェクト名が安全（パストラバーサル不可・許可文字のみ）か判定。"""
    return bool(name) and bool(_PROJECT_NAME_RE.match(name))


def projects_root() -> Path:
    """全プロジェクトの親ディレクトリ。なければ生成する。"""
    root = settings.projects_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_dir(name: str) -> Path:
    """指定プロジェクトのルートディレクトリ。"""
    return projects_root() / name


def project_yaml(name: str) -> Path:
    return project_dir(name) / "project.yaml"


def classes_yaml(name: str) -> Path:
    return project_dir(name) / "classes.yaml"


def raw_images_dir(name: str) -> Path:
    return project_dir(name) / "raw" / "images"


def processed_images_dir(name: str) -> Path:
    return project_dir(name) / "processed" / "images"


def processed_thumbnails_dir(name: str) -> Path:
    return project_dir(name) / "processed" / "thumbnails"


def processed_metadata_path(name: str) -> Path:
    return project_dir(name) / "processed" / "metadata.json"


def processed_preview_dir(name: str) -> Path:
    return project_dir(name) / "processed" / "preview"


def images_dir_for_source(name: str, source: str) -> Path:
    """source(raw/processed/auto) に応じた画像ディレクトリを返す。

    auto は processed/images が存在すれば processed、なければ raw。
    """
    if source == "processed":
        return processed_images_dir(name)
    if source == "raw":
        return raw_images_dir(name)
    # auto
    pdir = processed_images_dir(name)
    if pdir.exists() and any(pdir.iterdir()):
        return pdir
    return raw_images_dir(name)


def labels_dir(name: str) -> Path:
    return project_dir(name) / "annotations" / "labels"


def experiments_csv(name: str) -> Path:
    return project_dir(name) / "experiments.csv"


def datasets_dir(name: str) -> Path:
    return project_dir(name) / "datasets"


def dataset_dir(name: str, dataset_name: str) -> Path:
    return datasets_dir(name) / dataset_name


def train_runs_dir(name: str) -> Path:
    """学習ジョブの親ディレクトリ（runs/train）。Ultralyticsの project に渡す。"""
    return project_dir(name) / "runs" / "train"


def train_job_dir(name: str, job_id: str) -> Path:
    return train_runs_dir(name) / job_id


def predictions_dir(name: str) -> Path:
    return project_dir(name) / "predictions"


def predict_job_dir(name: str, predict_job_id: str) -> Path:
    return predictions_dir(name) / predict_job_id


def video_jobs_dir(name: str) -> Path:
    return project_dir(name) / "video"


def video_job_dir(name: str, video_job_id: str) -> Path:
    return video_jobs_dir(name) / video_job_id


def selection_path(name: str) -> Path:
    return project_dir(name) / "selection" / "selection.json"


def exports_dir(name: str) -> Path:
    return project_dir(name) / "exports"


def packages_dir(name: str) -> Path:
    return exports_dir(name) / "packages"


def package_dir(name: str, package_id: str) -> Path:
    return packages_dir(name) / package_id


def onnx_exports_dir(name: str) -> Path:
    return exports_dir(name) / "onnx"


def onnx_export_dir(name: str, export_job_id: str) -> Path:
    return onnx_exports_dir(name) / export_job_id


def sam_dir(name: str) -> Path:
    return project_dir(name) / "sam"


def sam_settings_path(name: str) -> Path:
    return sam_dir(name) / "settings.json"


def reports_dir(name: str) -> Path:
    return project_dir(name) / "reports"


def augmentation_presets_dir(name: str) -> Path:
    return project_dir(name) / "augmentation" / "presets"


def models_dir(name: str) -> Path:
    return project_dir(name) / "models"


def selected_model_path(name: str) -> Path:
    return models_dir(name) / "selected_model.json"


def model_weight_path(name: str, train_job_id: str, weight_type: str) -> Path:
    return train_job_dir(name, train_job_id) / "weights" / f"{weight_type}.pt"


def ensure_project_skeleton(name: str) -> Path:
    """プロジェクトの標準フォルダ構成を生成し、ルートパスを返す。"""
    root = project_dir(name)
    for sub in PROJECT_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
