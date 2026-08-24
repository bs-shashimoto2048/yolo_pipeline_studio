# AI開発ガイド

AIコーディングアシスタント（Claude Code等）がこのリポジトリで作業する際に守るべき事実ベースのルール。推測を含まず、実ソース・既存ドキュメント（`docs/development.md`, `docs/architecture.md`, `README.md`）で確認できた内容のみを記載する。

## プロジェクト概要（再掲）

YOLO Tuning Studio は、Ultralytics YOLO を用いた物体検出/インスタンスセグメンテーションのアノテーション〜学習〜評価〜ONNXエクスポートを一気通貫で行うローカルWebアプリ（FastAPI + React/Vite/TS/Konva）。詳細は [`00_PROJECT_OVERVIEW.md`](00_PROJECT_OVERVIEW.md)。

## ディレクトリの説明（AI作業観点）

| ディレクトリ | 役割 | AIが編集する頻度 |
|---|---|---|
| `backend/app/routers/` | HTTPエンドポイント層 | 機能追加時に編集 |
| `backend/app/services/` | ドメインロジック | 機能追加・修正時に編集 |
| `backend/app/schemas/` | Pydanticモデル | 機能追加時に編集 |
| `backend/app/core/` | 設定・パス解決 | 稀（新しいパス種別追加時のみ） |
| `backend/workers/` | 重い処理の独立スクリプト | 学習/推論/映像/撮影/ONNX関連の機能追加時 |
| `backend/tests/smoke_*.py` | スモークテスト | 機能追加・修正時は対応するテストも更新 |
| `frontend/src/pages/`, `components/` | UI | UI機能追加・修正時 |
| `frontend/src/api/client.ts` | APIクライアント | バックエンドAPI追加時に対応メソッドを追加 |
| `frontend/src/types.ts` | フロントエンド型定義 | APIスキーマ変更時に対応更新 |
| `docs/` | ドキュメント | 挙動を変えたら関連ドキュメントも更新 |
| `projects/` | 案件データ（Git管理外） | 通常は編集対象外（テスト時は一時ディレクトリを使う） |

## 編集してよい場所

- `backend/app/routers/`, `services/`, `schemas/`, `core/`（新規パス関数追加等）
- `backend/workers/`
- `backend/tests/smoke_*.py`（既存テストの更新、新規テストの追加）
- `frontend/src/`（`pages/`, `components/`, `api/client.ts`, `types.ts`, `workflow.ts`, `App.tsx`, `styles.css`）
- `docs/`（実装に追随したドキュメント更新）

## 編集してはならない・注意が必要な場所

- **`projects/`**: 案件データ（画像・ラベル・学習結果）。Git管理外（`.gitignore`）で実運用データが入る。テスト目的での操作は一時ディレクトリ（`YTS_PROJECTS_ROOT`で隔離）を使い、実運用プロジェクトには触れない。
- **`.env` / `.env.*` / `*.pem` / `*.key`**: `.gitignore` で除外される秘密情報ファイル。読み取り・編集をしない。
- **モデル重みファイル（`*.pt`, `*.onnx`, `*.engine` 等）**: `.gitignore` で除外対象。リポジトリにコミットしない。
- **`classes.yaml` のID順序**: 既存プロジェクトで学習・データセット作成済みの場合、IDの並び替え（追加順の変更）はラベル/モデルとの不整合を招くため、既存クラスの並びを変更しない（追加は末尾のみ）。
- **`backend/app/main.py` のルーター登録**: 新規ルーター追加時は import と `include_router` の両方を追加する（片方のみだと該当APIが404になる）。

## 実装ルール

1. **バックエンドで新しい工程/機能を追加する場合の手順**（`docs/development.md`）:
   1. `backend/app/schemas/` に入出力モデルを追加
   2. `backend/app/services/` にロジックを実装（例外は `XxxValidationError`(400) / `XxxNotFoundError`(404) / `XxxConflictError`(409) を使い分ける）
   3. `backend/app/routers/` にエンドポイントを追加し、`backend/app/main.py` で `include_router` する
   4. 重い処理は `backend/workers/` に独立スクリプトとして実装し、`subprocess.Popen` で起動。ドライラン用環境変数を用意する
   5. `backend/tests/smoke_<機能名>.py` を追加する
   6. フロントエンドは `frontend/src/api/client.ts` にメソッドを追加 → 画面/コンポーネントを実装 → 必要なら `frontend/src/workflow.ts` / `frontend/src/App.tsx` に反映する
