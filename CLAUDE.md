# CLAUDE.md

このファイルは Claude Code がこのリポジトリで作業する際に読み込む、プロジェクト固有の指示ファイルです。内容はすべて実際のソースコード・設定ファイル・既存ドキュメント（`docs/`）で確認できた事実に基づきます。詳細な調査結果は `docs/00_PROJECT_OVERVIEW.md` 〜 `docs/10_KNOWN_LIMITATIONS.md` を参照してください。

## プロジェクト概要

YOLO Tuning Studio — Ultralytics YOLO を用いた物体検出/インスタンスセグメンテーションのアノテーションから学習・評価・ONNXエクスポートまでを一気通貫で行うローカルWebアプリ。

- バックエンド: FastAPI（Python） — `backend/`
- フロントエンド: React + Vite + TypeScript + Konva（アノテーション描画） — `frontend/`
- 詳細: [`docs/00_PROJECT_OVERVIEW.md`](docs/00_PROJECT_OVERVIEW.md)

## ディレクトリ構造（要点）

```text
backend/app/routers/    HTTPエンドポイント層
backend/app/services/   ドメインロジック
backend/app/schemas/    Pydantic入出力モデル
backend/app/core/       設定（config.py）・パス解決（paths.py）
backend/workers/        学習/推論/映像/撮影/ONNXの独立ワーカー（subprocess起動）
backend/tests/smoke_*.py  スモークテスト（32ファイル、スタンドアロン実行）
frontend/src/pages/     画面コンポーネント
frontend/src/components/ 共通コンポーネント
frontend/src/api/client.ts  APIクライアント集約
frontend/src/workflow.ts    ワークフロー12工程の定義
docs/                   設計・仕様ドキュメント
projects/               案件データ（Git管理外）
```

詳細: [`docs/02_DIRECTORY_STRUCTURE.md`](docs/02_DIRECTORY_STRUCTURE.md)

## ビルド方法

```powershell
cd frontend
npm run build   # 実体: tsc -b && vite build
```

バックエンドに専用のビルドステップはない（Pythonはそのまま実行）。

## 実行方法

```powershell
# バックエンド（リポジトリ直下）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir backend --port 8000

# フロントエンド（別ターミナル）
cd frontend
npm install
npm run dev
```

- API: `http://localhost:8000`（Swagger UI: `/docs`）
- フロントエンド: `http://localhost:5173`（`/api` は Vite dev proxy で8000へ転送）

## テスト方法

```powershell
# バックエンド: 変更した機能に対応するスモークテストを個別実行
.\.venv\Scripts\python.exe backend\tests\smoke_<機能名>.py

# フロントエンド: 型チェック込みビルド
cd frontend
npm run build
```

pytest等の形式的テストランナーは存在しない。学習/推論/映像/撮影/ONNXなどの重い処理は `YTS_*_DRY_RUN=1` 系の環境変数でダミー化してテストする（一覧: [`docs/08_CONFIGURATION.md`](docs/08_CONFIGURATION.md)）。

Lint/フォーマットツール（ESLint/Prettier/Ruff/Black/mypy等）、CI/CD（`.github/workflows/`）、Dockerは、いずれもこのリポジトリに存在しない。

## コーディング規約

- Python: snake_case（関数/変数）、PascalCase（クラス）。全ファイル先頭に `from __future__ import annotations`。
- TypeScript: camelCase（関数/変数）、PascalCase（コンポーネント/インターフェース）。
- コメント/docstringは日本語。既存のコードスタイル・命名に合わせ、大規模な自発的リファクタリングをしない。
- バックエンドの例外は `<機能名>Error` を基底に `ValidationError`(400)/`NotFoundError`(404)/`ConflictError`(409) を派生させ、routers層でHTTPステータスに変換する。
- 新規の重い依存（torch/ultralytics等）は `requirements.txt`（軽量・必須）に入れず、`requirements-train.txt`/`backend/requirements-sam.txt` に分離する。

詳細: [`docs/05_CODING_CONVENTIONS.md`](docs/05_CODING_CONVENTIONS.md)

## 編集禁止・注意が必要な場所

- **`projects/`**: 案件データ（Git管理外）。実運用プロジェクトを編集・削除しない。テストは `YTS_PROJECTS_ROOT` で隔離した一時ディレクトリを使う。
- **`.env`/`.env.*`/`*.pem`/`*.key`**: 秘密情報ファイル。読み取り・編集をしない。
- **モデル重みファイル（`*.pt`/`*.onnx`等）**: `.gitignore` 対象。コミットしない。
- **`classes.yaml` のID順序**: 既存プロジェクトで追加順を変更しない（学習済みモデル/ラベルとの不整合の原因になる）。

詳細: [`docs/09_AI_DEVELOPMENT_GUIDE.md`](docs/09_AI_DEVELOPMENT_GUIDE.md)

## 推奨ワークフロー（新機能追加時）

1. `backend/app/schemas/` に入出力モデルを追加
2. `backend/app/services/` にロジックを実装
3. `backend/app/routers/` にエンドポイントを追加し、**`backend/app/main.py` に import と `include_router` の両方を追加**（片方のみだと404になる）
4. 重い処理は `backend/workers/` に独立スクリプトを実装し `subprocess.Popen` で起動、ドライラン用環境変数を用意
5. `backend/tests/smoke_<機能名>.py` を追加
6. フロントエンドは `frontend/src/api/client.ts` にメソッド追加 → 画面/コンポーネント実装 → 必要なら `frontend/src/workflow.ts`/`App.tsx` に反映

## 重要な設計思想

- **軽量/重量依存の分離**: アノテーション等の軽作業がGPU/学習ライブラリを要求しないよう依存関係を分離している。
- **非破壊性**: `raw/`→`processed/` の前処理、画像選別の `included/excluded/review` 管理など、元データを壊さない設計。
- **ワーカー分離による非ブロッキング処理**: 学習・推論・映像・撮影・ONNXエクスポートは別プロセス（`subprocess.Popen`）+ `job.json` ポーリングで実行し、APIサーバーをブロックしない。
- **クラスID append-only**: データ整合性維持のための明示的な制約。
- **認証なし・ローカル単一ユーザー前提**: 全APIエンドポイントに認証機構がない。

## よく使うコマンド

| コマンド | 説明 |
|---|---|
| `uvicorn app.main:app --reload --app-dir backend --port 8000` | バックエンド開発サーバー起動 |
| `npm run dev`（`frontend/`） | フロントエンド開発サーバー起動 |
| `npm run build`（`frontend/`） | 型チェック込みプロダクションビルド |
| `.\.venv\Scripts\python.exe backend\tests\smoke_<機能名>.py` | 該当機能のスモークテスト実行 |

## 補足

- 本ファイルは `docs/` ディレクトリではなくリポジトリルートに配置しています。Claude Code はカレントディレクトリ直下の `CLAUDE.md` を自動的に読み込むため、機能させるにはこの配置が必要と判断しました（判断の詳細は `docs/DOCUMENTATION_REPORT.md` を参照）。
- より詳細な情報は [`docs/README.md`](docs/README.md) の索引から各ドキュメントを参照してください。
