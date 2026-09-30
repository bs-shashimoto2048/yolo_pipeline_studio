"""Production inference contract 回帰検知テスト（Issue #27）。

目的はモデル精度評価ではなく、Ultralyticsバージョン更新・worker変更・前処理変更等によって
production inference挙動が意図せず変化していないかを検知すること。

2層構成:
- Layer A（常時実行、production weight不要）: predict_worker.py / predict_video_worker.py の
  kwargsにcontract定数（rect=True等）が明示されていること、image/video間で値が一致していることを
  ソースレベルで確認する。
- Layer B（production weight・fixture画像がローカルに存在する場合のみ実行）: 実際にproduction
  weightでpredictし、`backend/tests/fixtures/production_inference_contract_golden_v1.json`の
  golden値と比較する。weight/fixtureが無い環境ではSKIP（fail扱いにしない）。weightが存在するのに
  hashが不一致な場合はFAILする。

Test/Hard-Valは使用しない。fixtureはIssue #25/#26で既にfreeze・Test/Hard-Val非重複確認済みの
stem一覧から、7/7検出が安定し閾値に余裕のある画像を選定している（詳細は
docs/PRODUCTION_INFERENCE_CONTRACT.md 参照）。fixture画像本体（*.jpg）はGit管理外の
`projects/`配下から解決するため、本ファイル・golden JSONには画像バイト列を含まない。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_inference_contract.py
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "production_inference_contract_golden_v1.json"

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
    # Issue #38: CI/GPU runner上ではproduction artifact欠落をSKIPで握り潰さず、
    # 明示的にFAILさせる（silent successを防ぐ）。通常のlocal実行では従来通りSKIP。
    if os.environ.get("YTS_PRODUCTION_SMOKE_REQUIRED") == "1":
        print("FAIL(required) " + label)
        _FAIL += 1
        raise SystemExit(1)
    print("SKIP " + label)
    _SKIP += 1


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


PINNED_KEYS = ["rect=True", "max_det=300", "agnostic_nms=False", "augment=False", "batch=1", "quantize=None"]


# ---------------------------------------------------------------------------
# Layer A: production weight不要（ソースレベルの構造検査）
# ---------------------------------------------------------------------------

def layer_a() -> None:
    print("\n=== Layer A: contract constants in worker source (no model weight required) ===")

    predict_src = (_BACKEND_DIR / "workers" / "predict_worker.py").read_text(encoding="utf-8")
    image_block = predict_src.split("kwargs = dict(", 1)[-1].split(
        'if args.device and args.device != "auto":', 1
    )[0]
    for key in PINNED_KEYS:
        check(f"image worker kwargs has {key}", key in image_block)

    video_src = (_BACKEND_DIR / "workers" / "predict_video_worker.py").read_text(encoding="utf-8")
    video_blocks_raw = video_src.split("predict_kwargs = dict(")
    check("predict_video_worker.py has exactly 2 predict_kwargs constructions "
          "(初期生成 + live settings refresh再生成)", len(video_blocks_raw) - 1 == 2)
    video_blocks = [b.split(")", 1)[0] for b in video_blocks_raw[1:]]
    for i, block in enumerate(video_blocks, start=1):
        for key in PINNED_KEYS:
            check(f"video worker predict_kwargs block #{i} has {key}", key in block)

    # Image / Video parity: image workerとvideo workerの両方の生成箇所で、
    # pinした値が完全に同一であること（Issue #25/#26で学んだ「再生成箇所の片側だけ漏れる」防止）
    print("\n--- Image / Video parity ---")
    print(f"{'Parameter':<16}{'Image':<8}{'Video initial':<16}{'Video refresh':<16}{'Match'}")
    all_match = True
    for key in PINNED_KEYS:
        in_image = key in image_block
        in_video = [key in b for b in video_blocks]
        match = in_image and all(in_video)
        all_match = all_match and match
        print(f"{key:<16}{str(in_image):<8}{str(in_video[0]):<16}{str(in_video[1]):<16}{match}")
    check("all pinned parameters match across image/video (both generations)", all_match)

    # contract versionを人間向けdocへ記載していることの存在確認（内容の詳細検査はしない）
    contract_doc = _REPO_ROOT / "docs" / "PRODUCTION_INFERENCE_CONTRACT.md"
    check("docs/PRODUCTION_INFERENCE_CONTRACT.md exists", contract_doc.exists())
    if contract_doc.exists():
        doc_src = contract_doc.read_text(encoding="utf-8")
        golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
        check("contract doc references current contract version",
              golden["contract_version"] in doc_src)


# ---------------------------------------------------------------------------
# Layer B: production weight・fixture画像が存在する場合のみ実行
# ---------------------------------------------------------------------------

def boxes_from_result(r):
    out = []
    if r.boxes is not None and len(r.boxes) > 0:
        xyxy = r.boxes.xyxy.tolist()
        cls = r.boxes.cls.tolist()
        conf = r.boxes.conf.tolist()
        for (x1, y1, x2, y2), c, cf in zip(xyxy, cls, conf):
            out.append({"cls": int(c), "conf": float(cf), "xyxy": (x1, y1, x2, y2), "xc": (x1 + x2) / 2})
    out.sort(key=lambda b: b["xc"])
    return out


_WEIGHT_PATHS = {
    "digital": _REPO_ROOT / "projects/meter_src002/runs/train/production_combined_v2_5z/weights/best.pt",
    "drum": _REPO_ROOT / "projects/meter_src004/runs/train/candidate_roi_v3_5/weights/best.pt",
}
_FIXTURE_DIRS = {
    "digital": _REPO_ROOT / "projects/yolo26_digital/datasets/matched_source_v1/images/train",
    "drum": _REPO_ROOT / "projects/yolo26_dram_crop/datasets/matched_source_v1/images/train",
}


def layer_b() -> None:
    print("\n=== Layer B: real production weight prediction (skips if artifact not available locally) ===")

    if not _GOLDEN_PATH.exists():
        skip("golden fixture file not found (backend/tests/fixtures/production_inference_contract_golden_v1.json)")
        return
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    os.environ.setdefault("YOLO_AUTOINSTALL", "False")

    for label, weight_path in _WEIGHT_PATHS.items():
        proj_golden = golden["projects"][label]
        if not weight_path.exists():
            skip(f"[{label}] production model artifact not available ({weight_path})")
            continue

        actual_hash = sha256_file(weight_path)
        expected_hash = proj_golden["weight_sha256"]
        if actual_hash != expected_hash:
            check(f"[{label}] weight SHA256 matches provenance "
                  f"(expected {expected_hash}, got {actual_hash})", False)
            continue
        check(f"[{label}] weight SHA256 matches provenance", True)

        from ultralytics import YOLO  # noqa: PLC0415  (Layer Bのみ必要な重い依存)
        import cv2  # noqa: PLC0415

        model = YOLO(str(weight_path))
        img_dir = _FIXTURE_DIRS[label]

        for fx in proj_golden["fixtures"]:
            stem = fx["stem"]
            img_path = img_dir / f"{stem}.jpg"
            if not img_path.exists():
                # fixture画像はproduction weightと同じくGit管理外(projects/配下)のローカル専用
                # 資産のため、環境によっては個別に欠落しうる。これは production contract 違反の
                # 証拠ではないため、hard failではなく明示的skipとして扱う。
                skip(f"[{label}] fixture image not available locally ({img_path})")
                continue

            im0 = cv2.imread(str(img_path))
            h, w = im0.shape[:2]
            check(f"[{label}] {stem}: preprocess output size == golden",
                  [w, h] == fx["preprocess_output_size"])

            kwargs = dict(
                conf=proj_golden["conf"], iou=0.7, imgsz=640, verbose=False, save=False,
                **golden["pinned_args"],
            )
            r = model.predict(str(img_path), **kwargs)[0]
            a = model.predictor.args
            tensor = model.predictor.preprocess([im0])
            boxes = boxes_from_result(r)
            reading = "".join(str(b["cls"]) for b in boxes)

            resolved = {
                "rect": a.rect, "max_det": a.max_det, "agnostic_nms": a.agnostic_nms,
                "augment": a.augment, "batch": a.batch, "quantize": a.quantize,
                "conf": a.conf, "iou": a.iou, "imgsz": a.imgsz,
            }

            # --- strict fields ---
            check(f"[{label}] {stem}: tensor shape (strict)", list(tensor.shape) == fx["tensor_shape"])
            check(f"[{label}] {stem}: resolved args (strict)", resolved == fx["resolved_args"])
            check(f"[{label}] {stem}: detection count (strict)", len(boxes) == fx["detection_count"])
            check(f"[{label}] {stem}: class sequence (strict)",
                  [b["cls"] for b in boxes] == fx["class_sequence"])
            check(f"[{label}] {stem}: reading (strict)", reading == fx["reading"])

            # --- tolerance fields ---
            tol_conf = golden["tolerance"]["confidence_abs_diff"]
            tol_bbox = golden["tolerance"]["bbox_abs_diff_px"]
            if len(boxes) == fx["detection_count"]:
                conf_diffs = [abs(b["conf"] - g) for b, g in zip(boxes, fx["confidence"])]
                bbox_diffs = [
                    max(abs(v - gv) for v, gv in zip(b["xyxy"], g))
                    for b, g in zip(boxes, fx["bbox_xyxy"])
                ]
                check(f"[{label}] {stem}: confidence within tolerance "
                      f"(max diff {max(conf_diffs):.6f} <= {tol_conf})", max(conf_diffs) <= tol_conf)
                check(f"[{label}] {stem}: bbox within tolerance "
                      f"(max diff {max(bbox_diffs):.4f} <= {tol_bbox}px)", max(bbox_diffs) <= tol_bbox)


def main() -> None:
    layer_a()
    layer_b()
    print(f"\n{_PASS} passed, {_FAIL} failed, {_SKIP} skipped")
    print("\nALL INFERENCE CONTRACT SMOKE TESTS PASSED (or safely skipped)")


if __name__ == "__main__":
    main()
