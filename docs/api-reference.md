# API リファレンス

ベース URL: `http://localhost:8000`。全エンドポイントは `/api` 配下。
対話的な仕様は起動後の Swagger UI（`/docs`）でも確認できます。

- 認証はなし（ローカル単一ユーザー前提）。
- エラーは `400`（入力不正）/ `404`（不存在）/ `409`（競合）を JSON `{"detail": "..."}` で返す。
- `<name>` はプロジェクト名（英数・`_`・`-`）。

## メタ

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/health` | 稼働確認 |

## プロジェクト / クラス

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects` | プロジェクト一覧 |
| POST | `/api/projects` | 作成（name / description / task） |
| GET | `/api/projects/{name}` | 概要（画像/ラベル/クラス/学習回数） |
| DELETE | `/api/projects/{name}` | 削除（実行中ジョブがあると 409） |
| GET | `/api/projects/{name}/classes` | クラス一覧 |
| PUT | `/api/projects/{name}/classes` | クラス保存（id/name/color） |

## 画像 / アノテーション

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/images?source=raw\|processed\|auto` | 画像一覧 |
| POST | `/api/projects/{name}/images` | 個別アップロード |
| POST | `/api/projects/{name}/images/import-folder` | フォルダ一括取り込み |
| GET | `/api/projects/{name}/images/{filename}?source=` | 画像本体 |
| GET | `/api/projects/{name}/images/{filename}/thumbnail?source=` | サムネイル |
| GET | `/api/projects/{name}/images/{image_id}/annotations` | ラベル取得 |
| PUT | `/api/projects/{name}/images/{image_id}/annotations` | ラベル保存（detect/segment） |
| POST | `/api/projects/{name}/labels/validate` | ラベル品質チェック |

## 画像選別 / 前処理

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/selection` | 選別結果取得 |
| POST | `/api/projects/{name}/selection/run` | 選別実行（低品質・重複検出） |
| PUT | `/api/projects/{name}/selection/images/{image_id}` | status 変更（included/excluded/review） |
| POST | `/api/projects/{name}/selection/images/{image_id}/rotate` | 画像回転（raw/processed 両方に適用） |
| GET | `/api/projects/{name}/preprocess` | 前処理情報 |
| POST | `/api/projects/{name}/preprocess/run` | 前処理実行（raw→processed） |
| POST | `/api/projects/{name}/preprocess/preview` | Before/After プレビュー生成 |
| GET | `/api/projects/{name}/preprocess/preview-image/{filename}` | プレビュー画像 |

## データセット / データ拡張

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/datasets` | データセット一覧 |
| POST | `/api/projects/{name}/datasets` | 作成（train/val/test 分割・data.yaml 生成） |
| GET | `/api/projects/{name}/augmentation/presets` | 拡張プリセット一覧 |
| GET | `/api/projects/{name}/augmentation/presets/{preset_name}` | プリセット取得 |
| PUT | `/api/projects/{name}/augmentation/presets/{preset_name}` | プリセット保存 |
| DELETE | `/api/projects/{name}/augmentation/presets/{preset_name}` | プリセット削除（builtin 不可） |

## 学習 / 評価

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/train-jobs` | 学習ジョブ一覧 |
| POST | `/api/projects/{name}/train-jobs` | 学習開始 |
| GET | `/api/projects/{name}/train-jobs/{job_id}` | ジョブ詳細 |
| GET | `/api/projects/{name}/train-jobs/{job_id}/logs` | 学習ログ |
| GET | `/api/projects/{name}/train-jobs/{job_id}/evaluation` | 評価サマリー |
| GET | `/api/projects/{name}/train-jobs/{job_id}/metrics` | results.csv メトリクス |
| GET | `/api/projects/{name}/train-jobs/{job_id}/artifacts/{filename}` | 成果物画像 |

## 推論 / 誤検出分析 / 映像

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/predict-jobs` | 推論ジョブ一覧 |
| POST | `/api/projects/{name}/predict-jobs` | 推論開始 |
| GET | `/api/projects/{name}/predict-jobs/{id}` | 詳細 |
| GET | `/api/projects/{name}/predict-jobs/{id}/logs` | ログ |
| GET | `/api/projects/{name}/predict-jobs/{id}/results` | 結果 |
| GET | `/api/projects/{name}/predict-jobs/{id}/images/{filename}` | 結果画像 |
| POST | `/api/projects/{name}/predict-jobs/{id}/analysis` | 誤検出分析の実行 |
| GET | `/api/projects/{name}/predict-jobs/{id}/analysis` | 分析結果取得 |
| GET | `/api/projects/{name}/cameras` | 接続カメラ列挙 |
| GET | `/api/projects/{name}/video-jobs` | 映像ジョブ一覧 |
| POST | `/api/projects/{name}/video-jobs` | 映像推論開始 |
| GET | `/api/projects/{name}/video-jobs/{vid}` | 詳細 |
| POST | `/api/projects/{name}/video-jobs/{vid}/stop` | 停止 |
| GET | `/api/projects/{name}/video-jobs/{vid}/stream` | MJPEG ライブ配信 |

## 実験履歴 / モデル管理 / 配布 / ONNX

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/experiments` | 実験（学習ジョブ）一覧 |
| GET | `/api/projects/{name}/experiments/{experiment_id}` | 実験詳細 |
| GET | `/api/projects/{name}/models` | モデル一覧（best/last） |
| GET | `/api/projects/{name}/models/selected` | 採用モデル取得 |
| PUT | `/api/projects/{name}/models/selected` | 採用モデル設定 |
| GET | `/api/projects/{name}/models/{train_job_id}/{weight_type}` | モデル詳細 |
| GET | `/api/projects/{name}/model-export/{train_job_id}/{weight}/download` | 重み(.pt)ダウンロード |
| POST | `/api/projects/{name}/model-export/{train_job_id}/{weight}/package` | 配布パッケージ作成（ONNX 同梱可） |
| GET | `/api/projects/{name}/model-packages/{package_id}/download` | パッケージ(zip)ダウンロード |
| POST | `/api/projects/{name}/onnx-exports` | ONNX エクスポート開始 |
| GET | `/api/projects/{name}/onnx-exports` | エクスポート一覧 |
| GET | `/api/projects/{name}/onnx-exports/{export_job_id}` | 詳細 |
| GET | `/api/projects/{name}/onnx-exports/{export_job_id}/logs` | ログ |
| GET | `/api/projects/{name}/onnx-exports/{export_job_id}/download` | ONNX ダウンロード |

## レポート

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/reports` | レポート一覧 |
| POST | `/api/projects/{name}/reports` | 生成（format=json/markdown/both） |
| GET | `/api/projects/{name}/reports/{report_id}` | 詳細 |
| GET | `/api/projects/{name}/reports/{report_id}/download?format=` | ダウンロード |
