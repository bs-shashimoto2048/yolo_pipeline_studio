# API リファレンス

- ベースURL: `http://localhost:8000`。全エンドポイントは `/api` 配下（`backend/app/main.py`、各 `routers/*.py` の `APIRouter(prefix=...)`）。
- 対話的な仕様は起動後の Swagger UI（`http://localhost:8000/docs`）でも確認できる。
- 認証機構はなし（ローカル単一ユーザー前提）。
- エラーは `400`（入力不正）/ `404`（不存在）/ `409`（競合）を JSON `{"detail": "..."}` で返す（`backend/app/routers/*.py` の `HTTPException` 使用箇所より）。
- `{name}` はプロジェクト名（英数・`_`・`-`のみ、`core/paths.py` の `is_valid_project_name()` で検証）。
- Request/Responseの型は `backend/app/schemas/*.py` のPydanticモデルから抽出。フィールドが全て省略可（`| None = None` 等）のリクエストは「主なフィールド」として記載する。

## メタ

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/health` | 稼働確認 | なし | 不明（`backend/app/main.py` 内の簡易ハンドラ、専用スキーマなし） |

## プロジェクト / クラス

出典: `backend/app/routers/projects.py`, `backend/app/schemas/project.py`, `backend/app/schemas/cls.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects` | プロジェクト一覧 | なし | `list[ProjectSummary]` |
| POST | `/api/projects` | 作成 | `ProjectCreate` | `ProjectSummary`（201） |
| GET | `/api/projects/{name}` | 概要 | パスパラメータのみ | `ProjectSummary` |
| DELETE | `/api/projects/{name}` | 削除 | パスパラメータのみ | `MessageResponse`（実行中ジョブがあると409） |
| GET | `/api/projects/{name}/classes` | クラス一覧 | パスパラメータのみ | `ClassListResponse` |
| PUT | `/api/projects/{name}/classes` | クラス保存 | `ClassListUpdate` | `ClassListResponse` |

```python
# ProjectCreate
name: str            # 英数・_・-のみ
description: str = ""
task: str = "detect" # detect | segment

# ProjectSummary（レスポンス共通）
name: str
description: str = ""
task: str = "detect"
created_at: str | None = None
image_count: int = 0
label_count: int = 0
class_count: int = 0
train_count: int = 0

# ClassItem
id: int          # 0始まり
name: str
color: str = "#1677ff"

# ClassListUpdate（リクエスト）
classes: list[ClassInput]   # ClassInput = {name: str, color: str|None}
names: list[str] | None     # 後方互換（文字列配列）
```

エラー: `ProjectError`→404、`ProjectConflictError`→409（`create_project`はProjectError→400）。

## 画像 / アノテーション

出典: `backend/app/routers/images.py`, `backend/app/routers/annotations.py`, `backend/app/routers/label_validation.py`, `backend/app/schemas/image.py`, `backend/app/schemas/annotation.py`, `backend/app/schemas/label_validation.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/images?source=raw\|processed\|auto` | 画像一覧 | クエリ `source` | `ImageListResponse` |
| POST | `/api/projects/{name}/images` | 個別アップロード（multipart） | ファイル（`python-multipart`） | `UploadResponse` |
| POST | `/api/projects/{name}/images/import-folder` | フォルダ一括取り込み | 不明（サーバー側パス指定と推測されるが未確認） | `FolderImportResponse` |
| GET | `/api/projects/{name}/images/{filename}?source=` | 画像本体 | パス+クエリ | 画像バイナリ |
| GET | `/api/projects/{name}/images/{filename}/thumbnail?source=` | サムネイル | パス+クエリ | 画像バイナリ |
| GET | `/api/projects/{name}/images/{image_id}/annotations` | ラベル取得 | パスパラメータのみ | `AnnotationGetResponse` |
| PUT | `/api/projects/{name}/images/{image_id}/annotations` | ラベル保存 | `AnnotationSaveRequest` | `AnnotationSaveResponse` |
| POST | `/api/projects/{name}/labels/validate` | ラベル品質チェック | 不明（クエリ/ボディの詳細未確認） | `LabelValidationResponse` |

```python
# ImageInfo（一覧の1件）
filename: str
width: int
height: int
size_bytes: int
sha1: str
has_label: bool = False
low_resolution: bool = False

