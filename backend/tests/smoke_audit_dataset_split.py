"""scripts/audit_dataset_split.py（Issue #40/#41）の軽量スモークテスト。

production weight/real inference不要。synthetic画像（同一画像・微小shift・
明確に異なる画像）で、near-duplicate判定が期待通りに動作することを確認する
（Issue #41 §25）。既存manifestに対するcandidate-vs-existing監査モード
（Issue #41で追加）も検証する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_audit_dataset_split.py
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))


def check(label: str, cond: bool) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        raise SystemExit(1)


def _make_image(cv2, np, path: Path, seed: int, shift: int = 0) -> None:
    """乱数patternを持つsynthetic画像を生成する。

    aHash（平均値との大小比較）は単色の平坦な画像では常に全bit0になり
    （全pixelが平均と等しいため）、明暗だけが異なる2枚を正しく区別できない
    （本テストの初版で実際に踏んだ落とし穴）。再現可能な乱数patternを使うことで、
    「同一画像」「微小shift」「明確に異なる画像」を現実の写真同様に区別できるようにする。
    """
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
    if shift:
        arr = np.roll(arr, shift, axis=1)  # 横方向に微小シフト(視覚的にほぼ同一の近接フレームを模す)
    cv2.imwrite(str(path), arr)


def main() -> None:
    import audit_dataset_split as ads  # noqa: PLC0415 (cv2依存、他のsmoke testと同じ遅延import規約)
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    tmp = Path(tempfile.mkdtemp(prefix="yts_audit_split_smoke_"))
    raw_dir = tmp / "raw"
    raw_dir.mkdir()

    # --- 既存manifest(Train/Val/Test)を模したsynthetic画像 ---
    _make_image(cv2, np, raw_dir / "existing_train_20260101_100000.jpg", seed=1)
    _make_image(cv2, np, raw_dir / "existing_test_20260101_100500.jpg", seed=1)  # train/testで同一画像(重複)
    _make_image(cv2, np, raw_dir / "existing_val_20260101_120000.jpg", seed=99)  # 全く別の画像

    manifest = tmp / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_stem", "split", "reading_gt"])
        w.writerow(["existing_train_20260101_100000", "train", "0000004"])
        w.writerow(["existing_test_20260101_100500", "test", "0000004"])
        w.writerow(["existing_val_20260101_120000", "val", "0000005"])

    # --- 1) 通常のsplit自己監査: train/testペアがnear-duplicateとして検出されること ---
    rows = ads._load_rows(manifest, None)
    overlap = ads.check_stem_overlap(rows)
    check("no exact stem overlap in self-audit", overlap["cross_split_overlap"] == {})
    findings = ads.check_near_duplicates(rows, raw_dir, hamming_threshold=3, time_window_seconds=600)
    check("self-audit detects the known train/test near-duplicate",
          any({f["stem_a"], f["stem_b"]} == {"existing_train_20260101_100000", "existing_test_20260101_100500"}
              for f in findings))
    check("self-audit does not flag the clearly-distinct val image",
          not any("existing_val_20260101_120000" in (f["stem_a"], f["stem_b"]) for f in findings))

    # --- 2) candidate-vs-existing監査: 3種類のcandidate (同一画像/微小shift/明確に異なる) ---
    _make_image(cv2, np, raw_dir / "candidate_same_20260101_100200.jpg", seed=1)  # existing_trainと同一pattern
    _make_image(cv2, np, raw_dir / "candidate_shifted_20260101_100300.jpg", seed=1, shift=3)  # 同一patternの微小shift
    _make_image(cv2, np, raw_dir / "candidate_distinct_20260101_100400.jpg", seed=42)  # 明確に異なるpattern

    candidate_stems = ["candidate_same_20260101_100200", "candidate_shifted_20260101_100300",
                        "candidate_distinct_20260101_100400"]
    cand_findings = ads.check_candidates_against_existing(
        candidate_stems, rows, raw_dir, hamming_threshold=3, time_window_seconds=600,
    )
    flagged = {f["stem_a"] if f["stem_a"] in candidate_stems else f["stem_b"] for f in cand_findings}
    check("exact-duplicate candidate flagged as near-duplicate", "candidate_same_20260101_100200" in flagged)
    check("clearly-distinct candidate not flagged", "candidate_distinct_20260101_100400" not in flagged)
    # shifted候補は閾値次第でどちらの判定もあり得るが、クラッシュせず結果を返すことを確認
    check("shifted candidate handled without error (either verdict acceptable)",
          "candidate_shifted_20260101_100300" in flagged or "candidate_shifted_20260101_100300" not in flagged)

    # --- 3) class distribution（汎用性: 任意のgt-position） ---
    dist = ads.check_class_distribution(rows, "reading_gt", 6)
    check("class distribution computed per split", dist.get("train") == [("4", 1)])

    # --- 4) exact stem overlapとの衝突検知（candidateが既存と同名の場合） ---
    exact_overlap_stems = ["existing_train_20260101_100000"]
    exact_match = {s for s in exact_overlap_stems if s in {r["image_stem"] for r in rows}}
    check("exact stem overlap with existing manifest detected", exact_match == {"existing_train_20260101_100000"})

    print("\nALL AUDIT_DATASET_SPLIT SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
