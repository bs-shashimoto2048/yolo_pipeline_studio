"""汎用split integrity checker（Issue #40）。

Train/Val/Test manifestのstem重複・perceptual near-duplicate・class分布を機械確認する。
production weight・real inferenceは一切不要（read-only、manifest+raw画像のみ参照）。
Issue #39/#40で発見したdigital production splitのcross-split near-duplicate問題の
再発防止用に、Gate 1 CI（GPU/production artifact不要なCPU step）へ将来組み込める
軽量設計にしている。

使い方:
    .venv\\Scripts\\python.exe scripts\\audit_dataset_split.py \\
        --manifest data_manifests/meter_src002_split_v3.csv \\
        --raw-dir projects/meter_src002/raw/images \\
        --project meter_src002 \\
        --gt-column reading_gt --gt-position 3
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path


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
    ap.add_argument("--raw-dir", required=True)
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
    args = ap.parse_args()

    manifest = Path(args.manifest)
    raw_dir = Path(args.raw_dir)
    rows = _load_rows(manifest, args.project)
    print(f"manifest: {manifest} ({len(rows)} rows{f', project={args.project}' if args.project else ''})")

    if args.candidate_stems_file:
        candidate_stems = [
            s.strip() for s in Path(args.candidate_stems_file).read_text(encoding="utf-8").splitlines() if s.strip()
        ]
        exact_overlap = {s for s in candidate_stems if s in {r["image_stem"] for r in rows}}
        print(f"\n=== candidate vs existing manifest ({len(candidate_stems)} candidate stems) ===")
        if exact_overlap:
            print(f"FAIL: exact stem overlap with existing manifest: {sorted(exact_overlap)}")
        else:
            print("OK: no exact stem overlap with existing manifest")
        findings = check_candidates_against_existing(
            candidate_stems, rows, raw_dir, args.hamming_threshold, args.time_window_seconds,
        )
        if findings:
            print(f"found {len(findings)} candidate-vs-existing near-duplicate pair(s) "
                  f"(hamming<={args.hamming_threshold}, within {args.time_window_seconds}s):")
            for f in findings:
                print(f"  {f['stem_a']}({f['split_a']}) <-> {f['stem_b']}({f['split_b']}) "
                      f"hamming={f['hamming']} dt={f['delta_seconds']:.0f}s")
        else:
            print("OK: no candidate-vs-existing near-duplicates found")
        return

    overlap = check_stem_overlap(rows)
    print("\n=== stem overlap ===")
    print("split sizes:", overlap["splits"])
    print("within-split duplicates:", overlap["within_split_duplicates"])
    if overlap["cross_split_overlap"]:
        print("FAIL: cross-split exact stem overlap found:", overlap["cross_split_overlap"])
    else:
        print("OK: no cross-split exact stem overlap")

    if not args.skip_near_duplicate:
        print(f"\n=== near-duplicate check (hamming<={args.hamming_threshold}, "
              f"within {args.time_window_seconds}s) ===")
        findings = check_near_duplicates(rows, raw_dir, args.hamming_threshold, args.time_window_seconds)
        if findings:
            print(f"found {len(findings)} cross-split near-duplicate pair(s):")
            for f in findings:
                print(f"  {f['stem_a']}({f['split_a']}) <-> {f['stem_b']}({f['split_b']}) "
                      f"hamming={f['hamming']} dt={f['delta_seconds']:.0f}s")
        else:
            print("OK: no cross-split near-duplicates found")

    print(f"\n=== class distribution (gt_column={args.gt_column}, position={args.gt_position}) ===")
    dist = check_class_distribution(rows, args.gt_column, args.gt_position)
    for split, counts in dist.items():
        print(f"  {split}: {counts}")


if __name__ == "__main__":
    main()
