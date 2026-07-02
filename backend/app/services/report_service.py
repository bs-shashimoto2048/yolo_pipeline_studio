"""レポート生成。

プロジェクト各工程の結果（概要/クラス/選別/前処理/データセット/学習評価/
推論分析/採用モデル/改善候補）を既存サービスから集約し、JSON と Markdown を
reports/ に出力する。欠損・未実行データがあっても落ちないよう、各収集は
個別に try で握りつぶす。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import paths
from ..schemas.report import (
    ReportCreate,
    ReportGenerateResponse,
    ReportListItem,
    ReportListResponse,
)
from . import (
    class_service,
    dataset_service,
    experiment_service,
    label_validation_service,
    model_registry_service,
    prediction_service,
    preprocess_service,
    project_service,
    selection_service,
)
from .project_service import ProjectError, project_exists

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ReportError(Exception):
    pass


class ReportNotFoundError(ReportError):
    """404相当。"""


class ReportValidationError(ReportError):
    """400相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - レポート集約は欠損で落とさない
        return default


# ---- 各セクションの収集 ----

def _project_overview(name: str) -> dict:
    summary = _safe(lambda: project_service.get_summary(name).model_dump(), {})
    pre = _safe(lambda: preprocess_service.get_info(name), None)
    sel_exists = paths.selection_path(name).exists()
    datasets = _safe(lambda: dataset_service.list_datasets(name).datasets, [])
    train_jobs = _safe(lambda: experiment_service.list_experiments(name).experiments, [])
    predicts = _safe(lambda: prediction_service.list_jobs(name).jobs, [])
    selected = _safe(lambda: model_registry_service.get_selected(name).model_dump(), None)
    return {
        "project_name": name,
        "created_at": summary.get("created_at"),
        "image_count": summary.get("image_count", 0),
        "class_count": summary.get("class_count", 0),
        "processed_image_count": pre.processed_count if pre else 0,
        "selection_executed": sel_exists,
        "dataset_count": len(datasets),
        "train_job_count": len(train_jobs),
        "predict_job_count": len(predicts),
        "selected_model_id": selected.get("selected_model_id") if selected else None,
    }


def _classes(name: str) -> list[dict]:
    classes = _safe(lambda: class_service.get_classes(name), [])
    color_map = {c.id: c.color for c in classes}
    report = _safe(lambda: label_validation_service.validate_labels(name), None)
    stats = {cs.class_id: cs for cs in report.class_stats} if report else {}
    out = []
    for c in classes:
        st = stats.get(c.id)
        out.append({
            "class_id": c.id,
            "class_name": c.name,
            "color": color_map.get(c.id),
            "bbox_count": st.bbox_count if st else 0,
            "image_count": st.image_count if st else 0,
        })
    return out


def _selection(name: str) -> dict:
    sel = _safe(lambda: selection_service.get_selection(name), None)
    if sel is None:
        return {"status": "未実行"}
    return {"status": "実行済み", **sel.summary.model_dump()}


def _preprocess(name: str) -> dict:
    info = _safe(lambda: preprocess_service.get_info(name), None)
    if info is None or not info.has_processed_images:
        return {"status": "未実行"}
    meta = info.metadata or {}
    return {
        "status": "実行済み",
        "processed_count": info.processed_count,
        "job_name": meta.get("job_name"),
        "settings": meta.get("settings"),
    }


def _datasets(name: str) -> list[dict]:
    items = _safe(lambda: dataset_service.list_datasets(name).datasets, [])
    out = []
    for d in items:
        meta = {}
        meta_path = paths.dataset_dir(name, d.dataset_name) / "metadata.json"
        if meta_path.exists():
            meta = _safe(lambda mp=meta_path: json.loads(mp.read_text(encoding="utf-8-sig")), {})
        out.append({
            "dataset_name": d.dataset_name,
            "train_image_count": d.train_image_count,
            "val_image_count": d.val_image_count,
            "test_image_count": d.test_image_count,
            "class_count": d.class_count,
            "image_source": meta.get("image_source"),
            "include_empty_labels": meta.get("include_empty_labels"),
            "include_unlabeled_images": meta.get("include_unlabeled_images"),
        })
    return out


def _experiments(name: str) -> list[dict]:
    exps = _safe(lambda: experiment_service.list_experiments(name).experiments, [])
    out = []
    for e in exps:
        out.append({
            "train_job_id": e.train_job_id,
            "status": e.status,
            "dataset_name": e.dataset_name,
            "model": e.model,
            "augmentation_preset": e.augmentation_preset,
            "epochs": e.epochs,
            "imgsz": e.imgsz,
            "batch": e.batch,
            "device": e.device,
            "precision": e.precision,
            "recall": e.recall,
            "map50": e.map50,
            "map50_95": e.map50_95,
            "best_model_path": e.best_model_path,
        })
    return out


