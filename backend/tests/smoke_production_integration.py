"""Production integration smoke（Layer C, Issue #32）。

Issue #25〜#31でscratchpadや手動実行によって都度確認してきた
「production weight load → selected model resolution → preprocess →
実worker（subprocess/直接呼び出し） → real YOLO predict → inference contract
（Issue #29） → observability metadata」の一連の統合動作を、恒久testとして
実行できるようにする。**model精度評価ではなく、production wiring/runtime
integration/observability/contractの統合smoke**である。

Test/Hard-Valは一切使用しない（fixtureは`production_smoke_v1.json`で定義した
Train所属stemのみ。Test/Hard-Val manifestとのoverlapを実行毎に機械確認し、
重複があればSKIPではなくFAILする）。

production artifacts（weight・selected_model.json）はread-onlyで利用し、
書き換えないことをhash/content比較で確認する。predictionsはすべて一時ディレクトリへ
出力し、実production job historyは一切触らない。

production weight・fixture画像がローカルに存在しない環境ではSKIPする
（production weightをunit test必須条件にはしない。`smoke_inference_contract.py`
と同じ方針）。

実行:
    .\\.venv\\Scripts\\python.exe backend\\tests\\smoke_production_integration.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_GOLDEN_PATH = _FIXTURES_DIR / "production_inference_contract_golden_v1.json"
_CONFIG_PATH = _FIXTURES_DIR / "production_smoke_v1.json"

_tmp = tempfile.mkdtemp(prefix="yts_prod_smoke_")
os.environ["YTS_PROJECTS_ROOT"] = _tmp
os.environ.setdefault("YOLO_AUTOINSTALL", "False")
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_BACKEND_DIR / "workers"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
import predict_video_worker  # noqa: E402

client = TestClient(app)
ROOT = Path(_tmp)

_PASS = 0
_FAIL = 0
_SKIP = 0

_WEIGHT_TEMPLATE = "runs/train/{train_job_id}/weights/{weight_type}.pt"


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


# ---------------------------------------------------------------------------
# Fixture config / overlap guard
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    check("production_smoke_v1.json exists", _CONFIG_PATH.exists())
    cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    check("config version == production-smoke-v1", cfg.get("version") == "production-smoke-v1")
    for key in ("digital", "drum"):
        check(f"config has '{key}' section", key in cfg)
        entry = cfg[key]
        for req in ("project", "train_job_id", "weight_type", "conf", "weight_sha256", "manifest", "source_dir", "stems"):
            check(f"config.{key}.{req} present", req in entry)
        check(f"config.{key}.stems non-empty", len(entry["stems"]) > 0)
    check("config has video_smoke_project", cfg.get("video_smoke_project") in ("digital", "drum"))
    check("config has video_smoke_stem", bool(cfg.get("video_smoke_stem")))
    return cfg


def _manifest_stems(rel_path: str, split: str) -> set[str]:
    with (_REPO_ROOT / rel_path).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["image_stem"] for r in rows if r["split"] == split}


def _overlap_guard(cfg: dict) -> None:
    """fixture stemがTest/Hard-Valと重複していないかを機械確認する。

    重複が見つかった場合はSKIPではなくFAILする（将来manifestが変更され、
    偶然にもfreeze済みだったはずのstemがTest/Hard-Valへ移動した場合の
    安全側の検知）。
    """
    print("\n=== Fixture overlap guard (Test/Hard-Val) ===")
    digital_test = _manifest_stems(cfg["digital"]["manifest"], "test")
    drum_test = _manifest_stems(cfg["drum"]["manifest"], "test")
    with (_REPO_ROOT / cfg["drum"]["hard_val_manifest"]).open(encoding="utf-8") as fh:
        drum_hard_val = {r["image_stem"] for r in csv.DictReader(fh)}

    check("digital fixtures do not overlap Test", not (set(cfg["digital"]["stems"]) & digital_test))
    check("drum fixtures do not overlap Test", not (set(cfg["drum"]["stems"]) & drum_test))
    check("drum fixtures do not overlap Hard-Val", not (set(cfg["drum"]["stems"]) & drum_hard_val))


# ---------------------------------------------------------------------------
# Production artifact resolution（read-only）
# ---------------------------------------------------------------------------

def _real_weight_path(cfg_entry: dict) -> Path:
    return _REPO_ROOT / "projects" / cfg_entry["project"] / _WEIGHT_TEMPLATE.format(**cfg_entry)


def _real_selected_model_path(project: str) -> Path:
    return _REPO_ROOT / "projects" / project / "models" / "selected_model.json"


def _check_weight(label: str, cfg_entry: dict) -> Path | None:
    weight = _real_weight_path(cfg_entry)
    if not weight.exists():
        skip(f"[{label}] production weight not available locally ({weight})")
        return None
    actual = sha256_file(weight)
    expected = cfg_entry["weight_sha256"]
    if actual != expected:
        check(f"[{label}] weight SHA256 matches fixture config "
              f"(expected {expected}, got {actual})", False)
        return None
    check(f"[{label}] weight SHA256 matches fixture config", True)
    return weight


def _golden_fixture(label: str, stem: str) -> dict | None:
    if not _GOLDEN_PATH.exists():
        skip(f"[{label}] golden fixture file not found, cannot verify expected reading for {stem}")
        return None
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    for fx in golden["projects"][label]["fixtures"]:
        if fx["stem"] == stem:
            return fx
    check(f"[{label}] golden fixture entry exists for stem {stem} "
          f"(production_smoke_v1.json / golden fixture list must stay in sync)", False)
    return None


def _reading_from_detections(detections: list[dict]) -> str:
    ordered = sorted(detections, key=lambda d: d["x_center"])
    return "".join(str(d["class_id"]) for d in ordered)


# ---------------------------------------------------------------------------
# Image production smoke（実API → prediction_service → predict_worker.py subprocess）
# ---------------------------------------------------------------------------

def _wait_completed(proj: str, job_id: str, timeout: float = 90.0) -> dict:
    """process wait / job status pollingで判定する（固定sleep待ちのみに依存しない）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/projects/{proj}/predict-jobs/{job_id}")
        if r.status_code == 200:
            data = r.json()
            if data.get("status") in ("completed", "failed"):
                return data
        time.sleep(0.3)
    check(f"[{proj}/{job_id}] job completed within {timeout:.0f}s deadline", False)
    return {}


