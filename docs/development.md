# 開発ガイド

## セットアップ

QuickStart は [`../README.md`](../README.md) を参照。要点のみ再掲。

```powershell
# バックエンド（リポジトリ直下）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir backend --port 8000

# フロントエンド
cd frontend
npm install
npm run dev            # http://localhost:5173
```

- 学習/SAM/ONNX を使う場合は `requirements-train.txt` / `backend/requirements-sam.txt` を同じ `.venv` に追加導入。
- `--reload` は `.venv` を監視して過剰リロードになりやすいので、`--reload-dir backend/app` の併用を推奨。

## ディレクトリと責務

- `backend/app/routers/` … HTTP 層（検証と例外→ステータス変換のみ）
- `backend/app/services/` … ドメインロジック（ファイル入出力・集計・ジョブ起動）
- `backend/app/schemas/` … Pydantic 入出力モデル
- `backend/app/core/` … 設定（`config.py`）・パス解決（`paths.py`）
- `backend/workers/` … app 非依存の独立ワーカー（絶対パス引数のみ）
- `frontend/src/pages/` … 画面、`components/` … 共通部品、`api/client.ts` … API 呼び出し、`workflow.ts` … 工程定義

## テスト

バックエンドは `backend/tests/smoke_*.py` のスモークテスト（一時ディレクトリ + FastAPI TestClient）。
学習/推論など重い処理は `YTS_*_DRY_RUN=1` でダミー化して疎通を確認する。

```powershell
.\.venv\Scripts\python.exe backend\tests\smoke_dataset_builder.py
.\.venv\Scripts\python.exe backend\tests\smoke_segment_label_validation.py
.\.venv\Scripts\python.exe backend\tests\smoke_video_inference.py
# 変更した工程に対応する smoke_*.py を実行する
```

フロントは型チェック込みビルドで検証:

```powershell
cd frontend && npm run build     # tsc -b && vite build
```

## 作業者マニュアル（Operator Manual）のスクリーンショット再撮影

`docs/operator-manual.md` の画面キャプチャは `frontend/scripts/capture-operator-screenshots.mjs`
（Playwright + Chromium）で自動撮影する。UIの見た目・文言を変更した場合は、対応する画面を再撮影して
`docs/images/operator/` を更新すること。

```powershell
# 1) バックエンドを「秘密情報を含まない隔離環境」で起動する（実運用の projects/ には触れない）
$env:YTS_PROJECTS_ROOT = "$env:TEMP\yts_docs_scratch"
$env:YTS_TRAIN_DRY_RUN = "1"
$env:YTS_PREDICT_DRY_RUN = "1"
$env:YTS_VIDEO_DRY_RUN = "1"
$env:YTS_ONNX_DRY_RUN = "1"
$env:YTS_SAM_DRY_RUN = "1"
$env:YTS_CAPTURE_DRY_RUN = "1"
uvicorn app.main:app --app-dir backend --port 8000

# 2) フロントエンドを起動する（別ターミナル。ポート5173が別用途で使用中の場合は明示的に指定する）
cd frontend
npm run dev -- --port 5199

# 3) 撮影スクリプトを実行する（さらに別ターミナル）
cd frontend
node scripts/capture-operator-screenshots.mjs --base-url=http://localhost:5199 --sample-dir=<合成サンプル画像フォルダ>
```

- スクリプトは秘密情報を含まないテスト用プロジェクト（`operator_docs_demo`）を毎回新規作成して操作する。
  **実運用データが入ったプロジェクト（例: `projects/meter`）を対象に実行しないこと。**
- `--sample-dir` には実データではない合成画像（サムネイル用のダミー画像）を用意する。
- 出力は `docs/images/operator/` に上書き保存される。撮影後、**各画像を目視で確認し**、実IP・認証情報・
  ローカル絶対パス・個人情報が映り込んでいないことを確認してからコミットすること
  （URL入力欄等のplaceholderは本物の運用値を書かない。ダミー例には
  [RFC 5737](https://www.rfc-editor.org/rfc/rfc5737) の文書用予約アドレス、例: `192.0.2.10` を使う）。
- 撮影完了後は、バックエンドを通常設定（`YTS_PROJECTS_ROOT`未指定・DRY_RUN未設定）で再起動し、
  実運用環境に戻すこと。

## コーディング規約

- 既存のコードスタイル・命名・コメント量に合わせる（勝手な大規模リファクタリングをしない）。
- コメント/ドキュメントは日本語。
- 変数・関数は camelCase、React コンポーネントは PascalCase。
- 新規依存を追加する前に必要性を確認する。重い ML 依存は `requirements.txt` に入れない。
- `.env` などの秘密情報は読み書きしない。

## 新しい工程 / 機能を足すとき

1. `schemas/` に入出力モデルを追加。
2. `services/` にロジックを実装（例外は Validation/NotFound/Conflict を使い分け）。
3. `routers/` にエンドポイントを追加し、`app/main.py` で `include_router` する
   （**import と include の両方**が必要。片方忘れると 404 になる）。
4. 重い処理は `workers/` に独立スクリプトを作り、`subprocess.Popen` で起動。ドライラン用の環境変数を用意。
5. `backend/tests/smoke_<機能>.py` を追加。
6. フロントは `api/client.ts` にメソッド追加 → ページ/コンポーネント実装 → 必要なら `workflow.ts` / `App.tsx` に反映。

## 注意点（ハマりどころ）

- **ルーター登録**: `main.py` の import と `include_router` は両方必要。
- **パストラバーサル**: ファイル名を受け取る API は `core/paths.py` の解決 + 親ディレクトリ検証を通す。
- **文字コード**: ラベル/ログ読込は `utf-8-sig`。ワーカーは UTF-8 を明示。
- **クラス ID は append-only**: 学習後に既存クラスの並びを変えない（ラベル/モデルと不整合になる）。
- **Windows のファイルロック**: ログを開いたまま `rmtree` すると WinError32。`_safe_rmtree` 等でリトライ。
- **data.yaml の path は絶対パス（POSIX）**: Ultralytics が相対 path を自身の datasets_dir 基準で解決するため。
