# データベース

## 確認結果: データベースは存在しない

以下の観点で確認したが、いずれも該当なし。

| 確認観点 | 確認方法 | 結果 |
|---|---|---|
| ORM / DBドライバの依存 | `requirements.txt` / `requirements-train.txt` / `backend/requirements-sam.txt` / `frontend/package.json` を確認 | SQLAlchemy, Prisma, Django ORM 等の記載なし |
| DB接続文字列・設定 | `backend/app/core/config.py`（`Settings` クラス）を確認 | DB関連の設定項目なし（`projects_root`, `cors_origins` 等のみ） |
| マイグレーションファイル | リポジトリ全体を `alembic`/`migration` 等で検索 | 該当ファイルなし |
| DBエンジンの文字列 | リポジトリ全体を `sqlite`/`postgres`/`mysql`/`mongodb` 等で検索（大文字小文字無視） | 該当なし |

## 実際のデータ永続化方式

このアプリケーションはリレーショナルDB/NoSQLを使わず、**プロジェクトごとのファイルシステム上のファイル**（YAML/JSON/CSV/画像バイナリ）に永続化する構成である（`backend/app/core/paths.py`, `docs/architecture.md`）。

| データ種別 | 保存形式 | 保存先（`projects/<name>/` 配下） |
|---|---|---|
| プロジェクト概要 | YAML | `project.yaml` |
| クラス定義 | YAML | `classes.yaml` |
| アノテーション（ラベル） | YOLO形式テキスト（`*.txt`, utf-8-sig） | `annotations/labels/` |
| 画像選別結果 | JSON | `selection/selection.json` |
| データセット定義 | YAML（`data.yaml`）+ JSON（metadata） | `datasets/<dataset>/` |
| 学習ジョブ状態 | JSON（`job.json`）+ CSV（`results.csv`） | `runs/train/<job_id>/` |
| 推論結果 | JSON | `predictions/<id>/results.json` |
| 撮影ソース定義 | JSON | `capture/sources.json` |
| 映像取得済みURL履歴 | JSON | `video/known_sources.json` |
| SAM設定 | JSON | `sam/settings.json` |
| 採用モデル参照 | JSON | `models/selected_model.json` |

詳細な全体レイアウトは [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) の「データフロー」節を参照。

## 確認できなかった項目

該当なし（本ファイルの主題は「DBが存在しないこと」自体の確認であり、否定的事実として上記の通り確認済み）。