def _predictions(name: str) -> list[dict]:
    jobs = _safe(lambda: prediction_service.list_jobs(name).jobs, [])
    out = []
    for j in jobs:
        brief = _safe(lambda jj=j: experiment_service._analysis_brief(name, jj.predict_job_id), None)
        out.append({
            "predict_job_id": j.predict_job_id,
            "train_job_id": j.train_job_id,
            "weight_type": j.weight_type,
            "image_count": j.image_count,
            "detection_count": j.detection_count,
            "tp_count": brief.tp_count if brief else None,
            "fp_count": brief.fp_count if brief else None,
            "fn_count": brief.fn_count if brief else None,
            "class_mismatch_count": brief.class_mismatch_count if brief else None,
            "precision": brief.precision if brief else None,
            "recall": brief.recall if brief else None,
            "f1": brief.f1 if brief else None,
        })
    return out


def _selected_model(name: str) -> dict | None:
    sel = _safe(lambda: model_registry_service.get_selected(name).model_dump(), None)
    if sel is None:
        return None
    ev = _safe(lambda: experiment_service._evaluation(name, sel["train_job_id"]), None)
    latest = _safe(lambda: experiment_service._latest_analysis(name, sel["train_job_id"]), None)
    return {
        **sel,
        "evaluation": ev.model_dump() if ev else None,
        "latest_analysis": latest.model_dump() if latest else None,
    }


def _improvements(selection: dict, experiments: list[dict], predictions: list[dict]) -> list[str]:
    tips: list[str] = []
    tot_fp = sum((p.get("fp_count") or 0) for p in predictions)
    tot_fn = sum((p.get("fn_count") or 0) for p in predictions)
    tot_cm = sum((p.get("class_mismatch_count") or 0) for p in predictions)
    if tot_fn > 0:
        tips.append("FN（見逃し）があります。該当クラスの画像追加・再アノテーションを推奨します。")
    if tot_fp > 0:
        tips.append("FP（誤検出）があります。ネガティブ画像の追加を推奨します。")
    if tot_cm > 0:
        tips.append("class_mismatch があります。クラス定義の見直しを推奨します。")
    if selection.get("review_count", 0) > 0:
        tips.append("review 画像があります。画像選別結果の確認を推奨します。")
    map_vals = [e.get("map50_95") for e in experiments if e.get("map50_95") is not None]
    if map_vals and max(map_vals) < 0.5:
        tips.append("mAP50-95 が低めです。bbox精度・アノテーション品質の確認を推奨します。")
    if not tips:
        tips.append("現時点で明確な改善候補は検出されませんでした。")
    return tips


def _gather(name: str, req: ReportCreate) -> dict:
    selection = _selection(name)
    experiments = _experiments(name)
    predictions = _predictions(name) if req.include_predictions else []
    content: dict[str, Any] = {
        "project_overview": _project_overview(name),
        "classes": _classes(name),
        "selection": selection,
        "preprocess": _preprocess(name),
        "datasets": _datasets(name),
        "experiments": experiments,
        "selected_model": _selected_model(name),
        "improvement_suggestions": _improvements(selection, experiments, predictions),
    }
    if req.include_predictions:
        content["predictions"] = predictions
    return content


# ---- Markdown 生成 ----

def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "（データなし）\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join("---" for _ in headers) + " |\n"
    for r in rows:
        out += "| " + " | ".join("" if c is None else str(c) for c in r) + " |\n"
    return out


def _to_markdown(name: str, report_id: str, created_at: str, content: dict) -> str:
    ov = content["project_overview"]
    md = [f"# YOLO Tuning Studio レポート\n",
          f"- レポートID: {report_id}",
          f"- 生成日時: {created_at}\n",
          "## 1. プロジェクト概要\n",
          _md_table(
              ["項目", "値"],
              [
                  ["プロジェクト", ov.get("project_name")],
                  ["作成日時", ov.get("created_at")],
                  ["画像数", ov.get("image_count")],
                  ["クラス数", ov.get("class_count")],
                  ["processed画像数", ov.get("processed_image_count")],
                  ["画像選別", "実行済み" if ov.get("selection_executed") else "未実行"],
                  ["データセット数", ov.get("dataset_count")],
                  ["学習ジョブ数", ov.get("train_job_count")],
                  ["推論ジョブ数", ov.get("predict_job_count")],
                  ["採用モデル", ov.get("selected_model_id") or "未設定"],
              ],
          ),
          "## 2. クラス情報\n",
          _md_table(["ID", "クラス名", "色", "bbox数", "画像数"],
                    [[c["class_id"], c["class_name"], c["color"], c["bbox_count"], c["image_count"]]
                     for c in content["classes"]]),
          "## 3. 画像選別結果\n",
          _md_table(["項目", "値"], [[k, v] for k, v in content["selection"].items()]),
          "## 4. 前処理結果\n",
          _md_table(["項目", "値"],
                    [[k, (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v)]
                     for k, v in content["preprocess"].items()]),
          "## 5. データセット一覧\n",
          _md_table(["名前", "train", "val", "test", "クラス数", "image_source"],
                    [[d["dataset_name"], d["train_image_count"], d["val_image_count"],
                      d["test_image_count"], d["class_count"], d["image_source"]]
                     for d in content["datasets"]]),
          "## 6. 学習・評価結果\n",
          _md_table(["train_job", "status", "model", "aug", "epochs", "precision", "recall", "mAP50", "mAP50-95"],
                    [[e["train_job_id"], e["status"], e["model"], e["augmentation_preset"],
                      e["epochs"], e["precision"], e["recall"], e["map50"], e["map50_95"]]
                     for e in content["experiments"]]),
          "## 7. 推論・誤検出分析\n",
          _md_table(["predict_job", "train_job", "weight", "画像", "検出", "TP", "FP", "FN", "mismatch", "F1"],
                    [[p["predict_job_id"], p["train_job_id"], p["weight_type"], p["image_count"],
                      p["detection_count"], p["tp_count"], p["fp_count"], p["fn_count"],
                      p["class_mismatch_count"], p["f1"]]
                     for p in content.get("predictions", [])]),
          "## 8. 採用モデル\n"]
    sm = content["selected_model"]
    if sm:
        md.append(_md_table(["項目", "値"], [
            ["model_id", sm.get("selected_model_id")],
            ["train_job_id", sm.get("train_job_id")],
            ["weight_type", sm.get("weight_type")],
            ["model_path", sm.get("model_path")],
            ["selected_at", sm.get("selected_at")],
            ["memo", sm.get("memo")],
        ]))
    else:
        md.append("採用モデルは未設定です。\n")
    md.append("## 9. 改善候補\n")
    for tip in content["improvement_suggestions"]:
        md.append(f"- {tip}")
    md.append("\n## 10. 付録\n")
    md.append(f"- このレポートのJSON: reports/{report_id}.json")
    return "\n".join(md) + "\n"