# AnnotationItem（detect時のbbox。YOLO正規化形式）
class_id: int
x_center: float
y_center: float
width: float
height: float

# PolygonItem（segment時。type="polygon"固定）
class_id: int
points: list[{x: float, y: float}]  # 3点以上
source: str = "manual"  # manual | sam

# AnnotationSaveRequest
annotations: list[dict]  # 空配列可（ネガティブ画像）

# LabelValidationResponse
project_name: str
summary: ValidationSummary   # image_count, label_file_count, error_count, warning_count 等
class_stats: list[ClassStat] # class_id, class_name, bbox_count, image_count
issues: list[LabelIssue]     # severity(error|warning), type, image_id, line_number, message
```

## 画像選別 / 前処理

出典: `backend/app/routers/selection.py`, `backend/app/routers/preprocess.py`, `backend/app/schemas/selection.py`, `backend/app/schemas/preprocess.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/selection` | 選別結果取得 | なし | `SelectionGetResponse` |
| POST | `/api/projects/{name}/selection/run` | 選別実行 | `SelectionRunRequest` | `SelectionRunResponse` |
| PUT | `/api/projects/{name}/selection/images/{image_id}` | status変更 | `SelectionStatusUpdate` | `SelectionStatusResponse` |
| POST | `/api/projects/{name}/selection/images/{image_id}/rotate` | 画像回転 | `SelectionRotateRequest` | `SelectionRotateResponse` |
| DELETE | `/api/projects/{name}/selection/images/{image_id}` | 画像を完全削除 | パスパラメータのみ | `SelectionDeleteResponse` |
| GET | `/api/projects/{name}/preprocess` | 前処理情報 | なし | `PreprocessInfoResponse` |
| POST | `/api/projects/{name}/preprocess/run` | 前処理実行 | `PreprocessSettings` | `PreprocessRunResponse` |
| POST | `/api/projects/{name}/preprocess/preview` | プレビュー生成 | 不明（画像ID指定と推測されるが未確認） | `PreprocessPreviewResponse` |
| GET | `/api/projects/{name}/preprocess/preview-image/{filename}` | プレビュー画像 | パスパラメータのみ | 画像バイナリ |

```python
# SelectionRunRequest
source: str = "auto"        # raw | processed | auto
min_width: int = 320
min_height: int = 320
blur_threshold: float = 80.0
dark_threshold: float = 30.0
bright_threshold: float = 240.0
detect_duplicates: bool = True
overwrite: bool = False

# SelectionStatusUpdate
status: str                 # included | review（excludedは不可。405章参照）
manual_reason: str | None = None

# SelectionRotateRequest
source: str = "processed"
angle: int = 90              # 90 | -90 | 180

# PreprocessSettings（主なフィールド）
job_name: str = "preprocess_001"
overwrite: bool = False
output_format: str = "jpg"   # jpg | png
resize_enabled: bool = False
resize_mode: str | None = None  # width | height
resize_size: int = 640
brightness_enabled: bool = False
contrast_enabled: bool = False
grayscale_enabled: bool = False
binary_enabled: bool = False
sharpen_enabled: bool = False
clahe_enabled: bool = False
```

## データセット / データ拡張

出典: `backend/app/routers/datasets.py`, `backend/app/routers/augmentation.py`, `backend/app/schemas/dataset.py`, `backend/app/schemas/augmentation.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/datasets` | データセット一覧 | なし | `DatasetListResponse` |
| POST | `/api/projects/{name}/datasets` | 作成 | `DatasetCreate` | `DatasetCreateResponse` |
| GET | `/api/projects/{name}/augmentation/presets` | プリセット一覧 | なし | `PresetListResponse` |
| GET | `/api/projects/{name}/augmentation/presets/{preset_name}` | プリセット取得 | パスパラメータのみ | `PresetItem` |
| PUT | `/api/projects/{name}/augmentation/presets/{preset_name}` | プリセット保存 | `PresetSave` | `PresetItem` |
| DELETE | `/api/projects/{name}/augmentation/presets/{preset_name}` | プリセット削除 | パスパラメータのみ | `MessageResponse`（builtin不可） |

```python
# DatasetCreate
dataset_name: str
train_ratio: float = 0.8
val_ratio: float = 0.2
test_ratio: float = 0.0
seed: int = 42
include_empty_labels: bool = True
include_unlabeled_images: bool = False
overwrite: bool = False
image_source: str = "auto"   # auto | raw | processed
use_selection: bool = True
include_review_images: bool = False

