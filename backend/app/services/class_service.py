"""クラス設計の読み書き。

classes.yaml は Issue 011 以降、表示色付きのリスト形式で保存する:

    classes:
      - id: 0
        name: ct_h
        color: "#ff4d4f"

旧形式（`names: {0: ct_h}`）も後方互換で読み込み、color は自動補完する。
IDは並び順から 0..n-1 を自動採番する。
"""

from __future__ import annotations

import re

import yaml

from ..core import paths
from ..schemas.cls import ClassInput, ClassItem
from .project_service import ProjectError, project_exists

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 自動割当用パレット（id順に循環）
DEFAULT_COLORS = [
    "#ff4d4f", "#1677ff", "#52c41a", "#faad14", "#722ed1",
    "#13c2c2", "#eb2f96", "#a0d911", "#fa8c16", "#2f54eb",
]


def _auto_color(idx: int) -> str:
    return DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]


def _require_project(name: str) -> None:
    if not project_exists(name):
        raise ProjectError(f"プロジェクト '{name}' が見つかりません。")


def get_classes(name: str) -> list[ClassItem]:
    _require_project(name)
    path = paths.classes_yaml(name)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f) or {}

    items: list[ClassItem] = []
    if isinstance(data.get("classes"), list):
        for c in data["classes"]:
            cid = int(c["id"])
            color = c.get("color")
            if not color or not _COLOR_RE.match(str(color)):
                color = _auto_color(cid)
            items.append(ClassItem(id=cid, name=str(c["name"]), color=color))
    else:
        # 旧形式: names: {id: name}
        names = data.get("names", {}) or {}
        for k, v in names.items():
            cid = int(k)
            items.append(ClassItem(id=cid, name=str(v), color=_auto_color(cid)))

    items.sort(key=lambda c: c.id)
    return items


def save_classes(name: str, classes: list[ClassInput]) -> list[ClassItem]:
    """クラス定義を 0..n-1 で採番して保存する。color は検証/自動割当。"""
    _require_project(name)

    cleaned: list[ClassInput] = [
        c for c in classes if c.name and c.name.strip()
    ]
    names = [c.name.strip() for c in cleaned]
    if len(set(names)) != len(names):
        raise ProjectError("クラス名が重複しています。")

    result: list[ClassItem] = []
    for i, c in enumerate(cleaned):
        color = (c.color or "").strip()
        if color:
            if not _COLOR_RE.match(color):
                raise ProjectError(
                    f"color は #RRGGBB 形式で指定してください: '{color}'"
                )
        else:
            color = _auto_color(i)
        result.append(ClassItem(id=i, name=names[i], color=color))

    payload = {
        "classes": [
            {"id": c.id, "name": c.name, "color": c.color} for c in result
        ]
    }
    with paths.classes_yaml(name).open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

    return result
