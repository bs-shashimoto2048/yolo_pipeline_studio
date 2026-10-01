"""PT vs ONNX production inference parity smoke（Issue #47）。

`scripts/onnx_parity_check.py`の軽量regression。production weight・ONNX export
artifact（いずれもGit管理外、`data_manifests/production_deployment_baseline_v1.json`が
参照するローカルパス）が無い環境ではSKIPする（production weightをunit test必須条件に
しない、`smoke_production_integration.py`と同じ方針）。

Test/Hard-Valは一切使用しない（`backend/tests/fixtures/production_smoke_v1.json`の
公式fixture stemのみを使う軽量modeで実行）。production artifact（weight・ONNX・
selected_model.json）は一切変更しない（read-only）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_onnx_parity.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASELINE_PATH = _REPO_ROOT / "data_manifests" / "production_deployment_baseline_v1.json"

sys.path.insert(0, str(_REPO_ROOT / "scripts"))

_PASS = 0
_FAIL = 0
_SKIP = 0


def check(label: str, cond: bool) -> None:
    global _PASS, _FAIL
    print(("OK  " if cond else "FAIL") + " " + label)
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        raise SystemExit(1)


def skip(label: str) -> None:
    global _SKIP, _FAIL
    # Issue #38方針と同じ: CI/GPU runner等でYTS_PRODUCTION_SMOKE_REQUIRED=1の場合は
    # production artifact欠落をSKIPではなくFAILさせ、silent successを防ぐ。
    if os.environ.get("YTS_PRODUCTION_SMOKE_REQUIRED") == "1":
        print("FAIL(required) " + label)
        _FAIL += 1
        raise SystemExit(1)
    print("SKIP " + label)
    _SKIP += 1


def main() -> None:
    import onnx_parity_check as pc  # noqa: PLC0415 (cv2/torch依存、他のsmoke testと同じ遅延import規約)

    if not _BASELINE_PATH.exists():
        skip(f"deployment baseline manifest not found ({_BASELINE_PATH})")
        print(f"\n{_PASS} passed, {_FAIL} failed, {_SKIP} skipped")
        return
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))

    cfg = pc.load_config()
    for key in ("digital", "drum"):
        entry = cfg[key]
        weight = _REPO_ROOT / "projects" / entry["project"] / \
            f"runs/train/{entry['train_job_id']}/weights/{entry['weight_type']}.pt"
        onnx_rel = baseline[key]["onnx_artifact"]["path"]
        onnx_path = _REPO_ROOT / onnx_rel

        if not weight.exists():
            skip(f"[{key}] production weight not available locally ({weight})")
            continue
        if not onnx_path.exists():
            skip(f"[{key}] ONNX deployment artifact not available locally ({onnx_path})")
            continue

        actual_pt_sha = pc.sha256_file(weight)
        check(f"[{key}] PT weight SHA256 matches baseline manifest",
              actual_pt_sha == baseline[key]["weight_sha256"])
        actual_onnx_sha = pc.sha256_file(onnx_path)
        check(f"[{key}] ONNX artifact SHA256 matches baseline manifest",
              actual_onnx_sha == baseline[key]["onnx_artifact"]["sha256"])

        # 軽量: 公式fixture stem（2件）のみでparityを確認する（通常runの30件はローカル専用）。
        official_stems = entry["stems"]
        source_dir = _REPO_ROOT / entry["source_dir"]
        pt_out = pc.run_pt(weight, entry["conf"], source_dir)
        onnx_out = pc.run_onnx(
            onnx_path, entry["conf"], pc.STATIC_IMGSZ_HW[key], official_stems, source_dir,
            "CPUExecutionProvider",
        )
        for stem in official_stems:
            check(f"[{key}] {stem}: PT result present", stem in pt_out)
            check(f"[{key}] {stem}: ONNX result present", stem in onnx_out)
            r = pc.compare_stem(stem, pt_out[stem], onnx_out[stem])
            check(f"[{key}] {stem}: PT/ONNX parity ({r['pt_reading']!r} == {r['onnx_reading']!r}, "
                  f"count {r['pt_count']}=={r['onnx_count']}, "
                  f"max_conf_diff={r['max_conf_diff']:.6f}, max_bbox_diff_px={r['max_bbox_diff_px']:.3f})",
                  r["ok"])

    print(f"\n{_PASS} passed, {_FAIL} failed, {_SKIP} skipped")
    print("\nALL ONNX PARITY SMOKE TESTS PASSED (or safely skipped)")


if __name__ == "__main__":
    main()
