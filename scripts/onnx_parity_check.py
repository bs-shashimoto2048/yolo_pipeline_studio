"""PT(.pt) vs ONNX production inference parityチェッカー（Issue #47）。

production weightから既にexport済みのONNX（Issue #47 deployment baseline、
`scripts/onnx_parity_check.py`実行時点でrepo内に無いため事前に
`backend/app/services/onnx_export_service.start_export`等でexportしておくこと）に対し、
同一のproduction前処理済みfixture画像を使い、PT推論とONNX Runtime推論の検出結果
（detection count・class sequence・reading・bbox・confidence）が一致することを検証する。

Test/Hard-Valは一切使用しない。`backend/tests/fixtures/production_smoke_v1.json`の
2 stem（既存golden fixtureあり）に加え、同じsource_dir内の他画像から、現行production
manifestのTest/Hard-Val splitと重複しないstemを追加で選び、project毎に
`--samples-per-project`件（既定30件）まで拡張する。

production artifact（weight・selected_model.json）は一切変更しない（read-only）。

前処理について: fixture画像（source_dir配下）は既にIssue #24〜#27でproduction
前処理（ROI/resize/grayscale/sharpen、projectごとのselected_model.jsonのprofile）を
適用済みのコピーである。本scriptが追加で行うのは、YOLO自体が内部で行う letterbox
（rect推論と同一shapeになるようauto=Falseで固定shapeへ）・正規化のみ。

実行例:
    .venv\\Scripts\\python.exe scripts\\onnx_parity_check.py ^
        --digital-onnx projects\\meter_src002\\exports\\onnx\\digital_production_v1\\model.onnx ^
        --drum-onnx projects\\meter_src004\\exports\\onnx\\drum_production_v1\\model.onnx ^
        --samples-per-project 30 --provider CPUExecutionProvider
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "backend" / "tests" / "fixtures"
CONFIG_PATH = FIXTURES_DIR / "production_smoke_v1.json"
GOLDEN_PATH = FIXTURES_DIR / "production_inference_contract_golden_v1.json"

# production rect推論（Ultralytics `rect=True`）が実際に使うinput shape（Issue #25で
# "approximately"としていた値を、AutoBackend.forwardをフックして実測し確定した）。
STATIC_IMGSZ_HW: dict[str, list[int]] = {"digital": [384, 640], "drum": [160, 640]}

# 現行production manifest（Issue #45 baselineと同じ、Test/Hard-Val保護対象）
_TEST_HARDVAL_SOURCES = {
    "digital": [("data_manifests/meter_src002_split_v3.csv", "test")],
    "drum": [
        ("data_manifests/meter_src004_split_v4.csv", "test"),
        ("data_manifests/meter_src004_hard_val_v2.csv", "hard_val_v2"),
    ],
}

CONF_TOLERANCE = 1e-3
BBOX_TOLERANCE_PX = 1.0
IOU_NMS = 0.7
MAX_DET = 300


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_stems(rel_path: str, split: str) -> set[str]:
    with (REPO_ROOT / rel_path).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["image_stem"] for r in rows if r["split"] == split}


def _excluded_stems(project_key: str) -> set[str]:
    excluded: set[str] = set()
    for rel_path, split in _TEST_HARDVAL_SOURCES[project_key]:
        excluded |= _manifest_stems(rel_path, split)
    return excluded


def select_stems(project_key: str, cfg_entry: dict, target_count: int) -> list[str]:
    """公式fixture stem（golden比較対象）+ 追加のnon-Test/Hard-Val stemを選ぶ。

    追加分は、source_dir内のファイル名をsortした決定的な順で選び、現行production
    manifestのTest/Hard-Val splitと重複するものだけを除外する（「trainに属する」こと
    自体は要求しない。要求するのはTest/Hard-Valでないことのみ）。
    """
    source_dir = REPO_ROOT / cfg_entry["source_dir"]
    official = list(cfg_entry["stems"])
    excluded = _excluded_stems(project_key)

    chosen = list(official)
    seen = set(official)
    for p in sorted(source_dir.glob("*.jpg")):
        if len(chosen) >= target_count:
            break
        stem = p.stem
        if stem in seen:
            continue
        if stem in excluded:
            continue
        chosen.append(stem)
        seen.add(stem)
    return chosen


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_golden(project_key: str) -> dict[str, dict]:
    if not GOLDEN_PATH.exists():
        return {}
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return {fx["stem"]: fx for fx in golden["projects"][project_key]["fixtures"]}


def reading_from(xyxy, cls) -> tuple[str, list[int]]:
    """x_center（原画像座標、昇順）でsortしreadingを構成する。
    smoke_production_integration.pyの`_reading_from_detections`と同じ規約
    （左→右の並びで桁を結合）。
    """
    if len(cls) == 0:
        return "", []
    x_center = (xyxy[:, 0] + xyxy[:, 2]) / 2.0
    order = sorted(range(len(cls)), key=lambda i: x_center[i])
    reading = "".join(str(int(cls[i])) for i in order)
    return reading, order


def run_pt(weight_path: Path, conf: float, img_dir: Path) -> dict[str, dict]:
    from ultralytics import YOLO

    model = YOLO(str(weight_path))
    results = model.predict(
        source=str(img_dir), conf=conf, iou=IOU_NMS, imgsz=640, save=False, verbose=False,
        stream=True,
        # production inference contract（Issue #25/#26/#29）と同一のpinned args
        rect=True, max_det=MAX_DET, agnostic_nms=False, augment=False, batch=1, quantize=None,
    )
    out: dict[str, dict] = {}
    for r in results:
        stem = Path(r.path).stem
        boxes = r.boxes
        if boxes is None or len(boxes) == 0:
            xyxy, conf_arr, cls_arr = [], [], []
        else:
            xyxy = boxes.xyxy.cpu().numpy()
            conf_arr = boxes.conf.cpu().numpy()
            cls_arr = boxes.cls.cpu().numpy()
        out[stem] = {"xyxy": xyxy, "conf": conf_arr, "cls": cls_arr, "orig_shape": r.orig_shape}
    return out


def run_onnx(onnx_path: Path, conf: float, imgsz_hw: list[int], stems: list[str],
             img_dir: Path, provider: str) -> dict[str, dict]:
    import cv2
    import numpy as np
    import onnxruntime as ort
    import torch
    from ultralytics.data.augment import LetterBox
    from ultralytics.utils.nms import non_max_suppression
    from ultralytics.utils.ops import scale_boxes

    sess = ort.InferenceSession(str(onnx_path), providers=[provider])
    input_name = sess.get_inputs()[0].name
    # auto=False: productionのrect=True推論が実際に使うshapeへ固定（Issue #25実測値）。
    # center=True/stride=32/padding_value=114はUltralytics predictorの既定と同一。
    lb = LetterBox(new_shape=tuple(imgsz_hw), auto=False, stride=32, center=True, padding_value=114)

    out: dict[str, dict] = {}
    for stem in stems:
        img_path = img_dir / f"{stem}.jpg"
        img0 = cv2.imread(str(img_path))  # BGR, HWC
        img_lb = lb(image=img0)
        img_rgb = img_lb[:, :, ::-1]
        tensor = np.ascontiguousarray(img_rgb.transpose(2, 0, 1)[None].astype(np.float32) / 255.0)

        raw = sess.run(None, {input_name: tensor})[0]
        raw_t = torch.from_numpy(raw)
        preds = non_max_suppression(
            raw_t, conf_thres=conf, iou_thres=IOU_NMS, classes=None,
            agnostic=False, max_det=MAX_DET, nc=0, end2end=False, rotated=False,
        )
        pred = preds[0]
        if pred.shape[0]:
            pred = pred.clone()
            pred[:, :4] = scale_boxes(tuple(imgsz_hw), pred[:, :4], img0.shape)
            xyxy = pred[:, :4].numpy()
            conf_arr = pred[:, 4].numpy()
            cls_arr = pred[:, 5].numpy()
        else:
            xyxy, conf_arr, cls_arr = [], [], []
        out[stem] = {"xyxy": xyxy, "conf": conf_arr, "cls": cls_arr, "orig_shape": img0.shape[:2]}
    return out


def compare_stem(stem: str, pt: dict, onnx: dict) -> dict:
    pt_reading, pt_order = reading_from(pt["xyxy"], pt["cls"])
    onnx_reading, onnx_order = reading_from(onnx["xyxy"], onnx["cls"])

    violations = []
    if len(pt["cls"]) != len(onnx["cls"]):
        violations.append(f"detection_count mismatch: pt={len(pt['cls'])} onnx={len(onnx['cls'])}")
    if pt_reading != onnx_reading:
        violations.append(f"reading mismatch: pt={pt_reading!r} onnx={onnx_reading!r}")

    max_conf_diff = 0.0
    max_bbox_diff = 0.0
    if not violations:
        for i in range(len(pt_order)):
            pi, oi = pt_order[i], onnx_order[i]
            conf_diff = abs(float(pt["conf"][pi]) - float(onnx["conf"][oi]))
            bbox_diff = max(abs(float(a) - float(b)) for a, b in zip(pt["xyxy"][pi], onnx["xyxy"][oi]))
            max_conf_diff = max(max_conf_diff, conf_diff)
            max_bbox_diff = max(max_bbox_diff, bbox_diff)
        if max_conf_diff > CONF_TOLERANCE:
            violations.append(f"confidence tolerance exceeded: {max_conf_diff:.6f} > {CONF_TOLERANCE}")
        if max_bbox_diff > BBOX_TOLERANCE_PX:
            violations.append(f"bbox tolerance exceeded: {max_bbox_diff:.3f}px > {BBOX_TOLERANCE_PX}px")

    return {
        "stem": stem, "ok": not violations, "violations": violations,
        "pt_reading": pt_reading, "onnx_reading": onnx_reading,
        "pt_count": len(pt["cls"]), "onnx_count": len(onnx["cls"]),
        "max_conf_diff": max_conf_diff, "max_bbox_diff_px": max_bbox_diff,
    }


def run_project(project_key: str, cfg_entry: dict, onnx_path: Path, samples: int, provider: str) -> dict:
    print(f"\n=== {project_key} ===")
    weight = REPO_ROOT / "projects" / cfg_entry["project"] / \
        f"runs/train/{cfg_entry['train_job_id']}/weights/{cfg_entry['weight_type']}.pt"
    actual_sha = sha256_file(weight)
    assert actual_sha == cfg_entry["weight_sha256"], \
        f"PT weight SHA256 mismatch: expected {cfg_entry['weight_sha256']}, got {actual_sha}"
    print(f"PT weight SHA256 OK: {actual_sha}")
    onnx_sha = sha256_file(onnx_path)
    print(f"ONNX SHA256: {onnx_sha}")

    stems = select_stems(project_key, cfg_entry, samples)
    print(f"stems selected: {len(stems)} (official fixtures: {len(cfg_entry['stems'])})")
    source_dir = REPO_ROOT / cfg_entry["source_dir"]

    import time
    t0 = time.perf_counter()
    pt_out = run_pt(weight, cfg_entry["conf"], source_dir)
    pt_elapsed = time.perf_counter() - t0
    pt_out = {s: pt_out[s] for s in stems if s in pt_out}

    t0 = time.perf_counter()
    onnx_out = run_onnx(onnx_path, cfg_entry["conf"], STATIC_IMGSZ_HW[project_key], stems, source_dir, provider)
    onnx_elapsed = time.perf_counter() - t0

    golden = load_golden(project_key)
    results = []
    for stem in stems:
        if stem not in pt_out or stem not in onnx_out:
            print(f"  SKIP {stem}: missing PT or ONNX result")
            continue
        r = compare_stem(stem, pt_out[stem], onnx_out[stem])
        fx = golden.get(stem)
        if fx is not None:
            r["golden_reading"] = fx["reading"]
            r["pt_matches_golden"] = r["pt_reading"] == fx["reading"]
        results.append(r)
        status = "OK  " if r["ok"] else "FAIL"
        print(f"  {status} {stem}: pt={r['pt_reading']!r} onnx={r['onnx_reading']!r} "
              f"count={r['pt_count']}/{r['onnx_count']} "
              f"max_conf_diff={r['max_conf_diff']:.6f} max_bbox_diff_px={r['max_bbox_diff_px']:.3f}")
        if r["violations"]:
            for v in r["violations"]:
                print(f"       - {v}")

    n_ok = sum(1 for r in results if r["ok"])
    print(f"{project_key}: {n_ok}/{len(results)} stems parity OK "
          f"(PT {pt_elapsed/max(len(pt_out),1)*1000:.1f}ms/img avg incl. overhead, "
          f"ONNX[{provider}] {onnx_elapsed/max(len(onnx_out),1)*1000:.1f}ms/img avg)")

    return {
        "project_key": project_key, "pt_weight_sha256": actual_sha, "onnx_sha256": onnx_sha,
        "provider": provider, "n_samples": len(results), "n_ok": n_ok,
        "pt_avg_ms": pt_elapsed / max(len(pt_out), 1) * 1000,
        "onnx_avg_ms": onnx_elapsed / max(len(onnx_out), 1) * 1000,
        "results": results,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digital-onnx", required=True)
    ap.add_argument("--drum-onnx", required=True)
    ap.add_argument("--samples-per-project", type=int, default=30)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    ap.add_argument("--report-out", default=None, help="結果JSONの出力先（任意）")
    args = ap.parse_args()

    cfg = load_config()
    all_results = []
    overall_ok = True
    for key, onnx_arg in (("digital", args.digital_onnx), ("drum", args.drum_onnx)):
        res = run_project(key, cfg[key], Path(onnx_arg), args.samples_per_project, args.provider)
        all_results.append(res)
        if res["n_ok"] != res["n_samples"] or res["n_samples"] == 0:
            overall_ok = False

    print(f"\n=== overall: {'PASS' if overall_ok else 'FAIL'} ===")
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report written: {args.report_out}")

    if not overall_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
