"""学習時オーギュメンテーション・プリセット管理。

builtin（none/light/standard/strong）はコード内に持ち、ファイルが無くても返す。
ユーザープリセットは augmentation/presets/{name}.json に保存する。
params は Ultralytics の train 引数として渡す値。範囲外は 400。
"""

from __future__ import annotations

import json
import re

from ..core import paths
from ..schemas.augmentation import PresetItem, PresetListResponse, PresetSave
from .project_service import ProjectError, project_exists

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# (min, max, standardデフォルト, int?)
AUG_SPEC: dict[str, tuple[float, float | None, float, bool]] = {
    "degrees": (0.0, 180.0, 5.0, False),
    "translate": (0.0, 1.0, 0.1, False),
    "scale": (0.0, 2.0, 0.5, False),
    "shear": (0.0, 45.0, 0.0, False),
    "perspective": (0.0, 0.001, 0.0, False),
    "flipud": (0.0, 1.0, 0.0, False),
    "fliplr": (0.0, 1.0, 0.5, False),
    "mosaic": (0.0, 1.0, 1.0, False),
    "mixup": (0.0, 1.0, 0.0, False),
    "copy_paste": (0.0, 1.0, 0.0, False),
    "hsv_h": (0.0, 1.0, 0.015, False),
    "hsv_s": (0.0, 1.0, 0.7, False),
    "hsv_v": (0.0, 1.0, 0.4, False),
    "close_mosaic": (0, None, 10, True),
}

BUILTIN_PRESETS: dict[str, dict] = {
    "none": {
        "description": "オーギュメンテーションを最小限にする設定",
        "params": {
            "degrees": 0.0, "translate": 0.0, "scale": 0.0, "shear": 0.0,
            "perspective": 0.0, "flipud": 0.0, "fliplr": 0.0, "mosaic": 0.0,
            "mixup": 0.0, "copy_paste": 0.0, "hsv_h": 0.0, "hsv_s": 0.0,
            "hsv_v": 0.0, "close_mosaic": 0,
        },
    },
    "light": {
        "description": "製造業画像向けの軽い拡張設定",
        "params": {
            "degrees": 3.0, "translate": 0.05, "scale": 0.2, "shear": 0.0,
            "perspective": 0.0, "flipud": 0.0, "fliplr": 0.0, "mosaic": 0.5,
            "mixup": 0.0, "copy_paste": 0.0, "hsv_h": 0.01, "hsv_s": 0.3,
            "hsv_v": 0.2, "close_mosaic": 10,
        },
    },
    "standard": {
        "description": "YOLO学習向けの標準的な拡張設定",
        "params": {
            "degrees": 5.0, "translate": 0.1, "scale": 0.5, "shear": 0.0,
            "perspective": 0.0, "flipud": 0.0, "fliplr": 0.5, "mosaic": 1.0,
            "mixup": 0.0, "copy_paste": 0.0, "hsv_h": 0.015, "hsv_s": 0.7,
            "hsv_v": 0.4, "close_mosaic": 10,
        },
    },
    "strong": {
        "description": "画像条件のばらつきが大きい場合の強めの拡張設定",
        "params": {
            "degrees": 10.0, "translate": 0.15, "scale": 0.7, "shear": 2.0,
            "perspective": 0.0005, "flipud": 0.0, "fliplr": 0.5, "mosaic": 1.0,
            "mixup": 0.1, "copy_paste": 0.0, "hsv_h": 0.015, "hsv_s": 0.7,
            "hsv_v": 0.4, "close_mosaic": 10,
        },
    },
}


class AugmentationError(Exception):
    pass


class AugmentationNotFoundError(AugmentationError):
    """404相当。"""


class AugmentationValidationError(AugmentationError):
    """400相当。"""


class AugmentationConflictError(AugmentationError):
    """409相当。"""


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def standard_params() -> dict:
    return dict(BUILTIN_PRESETS["standard"]["params"])


