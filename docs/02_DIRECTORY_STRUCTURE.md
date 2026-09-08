# ディレクトリ構成

実際のディレクトリ走査結果に基づく（Git 管理外の `projects/`, `node_modules/`, `.venv/` 等は内容を省略）。

## リポジトリ全体

```text
yolo_pipeline_studio/
├── backend/                  FastAPIアプリ本体・ワーカー・テスト
├── frontend/                 React + Vite + TS SPA
├── docs/                     設計・仕様ドキュメント（本ドキュメント群を含む）
├── projects/                 案件データ（Git管理外、.gitignoreで除外）
├── scripts/                  運用補助スクリプト（Git未追跡）
├── .venv/                    Python仮想環境（Git管理外）
├── .github/ or CI設定        このプロジェクトでは確認できない
├── requirements.txt          バックエンド起動用の軽量依存
├── requirements-train.txt    学習/ONNX用の重い依存（別管理）
├── task.md                   要件定義・Issueメモ（Issue 029の内容を含む）
├── README.md                 プロジェクト概要・QuickStart
└── sam2_t.pt                 SAM事前学習重み（.gitignoreで除外対象パターンに合致するが実体が存在）
```

## `backend/`

| パス | 役割 |
|---|---|
| `backend/app/main.py` | FastAPI エントリポイント。CORS設定、`/api/health`、全ルーターの `include_router` |
| `backend/app/core/config.py` | アプリ設定（`Settings` クラス、環境変数の読み取り） |
| `backend/app/core/paths.py` | プロジェクト配下の全パス解決関数、プロジェクト名検証、パストラバーサル対策 |
| `backend/app/routers/*.py` | HTTPエンドポイント層（21個の実働ルーター + `stubs.py`） |
| `backend/app/services/*.py` | ドメインロジック本体（ルーターと1:1対応することが多い） |
| `backend/app/schemas/*.py` | Pydantic 入出力モデル（ルーター/サービスと対応） |
| `backend/workers/*.py` | `app` パッケージに依存しない独立ワーカースクリプト（5ファイル） |
| `backend/tests/smoke_*.py` | スモークテスト（32ファイル、一時ディレクトリ + FastAPI TestClient） |
| `backend/requirements-sam.txt` | SAM補助アノテーション用の追加依存 |

### `backend/app/routers/` 一覧（21ファイル）

`analysis.py, annotations.py, augmentation.py, capture.py, datasets.py, evaluation.py, experiments.py, images.py, label_validation.py, model_export.py, model_registry.py, onnx_export.py, prediction.py, preprocess.py, projects.py, reports.py, sam.py, selection.py, stubs.py, training.py, video.py`

### `backend/app/services/` 一覧（26ファイル）

`analysis_service.py, annotation_service.py, augmentation_service.py, capture_service.py, class_service.py, dataset_service.py, evaluation_service.py, experiment_service.py, image_service.py, label_validation_service.py, log_utils.py, model_export_service.py, model_registry_service.py, onnx_export_service.py, prediction_service.py, preprocess_service.py, project_service.py, report_service.py, sam_service.py, selection_service.py, training_service.py, video_service.py`

### `backend/workers/` 一覧（5ファイル）

| ファイル | 役割 |
|---|---|
| `train_worker.py` | 学習ジョブ（Ultralytics YOLO） |
| `predict_worker.py` | 画像推論ジョブ |
| `predict_video_worker.py` | 映像（カメラ/URL）推論ワーカー |
| `capture_worker.py` | カメラ/URLからの静止画撮影ワーカー（`predict_video_worker.py` の関数を再利用） |
| `onnx_export_worker.py` | ONNX エクスポートワーカー |

## `frontend/`

| パス | 役割 |
|---|---|
| `frontend/index.html` | SPA のエントリ HTML |
| `frontend/src/main.tsx` | React エントリポイント |
| `frontend/src/App.tsx` | ルーティング定義（`react-router-dom`） |
| `frontend/src/workflow.ts` | ワークフロー12工程の定義（`WORKFLOW_STEPS`） |
| `frontend/src/api/client.ts` | バックエンドAPI呼び出しの集約（約84メソッド、822行） |
| `frontend/src/types.ts` | バックエンドAPIの型定義（1021行） |
| `frontend/src/styles.css` | 全画面共通スタイル（CSS変数によるデザイントークン、3221行） |
| `frontend/src/pages/*.tsx` | 画面コンポーネント（14ファイル、工程ごとの画面） |
| `frontend/src/components/*.tsx` | 共通/再利用コンポーネント（11ファイル） |
| `frontend/scripts/capture-operator-screenshots.mjs` | 作業者マニュアル用スクリーンショットの自動撮影スクリプト（Playwright） |
| `frontend/vite.config.ts` | Vite設定（開発サーバーポート5173、`/api`プロキシ先8000） |
| `frontend/tsconfig.json` | TypeScriptコンパイラ設定（`strict: true`） |

