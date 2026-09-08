"""画像選別関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class SelectionRunRequest(BaseModel):
    """画像選別チェック実行リクエスト。

    mode が正式仕様（Issue #11 Checkpoint 3）:
      - "diff": 既存 selection.json の manual/unknown 判定を保持したまま、
        新規画像だけを自動判定で追加し、削除済み画像を除去する（既定・安全）。
      - "full": 全件を自動判定で再構築する（manual/unknown を含め status_source
        は auto に正規化される。破壊的操作のため呼び出し側で明示確認が必要）。

    overwrite は旧仕様の互換フィールド（非推奨）。mode 未指定時のみ参照され、
    overwrite=true は "full"、overwrite=false は「未作成なら full・既存なら
    409衝突」という旧挙動にマッピングされる。新規呼び出しは mode を使うこと。
    """

    source: str = "auto"  # raw | processed | auto
    min_width: int = 320
    min_height: int = 320
    blur_threshold: float = 80.0
    dark_threshold: float = 30.0
    bright_threshold: float = 240.0
    detect_duplicates: bool = True
    mode: str | None = None  # "diff" | "full"（正式仕様。省略時は overwrite から解決）
    overwrite: bool | None = None  # 非推奨（後方互換用）。新規呼び出しでは mode を使うこと


class SelectionItem(BaseModel):
    image_id: str
    image_name: str
    source: str
    width: int
    height: int
    status: str  # included | review（旧excludedのデータが残っている場合のみ表示上あり得る）
    # 判定の由来。auto=直近の自動判定、manual=利用者が明示的に変更、
    # unknown=この項目が作られた時点でstatus_sourceの概念が無かった旧データ
    # （読み込み時にキーが無ければPydanticの既定値でunknownになる＝暗黙のマイグレーション）。
    # diff更新では manual/unknown を保護（上書きしない）、full再構築では全件を
    # auto へ正規化する（Issue #11 Checkpoint 2 修正指摘に基づく）。
    status_source: str = "unknown"
    warnings: list[str] = []
    reasons: list[str] = []
    hash: str | None = None
    brightness_mean: float | None = None
    blur_score: float | None = None
    duplicate_of: str | None = None
    manual_reason: str | None = None
    updated_at: str | None = None  # このitemが最後に(自動/手動/reset問わず)更新された時刻


class SelectionSummary(BaseModel):
    image_count: int = 0
    included_count: int = 0
    excluded_count: int = 0
    review_count: int = 0
    duplicate_count: int = 0
    small_count: int = 0
    dark_count: int = 0
    bright_count: int = 0
    blur_count: int = 0


class SelectionJobStatus(BaseModel):
    """画像選別の非同期実行ジョブの状態（別プロセスのワーカーが更新する）。

    7,000枚規模でも同期HTTPリクエストをブロックしないよう、実行(run)は
    subprocess.Popenで起動したワーカーへ委譲し、job.jsonのポーリングで
    進捗・完了を確認する（capture/predict等の既存ジョブパターンと同じ方式）。
    """

    status: str = "unknown"  # queued | running | completed | failed
    mode: str | None = None  # diff | full
    source: str | None = None
    message: str | None = None
    total_count: int = 0
    processed_count: int = 0
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None


class SelectionRunResponse(BaseModel):
    """run開始直後の応答（非同期化により、完了を待たずジョブ情報を返す）。"""

    project_name: str
    selection_path: str
    job: SelectionJobStatus


class SelectionGetResponse(BaseModel):
    project_name: str
    source: str
    created_at: str | None = None
    summary: SelectionSummary
    items: list[SelectionItem]
    # 鮮度情報（PILデコードを伴わない軽量なディレクトリ走査のみで算出）
    current_image_count: int = 0
    new_image_count: int = 0
    missing_image_count: int = 0
    is_stale: bool = False
    # 直近/実行中のrunジョブ状態（一度もrunしていなければ null）
    job: SelectionJobStatus | None = None


class SelectionStatusUpdate(BaseModel):
    status: str
    manual_reason: str | None = None


class SelectionStatusResponse(BaseModel):
    image_id: str
    status: str
    status_source: str
    manual_reason: str | None = None


class SelectionResetResponse(BaseModel):
    """reset-to-auto: 単一画像の判定を自動判定へ戻した結果。"""

    item: SelectionItem


class SelectionRotateRequest(BaseModel):
    source: str = "processed"
    angle: int = 90  # 90 | -90 | 180


class SelectionRotateResponse(BaseModel):
    image_id: str
    source: str
    angle: int
    width: int
    height: int
    warning: str | None = None


class SelectionDeleteResponse(BaseModel):
    """画像削除の結果（raw/processed/サムネイル/ラベルのうち実際に消えたものの一覧）。"""

    image_id: str
    deleted_files: list[str]
