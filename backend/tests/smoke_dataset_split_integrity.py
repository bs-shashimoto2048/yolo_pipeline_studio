"""scripts/audit_dataset_split.py のLayer A（repo-only integrity）スモークテスト（Issue #45）。

raw画像/cv2は一切不要（`--ci` modeのみを検証）。Gate 1 CIで使うsynthetic manifestに対し、
clean/overlap/duplicate/invalid split/baseline fingerprint mismatchの各ケースで
exit codeとFAILメッセージが期待通りであることを確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_dataset_split_integrity.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_PYTHON = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
_SCRIPT = _REPO_ROOT / "scripts" / "audit_dataset_split.py"


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def _write_csv(path: Path, rows: list[dict], fieldnames=("image_stem", "project", "split", "reading_gt")) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fieldnames))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _run(args: list[str]) -> tuple[int, str, str]:
    python = _PYTHON if _PYTHON.exists() else Path(sys.executable)
    r = subprocess.run([str(python), str(_SCRIPT), *args], cwd=_REPO_ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="yts_split_integrity_smoke_"))

    # --- clean manifest: exit 0 ---
    clean = tmp / "clean.csv"
    _write_csv(clean, [
        {"image_stem": "f_20260101_100000", "project": "p", "split": "train", "reading_gt": "0001"},
        {"image_stem": "f_20260101_110000", "project": "p", "split": "val", "reading_gt": "0002"},
        {"image_stem": "f_20260101_120000", "project": "p", "split": "test", "reading_gt": "0003"},
    ])
    rc, out, _err = _run(["--manifest", str(clean), "--project", "p", "--ci"])
    check("clean manifest -> exit 0", rc == 0)
    check("clean manifest -> explicit visual-audit-not-part-of-Gate-1 message",
          "visual near-duplicate audit: not part of Gate 1" in out)

    # --- cross-split exact stem overlap: non-zero exit ---
    overlap = tmp / "overlap.csv"
    _write_csv(overlap, [
        {"image_stem": "a_20260101_100000", "project": "p", "split": "train", "reading_gt": "0001"},
        {"image_stem": "a_20260101_100000", "project": "p", "split": "test", "reading_gt": "0001"},
    ])
    rc, out, _err = _run(["--manifest", str(overlap), "--project", "p", "--ci"])
    check("cross-split overlap -> non-zero exit", rc != 0)
    check("cross-split overlap -> FAIL message", "FAIL: cross-split exact stem overlap" in out)

    # --- within-split duplicate stem: non-zero exit ---
    dup = tmp / "dup.csv"
    _write_csv(dup, [
        {"image_stem": "b_20260101_100000", "project": "p", "split": "train", "reading_gt": "0001"},
        {"image_stem": "b_20260101_100000", "project": "p", "split": "train", "reading_gt": "0002"},
    ])
    rc, out, _err = _run(["--manifest", str(dup), "--project", "p", "--ci"])
    check("within-split duplicate stem -> non-zero exit", rc != 0)

    # --- invalid split (missing split column entirely): non-zero exit ---
    invalid = tmp / "invalid.csv"
    with invalid.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["image_stem", "project", "reading_gt"])
        w.writeheader()
        w.writerow({"image_stem": "c_20260101_100000", "project": "p", "reading_gt": "0001"})
    rc, out, _err = _run(["--manifest", str(invalid), "--project", "p", "--ci"])
    check("missing split column -> non-zero exit", rc != 0)
    check("missing split column -> FAIL message", "FAIL: missing required columns" in out)

    # --- Test fingerprint mismatch (baseline frozen split): non-zero exit ---
    frozen = tmp / "frozen.csv"
    _write_csv(frozen, [
        {"image_stem": f"e_2026010{i}_100000", "project": "p", "split": "test", "reading_gt": "0001"}
        for i in range(1, 4)
    ])
    baseline = tmp / "baseline.json"
    baseline.write_text(json.dumps({
        str(frozen.as_posix()): {
            "expected_counts": {"test": 3},
            "frozen_splits": {"test": {"count": 3, "stem_set_sha256": "0" * 64}},
            "source": "smoke test fixture",
        }
    }), encoding="utf-8")
    rc, out, _err = _run(["--manifest", str(frozen), "--project", "p", "--ci", "--baseline", str(baseline)])
    check("Test fingerprint mismatch -> non-zero exit", rc != 0)
    check("Test fingerprint mismatch -> FAIL message",
          "FAIL: frozen split stem-set fingerprint mismatch" in out)

    # --- production manifests referenced by the baseline currently in repo are clean ---
    real_baseline = _REPO_ROOT / "data_manifests" / "split_integrity_baseline.json"
    for manifest_name, project in (
        ("meter_src002_split_v3.csv", "meter_src002"),
        ("meter_src004_split_v4.csv", "meter_src004"),
        ("meter_src004_hard_val_v2.csv", "meter_src004"),
    ):
        manifest_path = _REPO_ROOT / "data_manifests" / manifest_name
        rc, out, _err = _run([
            "--manifest", str(manifest_path), "--project", project, "--ci",
            "--baseline", str(real_baseline),
        ])
        check(f"production manifest clean against baseline: {manifest_name}", rc == 0)

    print("\nALL DATASET SPLIT INTEGRITY SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
