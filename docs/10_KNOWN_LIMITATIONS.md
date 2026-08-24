# 既知の制限事項

## コード内のTODO/FIXME/HACKコメント

`backend/app/`, `backend/tests/`, `frontend/src/` 全体を `TODO`/`FIXME`/`HACK`/`XXX`/`Deprecated`/`deprecated` で検索した結果、**該当するコメントは1件も存在しない**（grep実測: 0件）。そのため本節はコード内マーカーからではなく、構造上・設計上確認できる制約を記載する。

## 未実装機能

`backend/app/routers/stubs.py` の `_STUB_FEATURES` は空リストであり、コメントに「全工程が実ルーターへ移行済み。スタブは無し（構造は将来工程の追加用に残す）」と明記されている。すなわち、`frontend/src/workflow.ts` の12工程はすべて `implemented: true` であり、**API側に未実装（501を返す）工程は現在存在しない**。

`stubs.py` のスタブ機構自体（501エラーを返す `_make_router`）は将来の工程追加のために構造だけ残されている。

## 技術的制約（実装から確認できるもの）

| 制約 | 内容 | 出典 |
|---|---|---|
| クラスID append-only | `classes.yaml` の `id` は0始まり・追加順。学習済みモデル/データセット作成後に既存クラスの並びを変更すると、既存ラベル・モデルとの整合性が崩れる | `README.md`, `docs/architecture.md` |
| 認証機能なし | 全APIエンドポイントに認証機構が存在しない。ローカル単一ユーザー前提の設計 | `docs/api-reference.md`, `backend/app/main.py`（認証系ミドルウェア無し） |
| CORS許可オリジンが固定 | `http://localhost:5173` / `http://127.0.0.1:5173` のみ許可。他ホストからのアクセスには設定変更が必要 | `backend/app/core/config.py` |
| データベース未使用 | リレーショナルDB/NoSQLを使わず、ファイルシステム（YAML/JSON/CSV）に永続化。大量データでのクエリ性能等は未検証 | [`07_DATABASE.md`](07_DATABASE.md) |
| Windowsのファイルロック | ログファイルを開いたまま `rmtree` すると `WinError32` が発生し得るため、`_safe_rmtree` 等でリトライ処理を行っている箇所がある | `docs/development.md` |
| `data.yaml` のパスは絶対POSIXパス | Ultralyticsが相対パスを自身の `datasets_dir` 基準で解決するため、絶対パスで記述する必要がある | `docs/development.md` |
| ワーカーはポーリング方式 | 学習・推論・映像・撮影・ONNXエクスポートの進行状況はWebSocket等ではなく、フロントエンドによる2秒間隔のポーリングで取得する | [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) |
| `job.json` の排他制御 | 映像推論・撮影は設定変更・停止・ワーカー自身の状態更新が同じ `job.json` を read-modify-write するため、ファイルロック（`job.json.lock`）で直列化している。ロック機構自体の性能特性（高頻度更新時の挙動等）は未検証 | [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) |
| 依存分離 | 学習/ONNX/SAM関連の重い依存（torch/ultralytics/opencv-python等）は `requirements.txt` に含まれず、別ファイルでの追加インストールが必要 | [`03_TECH_STACK.md`](03_TECH_STACK.md) |

## テスト面の制約

- バックエンドのテストは `backend/tests/smoke_*.py`（32ファイル）のスタンドアロンスクリプトのみで、pytest等の形式的なテストランナー・カバレッジ計測は導入されていない。
- フロントエンドに専用のテストランナー（Vitest/Jest等）は導入されておらず、`npm run build`（型チェック込みビルド）が実質的な検証手段となっている。
- `playwright` はdevDependenciesに存在するが、E2Eテストスイートとしての利用は確認できず、実際の用途は `frontend/scripts/capture-operator-screenshots.mjs`（マニュアル用スクリーンショット自動撮影）のみ。

## CI/CD・自動化の制約

- `.github/workflows/` が存在せず、CI/CDパイプラインは構築されていない。
- ESLint/Prettier/Ruff/Black/mypy等の静的解析・自動フォーマットツールが導入されておらず、コードスタイルの一貫性は開発者の手動確認に依存する。
- `Dockerfile`/`docker-compose.yml` が存在せず、コンテナ化された実行環境は提供されていない。

## 運用面の制約

- `README.md`/`docs/development.md` に記載の通り、作業者マニュアル（`docs/operator-manual.md`）のスクリーンショット再撮影時は実運用データ（実IP・認証情報等）が映り込まないよう手動確認が必要であり、この確認プロセスは自動化されていない。
- 撮影/映像機能はネットワークカメラURL（RTSP/HTTP等）を受け付けるが、認証情報を含むURLがログ・API応答に露出しないよう `masked_url` によるマスキングが行われている（詳細な脆弱性スコープの検証はこのプロジェクトでは確認できない）。

## 確認できなかった項目

- パフォーマンス上限（画像枚数・データセットサイズ等のスケーラビリティ上限）に関する明示的な記述はコード・ドキュメントに確認できない。
- ブラウザ互換性（Chromium以外のブラウザでの動作保証範囲）に関する記述は確認できない。
- セキュリティレビュー・脆弱性診断の実施記録は確認できない。
