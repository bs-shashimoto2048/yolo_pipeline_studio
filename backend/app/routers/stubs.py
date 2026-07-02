"""未実装工程のスタブルーター。

骨組み段階では各工程のエンドポイントを登録だけしておき、501 を返す。
フロントの画面遷移・API疎通確認に使う。実装時にここから個別モジュールへ
切り出していく。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.common import StubResponse

# (path接尾辞, タグ, 表示名) の定義。task.md の工程に対応。
# 全工程が実ルーターへ移行済み。スタブは無し（構造は将来工程の追加用に残す）。
_STUB_FEATURES: list[tuple[str, str, str]] = []


def _make_router(suffix: str, tag: str, label: str) -> APIRouter:
    r = APIRouter(prefix=f"/api/projects/{{name}}/{suffix}", tags=[tag])

    @r.get("", response_model=StubResponse)
    def _stub(name: str) -> StubResponse:  # noqa: ARG001 - nameはルート整合用
        raise HTTPException(
            status_code=501,
            detail=f"'{label}' は未実装です（骨組み段階）。",
        )

    return r


def all_stub_routers() -> list[APIRouter]:
    return [_make_router(s, t, l) for s, t, l in _STUB_FEATURES]
