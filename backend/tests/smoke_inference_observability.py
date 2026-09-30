"""Production inference observability metadataのスモークテスト（Issue #29）。

job.json に記録する `inference_contract`（contract version・model identity・SHA256・
resolved args）が、実際のUltralytics実行なしで検証できる範囲について正しく構築・
維持されることを確認する。実Ultralytics/production weightでの動作は
backend/tests/smoke_inference_contract.py（Layer B、production weight存在時のみ実行）
および本Issueのnon-Test production smokeで別途確認する。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_inference_observability.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

import inference_contract  # noqa: E402
import predict_worker  # noqa: E402
import predict_video_worker  # noqa: E402

from app.schemas.prediction import PredictJobInfo  # noqa: E402
from app.schemas.video import VideoJobInfo  # noqa: E402

_PASS = 0
_FAIL = 0


def check(label: str, cond: bool) -> None:
    global _PASS, _FAIL
    print(("OK  " if cond else "FAIL") + " " + label)
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# 1. contract定数（single source of truth）
# ---------------------------------------------------------------------------

def test_contract_version_matches_docs() -> None:
    doc = (_REPO_ROOT / "docs" / "PRODUCTION_INFERENCE_CONTRACT.md").read_text(encoding="utf-8")
    check("inference_contract.CONTRACT_VERSION appears in PRODUCTION_INFERENCE_CONTRACT.md",
          inference_contract.CONTRACT_VERSION in doc)

    golden = json.loads(
        (_BACKEND_DIR / "tests" / "fixtures" / "production_inference_contract_golden_v1.json")
        .read_text(encoding="utf-8")
    )
    check("inference_contract.CONTRACT_VERSION matches golden fixture contract_version",
          inference_contract.CONTRACT_VERSION == golden["contract_version"])


def _kwargs_block(src: str, start_marker: str, end_markers: list[str]) -> str:
    block = src.split(start_marker, 1)[-1]
    for m in end_markers:
        if m in block:
            block = block.split(m, 1)[0]
    return block


def test_pinned_args_module_matches_worker_literals() -> None:
    """inference_contract.PINNED_ARGS の値が、両workerのkwargsリテラルと一致することを確認する。

    リテラル自体（smoke_inference_contract.pyが検査する rect=True 等の文字列）は
    Issue #25/#26/#27の回帰テストが直接依存しているため書き換えない。ここでは
    「observability用に別定義したPINNED_ARGSが、実際にpredict()へ渡る値とずれていないか」
    を文字列一致で検証し、2箇所が将来乖離するのを防ぐ。
    """
    image_src = (_BACKEND_DIR / "workers" / "predict_worker.py").read_text(encoding="utf-8")
    image_block = _kwargs_block(
        image_src, "kwargs = dict(", ['if args.device and args.device != "auto":']
    )
    video_src = (_BACKEND_DIR / "workers" / "predict_video_worker.py").read_text(encoding="utf-8")
    video_blocks_raw = video_src.split("predict_kwargs = dict(")
    video_blocks = [b.split(")", 1)[0] for b in video_blocks_raw[1:]]

    for key, value in inference_contract.PINNED_ARGS.items():
        literal = f"{key}={value!r}" if not isinstance(value, bool) else f"{key}={value}"
        check(f"image worker literal has {literal}", literal in image_block)
        for i, block in enumerate(video_blocks, start=1):
            check(f"video worker predict_kwargs block #{i} literal has {literal}", literal in block)


# ---------------------------------------------------------------------------
# 2. model identity / SHA256
# ---------------------------------------------------------------------------

def test_sha256_file_matches_hashlib() -> None:
    with tempfile.TemporaryDirectory(prefix="yts_obs_hash_") as td:
        p = Path(td) / "fake.pt"
        payload = b"not-a-real-weight-but-deterministic-bytes" * 100
        p.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        check("sha256_file matches hashlib for a fixture file", inference_contract.sha256_file(p) == expected)

    check("sha256_file returns None for missing file",
          inference_contract.sha256_file(Path(td) / "missing.pt") is None)


def test_resolve_model_identity_uses_relative_path_and_no_fabrication() -> None:
    with tempfile.TemporaryDirectory(prefix="yts_obs_identity_") as td:
        root = Path(td)
        job_json = root / "job.json"
        weight = root / "best.pt"
        weight.write_bytes(b"weight-bytes")
        job_json.write_text(json.dumps({"train_job_id": "train_x", "weight_type": "best"}), encoding="utf-8")

        identity = inference_contract.resolve_model_identity(job_json, weight)
        check("model identity train_job_id", identity["train_job_id"] == "train_x")
        check("model identity weight_type", identity["weight_type"] == "best")
        check("model identity model_path is project-relative (no absolute path)",
              identity["model_path"] == "runs/train/train_x/weights/best.pt")
        check("model identity model_path has no drive letter / no local username",
              ":" not in identity["model_path"] and "Users" not in identity["model_path"])
        check("model identity sha256 matches weight bytes",
              identity["sha256"] == hashlib.sha256(b"weight-bytes").hexdigest())

        # job.jsonが読めない/train_job_id不明 -> model_pathを捏造しない
        broken_job = root / "broken_job.json"
        broken_job.write_text("not json", encoding="utf-8")
        identity2 = inference_contract.resolve_model_identity(broken_job, weight)
        check("unresolved train_job_id -> model_path is None (not fabricated)", identity2["model_path"] is None)
        check("unresolved train_job_id -> sha256 still computed (weight file itself is readable)",
              identity2["sha256"] == hashlib.sha256(b"weight-bytes").hexdigest())

        # weight自体が存在しない -> hashを捏造しない
        identity3 = inference_contract.resolve_model_identity(job_json, root / "missing.pt")
        check("missing weight file -> sha256 is None (not fabricated)", identity3["sha256"] is None)


# ---------------------------------------------------------------------------
# 3. resolved args（pinned + runtime）
# ---------------------------------------------------------------------------

def test_build_resolved_args_shape_and_no_guessing() -> None:
    args = inference_contract.build_resolved_args(
        conf=0.6, iou=0.7, imgsz=640, requested_device="auto",
    )
    check("resolved_args has all pinned keys", all(k in args for k in inference_contract.PINNED_ARGS))
    check("resolved_args pinned values match module", all(args[k] == v for k, v in inference_contract.PINNED_ARGS.items()))
    check("resolved_args conf/iou/imgsz reflect runtime values", (args["conf"], args["iou"], args["imgsz"]) == (0.6, 0.7, 640))
    check("resolved_args requested_device reflects requested value", args["requested_device"] == "auto")
    check("resolved_args runtime_device defaults to None (not guessed)", args["runtime_device"] is None)

    args2 = inference_contract.build_resolved_args(
        conf=0.8, iou=0.7, imgsz=640, requested_device="auto", runtime_device="cuda:0",
    )
    check("resolved_args runtime_device is recorded once known", args2["runtime_device"] == "cuda:0")


def test_build_contract_full_shape() -> None:
    with tempfile.TemporaryDirectory(prefix="yts_obs_contract_") as td:
        root = Path(td)
        job_json = root / "job.json"
        weight = root / "best.pt"
        weight.write_bytes(b"weight-bytes-2")
        job_json.write_text(json.dumps({"train_job_id": "train_y", "weight_type": "last"}), encoding="utf-8")

        contract = inference_contract.build_contract(
            job_json, weight, conf=0.25, iou=0.7, imgsz=640, requested_device="auto",
        )
        check("contract has contract_version", contract["contract_version"] == inference_contract.CONTRACT_VERSION)
        check("contract has ultralytics_version key (value may be None if not importable)",
              "ultralytics_version" in contract)
        check("contract has torch_version key (value may be None if not importable)",
              "torch_version" in contract)
        check("contract.model.model_path is relative", contract["model"]["model_path"] == "runs/train/train_y/weights/last.pt")
        check("contract.resolved_args has pinned rect=True", contract["resolved_args"]["rect"] is True)

        # 意図的に未pinのパラメータ（classes/end2end/half/verbose等）を
        # 「resolved contract field」として無理に含めていないこと
        for unpinned in ("classes", "end2end", "half", "verbose"):
            check(f"contract does not fabricate unpinned field '{unpinned}'", unpinned not in contract["resolved_args"])


# ---------------------------------------------------------------------------
# 4. job.json永続化（status更新でinference_contractが消えないこと）
# ---------------------------------------------------------------------------

def test_metadata_survives_status_updates_image_worker() -> None:
    with tempfile.TemporaryDirectory(prefix="yts_obs_persist_img_") as td:
        job_json = Path(td) / "job.json"
        job_json.write_text(json.dumps({"status": "running"}), encoding="utf-8")
        contract = {"contract_version": inference_contract.CONTRACT_VERSION, "model": {"sha256": "abc"}}
        predict_worker._update_job(job_json, inference_contract=contract)

        for status in ("running", "completed"):
            predict_worker._update_job(job_json, status=status, message=status)
            data = json.loads(job_json.read_text(encoding="utf-8"))
            check(f"[image] inference_contract survives status={status}", data.get("inference_contract") == contract)

        # failed遷移でも消えないこと（推論失敗時の記録保護）
        predict_worker._update_job(job_json, status="failed", message="推論失敗: dummy")
        data = json.loads(job_json.read_text(encoding="utf-8"))
        check("[image] inference_contract survives status=failed", data.get("inference_contract") == contract)


def test_metadata_survives_status_updates_video_worker() -> None:
    with tempfile.TemporaryDirectory(prefix="yts_obs_persist_vid_") as td:
        job_json = Path(td) / "job.json"
        job_json.write_text(json.dumps({"status": "queued"}), encoding="utf-8")
        contract = {
            "contract_version": inference_contract.CONTRACT_VERSION,
            "model": {"sha256": "def"},
            "initial_resolved_args": {"conf": 0.6, "runtime_device": None},
            "current_resolved_args": {"conf": 0.6, "runtime_device": None},
        }
        predict_video_worker._update_job(job_json, inference_contract=contract)

        for status in ("running", "stopped", "completed", "failed"):
            predict_video_worker._update_job(job_json, status=status, message=status)
            data = json.loads(job_json.read_text(encoding="utf-8"))
            check(f"[video] inference_contract survives status={status}", data.get("inference_contract") == contract)


# ---------------------------------------------------------------------------
# 5. DRY_RUN経路ではinference_contractを捏造しないこと（Ultralytics未読込のため）
# ---------------------------------------------------------------------------

def test_dry_run_paths_do_not_reference_inference_contract() -> None:
    image_src = (_BACKEND_DIR / "workers" / "predict_worker.py").read_text(encoding="utf-8")
    image_dry_block = image_src.split('if os.environ.get("YTS_PREDICT_DRY_RUN"):', 1)[-1].split(
        "# 3) Ultralytics 読み込み", 1
    )[0]
    check("predict_worker.py DRY RUN branch does not reference inference_contract",
          "inference_contract" not in image_dry_block)

    video_src = (_BACKEND_DIR / "workers" / "predict_video_worker.py").read_text(encoding="utf-8")
    video_dry_block = video_src.split('if os.environ.get("YTS_VIDEO_DRY_RUN"):', 1)[-1].split(
        "# --- 実処理 ---", 1
    )[0]
    check("predict_video_worker.py DRY RUN branch does not reference inference_contract",
          "inference_contract" not in video_dry_block)


def test_workers_write_contract_before_predict_call() -> None:
    """model load直後・predict実行前にinference_contractがjob.jsonへ書かれることをソースで確認する。

    推論失敗時にも記録が残る設計（§21）であるためには、書き込みがpredict呼び出しより
    前になければならない。
    """
    image_src = (_BACKEND_DIR / "workers" / "predict_worker.py").read_text(encoding="utf-8")
    real_run_block = image_src.split("# 4) 推論実行", 1)[-1]
    idx_contract_write = real_run_block.index('_update_job(job_json, inference_contract=contract)')
    idx_predict_call = real_run_block.index("preds = model.predict(**kwargs)")
    check("image worker writes inference_contract before calling model.predict()",
          idx_contract_write < idx_predict_call)

    video_src = (_BACKEND_DIR / "workers" / "predict_video_worker.py").read_text(encoding="utf-8")
    real_run_block_v = video_src.split("# --- 実処理 ---", 1)[-1]
    idx_contract_write_v = real_run_block_v.index('_update_job(job_json, inference_contract=contract)')
    idx_loop_start_v = real_run_block_v.index("while time.time() < deadline:")
    check("video worker writes inference_contract before entering the capture loop",
          idx_contract_write_v < idx_loop_start_v)


# ---------------------------------------------------------------------------
# 6. Schema legacy compatibility（旧job.json = inference_contractキーが無い）
# ---------------------------------------------------------------------------

def test_legacy_job_without_inference_contract_key() -> None:
    legacy_predict_job = {
        "predict_job_id": "p_legacy",
        "predict_job_name": "p_legacy",
        "train_job_id": "train_x",
        "weight_type": "best",
        "source_type": "project_images",
        "status": "completed",
        "conf": 0.25,
    }
    info = PredictJobInfo(project_name="proj", **legacy_predict_job)
    check("legacy PredictJobInfo (no inference_contract key) parses without error", info.inference_contract is None)

    legacy_video_job = {
        "video_job_id": "v_legacy",
        "train_job_id": "train_x",
        "weight_type": "best",
        "source_type": "camera",
        "status": "completed",
        "conf": 0.25,
    }
    vinfo = VideoJobInfo(project_name="proj", stream_url="/api/x", **legacy_video_job)
    check("legacy VideoJobInfo (no inference_contract key) parses without error", vinfo.inference_contract is None)


def test_new_job_with_inference_contract_is_exposed() -> None:
    contract = {"contract_version": inference_contract.CONTRACT_VERSION, "model": {"sha256": "abc"}}
    new_predict_job = {
        "predict_job_id": "p_new", "predict_job_name": "p_new", "train_job_id": "t", "weight_type": "best",
        "source_type": "project_images", "status": "completed", "conf": 0.6, "inference_contract": contract,
    }
    info = PredictJobInfo(project_name="proj", **new_predict_job)
    check("PredictJobInfo exposes inference_contract when present", info.inference_contract == contract)


def main() -> None:
    test_contract_version_matches_docs()
    test_pinned_args_module_matches_worker_literals()
    test_sha256_file_matches_hashlib()
    test_resolve_model_identity_uses_relative_path_and_no_fabrication()
    test_build_resolved_args_shape_and_no_guessing()
    test_build_contract_full_shape()
    test_metadata_survives_status_updates_image_worker()
    test_metadata_survives_status_updates_video_worker()
    test_dry_run_paths_do_not_reference_inference_contract()
    test_workers_write_contract_before_predict_call()
    test_legacy_job_without_inference_contract_key()
    test_new_job_with_inference_contract_is_exposed()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    print("\nALL INFERENCE OBSERVABILITY SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
