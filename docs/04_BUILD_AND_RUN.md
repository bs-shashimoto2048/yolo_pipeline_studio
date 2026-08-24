# ビルド・実行方法

実際に存在するコマンドのみを記載する。存在しないもの（lintスクリプト、CI等）は明記して省略する。

## 前提

- Python: バージョン指定は `README.md`/`requirements.txt` に明記なし（不明）。
- Node.js: バージョン指定は `frontend/package.json` に `engines` フィールドなし（不明）。
- OS: 開発環境として Windows（PowerShell）が前提の記述が `README.md` に見られる（`.\.venv\Scripts\Activate.ps1` 等）。

## インストール

### バックエンド（軽量・必須）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### バックエンド（学習・ONNXを使う場合、任意）

```powershell
pip install -r requirements-train.txt
```

`README.md` にCUDA種別ごとのPyTorch個別インストール手順のコメントがある（GPU利用時）。

### バックエンド（SAM補助アノテーションを使う場合、任意）

```powershell
pip install -r backend\requirements-sam.txt
```

### フロントエンド

```powershell
cd frontend
npm install
```

## 開発サーバー起動

```powershell
# バックエンド（リポジトリ直下、別ターミナル）
uvicorn app.main:app --reload --app-dir backend --port 8000

# フロントエンド（frontend/、別ターミナル）
npm run dev
```

- バックエンド: `http://localhost:8000`（Swagger UI: `http://localhost:8000/docs`）
- フロントエンド: `http://localhost:5173`（`frontend/vite.config.ts` で `host: true`, `port: 5173`）
- フロントエンドの `/api/*` リクエストは Vite dev proxy 経由で `http://localhost:8000` へ転送される（`frontend/vite.config.ts`）。

## ビルド

`frontend/package.json` の `scripts`。

| コマンド | 実体 | 説明 |
|---|---|---|
| `npm run build` | `tsc -b && vite build` | 型チェック後にプロダクションビルド。出力先 `frontend/dist/` |
| `npm run preview` | `vite preview` | ビルド結果のローカル確認用サーバー |

バックエンドに専用のビルドステップは確認できない（Pythonはそのまま実行）。

## テスト

### バックエンド

`backend/tests/` に pytest 等の設定ファイルは存在せず、`smoke_*.py` という名前の**スタンドアロンスクリプト**が32個ある。各ファイルは `if __name__ == "__main__":` で直接実行する形式（`docs/development.md` より）。

```powershell
.\.venv\Scripts\python.exe backend\tests\smoke_dataset_builder.py
.\.venv\Scripts\python.exe backend\tests\smoke_video_inference.py
# 他の smoke_*.py も同様に個別実行する
```

一時ディレクトリ・FastAPI `TestClient`・ドライラン環境変数（[`08_CONFIGURATION.md`](08_CONFIGURATION.md)）を使い、実データやGPUに依存せず疎通確認する。

`backend/tests/` に存在するスモークテスト一覧（全32ファイル、`smoke_` 接頭辞）:

```text
smoke_analysis.py, smoke_annotations.py, smoke_augmentation.py, smoke_capture.py,
smoke_class_color.py, smoke_dataset_builder.py, smoke_evaluation.py,
smoke_evaluation_artifacts.py, smoke_experiments.py, smoke_folder_import.py,
smoke_image_rotation.py, smoke_label_validation.py, smoke_model_export.py,
smoke_model_export_onnx.py, smoke_model_registry.py, smoke_onnx_export.py,
smoke_prediction.py, smoke_prediction_preprocess.py, smoke_preprocess.py,
smoke_preprocess_binary.py, smoke_preprocess_preview.py, smoke_project_delete.py,
smoke_reports.py, smoke_sam.py, smoke_segment_annotations.py, smoke_segment_dataset.py,
smoke_segment_label_validation.py, smoke_segment_training.py, smoke_selection.py,
smoke_training.py, smoke_training_log.py, smoke_video_inference.py
```

### フロントエンド

専用のテストランナー（Vitest/Jest等）の設定・依存は `frontend/package.json` に存在しない。`npm run build`（`tsc -b`含む）による型チェックが実質的な検証手段（`docs/development.md` より）。

```powershell
cd frontend
npm run build
```

`playwright` は devDependencies に存在するが、`frontend/package.json` の `scripts` に対応する実行コマンド（例: `test:e2e`）は定義されていない。実際の利用箇所は `frontend/scripts/capture-operator-screenshots.mjs`（作業者マニュアル用スクリーンショットの自動撮影）であり、E2Eテストスイートとしての利用は確認できない。

## Lint / フォーマット

ESLint / Prettier / Ruff / Black / mypy 等の設定ファイル・依存パッケージは `frontend/package.json` / `requirements*.txt` に存在しない。このプロジェクトでは確認できない。

## CI / CD

`.github/workflows/` ディレクトリは存在しない。CI/CD設定はこのプロジェクトでは確認できない。

## コンテナ化

`Dockerfile` / `docker-compose.yml` は存在しない。コンテナ化構成はこのプロジェクトでは確認できない。