def _run_image_smoke(label: str, cfg_entry: dict) -> None:
    print(f"\n=== {label} image production smoke ===")
    weight = _check_weight(label, cfg_entry)
    if weight is None:
        return

    real_selected_path = _real_selected_model_path(cfg_entry["project"])
    if not real_selected_path.exists():
        skip(f"[{label}] production selected_model.json not available locally")
        return
    real_selected_before = real_selected_path.read_bytes()
    real_selected = json.loads(real_selected_before.decode("utf-8"))
    check(f"[{label}] selected_model.json conf matches fixture config",
          real_selected.get("conf") == cfg_entry["conf"])
    check(f"[{label}] selected_model.json train_job_id matches fixture config",
          real_selected.get("train_job_id") == cfg_entry["train_job_id"])

    source_dir = _REPO_ROOT / cfg_entry["source_dir"]
    stems_available = []
    for stem in cfg_entry["stems"]:
        img = source_dir / f"{stem}.jpg"
        if img.exists():
            stems_available.append(stem)
        else:
            # fixture画像はproduction weightと同じくGit管理外のローカル専用資産のため、
            # 環境によっては個別に欠落しうる。contract違反の証拠ではないためSKIP。
            skip(f"[{label}] fixture image not available locally ({img})")
    if not stems_available:
        skip(f"[{label}] no fixture images available, skipping image smoke")
        return

    proj = f"prodsmoke_{label}"
    r = client.post("/api/projects", json={"name": proj})
    check(f"[{label}] create temp project -> 2xx", r.status_code in (200, 201))

    weight_dst = ROOT / proj / _WEIGHT_TEMPLATE.format(**cfg_entry)
    weight_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(weight, weight_dst)
    (ROOT / proj / "runs" / "train" / cfg_entry["train_job_id"] / "job.json").write_text(
        json.dumps({"job_id": cfg_entry["train_job_id"], "status": "completed"}), encoding="utf-8"
    )

    # production selected_model.jsonの内容をそのままtemp projectへコピーする（read-only利用）。
    # これにより「selected model resolution」を、明示requestではなく実際にproduction同様の
    # 経路（model_registry_service.resolve_train_weight_conf）で解決させる。
    models_dir = ROOT / proj / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "selected_model.json").write_bytes(real_selected_before)

    img_dir = ROOT / proj / "raw" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for stem in stems_available:
        shutil.copy2(source_dir / f"{stem}.jpg", img_dir / f"{stem}.jpg")

    body = {
        "predict_job_name": "smoke_001",
        "source_type": "project_images",
        "image_ids": stems_available,
        # fixture画像は既にIssue #24/#25/#26/#27でproduction前処理済み（resize/grayscale/
        # sharpen適用後）のcopyであるため、ここでpreprocess_mode="selected"を使うと
        # 前処理が二重適用されてしまう（resize済み画像へさらにresize/grayscale/sharpenを
        # 掛け直すことになり、goldenのdetection_count/readingと一致しなくなる）。
        # "none"にすることで、production modelが実際に消費するのと同じ入力（前処理後の
        # 画像そのもの）をそのまま渡す。preprocess自体の適用ロジックはIssue #19の
        # 専用smoke test（smoke_preprocess*.py）で別途検証済み。
        "preprocess_mode": "none",
        "save_txt": False,
        "save_conf": False,
        "overwrite": False,
        # train_job_id/weight_type/confを意図的に省略し、selected model resolutionを実際に通す
    }
    r = client.post(f"/api/projects/{proj}/predict-jobs", json=body)
    check(f"[{label}] start predict job -> 201", r.status_code == 201)

    job = _wait_completed(proj, "smoke_001")
    check(f"[{label}] job completed", job.get("status") == "completed")
    check(f"[{label}] resolution_source all selected_model", job.get("resolution_source") == {
        "train_job_id": "selected_model", "weight_type": "selected_model", "conf": "selected_model",
    })
    check(f"[{label}] resolved conf == fixture conf", job.get("conf") == cfg_entry["conf"])

    ic = job.get("inference_contract")
    check(f"[{label}] inference_contract present", ic is not None)
    check(f"[{label}] contract_version == production-inference-contract-v1",
          ic["contract_version"] == "production-inference-contract-v1")
    check(f"[{label}] ultralytics_version == 8.4.83", ic["ultralytics_version"] == "8.4.83")
    check(f"[{label}] torch_version present", bool(ic.get("torch_version")))
    check(f"[{label}] model.sha256 matches production weight",
          ic["model"]["sha256"] == cfg_entry["weight_sha256"])
    check(f"[{label}] model.train_job_id matches fixture config",
          ic["model"]["train_job_id"] == cfg_entry["train_job_id"])
    ra = ic["resolved_args"]
    for key, expected in {
        "rect": True, "max_det": 300, "agnostic_nms": False,
        "augment": False, "batch": 1, "quantize": None,
    }.items():
        check(f"[{label}] resolved_args.{key} == {expected!r}", ra[key] == expected)
    check(f"[{label}] resolved_args.conf == fixture conf", ra["conf"] == cfg_entry["conf"])
    check(f"[{label}] resolved_args.runtime_device populated (not None)", ra["runtime_device"] is not None)

    r = client.get(f"/api/projects/{proj}/predict-jobs/smoke_001/results")
    check(f"[{label}] get results -> 200", r.status_code == 200)
    results_by_stem = {item["image_id"]: item for item in r.json()["results"]}
    for stem in stems_available:
        golden_fx = _golden_fixture(label, stem)
        if golden_fx is None:
            continue
        item = results_by_stem.get(stem)
        check(f"[{label}] {stem}: result present", item is not None)
        detections = item["detections"]
        reading = _reading_from_detections(detections)
        check(f"[{label}] {stem}: detection_count == golden ({golden_fx['detection_count']})",
              len(detections) == golden_fx["detection_count"])
        check(f"[{label}] {stem}: reading == golden ({golden_fx['reading']}) "
              f"[production smoke expected output, not a Val/Test accuracy claim]",
              reading == golden_fx["reading"])

    check(f"[{label}] production selected_model.json unchanged after smoke",
          real_selected_path.read_bytes() == real_selected_before)


