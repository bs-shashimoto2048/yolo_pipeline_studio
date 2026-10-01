"""C++(yps_infer.exe) vs Python ONNX Runtime parityチェッカー（Issue #48）。

scripts/onnx_parity_check.py が計算するPython ONNX Runtime推論結果（letterbox/NMS/
scale_boxesをUltralytics自身の関数で実行）を正とし、C++実装（cpp/build/Release/
yps_infer.exe）が同一画像に対して同一のdetection/reading/confidence/bboxを返すかを
検証する。Test/Hard-Valは一切使用しない（Python側と同じfixture選定ロジックを再利用）。

実行例（repo rootから）:
    .venv\\Scripts\\python.exe scripts\\cpp_parity_check.py --samples-per-project 30
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import onnx_parity_check as pc  # noqa: E402

CONF_TOLERANCE = 1e-3
BBOX_TOLERANCE_PX = 1.0


def run_cpp(exe: Path, profile_key: str, image_path: Path, onnx_path: Path) -> dict:
    cmd = [str(exe), "--profile", profile_key, "--image", str(image_path),
           "--onnx", str(onnx_path), "--json"]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"yps_infer.exe failed (exit {r.returncode}): {r.stderr}")
    return json.loads(r.stdout)


def compare(stem: str, py: dict, cpp: dict) -> dict:
    py_reading, py_order = pc.reading_from(py["xyxy"], py["cls"])
    cpp_dets = cpp["detections"]
    cpp_xyxy = [[d["x1"], d["y1"], d["x2"], d["y2"]] for d in cpp_dets]
    cpp_cls = [d["cls"] for d in cpp_dets]
    import numpy as np  # noqa: PLC0415
    cpp_reading, cpp_order = pc.reading_from(np.array(cpp_xyxy) if cpp_xyxy else np.zeros((0, 4)),
                                              np.array(cpp_cls))

    violations = []
    if len(py["cls"]) != len(cpp_dets):
        violations.append(f"count mismatch: py={len(py['cls'])} cpp={len(cpp_dets)}")
    if py_reading != cpp_reading:
        violations.append(f"reading mismatch: py={py_reading!r} cpp={cpp['reading']!r}")

    max_conf_diff = 0.0
    max_bbox_diff = 0.0
    if not violations:
        for i in range(len(py_order)):
            pi, ci = py_order[i], cpp_order[i]
            conf_diff = abs(float(py["conf"][pi]) - float(cpp_dets[ci]["conf"]))
            bbox_diff = max(abs(float(a) - float(b)) for a, b in zip(py["xyxy"][pi], cpp_xyxy[ci]))
            max_conf_diff = max(max_conf_diff, conf_diff)
            max_bbox_diff = max(max_bbox_diff, bbox_diff)
        if max_conf_diff > CONF_TOLERANCE:
            violations.append(f"confidence tolerance exceeded: {max_conf_diff:.6f}")
        if max_bbox_diff > BBOX_TOLERANCE_PX:
            violations.append(f"bbox tolerance exceeded: {max_bbox_diff:.3f}px")

    return {"stem": stem, "ok": not violations, "violations": violations,
            "py_reading": py_reading, "cpp_reading": cpp["reading"],
            "max_conf_diff": max_conf_diff, "max_bbox_diff_px": max_bbox_diff}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default="cpp/build/Release/yps_infer.exe")
    ap.add_argument("--digital-onnx", default="projects/meter_src002/exports/onnx/digital_production_v1/model.onnx")
    ap.add_argument("--drum-onnx", default="projects/meter_src004/exports/onnx/drum_production_v1/model.onnx")
    ap.add_argument("--samples-per-project", type=int, default=30)
    args = ap.parse_args()

    exe = REPO_ROOT / args.exe
    cfg = pc.load_config()
    overall_ok = True
    summary = []

    for key, onnx_rel in (("digital", args.digital_onnx), ("drum", args.drum_onnx)):
        entry = cfg[key]
        onnx_path = REPO_ROOT / onnx_rel
        source_dir = REPO_ROOT / entry["source_dir"]
        stems = pc.select_stems(key, entry, args.samples_per_project)
        print(f"\n=== {key}: C++ vs Python ONNX ({len(stems)} stems) ===")

        py_out = pc.run_onnx(onnx_path, entry["conf"], pc.STATIC_IMGSZ_HW[key], stems,
                              source_dir, "CPUExecutionProvider")

        n_ok = 0
        for stem in stems:
            img_path = source_dir / f"{stem}.jpg"
            cpp_out = run_cpp(exe, key, img_path, onnx_path)
            r = compare(stem, py_out[stem], cpp_out)
            status = "OK  " if r["ok"] else "FAIL"
            print(f"  {status} {stem}: py={r['py_reading']!r} cpp={r['cpp_reading']!r} "
                  f"max_conf_diff={r['max_conf_diff']:.6f} max_bbox_diff_px={r['max_bbox_diff_px']:.3f}")
            for v in r["violations"]:
                print(f"       - {v}")
            if r["ok"]:
                n_ok += 1
        print(f"{key}: {n_ok}/{len(stems)} OK")
        summary.append((key, n_ok, len(stems)))
        if n_ok != len(stems):
            overall_ok = False

    print(f"\n=== overall: {'PASS' if overall_ok else 'FAIL'} ===")
    for key, n_ok, n in summary:
        print(f"  {key}: {n_ok}/{n}")
    if not overall_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
