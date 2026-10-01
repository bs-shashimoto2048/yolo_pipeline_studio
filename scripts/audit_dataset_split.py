"""汎用split integrity checker（Issue #40、Issue #45でGate 1 CI組み込み対応）。

Train/Val/Test manifestのstem重複・perceptual near-duplicate・class分布を機械確認する。
production weight・real inferenceは一切不要（read-only、manifest+raw画像のみ参照）。
Issue #39/#40で発見したdigital production splitのcross-split near-duplicate問題の
再発防止用に、Gate 1 CI（GPU/production artifact不要なCPU step）へ組み込んでいる。

2層設計（Issue #45）:
- Layer A（repo-only、Gate 1で常時実行）: manifest parse・exact stem overlap・
  split値/必須列の妥当性・GT矛盾検知・baseline（期待件数・frozen split fingerprint）
  照合。raw画像・cv2は一切不要（`--ci`指定時）。
- Layer B（perceptual near-duplicate、raw画像必須）: ローカル専用。Gate 1には
  組み込まない（raw画像はgitignore対象でCI checkoutに含まれないため）。

使い方（ローカル、raw画像ありのフル監査）:
    .venv\\Scripts\\python.exe scripts\\audit_dataset_split.py \\
        --manifest data_manifests/meter_src002_split_v3.csv \\
        --raw-dir projects/meter_src002/raw/images \\
        --project meter_src002 \\
        --gt-column reading_gt --gt-position 3

使い方（CI向け、raw画像なしのLayer Aのみ + baseline照合）:
    python scripts\\audit_dataset_split.py \\
        --manifest data_manifests/meter_src002_split_v3.csv \\
        --project meter_src002 --ci \\
        --baseline data_manifests/split_integrity_baseline.json

終了コード: 0=integrity問題なし、非0=violation検出（CIをfailさせる）。
"""
from __future__ import annotations

import argparse
import csv
import json
import hashlib
import sys
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = ("image_stem", "split")


def _load_rows(manifest: Path, project: str | None) -> list[dict]:
    with manifest.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if project:
        rows = [r for r in rows if r.get("project") == project]
    return rows


def check_stem_overlap(rows: list[dict]) -> dict:
    by_split: dict[str, set[str]] = {}
    for r in rows:
        by_split.setdefault(r["split"], set()).add(r["image_stem"])
    splits = sorted(by_split)
    overlaps = {}
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            ov = by_split[a] & by_split[b]
            if ov:
                overlaps[f"{a}&{b}"] = sorted(ov)
    dupes_within = {s: len(lst) - len(set(lst)) for s, lst in
                    ((s, [r["image_stem"] for r in rows if r["split"] == s]) for s in splits)}
    return {"splits": {s: len(v) for s, v in by_split.items()}, "cross_split_overlap": overlaps,
            "within_split_duplicates": dupes_within}


def check_required_columns(fieldnames: list[str] | None, project_filter: str | None) -> list[str]:
    """manifestのheaderに必須列が揃っているか確認する（Issue #45 Layer A）。

    `--project`指定時はproject列も必須とする（フィルタが無言で空集合になるのを防ぐ）。
    """
    names = set(fieldnames or [])
    required = set(REQUIRED_COLUMNS)
    if project_filter is not None:
        required.add("project")
    missing = sorted(required - names)
    return missing


def check_row_integrity(rows: list[dict]) -> dict:
    """行レベルのintegrity違反を検出する（Issue #45 Layer A）。

    - 空のimage_stem/split
    - 完全重複行（全列が同一）
    - 同一image_stemでreading_gtが食い違う行（データ破損の兆候）

    出力はfilesystem順やdict反復順に依存せずsortして返す（deterministic）。
    """
    empty_stem_or_split = sorted(
        {r.get("image_stem", "") or "<empty>" for r in rows
         if not r.get("image_stem") or not r.get("split")}
    )

    seen_rows: dict[tuple, int] = {}
    for r in rows:
        key = tuple(sorted(r.items()))
        seen_rows[key] = seen_rows.get(key, 0) + 1
    duplicate_rows = sorted(
        {dict(k).get("image_stem", "?") for k, c in seen_rows.items() if c > 1}
    )

    gt_by_stem: dict[str, set[str]] = {}
    for r in rows:
        stem = r.get("image_stem")
        gt = r.get("reading_gt")
        if stem and gt is not None:
            gt_by_stem.setdefault(stem, set()).add(gt)
    conflicting_gt = sorted(s for s, gts in gt_by_stem.items() if len(gts) > 1)

    return {
        "empty_stem_or_split": empty_stem_or_split,
        "duplicate_rows": duplicate_rows,
        "conflicting_gt_stems": conflicting_gt,
    }


