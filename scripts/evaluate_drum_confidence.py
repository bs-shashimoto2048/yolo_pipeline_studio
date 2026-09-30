"""drum production confidence (現行0.80) の正式再評価（Issue #35）。

`data_manifests/meter_src004_split_v3.csv` の split=="val"（Standard Val58、58件）を
正式なthreshold selection用validationとして使用する。Test41（split=="test"）・
Frozen Hard-Val27（`meter_src004_hard_val_v1.csv`）は一切使用しない
（stem overlapを機械確認し、重複していればAssertionErrorで停止する）。

production weight・preprocess・ROI・contract args（rect=True等）はすべて現行production
と完全一致させ、confidenceのみをsweepする。read-only診断専用script。
production selected_model.jsonは変更しない（promotion判定・適用は別途手動で行う）。

実行:
    .venv\\Scripts\\python.exe scripts\\evaluate_drum_confidence.py
    .venv\\Scripts\\python.exe scripts\\evaluate_drum_confidence.py --out result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

PROJECT = "meter_src004"
TRAIN_JOB_ID = "candidate_roi_v3_5"
WEIGHT_TYPE = "best"
EXPECTED_SHA256 = "45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db"
CURRENT_PRODUCTION_CONF = 0.80
READING_LEN = 7

MANIFEST = REPO_ROOT / "data_manifests" / "meter_src004_split_v3.csv"
HARD_VAL_MANIFEST = REPO_ROOT / "data_manifests" / "meter_src004_hard_val_v1.csv"

DIAGNOSTIC_CONF = 0.05
DEFAULT_SWEEP = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_val58() -> list[dict]:
    rows = [r for r in _rows(MANIFEST) if r["project"] == PROJECT and r["split"] == "val"]
    rows.sort(key=lambda r: r["image_stem"])
    return rows


def overlap_guard(val_rows: list[dict]) -> None:
    """Val58がTest41/Hard-Val27と重複していないことを機械確認する（重複ならFAIL、SKIPしない）。"""
    val_stems = {r["image_stem"] for r in val_rows}
    test_stems = {r["image_stem"] for r in _rows(MANIFEST) if r["project"] == PROJECT and r["split"] == "test"}
    hard_val_stems = {r["image_stem"] for r in _rows(HARD_VAL_MANIFEST)}
    overlap_test = val_stems & test_stems
    overlap_hv = val_stems & hard_val_stems
    if overlap_test:
        raise RuntimeError(f"Val58 overlaps Test41: {overlap_test}")
    if overlap_hv:
        raise RuntimeError(f"Val58 overlaps Hard-Val27: {overlap_hv}")
    print(f"overlap guard OK: Val58={len(val_stems)} Test41={len(test_stems)} "
          f"Hard-Val27={len(hard_val_stems)}, no overlap")


def load_selected_model() -> dict:
    p = REPO_ROOT / "projects" / PROJECT / "models" / "selected_model.json"
    return json.loads(p.read_text(encoding="utf-8"))


def run_inference(val_rows: list[dict]) -> tuple[list[dict], str, dict]:
    sel = load_selected_model()
    if sel.get("train_job_id") != TRAIN_JOB_ID or sel.get("weight_type") != WEIGHT_TYPE:
        raise RuntimeError(
            f"selected_model.json が想定と異なります: {sel.get('train_job_id')}:{sel.get('weight_type')}"
        )
    if sel.get("conf") != CURRENT_PRODUCTION_CONF:
        raise RuntimeError(f"selected_model.json のconfが想定(0.80)と異なります: {sel.get('conf')}")
    weight_path = (
        REPO_ROOT / "projects" / PROJECT / "runs" / "train" / TRAIN_JOB_ID
        / "weights" / f"{WEIGHT_TYPE}.pt"
    )
    actual_sha = sha256_file(weight_path)
    if actual_sha != EXPECTED_SHA256:
        raise RuntimeError(f"weight SHA256 mismatch: expected {EXPECTED_SHA256}, got {actual_sha}")
    profile = sel["preprocess_profile"]

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from app.schemas.preprocess import PreprocessSettings  # noqa: PLC0415
    from app.services import preprocess_service  # noqa: PLC0415
    from ultralytics import YOLO  # noqa: PLC0415
    import ultralytics  # noqa: PLC0415
    import torch  # noqa: PLC0415

    ps = PreprocessSettings(**profile)
    model = YOLO(str(weight_path))

    img_dir = REPO_ROOT / "projects" / PROJECT / "raw" / "images"
    frames = []
    for row in val_rows:
        stem = row["image_stem"]
        img_path = img_dir / f"{stem}.jpg"
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
            for (x1, y1, x2, y2), c, cf in zip(b.xyxy.tolist(), b.cls.tolist(), b.conf.tolist()):
                candidates.append({"cls": int(c), "conf": float(cf), "x_center": (x1 + x2) / 2.0})
        candidates.sort(key=lambda d: d["x_center"])
        frames.append({"stem": stem, "reading_gt": row["reading_gt"], "candidates": candidates})

    env = {
        "ultralytics_version": ultralytics.__version__,
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "weight_sha256": actual_sha,
    }
    return frames, actual_sha, env


def calibrate_last_digit_region(frames: list[dict], production_conf: float) -> tuple[float, float]:
    last_xs, second_last_xs = [], []
    for f in frames:
        passing = [c for c in f["candidates"] if c["conf"] >= production_conf]
        if len(passing) != READING_LEN:
            continue
        reading = "".join(str(c["cls"]) for c in passing)
        if reading != f["reading_gt"]:
            continue
        last_xs.append(passing[-1]["x_center"])
        second_last_xs.append(passing[-2]["x_center"])
    if not last_xs:
        raise RuntimeError("clean frame（末尾桁含め完全一致）が1件も見つかりません。較正不能。")
    last_xs.sort()
    second_last_xs.sort()
    median_last = last_xs[len(last_xs) // 2]
    median_second_last = second_last_xs[len(second_last_xs) // 2]
    return (median_last + median_second_last) / 2.0, median_last


def evaluate_at_threshold(frames: list[dict], threshold: float, boundary_x: float) -> dict:
    n = len(frames)
    exact = 0
    seven_det = 0
    missing_frames = 0
    extra_frames = 0
    wrong_class_frames = 0
    char_total = 0
    char_correct = 0
    confusion = Counter()
    last_digit_correct = 0
    last_digit_missing = 0
    confidently_wrong_last = 0
    per_image = []

    for f in frames:
        passing = [c for c in f["candidates"] if c["conf"] >= threshold]
        passing.sort(key=lambda c: c["x_center"])
        decoded = "".join(str(c["cls"]) for c in passing)
        cnt = len(passing)
        gt = f["reading_gt"]

        if cnt == READING_LEN:
            seven_det += 1
            if decoded == gt:
                exact += 1
            else:
                wrong_class_frames += 1
            for i in range(READING_LEN):
                char_total += 1
                if decoded[i] == gt[i]:
                    char_correct += 1
                else:
                    confusion[(gt[i], decoded[i])] += 1
        elif cnt < READING_LEN:
            missing_frames += 1
        else:
            extra_frames += 1

        region = [c for c in f["candidates"] if c["x_center"] > boundary_x]
        region_passing = [c for c in region if c["conf"] >= threshold]
        gt_last = gt[-1]
        correct_last = [c for c in region_passing if str(c["cls"]) == gt_last]
        wrong_last = [c for c in region_passing if str(c["cls"]) != gt_last]
        if correct_last:
            last_digit_correct += 1
        else:
            last_digit_missing += 1
            if wrong_last:
                confidently_wrong_last += 1

        per_image.append({
            "stem": f["stem"], "gt": gt, "decoded": decoded, "detection_count": cnt,
            "exact": (cnt == READING_LEN and decoded == gt),
        })

    two_to_eight = confusion.get(("2", "8"), 0)
    eight_to_two = confusion.get(("8", "2"), 0)

    return {
        "threshold": threshold,
        "n": n,
        "exact_match_rate": exact / n,
        "seven_detection_rate": seven_det / n,
        "character_accuracy": (char_correct / char_total) if char_total else None,
        "missing_frame_rate": missing_frames / n,
        "extra_frame_rate": extra_frames / n,
        "wrong_class_frame_rate": wrong_class_frames / n,
        "two_to_eight": two_to_eight,
        "eight_to_two": eight_to_two,
        "top_confusions": confusion.most_common(5),
        "last_digit_accuracy": last_digit_correct / n,
        "last_digit_missing_rate": last_digit_missing / n,
        "confidently_wrong_last_count": confidently_wrong_last,
        "per_image": per_image,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default=",".join(str(t) for t in DEFAULT_SWEEP))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    thresholds = [float(t) for t in args.sweep.split(",")]

    val_rows = load_val58()
    print(f"Val58 rows: {len(val_rows)}")
    overlap_guard(val_rows)

    frames, weight_sha, env = run_inference(val_rows)
    boundary_x, anchor_x = calibrate_last_digit_region(frames, CURRENT_PRODUCTION_CONF)
    print(f"last-digit region boundary_x={boundary_x:.2f} anchor_x={anchor_x:.2f}")
    print(f"environment: {env}")

    all_results = {}
    print(f"\n{'conf':>6} {'exact':>7} {'7det':>7} {'characc':>8} {'missing':>8} "
          f"{'extra':>7} {'wrong':>7} {'2to8':>5} {'8to2':>5} {'lastacc':>8} {'lastmiss':>9} {'confwrong':>10}")
    for t in thresholds:
        res = evaluate_at_threshold(frames, t, boundary_x)
        all_results[t] = res
        print(f"{t:>6.2f} {res['exact_match_rate']*100:>6.1f}% {res['seven_detection_rate']*100:>6.1f}% "
              f"{(res['character_accuracy'] or 0)*100:>7.2f}% {res['missing_frame_rate']*100:>7.1f}% "
              f"{res['extra_frame_rate']*100:>6.1f}% {res['wrong_class_frame_rate']*100:>6.1f}% "
              f"{res['two_to_eight']:>5} {res['eight_to_two']:>5} "
              f"{res['last_digit_accuracy']*100:>7.1f}% {res['last_digit_missing_rate']*100:>8.1f}% "
              f"{res['confidently_wrong_last_count']:>10}")

    if args.out:
        payload = {
            "weight_sha256": weight_sha,
            "environment": env,
            "boundary_x": boundary_x,
            "anchor_x": anchor_x,
            "results": {str(t): r for t, r in all_results.items()},
        }
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
