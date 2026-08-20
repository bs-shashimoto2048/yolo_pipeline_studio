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
| PUT | `/api/projects/{name}/selection/images/{image_id}` | status 変更（included/review。excluded は不可） |
| POST | `/api/projects/{name}/selection/images/{image_id}/rotate` | 画像回転（raw/processed 両方に適用） |
| DELETE | `/api/projects/{name}/selection/images/{image_id}` | 画像を完全削除（raw/processed本体・サムネイル・ラベルを含む。元に戻せない） |
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
| GET | `/api/projects/{name}/video-sources` | 映像取得に成功した既知URLの一覧（新しい順） |
| DELETE | `/api/projects/{name}/video-sources?url=` | 記憶済みURLを1件削除 |
| GET | `/api/projects/{name}/video-jobs` | 映像ジョブ一覧 |
| POST | `/api/projects/{name}/video-jobs` | 映像推論開始（`source_type=camera\|url`。urlはRTSP/HTTP・MJPEG） |
| GET | `/api/projects/{name}/video-jobs/{vid}` | 詳細（`resolved_source_url`等を含む） |
| PATCH | `/api/projects/{name}/video-jobs/{vid}/settings` | 実行中ジョブのFPS/推論パラメータを再接続なしで即時変更 |
| POST | `/api/projects/{name}/video-jobs/{vid}/stop` | 停止 |
| GET | `/api/projects/{name}/video-jobs/{vid}/stream` | MJPEG ライブ配信 |

## 撮影ソース（カメラ・URLからの静止画撮影）

プロジェクト準備画面の「カメラ・URLで撮影」タブに対応する。撮影ソース（カメラ/URLの定義）はプロジェクトに保存され、セッション単位で定期撮影・都度撮影を行う。

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/capture-sources` | 保存済み撮影ソース一覧 |
| POST | `/api/projects/{name}/capture-sources` | 撮影ソース追加（label/source_type/camera_index or source_url） |
| PATCH | `/api/projects/{name}/capture-sources/{source_id}` | 撮影ソース更新 |
| DELETE | `/api/projects/{name}/capture-sources/{source_id}` | 撮影ソース削除 |
| GET | `/api/projects/{name}/capture-sessions` | 撮影セッション一覧 |
| POST | `/api/projects/{name}/capture-sessions` | 撮影セッション開始（自動撮影間隔・video_fps等） |
| GET | `/api/projects/{name}/capture-sessions/{sid}` | セッション詳細（captured_count・次回自動撮影時刻等） |
| POST | `/api/projects/{name}/capture-sessions/{sid}/capture` | 「今すぐ撮影」（撮影完了まで短時間待って結果を返す） |
| POST | `/api/projects/{name}/capture-sessions/{sid}/stop` | セッション停止 |
| GET | `/api/projects/{name}/capture-sessions/{sid}/frame` | 最新1フレーム取得（都度取得・接続を保持しないポーリング用） |
| GET | `/api/projects/{name}/capture-sessions/{sid}/stream` | MJPEG ライブ配信（単一ソースの詳細表示用） |

## SAM 補助アノテーション

アノテーション画面でのポリゴン候補自動生成に対応する（`backend/requirements-sam.txt` の追加導入が必要）。

| Method | Path | 概要 |
|---|---|---|
| GET | `/api/projects/{name}/sam/settings` | SAM設定取得 |
| PUT | `/api/projects/{name}/sam/settings` | SAM設定保存 |
| POST | `/api/projects/{name}/images/{image_id}/sam/propose` | クリック等からポリゴン候補を提案 |

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
