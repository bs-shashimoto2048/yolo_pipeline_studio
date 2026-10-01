"""共通スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """汎用メッセージ応答。"""

    message: str


class StubResponse(BaseModel):
    """未実装スタブ用の応答。"""

    status: str = "not_implemented"
    feature: str
    message: str


class ServerInfo(BaseModel):
    """フロントエンドがshared server mode向けUI（名前入力・queue表示等）を
    出し分けるためのフラグ（Issue #49）。認証情報は含まない。"""

    shared_server_mode: bool
