"""Ultralytics依存更新前後のenvironment snapshotを記録する（read-only）。

docs/ULTRALYTICS_UPGRADE_PROCEDURE.md の「pre-upgrade snapshot」用。
production model・selected_model.json・contract関連ファイルは一切変更しない。

使い方:
    .venv\\Scripts\\python.exe scripts\\capture_upgrade_snapshot.py > snapshot_before.md
    (依存を更新した後)
    .venv\\Scripts\\python.exe scripts\\capture_upgrade_snapshot.py > snapshot_after.md

出力はMarkdown。差分比較は diff / git diff --no-index 等で行う想定。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_GOLDEN_PATH = _REPO_ROOT / "backend" / "tests" / "fixtures" / "production_inference_contract_golden_v1.json"

_SELECTED_MODEL_PATHS = {
    "digital": _REPO_ROOT / "projects" / "meter_src002" / "models" / "selected_model.json",
    "drum": _REPO_ROOT / "projects" / "meter_src004" / "models" / "selected_model.json",
}
_WEIGHT_PATHS = {
    "digital": _REPO_ROOT / "projects/meter_src002/runs/train/production_combined_v2_5z/weights/best.pt",
    "drum": _REPO_ROOT / "projects/meter_src004/runs/train/candidate_roi_v3_5/weights/best.pt",
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True
        ).strip()
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"


def package_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for mod_name, attr in [
        ("ultralytics", "__version__"),
        ("torch", "__version__"),
        ("torchvision", "__version__"),
        ("torchaudio", "__version__"),
        ("numpy", "__version__"),
        ("cv2", "__version__"),
        ("PIL", "__version__"),
        ("onnx", "__version__"),
        ("onnxruntime", "__version__"),
        ("onnxslim", "__version__"),
    ]:
        try:
            mod = __import__(mod_name)
            out[mod_name] = str(getattr(mod, attr, "unknown"))
        except Exception as exc:  # noqa: BLE001
            out[mod_name] = f"IMPORT_ERROR: {exc}"
    return out


def cuda_info() -> dict[str, str]:
    try:
        import torch  # noqa: PLC0415

        available = torch.cuda.is_available()
        return {
            "cuda_version": str(torch.version.cuda),
            "cuda_available": str(available),
            "gpu": torch.cuda.get_device_name(0) if available else "(none)",
        }
    except Exception as exc:  # noqa: BLE001
        return {"cuda_version": "unknown", "cuda_available": "unknown", "gpu": f"IMPORT_ERROR: {exc}"}


def python_version() -> str:
    import platform  # noqa: PLC0415

    return platform.python_version()


def contract_info() -> dict[str, object]:
    if not _GOLDEN_PATH.exists():
        return {"contract_version": "(golden fixture not found)", "generation_environment": {}}
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    return {
        "contract_version": golden.get("contract_version"),
        "generation_environment": golden.get("generation_environment", {}),
    }


def production_artifacts() -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for label, weight_path in _WEIGHT_PATHS.items():
        selected_model_path = _SELECTED_MODEL_PATHS[label]
        entry: dict[str, object] = {}
        entry["weight_path"] = str(weight_path.relative_to(_REPO_ROOT))
        entry["weight_exists"] = weight_path.exists()
        entry["weight_sha256"] = sha256_file(weight_path) if weight_path.exists() else "(not found)"
        if selected_model_path.exists():
            entry["selected_model"] = json.loads(selected_model_path.read_text(encoding="utf-8"))
        else:
            entry["selected_model"] = "(not found)"
        out[label] = entry
    return out


def main() -> None:
    print("# Ultralytics upgrade snapshot\n")
    print(f"- captured_at (UTC not tracked; use file mtime / git commit time as reference)")
    print(f"- git HEAD: `{git_head()}`")

    contract = contract_info()
    print(f"- contract version: `{contract['contract_version']}`")
    print(f"- golden fixture generation_environment: `{json.dumps(contract['generation_environment'], ensure_ascii=False)}`")

    print("\n## Installed package versions\n")
    for name, version in package_versions().items():
        print(f"- {name}: `{version}`")

    print("\n## CUDA / GPU\n")
    for k, v in cuda_info().items():
        print(f"- {k}: `{v}`")
    print(f"- python: `{python_version()}`")

    print("\n## Production artifacts\n")
    for label, entry in production_artifacts().items():
        print(f"### {label}\n")
        print(f"- weight_path: `{entry['weight_path']}`")
        print(f"- weight_exists: `{entry['weight_exists']}`")
        print(f"- weight_sha256: `{entry['weight_sha256']}`")
        print(f"- selected_model.json: `{json.dumps(entry['selected_model'], ensure_ascii=False)}`")
        print()

    print("## Next step\n")
    print("依存を変更した後、同じコマンドを再実行し、本snapshotとの差分を確認すること。")
    print("その後 `backend/tests/smoke_inference_contract.py` と backend smoke suite全体を実行すること。")


if __name__ == "__main__":
    main()