# ---------------------------------------------------------------------------
# Video production smoke（mock camera、predict_video_worker.pyの実worker経路）
# ---------------------------------------------------------------------------

def _run_video_smoke(cfg: dict) -> None:
    label = cfg["video_smoke_project"]
    cfg_entry = cfg[label]
    print(f"\n=== video production smoke ({label}, mock camera, real worker) ===")

    weight = _check_weight(f"{label}-video", cfg_entry)
    if weight is None:
        return

    real_selected_path = _real_selected_model_path(cfg_entry["project"])
    if not real_selected_path.exists():
        skip(f"[{label}-video] production selected_model.json not available locally")
        return
    real_selected_before = real_selected_path.read_bytes()
    real_selected = json.loads(real_selected_before.decode("utf-8"))
    profile = real_selected.get("preprocess_profile")
    check(f"[{label}-video] production preprocess_profile present", profile is not None)

    import numpy as np  # noqa: PLC0415  (weight/selected_model確認後の遅延import)
    import cv2  # noqa: PLC0415

    tmp = Path(tempfile.mkdtemp(prefix="yts_prod_smoke_video_"))
    job_json = tmp / "job.json"
    live_dir = tmp / "live"
    weight_dst = tmp / "best.pt"
    shutil.copy2(weight, weight_dst)
    pre_path = tmp / "preprocess.json"
    pre_path.write_text(json.dumps(profile), encoding="utf-8")

    job_json.write_text(json.dumps({
        "video_job_id": "smoke_video", "train_job_id": cfg_entry["train_job_id"],
        "weight_type": cfg_entry["weight_type"], "status": "queued",
    }), encoding="utf-8")

    class _FakeCap:
        """実カメラを使わず、実解像度相当の合成フレームを返すモック（Issue #32）。

        目的はROI等の実preprocessを正しく通すことであり、精度確認ではない。
        """

        def __init__(self) -> None:
            self._frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            self._frame[:, :, 1] = 90

        def isOpened(self) -> bool:
            return True

        def read(self):
            return True, self._frame.copy()

        def set(self, *args, **kwargs) -> bool:
            return True

        def release(self) -> None:
            pass

    orig_open_camera = predict_video_worker._open_camera
    predict_video_worker._open_camera = lambda cv2mod, source_type, source: _FakeCap()  # noqa: ARG005

    sys.argv = [
        "predict_video_worker.py",
        "--job-json", str(job_json),
        "--live-dir", str(live_dir),
        "--weight", str(weight_dst),
        "--backend-dir", str(_BACKEND_DIR),
        "--source-type", "camera",
        "--source", "0",
        "--video-fps", "5",
        "--infer-fps", "5",
        "--conf", str(cfg_entry["conf"]),
        "--iou", "0.7",
        "--imgsz", "640",
        "--device", "auto",
        "--preprocess-json", str(pre_path),
    ]

    try:
        t = threading.Thread(target=predict_video_worker.main, daemon=True)
        t.start()

        deadline = time.time() + 60
        ic = None
        while time.time() < deadline:
            time.sleep(0.3)
            try:
                data = json.loads(job_json.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                continue
            cand = data.get("inference_contract")
            if cand and cand.get("initial_resolved_args", {}).get("runtime_device"):
                ic = cand
                break
        check("video smoke: inference_contract populated (incl. runtime_device) within deadline", ic is not None)

        (live_dir.parent / "stop.flag").write_text("stop", encoding="utf-8")
        t.join(timeout=15)
    finally:
        predict_video_worker._open_camera = orig_open_camera

    if ic is not None:
        check("video smoke: contract_version == production-inference-contract-v1",
              ic["contract_version"] == "production-inference-contract-v1")
        check("video smoke: model.sha256 matches production weight",
              ic["model"]["sha256"] == cfg_entry["weight_sha256"])
        check("video smoke: initial_resolved_args.conf == fixture conf",
              ic["initial_resolved_args"]["conf"] == cfg_entry["conf"])
        check("video smoke: current_resolved_args present", "current_resolved_args" in ic)
        check("video smoke: current_resolved_args pinned rect still True",
              ic["current_resolved_args"]["rect"] is True)

    try:
        data = json.loads(job_json.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        data = {}
    check("video smoke: job stopped cleanly", data.get("status") == "stopped")

    check(f"[{label}-video] production selected_model.json unchanged after smoke",
          real_selected_path.read_bytes() == real_selected_before)

    shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    cfg = _load_config()
    _overlap_guard(cfg)
    _run_image_smoke("digital", cfg["digital"])
    _run_image_smoke("drum", cfg["drum"])
    _run_video_smoke(cfg)
    print(f"\n{_PASS} passed, {_FAIL} failed, {_SKIP} skipped")
    print("\nALL PRODUCTION INTEGRATION SMOKE TESTS PASSED (or safely skipped)")


if __name__ == "__main__":
    main()
