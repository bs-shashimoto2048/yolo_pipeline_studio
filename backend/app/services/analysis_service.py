"""誤検出分析。

推論結果（predictions/{predict_job_id}/results.json）と正解ラベル
（annotations/labels/{stem}.txt）を比較し、画像単位・クラス単位で
TP / FP / FN / class_mismatch を判定する。

判定ルール（task.md）:
- TP: class一致 かつ IoU>=iou_threshold。同一GTへ複数一致は最高IoUのみTP、残りはFP。
- FP: どのGTとも一致しない、または重複として余った prediction。
- class_mismatch: IoU>=iou_threshold だが class不一致。
- FN: どのTPにも対応しなかった ground_truth（class_mismatch はGTを消費しない）。
- precision = tp/(tp+fp), recall = tp/gt_count, f1 = 2PR/(P+R)。
  prediction_count = tp+fp+class_mismatch、gt_count = tp+fn。

正解ラベルは utf-8-sig で読む。不正なYOLO行は 400。元データは破壊しない。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core import paths
from ..schemas.analysis import (
    AnalysisItem,
    AnalysisResponse,
    AnalysisSummary,
    Bbox,
    ClassStat,
    ImageResult,
)
from . import class_service
from .project_service import ProjectError, project_exists


class AnalysisError(Exception):
    pass


class AnalysisNotFoundError(AnalysisError):
    """対象が見つからない（404）。"""


class AnalysisValidationError(AnalysisError):
    """事前チェック・入力不正（400）。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return round(precision, 6), round(recall, 6), round(f1, 6)


def _parse_gt(path: Path) -> list[dict]:
    """正解ラベルを読む。不正行は AnalysisValidationError。

    detect(bbox) 形式 ``class xc yc w h`` (5列) に加え、
    segment(polygon) 形式 ``class x1 y1 x2 y2 ...`` (1+2*点数, 点数>=3) も受理し、
    polygon は外接bboxへ変換して bbox 同士で比較する。
    """
    if not path.exists():
        return []
    gts: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        n = len(parts)
        # 5列=bbox、それ以外は polygon(奇数列・点3つ以上)として扱う
        is_bbox = n == 5
        is_polygon = n >= 7 and (n - 1) % 2 == 0
        if not (is_bbox or is_polygon):
            raise AnalysisValidationError(
                f"正解ラベル {path.name} の {lineno} 行目: 列数が不正です。"
            )
        try:
            cid = int(parts[0])
            vals = [float(v) for v in parts[1:]]
        except ValueError as e:
            raise AnalysisValidationError(
                f"正解ラベル {path.name} の {lineno} 行目: 数値変換に失敗しました。"
            ) from e
        if is_bbox:
            xc, yc, w, h = vals[0], vals[1], vals[2], vals[3]
        else:
            # polygon 頂点(正規化)の外接矩形を bbox とする
            xs = vals[0::2]
            ys = vals[1::2]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            xc, yc = (x1 + x2) / 2, (y1 + y2) / 2
            w, h = x2 - x1, y2 - y1
        gts.append({"class_id": cid, "bbox": (xc, yc, w, h)})
    return gts


def _bbox(t: tuple[float, float, float, float]) -> Bbox:
    return Bbox(x_center=t[0], y_center=t[1], width=t[2], height=t[3])


def _analyze_image(preds: list[dict], gts: list[dict], iou_thr: float):
    """1画像分の判定。items と各カウントを返す。"""
    n_p, n_g = len(preds), len(gts)
    iou_mat = [[_iou(preds[i]["bbox"], gts[j]["bbox"]) for j in range(n_g)] for i in range(n_p)]

    status: list[str | None] = [None] * n_p
    match_gt: list[int | None] = [None] * n_p
    match_iou: list[float | None] = [None] * n_p
    gt_tp_matched = [False] * n_g

    # TP割当: class一致 & IoU>=thr のペアを IoU降順で貪欲マッチ
    cands = []
    for i in range(n_p):
        for j in range(n_g):
            if iou_mat[i][j] >= iou_thr and preds[i]["class_id"] == gts[j]["class_id"]:
                cands.append((iou_mat[i][j], preds[i]["confidence"], i, j))
    cands.sort(key=lambda t: (-t[0], -t[1]))
    for iou_v, _conf, i, j in cands:
        if status[i] is None and not gt_tp_matched[j]:
            status[i] = "tp"
            match_gt[i] = j
            match_iou[i] = iou_v
            gt_tp_matched[j] = True

    # 残りの prediction を分類
    for i in range(n_p):
        if status[i] is not None:
            continue
        best_same = best_diff = None
        for j in range(n_g):
            if iou_mat[i][j] < iou_thr:
                continue
            if preds[i]["class_id"] == gts[j]["class_id"]:
                if best_same is None or iou_mat[i][j] > iou_mat[i][best_same]:
                    best_same = j
            else:
                if best_diff is None or iou_mat[i][j] > iou_mat[i][best_diff]:
                    best_diff = j
        if best_same is not None:
            status[i] = "fp"  # 同クラス重複
            match_gt[i] = best_same
            match_iou[i] = iou_mat[i][best_same]
        elif best_diff is not None:
            status[i] = "class_mismatch"
            match_gt[i] = best_diff
            match_iou[i] = iou_mat[i][best_diff]
        else:
            status[i] = "fp"

    return status, match_gt, match_iou, gt_tp_matched


