"""学習時オーギュメンテーション関連スキーマ。

params は Ultralytics の train 引数名（degrees / translate / ... / close_mosaic）。
範囲検証はサービス側で行い、違反は 400。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PresetSave(BaseModel):
    """プリセット保存リクエスト。"""

    description: str = ""
    params: dict[str, Any] = {}


class PresetItem(BaseModel):
    """プリセット1件。"""

    name: str
    description: str = ""
    params: dict[str, Any]
    builtin: bool = False


class PresetListResponse(BaseModel):
    project_name: str
    presets: list[PresetItem]
