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
    # LAN公開時もフロントエンド(Vite dev server, host: true)が同一オリジンで
    # /api をプロキシするため、ブラウザからはCORSが一切関与しない
    # （Vite→backendはサーバー間通信でブラウザのCORS制約対象外）。
    # そのためshared server mode向けにこの一覧を広げる必要はない(Issue #49 §57-60)。
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Issue #49: 複数ユーザーがLAN経由で同時利用するshared server mode。
    # 未設定(false)時は既存の1ユーザー利用のまま（挙動に一切変更なし、opt-in）。
    shared_server_mode: bool = os.environ.get(
        "YTS_SHARED_SERVER_MODE", ""
    ).strip().lower() in ("1", "true", "yes")

    # shared server mode時のqueue投入上限（config化、Issue #49 §28/§30）
    max_queued_jobs_per_user: int = int(
        os.environ.get("YTS_MAX_QUEUED_JOBS_PER_USER", "2")
    )
    max_queued_jobs_global: int = int(
        os.environ.get("YTS_MAX_QUEUED_JOBS_GLOBAL", "20")
    )

    # 学習ジョブ開始前の最低空きディスク容量チェック（バイト、Issue #49 §54）
    train_min_free_disk_bytes: int = int(
        os.environ.get("YTS_TRAIN_MIN_FREE_DISK_BYTES", str(2 * 1024 * 1024 * 1024))
    )

    # 取り込み対応画像形式（マスター）。フォルダ取り込みはこの範囲内で選択させる。
    allowed_image_suffixes: tuple[str, ...] = (
        ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    )

    # サムネイル最大辺
    thumbnail_max_size: int = 256

    # 解像度警告のしきい値（最小辺がこれ未満なら警告）
    min_resolution_warn: int = 320


settings = Settings()