# PresetSave
description: str = ""
params: dict  # Ultralytics train引数名（degrees/translate/.../close_mosaic）
```

## 学習 / 評価

出典: `backend/app/routers/training.py`, `backend/app/routers/evaluation.py`, `backend/app/schemas/training.py`, `backend/app/schemas/evaluation.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/train-jobs` | 一覧 | なし | `TrainJobListResponse` |
| POST | `/api/projects/{name}/train-jobs` | 開始 | `TrainJobCreate` | `TrainJobStartResponse` |
| GET | `/api/projects/{name}/train-jobs/{job_id}` | 詳細 | パスパラメータのみ | `TrainJobInfo` |
| GET | `/api/projects/{name}/train-jobs/{job_id}/logs` | 学習ログ | パスパラメータのみ | `TrainLogResponse` |
| GET | `/api/projects/{name}/train-jobs/{job_id}/evaluation` | 評価サマリー | パスパラメータのみ | `EvaluationResponse` |
| GET | `/api/projects/{name}/train-jobs/{job_id}/metrics` | メトリクス | パスパラメータのみ | `MetricsResponse` |
| GET | `/api/projects/{name}/train-jobs/{job_id}/artifacts/{filename}` | 成果物画像 | パスパラメータのみ | 画像バイナリ |

```python
# TrainJobCreate
dataset_name: str
job_name: str
task: str | None = None       # detect | segment（未指定はプロジェクトのtask）
model: str = "yolov8n.pt"
epochs: int = 50
imgsz: int = 640
batch: int = 8
device: str = "auto"          # auto | cpu | mps | cuda
workers: int = 2
patience: int = 20
seed: int = 42
overwrite: bool = False
augmentation_preset: str | None = None
augmentation_params: dict | None = None

# TrainJobInfo.status: queued | running | completed | failed | stopped（job.json由来）

# EvaluationSummary
precision, recall, map50, map50_95: float | None
mask_precision, mask_recall, mask_map50, mask_map50_95: float | None  # segmentのみ
train_box_loss, train_cls_loss, train_dfl_loss: float | None
val_box_loss, val_cls_loss, val_dfl_loss: float | None
```

## 推論 / 誤検出分析 / 映像

出典: `backend/app/routers/prediction.py`, `backend/app/routers/analysis.py`, `backend/app/routers/video.py`, `backend/app/schemas/prediction.py`, `backend/app/schemas/analysis.py`, `backend/app/schemas/video.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/predict-jobs` | 一覧 | なし | `PredictJobListResponse` |
| POST | `/api/projects/{name}/predict-jobs` | 開始 | `PredictJobCreate` | `PredictJobStartResponse` |
| GET | `/api/projects/{name}/predict-jobs/{id}` | 詳細 | パスパラメータのみ | `PredictJobInfo` |
| GET | `/api/projects/{name}/predict-jobs/{id}/logs` | ログ | パスパラメータのみ | `PredictLogResponse` |
| GET | `/api/projects/{name}/predict-jobs/{id}/results` | 結果 | パスパラメータのみ | `PredictResultsResponse` |
| GET | `/api/projects/{name}/predict-jobs/{id}/images/{filename}` | 結果画像 | パスパラメータのみ | 画像バイナリ |
| POST | `/api/projects/{name}/predict-jobs/{id}/analysis` | 誤検出分析の実行 | `AnalysisRequest` | `AnalysisResponse` |
| GET | `/api/projects/{name}/predict-jobs/{id}/analysis` | 分析結果取得 | パスパラメータのみ | `AnalysisResponse` |
| GET | `/api/projects/{name}/cameras` | 接続カメラ列挙 | なし | `CameraListResponse` |
| GET | `/api/projects/{name}/video-sources` | 既知URL一覧 | なし | `VideoSourceListResponse` |
| DELETE | `/api/projects/{name}/video-sources?url=` | 既知URL削除 | クエリ `url` | `MessageResponse`（不明: 未確認） |
| GET | `/api/projects/{name}/video-jobs` | 一覧 | なし | `VideoJobListResponse` |
| POST | `/api/projects/{name}/video-jobs` | 映像推論開始 | `VideoJobCreate` | 不明（`VideoJobInfo`類似と推測されるが専用Start Responseスキーマ未確認） |
| GET | `/api/projects/{name}/video-jobs/{vid}` | 詳細 | パスパラメータのみ | `VideoJobInfo` |
| PATCH | `/api/projects/{name}/video-jobs/{vid}/settings` | 設定変更 | `VideoJobSettingsUpdate` | `VideoJobInfo`（推測せず: 不明） |
| POST | `/api/projects/{name}/video-jobs/{vid}/stop` | 停止 | パスパラメータのみ | `MessageResponse`（不明: 未確認） |
| GET | `/api/projects/{name}/video-jobs/{vid}/stream` | MJPEG配信 | パスパラメータのみ | `multipart/x-mixed-replace` ストリーム |

```python
# PredictJobCreate
predict_job_name: str
train_job_id: str
weight_type: str = "best"          # best | last
source_type: str = "project_images" # project_images | upload
image_ids: list[str] = []
conf: float = 0.25
iou: float = 0.7
imgsz: int = 640
device: str = "auto"
save_txt: bool = True
save_conf: bool = True
overwrite: bool = False
preprocess_mode: str = "none"       # none | latest

