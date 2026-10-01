"""カメラ/URL映像からの静止画撮影（プロジェクト準備・画像取り込み用）関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class CaptureTarget(BaseModel):
    """targeted capture（Issue #41）: 不足しているdigit position/classを計画的に
    収集するための「収集意図」メタデータ。GTを自動確定するものではない
    （targetはあくまで撮影者の意図であり、後で人手確認する。§8）。"""

    digit_position: int | None = None  # 0-indexed
    target_class: str | None = None  # 1文字（"0"-"9"）を想定するが型は緩くstrのまま


class CaptureSessionCreate(BaseModel):
    session_name: str
    source_type: str = "camera"  # camera | url
    camera_index: int = 0
    source_url: str | None = None  # source_type=url のとき使用
    video_fps: int = 10  # プレビュー表示FPS
    interval_minutes: float | None = None  # 自動撮影間隔（分）。未指定/0以下なら手動撮影のみ
    overwrite: bool = False
    # --- Issue #41: targeted rare-class capture（既存capture機能との後方互換のため
    # 全てoptional。未指定の既存クライアント/既存job.jsonは従来通り動作する）。
    purpose: str | None = None  # 例: "rare_class_collection"
    target: CaptureTarget | None = None
    max_frames: int | None = None  # 指定時、この枚数に達したら自動停止（連写水増し防止、§9）


class CaptureSessionInfo(BaseModel):
    project_name: str | None = None
    session_id: str
    source_type: str | None = None
    camera_index: int | None = None
    source_url: str | None = None  # 表示用（password等の認証情報はマスク済み。実接続はサーバー内部のjob.jsonのraw値を使う）
    resolved_source_url: str | None = None  # 同上（表示用マスク済み）
    video_fps: int | None = None
    interval_minutes: float | None = None
    status: str = "unknown"  # queued | running | stopped | failed | completed
    message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    captured_count: int = 0
    last_captured_at: str | None = None
    last_captured_filename: str | None = None
    next_auto_capture_at: str | None = None  # 自動撮影が有効なときの次回撮影予定時刻
    stream_url: str | None = None
    purpose: str | None = None
    target: CaptureTarget | None = None
    max_frames: int | None = None


class CaptureFrameMetadata(BaseModel):
    """targeted capture session内の1枚ごとの記録（Issue #41 §7）。GTではなく
    「どういう意図・条件で撮られたか」の記録であることに注意（§8）。"""

    stem: str
    captured_at: str
    source: str  # session_id（logical ID。camera credential/URLは含めない、§29）
    target_digit_position: int | None = None
    target_class: str | None = None
    frame_index: int = 0
    review_status: str = "unreviewed"  # unreviewed|accepted|rejected_duplicate|rejected_ambiguous|rejected_wrong_target
    note: str | None = None


class CaptureFrameListResponse(BaseModel):
    project_name: str
    session_id: str
    frames: list[CaptureFrameMetadata]


class CaptureFrameReviewUpdate(BaseModel):
    review_status: str
    note: str | None = None


# --- Issue #42: targeted capture review workflow ---


class CaptureReviewSummary(BaseModel):
    """targeted capture 1 sessionぶんのreview進捗サマリ。"""

    session_id: str
    purpose: str | None = None
    target: CaptureTarget | None = None
    status: str = "unknown"
    created_at: str | None = None
    captured_count: int = 0
    unreviewed_count: int = 0
    accepted_count: int = 0
    rejected_duplicate_count: int = 0
    rejected_ambiguous_count: int = 0
    rejected_wrong_target_count: int = 0


class CaptureReviewSummaryListResponse(BaseModel):
    project_name: str
    sessions: list[CaptureReviewSummary]


class CaptureFrameDuplicateVerdict(BaseModel):
    stem: str
    verdict: str  # "no_overlap" | "near_duplicate"
    duplicate_splits: list[str] = []  # 例: ["train"], ["test"] 。Test内容自体は返さない


class CaptureDuplicateAuditResponse(BaseModel):
    session_id: str
    manifest_path: str
    gt_position: int | None = None
    results: list[CaptureFrameDuplicateVerdict]


class CaptureTargetProgress(BaseModel):
    """project + digit_position + target_class 単位でのセッション跨ぎ集計
    （Issue #41/#42の再学習開始条件判定用）。"""

    project_name: str
    digit_position: int | None = None
    target_class: str | None = None
    accepted_total: int = 0
    accepted_flagged_duplicate: int = 0  # acceptedだが監査でnear-duplicateと判明した件数
    independent_primary: int = 0  # accepted_total - accepted_flagged_duplicate
    threshold_minimum: int = 20
    threshold_recommended_low: int = 30
    threshold_recommended_high: int = 50


class CaptureSessionListResponse(BaseModel):
    project_name: str
    sessions: list[CaptureSessionInfo]


class CaptureNowResult(BaseModel):
    status: str  # "captured" | "pending" | "failed"
    filename: str | None = None
    captured_at: str | None = None
    captured_count: int = 0
    message: str | None = None


# --- 撮影ソース（カメラ/URLの定義。プロジェクトに永続化して再利用する） ---


class CaptureSourceCreate(BaseModel):
    label: str
    source_type: str = "camera"  # camera | url
    camera_index: int = 0
    source_url: str | None = None


class CaptureSourceUpdate(BaseModel):
    label: str | None = None
    source_type: str | None = None
    camera_index: int | None = None
    source_url: str | None = None


class CaptureSourceInfo(BaseModel):
    source_id: str
    label: str
    source_type: str
    camera_index: int | None = None
    source_url: str | None = None  # 編集フォーム再入力用（passwordを含む場合がある）。表示には使わない
    masked_source_url: str | None = None  # 表示用（passwordをマスク済み）。一覧表示はこちらを使うこと


class CaptureSourceListResponse(BaseModel):
    project_name: str
    sources: list[CaptureSourceInfo]
