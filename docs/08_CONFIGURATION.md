# 設定

## 設定ファイル

### `backend/app/core/config.py`（`Settings` クラス）

| フィールド | 型 | デフォルト値 | 説明 |
|---|---|---|---|
| `app_name` | `str` | `"YOLO Tuning Studio"` | アプリ名 |
| `version` | `str` | `"0.1.0"` | バージョン文字列 |
| `projects_root` | `Path` | `<リポジトリルート>/projects`（環境変数 `YTS_PROJECTS_ROOT` で上書き可） | 案件データ（画像・ラベル・学習結果）の格納先 |
| `cors_origins` | `list[str]` | `["http://localhost:5173", "http://127.0.0.1:5173"]` | CORSで許可するオリジン（Viteフロントエンドの開発サーバー） |
| `allowed_image_suffixes` | `tuple[str, ...]` | `(".jpg", ".jpeg", ".png", ".bmp", ".webp")` | 取り込み対応画像形式（フォルダ取り込み時の選択範囲） |
| `thumbnail_max_size` | `int` | `256` | サムネイル生成時の最大辺（px） |
| `min_resolution_warn` | `int` | `320` | 画像選別時の低解像度警告しきい値（最小辺、px未満で警告） |

`REPO_ROOT` はこのファイル自身の位置（`backend/app/core/config.py`）から3階層上として解決される。

### `frontend/vite.config.ts`

| 設定 | 値 |
|---|---|
| 開発サーバー port | `5173`（環境変数 `VITE_DEV_PORT` で上書き可） |
| 開発サーバー host | `true`（全インターフェースでリスン） |
| `/api` プロキシ先 | `http://localhost:8000`（環境変数 `VITE_BACKEND_PORT` で上書き可） |

`VITE_DEV_PORT` / `VITE_BACKEND_PORT` は、他アプリとのポート衝突を避けたい場合に指定する（未指定時は上記デフォルト値のまま）。1〜65535の整数以外（空文字・非数値・0・負数・65536以上・小数・`Infinity`等）を指定した場合はデフォルト値へフォールバックする。

### `frontend/tsconfig.json`

| 設定 | 値 |
|---|---|
| `target` | `ES2020` |
| `strict` | `true` |
| `noUnusedLocals` / `noUnusedParameters` | `true` |
| `jsx` | `react-jsx` |
| `moduleResolution` | `bundler` |
| `noEmit` | `true` |

## 環境変数

grep実測で確認された、このプロジェクトが読む環境変数は以下の8個。

| 環境変数 | 用途 | 参照元 |
|---|---|---|
| `YTS_PROJECTS_ROOT` | 案件データ格納先のパスを上書き | `backend/app/core/config.py` |
| `YTS_TRAIN_DRY_RUN` | `1`のとき学習ワーカーがUltralyticsを読み込まず空実行する | `backend/workers/train_worker.py` |
| `YTS_PREDICT_DRY_RUN` | `1`のとき推論ワーカーがUltralyticsを読み込まず空実行する | `backend/workers/predict_worker.py` |
| `YTS_VIDEO_DRY_RUN` | `1`のとき映像推論ワーカーがカメラ/Ultralyticsを使わず合成フレームを出力する | `backend/workers/predict_video_worker.py` |
| `YTS_CAPTURE_DRY_RUN` | `1`のとき撮影ワーカーが実カメラ/OpenCVを使わず合成フレームを出力する | `backend/workers/capture_worker.py` |
| `YTS_ONNX_DRY_RUN` | `1`のときONNXエクスポートワーカーがUltralyticsを読み込まずダミーの `model.onnx` を生成する | `backend/workers/onnx_export_worker.py` |
| `YTS_SAM_DRY_RUN` | `1`のときSAMを読み込まず、bbox/点から擬似polygon候補を生成する | `backend/app/services/sam_service.py` |
| `YTS_SAM_SIMULATE_NO_DEP` | `1`のときSAM依存未導入エラーを疑似的に発生させる（テスト用） | `backend/app/services/sam_service.py` |

いずれも `backend/tests/smoke_*.py` の各スモークテストが、実ML依存やGPU/カメラなしで疎通確認するために設定して使用している。

## Feature Flag

コード内に汎用的な Feature Flag 機構（LaunchDarkly等の外部サービス、または独自の `feature_flags.yaml` 等）は確認できない。`backend/app/routers/stubs.py` の `_STUB_FEATURES` は空リストであり、未実装機能の出し分け用スタブは現在使用されていない（コメント: 「全工程が実ルーターへ移行済み。スタブは無し」）。

## その他の設定ファイル

| ファイル | 説明 |
|---|---|
| `.gitignore` | Python/Node生成物、`projects/`、モデル重み拡張子（`*.pt`,`*.onnx`等）、`.env`系、IDE/OSファイル等を除外 |
| `requirements.txt` / `requirements-train.txt` / `backend/requirements-sam.txt` | Python依存関係（詳細は [`03_TECH_STACK.md`](03_TECH_STACK.md)） |
| `frontend/package.json` | Node依存関係・npm scripts |

## `.env` 等の秘密情報ファイル

リポジトリ内に `.env` / `.env.*` の実体は確認できない（`.gitignore` に除外パターンはあるが、実ファイルは存在しない）。本ドキュメント作成にあたり、このようなファイルの内容には触れていない。

## 確認できなかった項目

- `backend/app/core/config.py` 以外に、実行時に読み込まれる設定ファイル（`.ini`/`.toml`/`.json`形式の設定ファイル）は確認できない。
