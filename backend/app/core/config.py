"""アプリ全体の設定。

環境変数 ``YTS_PROJECTS_ROOT`` で案件データの格納先を上書きできる。
未指定の場合はリポジトリ直下の ``projects/`` を使う。
"""

from __future__ import annotations

import os
from pathlib import Path

# このファイル: backend/app/core/config.py → リポジトリルートは3つ上
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings:
    """アプリ設定。"""

    app_name: str = "YOLO Tuning Studio"
    version: str = "0.1.0"

    # 案件データ（画像・ラベル・学習結果）の格納先
    projects_root: Path = Path(
        os.environ.get("YTS_PROJECTS_ROOT", str(REPO_ROOT / "projects"))
    ).resolve()

    # 開発フロントエンドの許可オリジン（CORS）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 取り込み対応画像形式（マスター）。フォルダ取り込みはこの範囲内で選択させる。
    allowed_image_suffixes: tuple[str, ...] = (
        ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    )

    # サムネイル最大辺
    thumbnail_max_size: int = 256

    # 解像度警告のしきい値（最小辺がこれ未満なら警告）
    min_resolution_warn: int = 320


settings = Settings()
