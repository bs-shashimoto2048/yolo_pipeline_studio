"""digital右端桁・drum赤サブ桁のconfidence安定性を非Testデータで診断する（Issue #34）。

production model・weight・preprocess_profileをそのまま使い、production threshold
（digital 0.60 / drum 0.80）に加えて診断専用の低threshold（0.05）でも推論し、
「boxが本当に存在しないのか、閾値未満で切られているだけなのか」を区別する。

対象データはIssue #24/#25/#26で既にfreeze・Test/Hard-Val非重複確認済みの
Train所属stem（`data_manifests/meter_digital_combined_split_v2.csv` /
`meter_src004_split_v3.csv`のsplit=="train"行）のみ。Test/Hard-Valの
predict/evaluateは一切行わない。

read-only診断専用script。production worker/service/model/threshold/ROI/preprocessは
一切変更しない。fixture画像本体（projects/配下の生画像）もGit管理外のローカル専用資産。

実行例:
    .venv\\Scripts\\python.exe scripts\\analyze_last_digit_stability.py --project digital
    .venv\\Scripts\\python.exe scripts\\analyze_last_digit_stability.py --project drum
    .venv\\Scripts\\python.exe scripts\\analyze_last_digit_stability.py --project digital --limit 20
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

DIAGNOSTIC_CONF = 0.05
READING_LEN = 7

PROJECTS: dict[str, dict] = {
    "digital": {
        "project": "meter_src002",
        "manifest": REPO_ROOT / "data_manifests" / "meter_digital_combined_split_v2.csv",
        "train_job_id": "production_combined_v2_5z",
        "weight_type": "best",
        "expected_sha256": "630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61",
        "production_conf": 0.60,
        "sweep": [0.40, 0.50, 0.55, 0.60, 0.65, 0.70],
    },
    "drum": {
        "project": "meter_src004",
        "manifest": REPO_ROOT / "data_manifests" / "meter_src004_split_v3.csv",
        "train_job_id": "candidate_roi_v3_5",
        "weight_type": "best",
        "expected_sha256": "45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db",
        "production_conf": 0.80,
        "sweep": [0.50, 0.60, 0.70, 0.75, 0.80, 0.85],
    },
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest_rows(label: str) -> list[dict]:
    cfg = PROJECTS[label]
    with cfg["manifest"].open(encoding="utf-8") as fh:
        rows = [
            r for r in csv.DictReader(fh)
            if r["project"] == cfg["project"] and r["split"] == "train"
        ]
    rows.sort(key=lambda r: r["image_stem"])
    return rows


def compute_phase(rows: list[dict]) -> list[str]:
    """隣接するreading_gtの末尾桁と比較し、stable/boundary（transitionの近似proxy）を判定する。

    真の"ambiguous-middle"フレーム（回転途中の物理形状）は、periodic snapshot
    capture（2〜10分間隔）では取得できないため、本scriptでは「隣接capture間で
    末尾桁が変化しているか」をtransitionの近似proxyとして扱う（docの限界節参照）。
    """
    last_digits = [r["reading_gt"][-1] for r in rows]
    phases = []
    for i in range(len(rows)):
        prev_diff = i > 0 and last_digits[i] != last_digits[i - 1]
        next_diff = i < len(rows) - 1 and last_digits[i] != last_digits[i + 1]
        phases.append("boundary" if (prev_diff or next_diff) else "stable")
    return phases


def load_selected_model(project: str) -> dict:
    p = REPO_ROOT / "projects" / project / "models" / "selected_model.json"
    return json.loads(p.read_text(encoding="utf-8"))


def analyze_project(label: str, limit: int | None = None) -> dict:
    cfg = PROJECTS[label]
    rows = load_manifest_rows(label)
    if limit:
        rows = rows[:limit]
    phases = compute_phase(load_manifest_rows(label))[: len(rows)] if limit else compute_phase(rows)

    sel = load_selected_model(cfg["project"])
    if sel.get("train_job_id") != cfg["train_job_id"] or sel.get("weight_type") != cfg["weight_type"]:
        raise RuntimeError(
            f"[{label}] selected_model.json が想定と異なります（production構成が変わっている"
            f"可能性）。診断を中止します: {sel.get('train_job_id')}:{sel.get('weight_type')}"
        )
    weight_path = (
        REPO_ROOT / "projects" / cfg["project"] / "runs" / "train"
        / cfg["train_job_id"] / "weights" / f"{cfg['weight_type']}.pt"
    )
    if not weight_path.exists():
        return {"skipped": True, "reason": f"production weight not available locally ({weight_path})"}
    actual_sha = sha256_file(weight_path)
    if actual_sha != cfg["expected_sha256"]:
        raise RuntimeError(
            f"[{label}] weight SHA256 mismatch (expected {cfg['expected_sha256']}, got {actual_sha}). "
            "production artifactが想定と異なるため診断を中止します。"
        )
    profile = sel.get("preprocess_profile")
    if not profile:
        raise RuntimeError(f"[{label}] selected_model.json に preprocess_profile がありません。")

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from app.schemas.preprocess import PreprocessSettings  # noqa: PLC0415
    from app.services import preprocess_service  # noqa: PLC0415
    from ultralytics import YOLO  # noqa: PLC0415

    ps = PreprocessSettings(**profile)
    model = YOLO(str(weight_path))

    img_dir = REPO_ROOT / "projects" / cfg["project"] / "raw" / "images"
    frames = []
    skipped_missing_image = 0
    for row, phase in zip(rows, phases):
        stem = row["image_stem"]
        img_path = img_dir / f"{stem}.jpg"
        if not img_path.exists():
            skipped_missing_image += 1
            continue
        raw_bytes = img_path.read_bytes()
        pil = preprocess_service.apply(raw_bytes, ps)
        arr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

        r = model.predict(
            arr, conf=DIAGNOSTIC_CONF, iou=0.7, imgsz=640, verbose=False,
            rect=True, max_det=300, agnostic_nms=False, augment=False, batch=1, quantize=None,
        )[0]
        candidates = []
        b = r.boxes
        if b is not None and len(b) > 0:
            xyxy = b.xyxy.tolist()
            cls = b.cls.tolist()
            conf = b.conf.tolist()
            for (x1, y1, x2, y2), c, cf in zip(xyxy, cls, conf):
                candidates.append({
                    "cls": int(c), "conf": float(cf),
                    "x_center": (x1 + x2) / 2.0, "width": x2 - x1,
                })
        candidates.sort(key=lambda d: d["x_center"])

        frames.append({
            "stem": stem,
            "reading_gt": row["reading_gt"],
            "phase": phase,
            "candidates": candidates,
        })

    return {
        "skipped": False,
        "weight_sha256": actual_sha,
        "production_conf": cfg["production_conf"],
        "sweep": cfg["sweep"],
        "frames": frames,
        "skipped_missing_image": skipped_missing_image,
    }


def _at_threshold(candidates: list[dict], threshold: float) -> list[dict]:
    return [c for c in candidates if c["conf"] >= threshold]


def _reading_at_threshold(candidates: list[dict], threshold: float) -> str:
    return "".join(str(c["cls"]) for c in _at_threshold(candidates, threshold))


def compute_last_digit_region(frames: list[dict], production_conf: float) -> tuple[float, float]:
    """"clean"フレーム（production閾値でdetection_count==7かつreading一致）から、
    末尾桁（右端box）のx_center分布を求め、末尾桁スロットの領域境界を決める。
    """
    last_xs = []
    second_last_xs = []
    for f in frames:
        boxes = _at_threshold(f["candidates"], production_conf)
        if len(boxes) != READING_LEN:
            continue
        reading = "".join(str(c["cls"]) for c in boxes)
        if reading != f["reading_gt"]:
            continue
        last_xs.append(boxes[-1]["x_center"])
        second_last_xs.append(boxes[-2]["x_center"])
    if not last_xs:
        raise RuntimeError("clean frame（末尾桁を含め完全一致）が1件も見つからず、"
                            "末尾桁の位置を較正できません。")
    last_xs.sort()
    second_last_xs.sort()
    median_last = last_xs[len(last_xs) // 2]
    median_second_last = second_last_xs[len(second_last_xs) // 2]
    boundary = (median_last + median_second_last) / 2.0
    return boundary, median_last


def analyze_last_digit(frames: list[dict], production_conf: float, sweep: list[float]) -> dict:
    boundary, anchor_x = compute_last_digit_region(frames, production_conf)

    per_frame = []
    for f in frames:
        gt_digit = f["reading_gt"][-1]
        region_candidates = [c for c in f["candidates"] if c["x_center"] > boundary]
        correct = [c for c in region_candidates if str(c["cls"]) == gt_digit]
        wrong = [c for c in region_candidates if str(c["cls"]) != gt_digit]
        best_correct_conf = max((c["conf"] for c in correct), default=0.0)
        best_wrong_conf = max((c["conf"] for c in wrong), default=0.0)
        passes_production = best_correct_conf >= production_conf
        extra_wrong_at_production = any(c["conf"] >= production_conf for c in wrong)
        per_frame.append({
            "stem": f["stem"],
            "phase": f["phase"],
            "gt_digit": gt_digit,
            "n_region_candidates": len(region_candidates),
            "best_correct_conf": best_correct_conf,
            "best_wrong_conf": best_wrong_conf,
            "passes_production": passes_production,
            "extra_wrong_at_production": extra_wrong_at_production,
            "missing_at_production": not passes_production,
        })

    def _subset(phase):
        return [p for p in per_frame if p["phase"] == phase]

    def _rate(items, key):
        return (sum(1 for i in items if i[key]) / len(items)) if items else None

    stable = _subset("stable")
    boundary_frames = _subset("boundary")

    summary = {
        "last_digit_region_boundary_x": boundary,
        "last_digit_anchor_x": anchor_x,
        "n_frames": len(per_frame),
        "n_stable": len(stable),
        "n_boundary": len(boundary_frames),
        "stable_recall": _rate([{"k": not p["missing_at_production"]} for p in stable], "k") if stable else None,
        "stable_missing_rate": _rate(stable, "missing_at_production"),
        "boundary_missing_rate": _rate(boundary_frames, "missing_at_production"),
        "stable_extra_rate": _rate(stable, "extra_wrong_at_production"),
        "boundary_extra_rate": _rate(boundary_frames, "extra_wrong_at_production"),
    }

    sweep_table = []
    for t in sweep:
        row = {"threshold": t}
        for label, subset in (("stable", stable), ("boundary", boundary_frames), ("all", per_frame)):
            items = [p for p in per_frame if p["stem"] in {s["stem"] for s in subset}]
            passes = [p["best_correct_conf"] >= t for p in items]
            row[f"{label}_pass_rate"] = (sum(passes) / len(passes)) if passes else None
        sweep_table.append(row)

    return {"summary": summary, "per_frame": per_frame, "sweep_table": sweep_table}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", choices=["digital", "drum", "both"], default="both")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None, help="結果JSONの出力先（省略時はscratchpad想定で標準出力のみ）")
    args = ap.parse_args()

    labels = ["digital", "drum"] if args.project == "both" else [args.project]
    all_results = {}
    for label in labels:
        print(f"\n=== {label} ===")
        raw = analyze_project(label, limit=args.limit)
        if raw.get("skipped"):
            print(f"SKIP: {raw['reason']}")
            all_results[label] = raw
            continue
        print(f"frames={len(raw['frames'])} (missing image files skipped: {raw['skipped_missing_image']})")
        analysis = analyze_last_digit(raw["frames"], raw["production_conf"], raw["sweep"])
        print(json.dumps(analysis["summary"], indent=2, ensure_ascii=False))
        print("sweep:")
        for row in analysis["sweep_table"]:
            print(f"  conf={row['threshold']:.2f} stable_pass={row['stable_pass_rate']} "
                  f"boundary_pass={row['boundary_pass_rate']} all_pass={row['all_pass_rate']}")
        all_results[label] = {
            "weight_sha256": raw["weight_sha256"],
            "production_conf": raw["production_conf"],
            "summary": analysis["summary"],
            "sweep_table": analysis["sweep_table"],
            "per_frame": analysis["per_frame"],
        }

    if args.out:
        Path(args.out).write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
