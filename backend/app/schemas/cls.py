"""クラス設計関連スキーマ。

task.md「5. クラス設計機能」: クラスIDは 0 から自動採番。並び替え禁止。
Issue 011: クラスごとに表示色(color, #RRGGBB)を持つ。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassItem(BaseModel):
    """1クラス分の定義。"""

    id: int = Field(..., ge=0, description="クラスID（0始まり）")
    name: str = Field(..., description="クラス名", examples=["ct_h"])
    color: str = Field("#1677ff", description="表示色（#RRGGBB）")


class ClassListResponse(BaseModel):
    """クラス一覧応答。"""

    classes: list[ClassItem]


class ClassInput(BaseModel):
    """保存時の1クラス入力（colorは省略時に自動採番）。"""

    name: str
    color: str | None = None


class ClassListUpdate(BaseModel):
    """クラス定義の保存リクエスト。

    既存ラベルとの不整合を防ぐため、IDの振り直しはサーバ側で 0..n-1 に正規化する。
    color 省略時はパレットから自動割当する。
    後方互換: 旧形式の `names: [..]`（文字列配列）でも受け付ける。
    """

    classes: list[ClassInput] = Field(
        default_factory=list,
        description="クラス定義の配列（並び順がそのままIDになる）",
    )
    names: list[str] | None = Field(
        default=None, description="後方互換: クラス名の配列（color自動割当）"
    )

    def to_inputs(self) -> list[ClassInput]:
        if self.classes:
            return self.classes
        if self.names:
            return [ClassInput(name=n) for n in self.names]
        return []