def _run_analysis(name: str, predict_job_id: str, iou_thr: float, conf_thr: float) -> AnalysisResponse:
    pred_dir = paths.predict_job_dir(name, predict_job_id)
    if not pred_dir.exists():
        raise AnalysisNotFoundError(f"推論ジョブ '{predict_job_id}' が見つかりません。")

    # status チェック
    job_json = pred_dir / "job.json"
    status = "unknown"
    if job_json.exists():
        try:
            status = json.loads(job_json.read_text(encoding="utf-8-sig")).get("status", "unknown")
        except json.JSONDecodeError:
            status = "unknown"
    if status != "completed":
        raise AnalysisValidationError(
            f"推論ジョブの status が '{status}' です。completed のジョブのみ分析できます。"
        )

    results_json = pred_dir / "results.json"
    if not results_json.exists():
        raise AnalysisValidationError("results.json が存在しません。")
    data = json.loads(results_json.read_text(encoding="utf-8-sig"))

    class_name_map = {c.id: c.name for c in class_service.get_classes(name)}

    def cname(cid: int | None) -> str | None:
        if cid is None:
            return None
        return class_name_map.get(cid, str(cid))

    labels_dir = paths.labels_dir(name)
    image_results: list[ImageResult] = []

    # 全体集計
    tot = {"tp": 0, "fp": 0, "fn": 0, "cm": 0, "gt": 0, "pred": 0}
    # クラス別集計（pred classで tp/fp/cm/pred、gt classで gt/fn）
    cls: dict[int, dict[str, int]] = {}

    def cbucket(cid: int) -> dict[str, int]:
        return cls.setdefault(cid, {"tp": 0, "fp": 0, "fn": 0, "cm": 0, "gt": 0, "pred": 0})

    for r in data.get("results", []):
        image_id = r.get("image_id", "")
        image_name = r.get("image_name", "")

        preds = []
        for d in r.get("detections", []):
            if float(d.get("confidence", 0.0)) >= conf_thr:
                preds.append({
                    "class_id": int(d["class_id"]),
                    "confidence": float(d.get("confidence", 0.0)),
                    "class_name": d.get("class_name"),
                    "bbox": (
                        float(d["x_center"]), float(d["y_center"]),
                        float(d["width"]), float(d["height"]),
                    ),
                })

        gts = _parse_gt(labels_dir / f"{image_id}.txt")

        status_list, match_gt, match_iou, gt_tp_matched = _analyze_image(preds, gts, iou_thr)

        items: list[AnalysisItem] = []
        c_tp = c_fp = c_cm = 0
        for i, st in enumerate(status_list):
            p = preds[i]
            j = match_gt[i]
            gt_cls = gts[j]["class_id"] if j is not None else None
            gt_box = _bbox(gts[j]["bbox"]) if j is not None else None
            item = AnalysisItem(
                type=st,
                class_id=p["class_id"],
                class_name=cname(p["class_id"]),
                confidence=p["confidence"],
                iou=round(match_iou[i], 6) if match_iou[i] is not None else None,
                prediction_bbox=_bbox(p["bbox"]),
                ground_truth_bbox=gt_box,
            )
            if st == "class_mismatch":
                item.gt_class_id = gt_cls
                item.gt_class_name = cname(gt_cls)
            items.append(item)

            cbucket(p["class_id"])["pred"] += 1
            if st == "tp":
                c_tp += 1
                cbucket(p["class_id"])["tp"] += 1
            elif st == "fp":
                c_fp += 1
                cbucket(p["class_id"])["fp"] += 1
            elif st == "class_mismatch":
                c_cm += 1
                cbucket(p["class_id"])["cm"] += 1

        # FN（TP未対応のGT）
        c_fn = 0
        for j, matched in enumerate(gt_tp_matched):
            cbucket(gts[j]["class_id"])["gt"] += 1
            if not matched:
                c_fn += 1
                items.append(AnalysisItem(
                    type="fn",
                    class_id=gts[j]["class_id"],
                    class_name=cname(gts[j]["class_id"]),
                    ground_truth_bbox=_bbox(gts[j]["bbox"]),
                ))

        p_, r_, f_ = _metrics(c_tp, c_fp, c_fn)
        result_url = (
            f"/api/projects/{name}/predict-jobs/{predict_job_id}/images/{image_name}"
            if image_name else None
        )
        image_results.append(ImageResult(
            image_id=image_id,
            image_name=image_name,
            result_image_url=result_url,
            ground_truth_count=len(gts),
            prediction_count=len(preds),
            tp_count=c_tp,
            fp_count=c_fp,
            fn_count=c_fn,
            class_mismatch_count=c_cm,
            precision=p_, recall=r_, f1=f_,
            items=items,
        ))

        tot["tp"] += c_tp
        tot["fp"] += c_fp
        tot["fn"] += c_fn
        tot["cm"] += c_cm
        tot["gt"] += len(gts)
        tot["pred"] += len(preds)

    # クラス別統計（classes.yaml のクラス + 実際に出現したクラス）
    all_cids = sorted(set(class_name_map.keys()) | set(cls.keys()))
    class_stats: list[ClassStat] = []
    for cid in all_cids:
        b = cls.get(cid, {"tp": 0, "fp": 0, "fn": 0, "cm": 0, "gt": 0, "pred": 0})
        fn_c = b["gt"] - b["tp"]
        p_, r_, f_ = _metrics(b["tp"], b["fp"], fn_c)
        class_stats.append(ClassStat(
            class_id=cid,
            class_name=cname(cid),
            ground_truth_count=b["gt"],
            prediction_count=b["pred"],
            tp_count=b["tp"],
            fp_count=b["fp"],
            fn_count=fn_c,
            class_mismatch_count=b["cm"],
            precision=p_, recall=r_, f1=f_,
        ))

    gp, gr, gf = _metrics(tot["tp"], tot["fp"], tot["fn"])
    summary = AnalysisSummary(
        image_count=len(image_results),
        ground_truth_count=tot["gt"],
        prediction_count=tot["pred"],
        tp_count=tot["tp"],
        fp_count=tot["fp"],
        fn_count=tot["fn"],
        class_mismatch_count=tot["cm"],
        precision=gp, recall=gr, f1=gf,
    )

    return AnalysisResponse(
        project_name=name,
        predict_job_id=predict_job_id,
        iou_threshold=iou_thr,
        conf_threshold=conf_thr,
        summary=summary,
        class_stats=class_stats,
        image_results=image_results,
    )


def run_and_save(name: str, predict_job_id: str, iou_thr: float, conf_thr: float) -> AnalysisResponse:
    _require_project(name)
    if not (0.0 <= iou_thr <= 1.0):
        raise AnalysisValidationError("iou_threshold は 0〜1 で指定してください。")
    if not (0.0 <= conf_thr <= 1.0):
        raise AnalysisValidationError("conf_threshold は 0〜1 で指定してください。")

    result = _run_analysis(name, predict_job_id, iou_thr, conf_thr)

    analysis_json = paths.predict_job_dir(name, predict_job_id) / "analysis.json"
    analysis_json.write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    return result


def get_saved(name: str, predict_job_id: str) -> AnalysisResponse:
    _require_project(name)
    pred_dir = paths.predict_job_dir(name, predict_job_id)
    if not pred_dir.exists():
        raise AnalysisNotFoundError(f"推論ジョブ '{predict_job_id}' が見つかりません。")
    analysis_json = pred_dir / "analysis.json"
    if not analysis_json.exists():
        raise AnalysisNotFoundError("分析結果がまだありません。先に分析を実行してください。")
    data = json.loads(analysis_json.read_text(encoding="utf-8-sig"))
    return AnalysisResponse(**data)
