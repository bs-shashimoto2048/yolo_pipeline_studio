"""学習結果評価・results.csv 解析。

Ultralytics の学習結果ディレクトリ（runs/train/{job_id}）から results.csv や
成果物画像を読み取り、評価サマリー・メトリクス推移・画像配信を提供する。

- results.csv は UTF-8 / UTF-8-SIG 両対応、列名前後の空白を strip、空行無視。
- 数値変換できるものは float（epoch は int）。最終行を評価サマリーとして扱う。
- 列名は Ultralytics バージョン差を吸収するため候補リストから柔軟に拾う。
- 成果物配信は画像のみ・ファイル名のみ許可（パストラバーサル対策）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..core import paths
from ..schemas.evaluation import (
    Artifact,
    EvaluationResponse,
    EvaluationSummary,
    MetricsResponse,
)
from .project_service import ProjectError, project_exists

_IMAGE_EXTS = (".png", ".jpg", ".jpeg")

# 列名候補（前のものを優先して拾う）
_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "precision": ["metrics/precision(B)", "metrics/precision", "precision"],
    "recall": ["metrics/recall(B)", "metrics/recall", "recall"],
    "map50": ["metrics/mAP50(B)", "metrics/mAP50", "mAP50"],
    "map50_95": ["metrics/mAP50-95(B)", "metrics/mAP50-95", "mAP50-95"],
    # segment（Mask）メトリクス。detect学習では存在しないため null になる。
    "mask_precision": ["metrics/precision(M)"],
    "mask_recall": ["metrics/recall(M)"],
    "mask_map50": ["metrics/mAP50(M)"],
    "mask_map50_95": ["metrics/mAP50-95(M)"],
    "train_box_loss": ["train/box_loss"],
    "train_cls_loss": ["train/cls_loss"],
    "train_dfl_loss": ["train/dfl_loss"],
    "val_box_loss": ["val/box_loss"],
    "val_cls_loss": ["val/cls_loss"],
    "val_dfl_loss": ["val/dfl_loss"],
}

# 成果物の表示優先順位
_ARTIFACT_PRIORITY = [
    "results.png",
    "confusion_matrix.png",
    "confusion_matrix_normalized.png",
    "PR_curve.png",
    "F1_curve.png",
    "P_curve.png",
    "R_curve.png",
    "labels.jpg",
    "labels_correlogram.jpg",
]


class EvaluationError(Exception):
    """評価操作の業務エラー。"""


class EvaluationNotFoundError(EvaluationError):
    """対象が見つからない（HTTP 404相当）。"""


class EvaluationBadRequestError(EvaluationError):
    """不正なリクエスト（HTTP 400相当）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _require_run_dir(name: str, job_id: str) -> Path:
    run_dir = paths.train_job_dir(name, job_id)
    if not run_dir.exists():
        raise EvaluationNotFoundError(f"学習ジョブ '{job_id}' が見つかりません。")
    return run_dir


def _read_status(run_dir: Path) -> str:
    job_json = run_dir / "job.json"
    if job_json.exists():
        try:
            return json.loads(job_json.read_text(encoding="utf-8-sig")).get(
                "status", "unknown"
            )
        except (json.JSONDecodeError, OSError):
            return "unknown"
    return "unknown"


def _to_number(value: str) -> Any:
    """数値変換できれば float、できなければ元の文字列を返す。"""
    v = value.strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return v