### `frontend/src/pages/` 一覧（14ファイル）

`AnalysisPage.tsx, AnnotatePage.tsx, AugmentationPage.tsx, DatasetPage.tsx, EvaluatePage.tsx, ExperimentsPage.tsx, ModelsPage.tsx, PredictPage.tsx, PreprocessPage.tsx, ProjectsPage.tsx, ReportsPage.tsx, SelectionPage.tsx, SetupPage.tsx, TrainPage.tsx`

（`AugmentationPage.tsx` は `frontend/src/App.tsx` のルーティングには存在しない。データ拡張機能は `TrainPage.tsx` に統合されている旨が `frontend/src/workflow.ts` のコメントに記載されている）

### `frontend/src/components/` 一覧（11ファイル）

| ファイル | 役割（ファイル名・利用箇所から判断できる範囲） |
|---|---|
| `AugmentationPanel.tsx` | データ拡張プリセット設定パネル |
| `CaptureSourcesPanel.tsx` | カメラ・URL撮影ソースの管理パネル（`ImagesPanel.tsx` から利用） |
| `ClassesPanel.tsx` | クラス設計パネル |
| `HoverImagePreview.tsx` | ホバー時拡大表示付き画像プレビュー（`createPortal` で body 直下に描画） |
| `ImagesPanel.tsx` | 画像取り込み（フォルダ一括/個別アップロード/カメラ・URL撮影）パネル |
| `InfoTooltip.tsx` | 補足情報のツールチップ表示 |
| `LabelCheckPanel.tsx` | ラベル品質チェックパネル |
| `OverviewPanel.tsx` | プロジェクト概要表示パネル |
| `ProjectLayout.tsx` | プロジェクト配下の共通レイアウト（左サイドバー + `Outlet`） |
| `StubPage.tsx` | 未実装画面用のスタブ表示 |

## `docs/`

| パス | 役割 |
|---|---|
| `docs/README.md` | ドキュメント一覧（読み手別の導線） |
| `docs/operator-manual.md` | 作業者向け操作マニュアル（実UIスクリーンショット付き） |
| `docs/architecture.md` | 内部構成・データレイアウト・設計方針 |
| `docs/api-reference.md` | REST APIエンドポイント一覧 |
| `docs/development.md` | 開発環境セットアップ・テスト・コーディング規約 |
| `docs/images/operator/` | 作業者マニュアル用スクリーンショット格納先 |
| `docs/00_PROJECT_OVERVIEW.md` 〜 `docs/10_KNOWN_LIMITATIONS.md` | 本ドキュメント群（AIコーディング支援用） |

## `projects/`（Git管理外）

`.gitignore` で除外。`YTS_PROJECTS_ROOT` 環境変数で格納先を変更可能（未指定時は本ディレクトリ）。データレイアウトの詳細は [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) を参照。

## `scripts/`（Git管理下）

Issue #9のクリーンアップにより、当初存在した特定時点・特定データ向けの補正/再ラベリングスクリプト5本（`apply_readings_*.py`、`ensemble_autolabel.py`）は削除した。いずれもアプリ本体・tests・docsから実行時参照されておらず、既存ラベルを無条件に上書きする破壊的処理を含み、一部はローカル環境固有の絶対パスに依存していたため、Git管理下に残す価値がないと判断した。

現在は `review_montage.py` のみが正式に収録されている。

### `review_montage.py`

目視アノテーション補助用のユーティリティ。`projects/<project名>/raw/images` と `annotations/labels` を**読み取るだけ**で、どちらも変更しない（read-only）。指定した領域でraw画像をクロップし、グリッド状のmontage画像1枚として出力する。`--show-boxes` を付けると現在のラベル（矩形・クラス）をクロップ画像へ重ねて表示できるため、目視で読んだ数値と現行ラベルの突き合わせに使う。

| 項目 | 内容 |
|---|---|
| 入力 | `projects/<project>/raw/images/*`（画像）、`projects/<project>/annotations/labels/*.txt`（`--show-boxes`時のみ） |
| 出力 | `--out` で指定した1枚のmontage画像ファイルのみ（projectデータへの書き込みなし） |
| 対象project | `--project`（既定: `meter`）で切り替え可能 |

実行例:

```powershell
.venv\Scripts\python.exe scripts\review_montage.py --project meter --prefix src_003_ `
  --crop 0.50 0.76 0.44 0.68 --cols 5 --start 0 --count 20 `
  --out C:\path\to\output\src_003_batch01.jpg --show-boxes
```

`--out` は既存ファイルを上書きするが、対象は明示的に指定した出力パスのみであり、`projects/` 配下の画像・ラベルは一切変更しない。