# AnalysisRequest
iou_threshold: float = 0.5
conf_threshold: float = 0.25

# AnalysisItem.type: tp | fp | fn | class_mismatch

# VideoJobCreate
video_job_name: str
train_job_id: str
weight_type: str = "best"
source_type: str = "camera"   # camera | url（url: RTSP/HTTP(MJPEG)）
camera_index: int = 0
source_url: str | None = None
video_fps: int = 15
infer_fps: int = 5
conf: float = 0.25
iou: float = 0.7
imgsz: int = 640
device: str = "auto"
preprocess_mode: str = "none"
overwrite: bool = False

# VideoJobInfo（表示用。source_url/resolved_source_urlは認証情報マスク済み）
status: str  # queued | running | stopped | failed | completed
```

**セキュリティ上の注記**: `VideoJobInfo.source_url` / `resolved_source_url` はパスワード等の認証情報をマスクした表示用の値であり、実接続用の生値はサーバー内部の `job.json` にのみ保持される（`backend/app/schemas/video.py` のコメント）。`VideoSourceInfo` も同様に `url`（生値）と `masked_url`（表示用）を分離している。

## 撮影ソース（カメラ・URLからの静止画撮影）

出典: `backend/app/routers/capture.py`, `backend/app/schemas/capture.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/capture-sources` | 一覧 | なし | `CaptureSourceListResponse` |
| POST | `/api/projects/{name}/capture-sources` | 追加 | `CaptureSourceCreate` | `CaptureSourceInfo` |
| PATCH | `/api/projects/{name}/capture-sources/{source_id}` | 更新 | `CaptureSourceUpdate` | `CaptureSourceInfo` |
| DELETE | `/api/projects/{name}/capture-sources/{source_id}` | 削除 | パスパラメータのみ | `MessageResponse`（不明: 未確認） |
| GET | `/api/projects/{name}/capture-sessions` | 一覧 | なし | `CaptureSessionListResponse` |
| POST | `/api/projects/{name}/capture-sessions` | セッション開始 | `CaptureSessionCreate` | 不明（専用Start Responseスキーマ未確認） |
| GET | `/api/projects/{name}/capture-sessions/{sid}` | 詳細 | パスパラメータのみ | `CaptureSessionInfo` |
| POST | `/api/projects/{name}/capture-sessions/{sid}/capture` | 今すぐ撮影 | パスパラメータのみ | `CaptureNowResult` |
| POST | `/api/projects/{name}/capture-sessions/{sid}/stop` | 停止 | パスパラメータのみ | `MessageResponse`（不明: 未確認） |
| GET | `/api/projects/{name}/capture-sessions/{sid}/frame` | 最新1フレーム | パスパラメータのみ | 画像バイナリ |
| GET | `/api/projects/{name}/capture-sessions/{sid}/stream` | MJPEG配信 | パスパラメータのみ | `multipart/x-mixed-replace` ストリーム |

```python
# CaptureSourceCreate / CaptureSourceInfo
label: str
source_type: str = "camera"  # camera | url
camera_index: int = 0
source_url: str | None = None
# CaptureSourceInfo追加: masked_source_url（表示用マスク済み）