# ---- 公開API ----

def _resolve_report_id(report_name: str | None) -> str:
    if report_name:
        if not _NAME_RE.match(report_name):
            raise ReportValidationError(
                "report_name は英数・アンダースコア・ハイフンのみです。"
            )
        return report_name
    return "report_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def generate(name: str, req: ReportCreate) -> ReportGenerateResponse:
    _require_project(name)
    if req.format not in ("markdown", "json", "both"):
        raise ReportValidationError("format は markdown / json / both のいずれかです。")

    report_id = _resolve_report_id(req.report_name)
    created_at = datetime.now().isoformat(timespec="seconds")
    content = _gather(name, req)
    record = {"report_id": report_id, "created_at": created_at, "content": content}

    rdir = paths.reports_dir(name)
    rdir.mkdir(parents=True, exist_ok=True)

    # JSON は常に保存（一覧/詳細/latest の正本）
    json_path = rdir / f"{report_id}.json"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (rdir / "latest_report.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md_rel = None
    if req.format in ("markdown", "both"):
        md_path = rdir / f"{report_id}.md"
        md_path.write_text(_to_markdown(name, report_id, created_at, content), encoding="utf-8")
        md_rel = f"reports/{report_id}.md"

    return ReportGenerateResponse(
        project_name=name,
        report_id=report_id,
        created_at=created_at,
        markdown_path=md_rel,
        json_path=f"reports/{report_id}.json",
    )


def list_reports(name: str) -> ReportListResponse:
    _require_project(name)
    rdir = paths.reports_dir(name)
    items: list[ReportListItem] = []
    if rdir.exists():
        for jp in sorted(rdir.glob("*.json")):
            if jp.name == "latest_report.json":
                continue
            created = None
            data = _safe(lambda p=jp: json.loads(p.read_text(encoding="utf-8-sig")), {})
            created = data.get("created_at")
            rid = jp.stem
            md = rdir / f"{rid}.md"
            items.append(ReportListItem(
                report_id=rid,
                created_at=created,
                markdown_path=f"reports/{rid}.md" if md.exists() else None,
                json_path=f"reports/{rid}.json",
            ))
    return ReportListResponse(project_name=name, reports=items)


def _validate_report_id(report_id: str) -> None:
    if not _NAME_RE.match(report_id):
        raise ReportValidationError("不正な report_id です。")


def get_report(name: str, report_id: str) -> dict:
    _require_project(name)
    _validate_report_id(report_id)
    jp = paths.reports_dir(name) / f"{report_id}.json"
    if not jp.exists():
        raise ReportNotFoundError(f"レポート '{report_id}' が見つかりません。")
    return json.loads(jp.read_text(encoding="utf-8-sig"))


def resolve_download(name: str, report_id: str, fmt: str) -> Path:
    _require_project(name)
    _validate_report_id(report_id)
    if fmt not in ("markdown", "json"):
        raise ReportValidationError("format は markdown または json です。")
    ext = ".md" if fmt == "markdown" else ".json"
    rdir = paths.reports_dir(name).resolve()
    target = (rdir / f"{report_id}{ext}").resolve()
    if rdir not in target.parents:
        raise ReportValidationError("不正なパスです。")
    if not target.is_file():
        raise ReportNotFoundError(f"レポートファイルが見つかりません（{fmt}）。")
    return target
