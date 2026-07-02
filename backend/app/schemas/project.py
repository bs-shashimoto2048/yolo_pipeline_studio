"""プロジェクト関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """プロジェクト作成リクエスト。"""

    name: str = Field(
        ...,
        description="プロジェクト名（英数・アンダースコア・ハイフンのみ）",
        examples=["switchboard_parts"],
    )
    description: str = Field("", description="任意の説明")
    task: str = Field(
        "detect",
        description="タスク種別: detect（物体検出/bbox） または segment（セグメンテーション/polygon）",
    )


class ProjectSummary(BaseModel):
    """プロジェクト概要（一覧・詳細共通）。"""

    name: str
    description: str = ""
    task: str = "detect"  # detect | segment（未定義の既存案件は detect 扱い）
    created_at: str | None = None
    image_count: int = 0
    label_count: int = 0
    class_count: int = 0
    train_count: int = 0  # 学習回数（実験数）