# CaptureSessionCreate
session_name: str
source_type: str = "camera"
camera_index: int = 0
source_url: str | None = None
video_fps: int = 10
interval_minutes: float | None = None  # 未指定/0以下は手動撮影のみ
overwrite: bool = False

# CaptureNowResult
status: str  # captured | pending | failed
```

## SAM 補助アノテーション

出典: `backend/app/routers/sam.py`, `backend/app/schemas/sam.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/sam/settings` | 設定取得 | なし | `SamSettings` |
| PUT | `/api/projects/{name}/sam/settings` | 設定保存 | `SamSettings` | `SamSettings` |
| POST | `/api/projects/{name}/images/{image_id}/sam/propose` | ポリゴン候補提案 | `SamProposeRequest` | `SamProposeResponse` |

```python
# SamSettings
model: str = "sam2_t.pt"        # sam_b.pt | sam_l.pt | sam2_t.pt | sam2_b.pt
device: str = "auto"            # auto | cpu | cuda
polygon_simplify_epsilon: float = 2.0
min_area: int = 50
max_points: int = 300
merge_nearby_regions: bool = True
merge_distance_px: int = 8

# SamProposeRequest
source: str = "auto"            # auto | raw | processed
class_id: int = 0
prompt: SamPrompt               # type: box|point, box or positive/negative_points
settings: SamSettings | None = None
```

## 実験履歴 / モデル管理 / 配布 / ONNX

出典: `backend/app/routers/experiments.py`, `backend/app/routers/model_registry.py`, `backend/app/routers/model_export.py`, `backend/app/routers/onnx_export.py`, `backend/app/schemas/experiment.py`, `backend/app/schemas/model_registry.py`, `backend/app/schemas/model_export.py`, `backend/app/schemas/onnx_export.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/experiments` | 一覧 | なし | `ExperimentListResponse` |
| GET | `/api/projects/{name}/experiments/{experiment_id}` | 詳細 | パスパラメータのみ | `ExperimentDetailResponse` |
| GET | `/api/projects/{name}/models` | 一覧 | なし | `ModelListResponse` |
| GET | `/api/projects/{name}/models/selected` | 採用モデル取得 | なし | `SelectedModelResponse` |
| PUT | `/api/projects/{name}/models/selected` | 採用モデル設定 | `SelectModelRequest` | `SelectedModelResponse` |
| GET | `/api/projects/{name}/models/{train_job_id}/{weight_type}` | モデル詳細 | パスパラメータのみ | `ModelDetailResponse` |
| GET | `/api/projects/{name}/model-export/{train_job_id}/{weight}/download` | 重みダウンロード | パスパラメータのみ | `.pt` バイナリ |
| POST | `/api/projects/{name}/model-export/{train_job_id}/{weight}/package` | 配布パッケージ作成 | `ModelPackageCreate` | `ModelPackageResponse` |
| GET | `/api/projects/{name}/model-packages/{package_id}/download` | パッケージダウンロード | パスパラメータのみ | `.zip` バイナリ |
| POST | `/api/projects/{name}/onnx-exports` | ONNXエクスポート開始 | `OnnxExportCreate` | `OnnxExportStartResponse` |
| GET | `/api/projects/{name}/onnx-exports` | 一覧 | なし | `OnnxExportListResponse` |
| GET | `/api/projects/{name}/onnx-exports/{export_job_id}` | 詳細 | パスパラメータのみ | `OnnxExportInfo` |
| GET | `/api/projects/{name}/onnx-exports/{export_job_id}/logs` | ログ | パスパラメータのみ | `OnnxExportLogResponse` |
| GET | `/api/projects/{name}/onnx-exports/{export_job_id}/download` | ダウンロード | パスパラメータのみ | `.onnx` バイナリ |

```python
# SelectModelRequest
train_job_id: str
weight_type: str = "best"
memo: str = ""

