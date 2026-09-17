"""映像（カメラ）推論関連スキーマ。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CameraInfo(BaseModel):
    index: int
    label: str


class CameraListResponse(BaseModel):
    cameras: list[CameraInfo]


class VideoJobCreate(BaseModel):
    """train_job_id / weight_type / conf は省略可（Issue #19）。省略時は image predict と同じ
    優先順位（明示指定 > 採用モデル(selected_model.json) > 安全なdefault）で解決する。
    明示指定は常にselected model設定より優先される。
    """

    video_job_name: str
    train_job_id: str | None = None
    weight_type: str | None = None
    source_type: str = "camera"  # camera | url（url: RTSP/HTTP(MJPEG)ストリーム）
    camera_index: int = 0
    source_url: str | None = None  # source_type=url のとき使用
    video_fps: int = 15  # キャプチャ/表示FPS
    infer_fps: int = 5   # 推論FPS（video_fps以下）
    conf: float | None = None
    iou: float = 0.7
    imgsz: int = 640
    device: str = "auto"
    preprocess_mode: str = "none"  # none | latest | selected
    overwrite: bool = False


class VideoJobInfo(BaseModel):
    project_name: str | None = None
    video_job_id: str
    train_job_id: str | None = None
    weight_type: str | None = None
    source_type: str | None = None
    camera_index: int | None = None
    source_url: str | None = None  # 表示用（password等の認証情報はマスク済み。実接続はサーバー内部のjob.jsonのraw値を使う）
    resolved_source_url: str | None = None  # 同上（表示用マスク済み）
    video_fps: int | None = None
    infer_fps: int | None = None
    conf: float | None = None
    preprocess_mode: str | None = None
    # 実際に解決されたtrain_job_id/weight_type/confの由来（"request" | "selected_model" | "default"）
    resolution_source: dict[str, str] | None = None
    # preprocess_mode="latest"/"selected"の場合に実際に適用されたPreprocessSettings（dict）
    resolved_preprocess_profile: dict[str, Any] | None = None
    # 実際に適用された前処理ステップの列（例: ["roi_crop","resize","grayscale","sharpen"]）
    processing_order: list[str] | None = None
    status: str = "unknown"  # queued | running | stopped | failed | completed
    message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    stream_url: str | None = None


class VideoJobSettingsUpdate(BaseModel):
    """実行中ジョブのFPS・推論設定を即時変更するための部分更新リクエスト。

    カメラ/URL/モデル/前処理の変更は再接続が必要になるため対象外（未指定項目は変更しない）。
    """

    video_fps: int | None = None
    infer_fps: int | None = None
    conf: float | None = None
    iou: float | None = None
    imgsz: int | None = None
    device: str | None = None


class VideoSourceInfo(BaseModel):
    """過去に映像取得に成功したURL（プロジェクト単位で記憶）。"""

    url: str  # 実接続・再入力用（password等の認証情報を含む場合がある。表示には使わない）
    masked_url: str  # 表示専用（password をマスク済み）。UI一覧表示はこちらを使うこと
    video_job_id: str | None = None
    last_verified_at: str | None = None


class VideoSourceListResponse(BaseModel):
    project_name: str
    sources: list[VideoSourceInfo]


class VideoJobListResponse(BaseModel):
    project_name: str
    jobs: list[VideoJobInfo]