def validate_params(params: dict) -> dict:
    """既知キーの範囲を検証し、正規化（int化など）した dict を返す。違反は 400。"""
    out: dict = {}
    for key, value in params.items():
        if key not in AUG_SPEC:
            continue  # 未知キーは無視
        lo, hi, _default, is_int = AUG_SPEC[key]
        try:
            num = int(value) if is_int else float(value)
        except (TypeError, ValueError) as e:
            raise AugmentationValidationError(f"{key} が数値ではありません。") from e
        if is_int and num < 0:
            raise AugmentationValidationError(f"{key} は0以上の整数にしてください。")
        if not is_int:
            if num < lo or (hi is not None and num > hi):
                raise AugmentationValidationError(
                    f"{key}={num} が範囲外です（{lo}〜{hi}）。"
                )
        out[key] = num
    return out


def _full_params(partial: dict) -> dict:
    """standardデフォルトで欠損を埋めた全14キーの dict を返す。"""
    full = standard_params()
    full.update(partial)
    return full


def _user_preset_path(name: str, preset_name: str):
    return paths.augmentation_presets_dir(name) / f"{preset_name}.json"


def list_presets(name: str) -> PresetListResponse:
    _require_project(name)
    presets: list[PresetItem] = []
    for pname, spec in BUILTIN_PRESETS.items():
        presets.append(PresetItem(
            name=pname, description=spec["description"],
            params=dict(spec["params"]), builtin=True,
        ))
    pdir = paths.augmentation_presets_dir(name)
    if pdir.exists():
        for f in sorted(pdir.glob("*.json")):
            if f.stem in BUILTIN_PRESETS:
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                continue
            presets.append(PresetItem(
                name=data.get("name", f.stem),
                description=data.get("description", ""),
                params=data.get("params", {}) or {},
                builtin=False,
            ))
    return PresetListResponse(project_name=name, presets=presets)


def get_preset(name: str, preset_name: str) -> PresetItem:
    _require_project(name)
    if preset_name in BUILTIN_PRESETS:
        spec = BUILTIN_PRESETS[preset_name]
        return PresetItem(name=preset_name, description=spec["description"],
                          params=dict(spec["params"]), builtin=True)
    path = _user_preset_path(name, preset_name)
    if not path.exists():
        raise AugmentationNotFoundError(f"プリセット '{preset_name}' が見つかりません。")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return PresetItem(
        name=data.get("name", preset_name),
        description=data.get("description", ""),
        params=data.get("params", {}) or {},
        builtin=False,
    )


def save_preset(name: str, preset_name: str, payload: PresetSave) -> PresetItem:
    _require_project(name)
    if not _NAME_RE.match(preset_name):
        raise AugmentationValidationError(
            "プリセット名は英数・アンダースコア・ハイフンのみです。"
        )
    if preset_name in BUILTIN_PRESETS:
        raise AugmentationConflictError(
            f"'{preset_name}' は builtin プリセットのため上書きできません。"
        )
    validated = validate_params(payload.params)
    pdir = paths.augmentation_presets_dir(name)
    pdir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": preset_name,
        "description": payload.description,
        "params": validated,
        "builtin": False,
    }
    _user_preset_path(name, preset_name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return PresetItem(name=preset_name, description=payload.description,
                      params=validated, builtin=False)


def delete_preset(name: str, preset_name: str) -> None:
    _require_project(name)
    if preset_name in BUILTIN_PRESETS:
        raise AugmentationValidationError(
            f"'{preset_name}' は builtin プリセットのため削除できません。"
        )
    path = _user_preset_path(name, preset_name)
    if not path.exists():
        raise AugmentationNotFoundError(f"プリセット '{preset_name}' が見つかりません。")
    path.unlink()


def resolve(name: str, preset_name: str | None, overrides: dict | None) -> tuple[str, dict]:
    """学習用に (使用プリセット名, 全paramsのdict) を返す。

    - preset指定なし → standard
    - preset指定あり → そのプリセット（builtin/user）。見つからなければ 400。
    - overrides があれば preset値の上で上書き（検証済み）。
    """
    used = preset_name or "standard"
    if preset_name:
        try:
            base = get_preset(name, preset_name).params
        except AugmentationNotFoundError as e:
            raise AugmentationValidationError(
                f"プリセット '{preset_name}' が見つかりません。"
            ) from e
    else:
        base = standard_params()

    params = _full_params(base)
    if overrides:
        params.update(validate_params(overrides))
    return used, params