# ModelPackageCreate
include_onnx: bool = False
onnx_export_job_id: str | None = None

# OnnxExportCreate
train_job_id: str
weight_type: str = "best"      # best | last
export_job_name: str | None = None
imgsz: int | None = None
opset: int = 12
simplify: bool = True
dynamic: bool = False
half: bool = False
device: str = "cpu"            # auto | cpu | cuda
overwrite: bool = False
```

## レポート

出典: `backend/app/routers/reports.py`, `backend/app/schemas/report.py`

| Method | Path | 概要 | Request | Response |
|---|---|---|---|---|
| GET | `/api/projects/{name}/reports` | 一覧 | なし | `ReportListResponse` |
| POST | `/api/projects/{name}/reports` | 生成 | `ReportCreate` | `ReportGenerateResponse` |
| GET | `/api/projects/{name}/reports/{report_id}` | 詳細 | パスパラメータのみ | `ReportDetailResponse` |
| GET | `/api/projects/{name}/reports/{report_id}/download?format=` | ダウンロード | クエリ `format` | ファイルバイナリ（markdown/json） |

```python
# ReportCreate
report_name: str | None = None
include_images: bool = False
include_predictions: bool = True
include_analysis: bool = True
format: str = "markdown"  # markdown | json | both
```

## 未実装エンドポイント

`backend/app/routers/stubs.py` の `_STUB_FEATURES` は空リストであり、現時点で501を返すスタブエンドポイントは存在しない（詳細: [`10_KNOWN_LIMITATIONS.md`](10_KNOWN_LIMITATIONS.md)）。

## 共通レスポンス型

```python
# backend/app/schemas/common.py
class MessageResponse(BaseModel):
    message: str

class StubResponse(BaseModel):
    status: str = "not_implemented"
    feature: str
    message: str
```

## この文書作成にあたって確認した主なファイル

- `backend/app/main.py`（ルーター登録順）
- `backend/app/routers/projects.py`（エラーハンドリングの実例）
- `backend/app/schemas/` 配下の全23ファイル（`common.py`, `project.py`, `cls.py`, `image.py`, `annotation.py`, `label_validation.py`, `selection.py`, `preprocess.py`, `dataset.py`, `augmentation.py`, `training.py`, `evaluation.py`, `prediction.py`, `analysis.py`, `video.py`, `capture.py`, `sam.py`, `experiment.py`, `model_registry.py`, `model_export.py`, `onnx_export.py`, `report.py`）
- `docs/api-reference.md`（既存ドキュメント、目次構成の一次情報源）

## 不明・確認できなかった項目

- `POST /api/projects/{name}/images/import-folder` のリクエストボディの厳密な形（サーバー側パス指定かクライアントアップロードか、`backend/app/routers/images.py` の関数シグネチャを本ドキュメント作成時点で個別確認していない）。
- `POST /api/projects/{name}/preprocess/preview` のリクエストボディ詳細。
- `DELETE /api/projects/{name}/video-sources`, `POST /api/projects/{name}/video-jobs`（開始時の正確なレスポンススキーマ）, `PATCH .../video-jobs/{vid}/settings`, `POST .../video-jobs/{vid}/stop`, `DELETE .../capture-sources/{source_id}`, `POST .../capture-sessions`（開始時のレスポンススキーマ）, `POST .../capture-sessions/{sid}/stop` の正確なレスポンス型（`backend/app/routers/video.py` / `capture.py` のハンドラ関数シグネチャを個別確認していない。`MessageResponse`や既存Infoスキーマの再利用が推測されるが、推測での明記は避けた）。
- 各エンドポイントの「どの例外がどのステータスに変換されるか」の全件対応表（`projects.py`以外の各routerファイルの`try/except`を1つずつ確認する必要があり、本ドキュメントでは網羅していない）。
