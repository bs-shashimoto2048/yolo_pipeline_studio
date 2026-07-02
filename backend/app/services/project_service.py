"""プロジェクトの作成・一覧・概要を扱う業務ロジック。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

import yaml

from ..core import paths
from ..schemas.project import ProjectSummary


class ProjectError(Exception):
    """プロジェクト操作に関する業務エラー。"""


class ProjectConflictError(ProjectError):
    """実行中ジョブ等により操作できない（HTTP 409相当）。"""


# 有効なタスク種別
VALID_TASKS = ("detect", "segment")


def list_projects() -> list[ProjectSummary]:
    """プロジェクト一覧を返す（project.yaml を持つディレクトリのみ）。"""
    root = paths.projects_root()
    summaries: list[ProjectSummary] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "project.yaml").exists():
            summaries.append(get_summary(child.name))
    return summaries


def project_exists(name: str) -> bool:
    return paths.project_yaml(name).exists()


def create_project(
    name: str, description: str = "", task: str = "detect"
) -> ProjectSummary:
    """プロジェクトを作成し、標準フォルダ構成を生成する。"""
    if not paths.is_valid_project_name(name):
        raise ProjectError(
            "プロジェクト名は英数・アンダースコア・ハイフンのみ使用できます。"
        )
    if project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' は既に存在します。")
    if task not in VALID_TASKS:
        raise ProjectError(
            f"task は {' / '.join(VALID_TASKS)} のいずれかを指定してください。"
        )

    paths.ensure_project_skeleton(name)

    meta = {
        "name": name,
        "description": description,
        "task": task,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with paths.project_yaml(name).open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)

    # 空のクラス定義を作成
    with paths.classes_yaml(name).open("w", encoding="utf-8") as f:
        yaml.safe_dump({"names": {}}, f, allow_unicode=True, sort_keys=False)

    return get_summary(name)


def _load_meta(name: str) -> dict:
    path = paths.project_yaml(name)
    if not path.exists():
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_task(name: str) -> str:
    """プロジェクトのタスク種別を返す。未定義の既存案件は 'detect' 扱い。"""
    try:
        meta = _load_meta(name)
    except ProjectError:
        return "detect"
    task = meta.get("task")
    return task if task in VALID_TASKS else "detect"


def _has_active_job(name: str) -> bool:
    """実行中(queued/running)の train/predict ジョブがあるか。"""
    for base in (paths.train_runs_dir(name), paths.predictions_dir(name)):
        if not base.exists():
            continue
        for child in base.iterdir():
            jp = child / "job.json"
            if not jp.exists():
                continue
            try:
                status = json.loads(jp.read_text(encoding="utf-8-sig")).get("status")
            except (json.JSONDecodeError, OSError):
                continue
            if status in ("queued", "running"):
                return True
    return False


def delete_project(name: str) -> None:
    """プロジェクトディレクトリを削除する。実行中ジョブがあれば 409。"""
    if not paths.is_valid_project_name(name):
        raise ProjectError("不正なプロジェクト名です。")
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")
    if _has_active_job(name):
        raise ProjectConflictError(
            "実行中の学習/推論ジョブがあるため削除できません。完了後に再試行してください。"
        )
    # パストラバーサル防止: 解決先が projects_root 配下であることを確認
    target = paths.project_dir(name).resolve()
    root = paths.projects_root().resolve()
    if root not in target.parents:
        raise ProjectError("不正なパスです。")
    shutil.rmtree(target)


def get_summary(name: str) -> ProjectSummary:
    """プロジェクト概要を集計して返す。"""
    meta = _load_meta(name)

    # 画像枚数
    img_dir = paths.raw_images_dir(name)
    image_count = (
        sum(1 for p in img_dir.iterdir() if p.is_file()) if img_dir.exists() else 0
    )

    # ラベル数（txtファイル数）
    lbl_dir = paths.labels_dir(name)
    label_count = (
        sum(1 for p in lbl_dir.glob("*.txt")) if lbl_dir.exists() else 0
    )

    # クラス数
    class_count = 0
    cpath = paths.classes_yaml(name)
    if cpath.exists():
        with cpath.open("r", encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data.get("classes"), list):
            class_count = len(data["classes"])
        else:
            class_count = len(data.get("names", {}) or {})

    # 学習回数（runs配下のディレクトリ数）
    runs_dir = paths.project_dir(name) / "runs"
    train_count = (
        sum(1 for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else 0
    )

    task = meta.get("task")
    return ProjectSummary(
        name=name,
        description=meta.get("description", ""),
        task=task if task in VALID_TASKS else "detect",
        created_at=meta.get("created_at"),
        image_count=image_count,
        label_count=label_count,
        class_count=class_count,
        train_count=train_count,
    )