def _test_fingerprint(stems: list[str]) -> str:
    """stem集合（画像内容ではなくstem名のみ）をsortしてSHA256化する（Issue #45 §10）。"""
    joined = "\n".join(sorted(stems))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def load_baseline(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def check_against_baseline(rows: list[dict], manifest_key: str, baseline: dict) -> dict:
    """Issue #45: 期待件数・frozen split（例: Digital Test66）のstem fingerprintを
    `data_manifests/split_integrity_baseline.json`と照合する。baselineに未登録の
    manifestはskip扱い（violationにはしない。新規manifestを段階的に追加できるように
    するため）。
    """
    entry = baseline.get(manifest_key)
    if entry is None:
        return {"status": "not_in_baseline"}

    by_split: dict[str, list[str]] = {}
    for r in rows:
        by_split.setdefault(r["split"], []).append(r["image_stem"])
    actual_counts = {s: len(v) for s, v in by_split.items()}

    count_mismatches = {}
    for split, expected in entry.get("expected_counts", {}).items():
        actual = actual_counts.get(split, 0)
        if actual != expected:
            count_mismatches[split] = {"expected": expected, "actual": actual}

    fingerprint_mismatches = {}
    for split, frozen in entry.get("frozen_splits", {}).items():
        actual_stems = by_split.get(split, [])
        actual_count = len(actual_stems)
        actual_hash = _test_fingerprint(actual_stems)
        if actual_count != frozen.get("count") or actual_hash != frozen.get("stem_set_sha256"):
            fingerprint_mismatches[split] = {
                "expected_count": frozen.get("count"), "actual_count": actual_count,
                "expected_sha256": frozen.get("stem_set_sha256"), "actual_sha256": actual_hash,
            }

    return {
        "status": "checked",
        "count_mismatches": count_mismatches,
        "fingerprint_mismatches": fingerprint_mismatches,
        "source": entry.get("source"),
    }


def _ahash(img_path: Path, hash_size: int = 32) -> int:
    import cv2
    img = cv2.imread(str(img_path))
    small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (hash_size, hash_size), interpolation=cv2.INTER_AREA)
    avg = small.mean()
    bits = (small > avg).flatten()
    val = 0
    for b in bits:
        val = (val << 1) | int(b)
    return val


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _parse_ts(stem: str) -> datetime | None:
    parts = stem.split("_")
    try:
        return datetime.strptime(parts[-2] + parts[-1], "%Y%m%d%H%M%S")
    except (ValueError, IndexError):
        return None


def check_near_duplicates(rows: list[dict], raw_dir: Path, hamming_threshold: int = 3,
                           time_window_seconds: int = 600) -> list[dict]:
    stems = [r["image_stem"] for r in rows if (raw_dir / f"{r['image_stem']}.jpg").exists()]
    split_of = {r["image_stem"]: r["split"] for r in rows}
    times = {s: _parse_ts(s) for s in stems}
    stems = [s for s in stems if times[s] is not None]
    hashes = {s: _ahash(raw_dir / f"{s}.jpg") for s in stems}

    ordered = sorted(stems, key=lambda s: times[s])
    findings = []
    for i, s1 in enumerate(ordered):
        for s2 in ordered[i + 1:]:
            dt = (times[s2] - times[s1]).total_seconds()
            if dt > time_window_seconds:
                break
            if split_of[s1] == split_of[s2]:
                continue
            d = _hamming(hashes[s1], hashes[s2])
            if d <= hamming_threshold:
                findings.append({"stem_a": s1, "split_a": split_of[s1], "stem_b": s2,
                                  "split_b": split_of[s2], "hamming": d, "delta_seconds": dt})
    return findings


def check_class_distribution(rows: list[dict], gt_column: str, gt_position: int | None) -> dict:
    from collections import Counter
    by_split: dict[str, Counter] = {}
    for r in rows:
        gt = r.get(gt_column, "")
        if gt_position is not None:
            if len(gt) <= gt_position:
                continue
            key = gt[gt_position]
        else:
            key = gt
        by_split.setdefault(r["split"], Counter())[key] += 1
    return {s: c.most_common() for s, c in by_split.items()}