2. 既存のコードスタイル・命名規則・コメント量に合わせる。大規模な自発的リファクタリングをしない。
3. コメント・docstringは日本語で書く（既存コードの一致率100%で確認済み）。
4. 新規の外部依存パッケージを追加する前に、必要性を確認する。重いML依存（torch/ultralytics等）は `requirements.txt`（軽量・必須）に入れず、`requirements-train.txt` 等の別ファイルに分離する。

## コーディング規約（詳細）

[`05_CODING_CONVENTIONS.md`](05_CODING_CONVENTIONS.md) を参照。要点:

- Python: snake_case（関数/変数）、PascalCase（クラス）、`from __future__ import annotations` を全ファイル先頭に付与。
- TypeScript: camelCase（関数/変数）、PascalCase（コンポーネント/インターフェース）。
- 例外は機能ごとに `<機能名>Error` を基底とした階層を作り、routers層でHTTPステータスに変換する。

## テスト方法

- バックエンド: 変更した機能に対応する `backend/tests/smoke_<機能名>.py` を実行する（`.\.venv\Scripts\python.exe backend\tests\smoke_xxx.py`）。pytestではなく直接実行するスタンドアロンスクリプト形式。
- フロントエンド: `cd frontend && npm run build`（`tsc -b && vite build`）で型チェック込みビルドが通ることを確認する。
- 学習・推論・映像・撮影・ONNXエクスポート等の重い処理は、対応する `YTS_*_DRY_RUN` 環境変数（[`08_CONFIGURATION.md`](08_CONFIGURATION.md)）を設定して実ML依存なしに疎通確認する。

## コミット前の確認事項

このプロジェクトに `pre-commit` フック、CI設定（`.github/workflows/`）、lintツール（ESLint/Ruff等）は存在しない（確認済み・不在）。そのため機械的な自動チェックはなく、以下を手動で確認する必要がある。

- [ ] 変更した機能に対応するスモークテスト（`backend/tests/smoke_*.py`）が通ること
- [ ] `cd frontend && npm run build` が成功すること（型エラーがないこと）
- [ ] `classes.yaml` のID順序を変更していないこと（既存プロジェクトの場合）
- [ ] 新規ルーターを追加した場合、`backend/app/main.py` に import と `include_router` の両方を追加したこと
- [ ] 秘密情報（実IP・認証情報・個人情報）をコード/ドキュメント/スクリーンショットに含めていないこと（`docs/development.md` の運用マニュアル再撮影手順を参照）
- [ ] `projects/` 配下の実運用データを変更・削除していないこと

## PRチェック

このプロジェクトには `.github/` ディレクトリ（Issue/PRテンプレート、CI等）が存在しない。PRの自動チェック項目は確認できない。上記「コミット前の確認事項」を手動で満たしていることが実質的な基準となる。

## 推奨ワークフロー

1. `task.md` や既存Issue（GitHub）で要件を確認する。
2. 関連する既存実装（同種の工程のrouter/service/schema/worker）を読み、パターンを踏襲する。
3. 上記「実装ルール」の手順で変更を行う。
4. 対応するスモークテスト・`npm run build` で検証する。
5. 変更内容に応じて `docs/` 配下の関連ドキュメントを更新する。

## 重要な設計思想（確認できる範囲）

- **軽量/重量依存の分離**: アノテーション等の軽作業がGPU/学習ライブラリのインストールを要求しないよう、`requirements.txt`（軽量）と `requirements-train.txt`/`backend/requirements-sam.txt`（重量・別管理）を分離している。
- **非破壊性**: `raw/` → `processed/` の前処理、画像選別の `included/excluded/review` 管理など、元データを壊さない設計が複数箇所で確認できる（[`00_PROJECT_OVERVIEW.md`](00_PROJECT_OVERVIEW.md) 参照）。
- **ワーカー分離による非ブロッキング処理**: 学習・推論・映像・撮影・ONNXエクスポートは `subprocess.Popen` による別プロセス実行 + `job.json` ポーリングで、APIサーバーをブロックしない構成（[`01_ARCHITECTURE.md`](01_ARCHITECTURE.md)）。
- **クラスID append-only**: データ整合性維持のための明示的な制約（`README.md`, `docs/architecture.md`）。

## 確認できなかった項目

- PR/Issueテンプレート、CI上の自動チェック内容（`.github/` が存在しないため）。
- 自動フォーマッタ/静的解析ツールの導入予定（設定ファイルが存在しないため方針は不明）。
