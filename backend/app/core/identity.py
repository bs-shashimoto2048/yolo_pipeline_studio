"""リクエストのuser identity解決（Issue #49）。

Phase 1ではenterprise authenticationを導入しない。HTTPヘッダ（X-YTS-User-Id /
X-YTS-Display-Name）のみを信頼する簡易実装であり、これは**セキュリティ認証では
なくjob/project所有者識別用**（Issue #49 §7/§81、trusted LAN use onlyが前提）。

将来AD/Microsoft Entra ID/LDAP/SSOへ差し替える場合は、この関数の中身だけを
置き換えれば呼び出し側（routers層）には影響しない（Issue #49 §8）。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Header


@dataclass
class UserIdentity:
    user_id: str | None
    display_name: str | None


def get_current_user(
    x_yts_user_id: str | None = Header(default=None, alias="X-YTS-User-Id"),
    x_yts_display_name: str | None = Header(default=None, alias="X-YTS-Display-Name"),
) -> UserIdentity:
    """現在のリクエストのuser identityを解決するFastAPI依存関数。

    ヘッダ未送信時（local mode、またはshared mode未対応の旧クライアント）は
    user_id/display_name共にNoneとなり、既存の「所有者情報なし」の挙動と一致する。

    HTTPヘッダ値はASCII以外を直接格納できないため、display_nameは
    フロントエンド側でencodeURIComponent()されている前提でunquote()する
    （「橋本」等の日本語表示名を想定、Issue #49 §7）。
    """
    return UserIdentity(
        user_id=x_yts_user_id,
        display_name=unquote(x_yts_display_name) if x_yts_display_name else None,
    )