def _parse_csv(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """results.csv を (列名, 行リスト) に解析する。"""
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.reader(text.splitlines())
    raw_rows = [r for r in reader if any(cell.strip() for cell in r)]  # 空行無視
    if not raw_rows:
        return [], []

    columns = [c.strip() for c in raw_rows[0]]
    rows: list[dict[str, Any]] = []
    for raw in raw_rows[1:]:
        row: dict[str, Any] = {}
        for col, cell in zip(columns, raw):
            num = _to_number(cell)
            if col == "epoch" and isinstance(num, float):
                num = int(num)
            row[col] = num
        rows.append(row)
    return columns, rows


def _pick(row: dict[str, Any], candidates: list[str]) -> float | None:
    for key in candidates:
        if key in row and isinstance(row[key], (int, float)):
            return float(row[key])
    return None


def _summary_from_rows(rows: list[dict[str, Any]]) -> EvaluationSummary | None:
    if not rows:
        return None
    last = rows[-1]
    epoch_val = last.get("epoch")
    epoch = int(epoch_val) if isinstance(epoch_val, (int, float)) else None
    values = {key: _pick(last, cands) for key, cands in _COLUMN_CANDIDATES.items()}
    return EvaluationSummary(epoch=epoch, **values)


def _list_artifacts(name: str, job_id: str, run_dir: Path) -> list[Artifact]:
    proj_dir = paths.project_dir(name)
    # 直下＋サブディレクトリ(rglob)を走査。Ultralyticsのバージョン差でweights以外の
    # 階層に出る場合にも対応。画像拡張子のみ。同名は直下を優先（重複除外）。
    seen: dict[str, Path] = {}
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS:
            continue
        if "weights" in p.relative_to(run_dir).parts:
            continue  # weights配下の画像は対象外
        key = p.name.lower()
        if key not in seen:
            seen[key] = p
    found: list[Path] = list(seen.values())

    priority_lower = [n.lower() for n in _ARTIFACT_PRIORITY]

    def sort_key(p: Path) -> tuple[int, str]:
        try:
            return (priority_lower.index(p.name.lower()), p.name)
        except ValueError:
            return (len(priority_lower), p.name)

    artifacts: list[Artifact] = []
    for p in sorted(found, key=sort_key):
        rel = p.relative_to(proj_dir).as_posix()
        artifacts.append(
            Artifact(
                name=p.name,
                type="image",
                path=rel,
                url=(
                    f"/api/projects/{name}/train-jobs/{job_id}/artifacts/{p.name}"
                ),
            )
        )
    return artifacts


def get_evaluation(name: str, job_id: str) -> EvaluationResponse:
    _require_project(name)
    run_dir = _require_run_dir(name, job_id)
    proj_dir = paths.project_dir(name)

    results_csv = run_dir / "results.csv"
    best = run_dir / "weights" / "best.pt"
    last = run_dir / "weights" / "last.pt"

    summary: EvaluationSummary | None = None
    if results_csv.exists():
        try:
            _, rows = _parse_csv(results_csv)
            summary = _summary_from_rows(rows)
        except (OSError, csv.Error):
            summary = None

    return EvaluationResponse(
        project_name=name,
        job_id=job_id,
        status=_read_status(run_dir),
        run_path=run_dir.relative_to(proj_dir).as_posix(),
        has_results_csv=results_csv.exists(),
        has_best_model=best.exists(),
        has_last_model=last.exists(),
        summary=summary,
        artifacts=_list_artifacts(name, job_id, run_dir),
    )


def get_metrics(name: str, job_id: str) -> MetricsResponse:
    _require_project(name)
    run_dir = _require_run_dir(name, job_id)
    results_csv = run_dir / "results.csv"
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    if results_csv.exists():
        try:
            columns, rows = _parse_csv(results_csv)
        except (OSError, csv.Error):
            columns, rows = [], []
    return MetricsResponse(
        project_name=name, job_id=job_id, columns=columns, rows=rows
    )


def resolve_artifact(name: str, job_id: str, filename: str) -> Path:
    """成果物画像の実パスを安全に解決する（パストラバーサル対策）。"""
    _require_project(name)
    run_dir = _require_run_dir(name, job_id)

    # ファイル名のみ許可（サブディレクトリ・".." を拒否）
    if filename != Path(filename).name or filename in ("", ".", ".."):
        raise EvaluationBadRequestError("不正なファイル名です。")
    if Path(filename).suffix.lower() not in _IMAGE_EXTS:
        raise EvaluationBadRequestError("画像ファイル（png/jpg/jpeg）のみ配信できます。")

    # まず直下、無ければ run_dir 配下を再帰探索（大文字小文字無視・画像のみ）
    direct = (run_dir / filename).resolve()
    run_resolved = run_dir.resolve()
    if direct.is_file() and run_resolved in direct.parents:
        return direct
    for p in run_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS:
            continue
        if "weights" in p.relative_to(run_dir).parts:
            continue
        if p.name.lower() == filename.lower():
            return p.resolve()
    raise EvaluationNotFoundError(f"成果物 '{filename}' が見つかりません。")