def check_candidates_against_existing(
    candidate_stems: list[str], existing_rows: list[dict], raw_dir: Path,
    hamming_threshold: int = 3, time_window_seconds: int = 600,
) -> list[dict]:
    """Issue #41: targeted capture等で新規に得たcandidate stem群を、既存
    Train/Val/Test（`existing_rows`、split列を持つ）に対してnear-duplicate監査する。
    既存manifestは一切変更しない（read-only）。Test保護のための主用途。
    candidate側はsplit="candidate"として扱う（既存split同士の重複チェックは
    check_near_duplicatesが既に担当するため、ここではcandidate-vs-existingのみ返す）。
    """
    synthetic_rows = [{"image_stem": s, "split": "candidate"} for s in candidate_stems]
    findings = check_near_duplicates(
        existing_rows + synthetic_rows, raw_dir, hamming_threshold, time_window_seconds,
    )
    return [f for f in findings if f["split_a"] == "candidate" or f["split_b"] == "candidate"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--raw-dir", default=None,
                     help="perceptual near-duplicate check（Layer B）に必要。--ci指定時や "
                          "raw画像が無い環境では省略可（Layer A repo-only checkのみ実行）。")
    ap.add_argument("--project", default=None)
    ap.add_argument("--gt-column", default="reading_gt")
    ap.add_argument("--gt-position", type=int, default=None,
                     help="reading_gtの特定桁(0-indexed)のclass分布を見たい場合に指定")
    ap.add_argument("--candidate-stems-file", default=None,
                     help="Issue #41: targeted captureで新規に得たstem一覧（1行1stem、"
                          "拡張子なし）。指定時、既存manifestのTrain/Val/Testに対する "
                          "near-duplicate監査のみを実行し、通常のsplit自己監査は行わない。")
    ap.add_argument("--hamming-threshold", type=int, default=3)
    ap.add_argument("--time-window-seconds", type=int, default=600)
    ap.add_argument("--skip-near-duplicate", action="store_true",
                     help="raw画像が無い/重い環境向けに、near-duplicate(cv2)checkをskip")
    ap.add_argument("--ci", action="store_true",
                     help="Issue #45: Gate 1 CI向けmode。raw画像/cv2に依存するLayer B "
                          "（perceptual near-duplicate）を一切実行せず、repo内情報のみの "
                          "Layer A（stem overlap・manifest row整合性・baseline照合）のみ "
                          "実行する。visual near-duplicate auditは『Gate 1の対象外』である "
                          "ことを明示的に出力する（SKIPと曖昧にしない、Issue #45 §24）。")
    ap.add_argument("--baseline", default=None,
                     help="Issue #45: 期待split件数・frozen split（例: Digital Test66, "
                          "Hard-Val v2）のstem fingerprintを記録したJSON "
                          "（data_manifests/split_integrity_baseline.json）。指定時、"
                          "manifestをこのbaselineと照合する。")
    args = ap.parse_args()

    ok = True
    manifest = Path(args.manifest)
    raw_dir = Path(args.raw_dir) if args.raw_dir else None
    rows = _load_rows(manifest, args.project)
    with manifest.open(encoding="utf-8") as f:
        fieldnames = csv.DictReader(f).fieldnames
    print(f"manifest: {manifest} ({len(rows)} rows{f', project={args.project}' if args.project else ''})")

    if args.candidate_stems_file:
        if raw_dir is None:
            print("FAIL: --candidate-stems-file には --raw-dir が必須です（perceptual近接判定に raw画像が必要）。")
            sys.exit(1)
        candidate_stems = [
            s.strip() for s in Path(args.candidate_stems_file).read_text(encoding="utf-8").splitlines() if s.strip()
        ]
        exact_overlap = {s for s in candidate_stems if s in {r["image_stem"] for r in rows}}
        print(f"\n=== candidate vs existing manifest ({len(candidate_stems)} candidate stems) ===")
        if exact_overlap:
            print(f"FAIL: exact stem overlap with existing manifest: {sorted(exact_overlap)}")
            ok = False
        else:
            print("OK: no exact stem overlap with existing manifest")
        findings = check_candidates_against_existing(
            candidate_stems, rows, raw_dir, args.hamming_threshold, args.time_window_seconds,
        )
        if findings:
            print(f"found {len(findings)} candidate-vs-existing near-duplicate pair(s) "
                  f"(hamming<={args.hamming_threshold}, within {args.time_window_seconds}s):")
            for f in sorted(findings, key=lambda x: (x["stem_a"], x["stem_b"])):
                print(f"  {f['stem_a']}({f['split_a']}) <-> {f['stem_b']}({f['split_b']}) "
                      f"hamming={f['hamming']} dt={f['delta_seconds']:.0f}s")
            ok = False
        else:
            print("OK: no candidate-vs-existing near-duplicates found")
        sys.exit(0 if ok else 1)

    # --- Layer A: repo-only integrity（raw画像/cv2不要、Gate 1常時実行対象） ---
    print("\n=== required columns ===")
    missing_cols = check_required_columns(fieldnames, args.project)
    if missing_cols:
        print(f"FAIL: missing required columns: {missing_cols}")
        ok = False
    else:
        print("OK: all required columns present")

    print("\n=== row integrity ===")
    row_issues = check_row_integrity(rows)
    if row_issues["empty_stem_or_split"]:
        print(f"FAIL: empty image_stem/split in rows: {row_issues['empty_stem_or_split']}")
        ok = False
    if row_issues["duplicate_rows"]:
        print(f"FAIL: fully duplicate rows for stem(s): {row_issues['duplicate_rows']}")
        ok = False
    if row_issues["conflicting_gt_stems"]:
        print(f"FAIL: same image_stem with conflicting reading_gt: {row_issues['conflicting_gt_stems']}")
        ok = False
    if not any(row_issues.values()):
        print("OK: no empty/duplicate/conflicting rows")

    overlap = check_stem_overlap(rows)
    print("\n=== stem overlap ===")
    print("split sizes:", dict(sorted(overlap["splits"].items())))
    print("within-split duplicates:", dict(sorted(overlap["within_split_duplicates"].items())))
    if overlap["cross_split_overlap"]:
        print("FAIL: cross-split exact stem overlap found:", overlap["cross_split_overlap"])
        ok = False
    elif any(overlap["within_split_duplicates"].values()):
        print("FAIL: within-split duplicate stem(s) found:", overlap["within_split_duplicates"])
        ok = False
    else:
        print("OK: no cross-split exact stem overlap, no within-split duplicates")

    if args.baseline:
        print("\n=== baseline check (expected counts / frozen split fingerprint) ===")
        baseline = load_baseline(Path(args.baseline))
        manifest_key = str(manifest.as_posix())
        result = check_against_baseline(rows, manifest_key, baseline)
        if result["status"] == "not_in_baseline":
            print(f"(manifest not registered in baseline, skipping: {manifest_key})")
        else:
            if result["count_mismatches"]:
                print(f"FAIL: split count mismatch vs baseline ({result['source']}): "
                      f"{result['count_mismatches']}")
                ok = False
            if result["fingerprint_mismatches"]:
                print(f"FAIL: frozen split stem-set fingerprint mismatch vs baseline "
                      f"({result['source']}): {result['fingerprint_mismatches']}")
                ok = False
            if not result["count_mismatches"] and not result["fingerprint_mismatches"]:
                print(f"OK: matches baseline ({result['source']})")

    # --- Layer B: perceptual near-duplicate（raw画像必須。Gate 1では実行しない） ---
    if args.ci:
        print("\n=== visual near-duplicate audit ===")
        print("visual near-duplicate audit: not part of Gate 1 (requires raw images; "
              "run locally with --raw-dir instead, see docs/CI_GPU_RUNNER.md)")
    elif not args.skip_near_duplicate:
        if raw_dir is None:
            print("FAIL: near-duplicate check には --raw-dir が必要です（--ci または "
                  "--skip-near-duplicate で明示的にskipしてください）。")
            ok = False
        else:
            print(f"\n=== near-duplicate check (hamming<={args.hamming_threshold}, "
                  f"within {args.time_window_seconds}s) ===")
            findings = check_near_duplicates(rows, raw_dir, args.hamming_threshold, args.time_window_seconds)
            if findings:
                print(f"found {len(findings)} cross-split near-duplicate pair(s):")
                for f in sorted(findings, key=lambda x: (x["stem_a"], x["stem_b"])):
                    print(f"  {f['stem_a']}({f['split_a']}) <-> {f['stem_b']}({f['split_b']}) "
                          f"hamming={f['hamming']} dt={f['delta_seconds']:.0f}s")
                ok = False
            else:
                print("OK: no cross-split near-duplicates found")

    print(f"\n=== class distribution (gt_column={args.gt_column}, position={args.gt_position}) ===")
    dist = check_class_distribution(rows, args.gt_column, args.gt_position)
    for split, counts in sorted(dist.items()):
        print(f"  {split}: {counts}")

    print(f"\n=== result: {'OK (exit 0)' if ok else 'FAIL (exit 1)'} ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
