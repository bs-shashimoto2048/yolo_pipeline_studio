# YOLO Tuning Studio

Ultralytics YOLO を用いたコンピュータビジョンモデル開発を、**アノテーションから学習・
評価・ONNX エクスポートまで一気通貫**で行うローカル Web アプリケーションです。
物体検出（BBOX）と**インスタンスセグメンテーション**の両タスクに対応します。

- バックエンド: **FastAPI**（Python）
- フロントエンド: **React + Vite + TypeScript + Konva**（アノテーション描画）
- 学習・推論は **別プロセスのワーカー**として実行され、実行中も API は応答します。

> 重い ML ライブラリ（ultralytics / torch など）は起動に必須の `requirements.txt` には含めず、
> `requirements-train.txt` / `backend/requirements-sam.txt` で**別管理**しています。
> アノテーション等の作業は GPU/学習ライブラリなしでも動作します。

---

## 主な機能（ワークフロー）

サイドバーの工程順に、1つのプロジェクトを最初から最後まで進められます（全 12 工程）。

1. **プロジェクト準備** — 概要 / クラス設計（色付き）/ 画像取り込み（フォルダ一括・個別）
2. **画像選別** — 低品質（暗い・明るい・ブレ・小さい）・重複を検出し included/excluded/review 管理（非破壊）
3. **前処理** — リサイズ・明るさ/コントラスト・グレースケール・2値化・シャープ・CLAHE（`raw`→`processed`、非破壊）
4. **アノテーション** — BBOX / ポリゴン（輪郭）作成・編集、**SAM 補助**、ズーム/パン、EXIF 対応
5. **データセット作成** — train/val/test 分割・`data.yaml` 生成（作成前にラベル品質チェック）
6. **学習** — Ultralytics YOLO 学習（データ拡張プリセットを同画面で設定）
7. **評価** — results.csv サマリー・推移グラフ・成果物画像・メトリクス表
8. **推論テスト** — 画像/映像（カメラ）推論、結果画像と検出一覧
9. **誤検出分析** — GT と予測の IoU 比較（TP/FP/FN/class_mismatch）、クラス別統計
10. **実験履歴** — 学習ジョブ単位で条件と結果を比較
11. **モデル管理** — best/last の一覧・採用設定・配布パッケージ・ONNX エクスポート
12. **レポート** — 全工程を集約した JSON / Markdown レポート出力

詳細な設計は [`docs/`](docs/) を参照してください。

---

## ディレクトリ構成

```
yolo_pipeline_studio/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI エントリポイント
│   │   ├── core/             # 設定・パス解決
│   │   ├── routers/          # API エンドポイント（工程別）
│   │   ├── services/         # ドメインロジック
│   │   └── schemas/          # Pydantic モデル
│   ├── workers/              # 学習/推論/ONNX/映像の別プロセスワーカー
│   ├── tests/                # スモークテスト
│   ├── requirements-sam.txt  # SAM 補助アノテーション用の依存
├── frontend/                 # React + Vite + TS + Konva
├── docs/                     # 設計・仕様ドキュメント
├── projects/                 # 案件データ（画像/ラベル/学習結果/モデル）※Git 管理外
├── requirements.txt          # バックエンド起動に必要な軽量依存のみ
└── requirements-train.txt    # 学習/ONNX 用の重い依存（別管理）
```

案件データの格納先は環境変数 `YTS_PROJECTS_ROOT` で変更できます（未指定時はリポジトリ直下の `projects/`）。

---

## 動作要件

- Python 3.10 以上
- Node.js 18 以上
- （学習・SAM・ONNX を使う場合のみ）追加の ML 依存。GPU 学習は NVIDIA + CUDA 対応 PyTorch。

---

## QuickStart

### 1. バックエンド（API）

```powershell
# リポジトリ直下で
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell（macOS/Linux は source .venv/bin/activate）
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir backend --port 8000
```

- API: http://localhost:8000
- API ドキュメント（Swagger UI）: http://localhost:8000/docs

> `--reload` 使用時は `.venv` を監視して過剰リロードにならないよう、
> 開発中は `--reload-dir backend/app` の併用を推奨します。

### 2. フロントエンド（UI）

```powershell
cd frontend
npm install
npm run dev
```

- 開発サーバー: http://localhost:5173 （`/api` は自動で 8000 にプロキシ）
- ブラウザで開き、トップ画面からプロジェクトを作成してワークフローを開始します。

本番用ビルドは `npm run build`（出力: `frontend/dist/`）。

---

## 学習 / SAM / ONNX 機能の導入（任意）

作業（取り込み・アノテーション等）だけなら不要です。**学習・SAM 補助・ONNX 変換**を使うときに、
同じ `.venv` へ追加導入します。

### 学習・ONNX エクスポート

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-train.txt
```

### SAM 補助アノテーション

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-sam.txt
```

### GPU（NVIDIA + CUDA）で学習する場合

CPU 版が入らないよう、**先に** PyTorch 公式インデックスから CUDA 版 torch を導入してから
`ultralytics` を入れます（例: CUDA 12.x → `cu128`。環境に応じて `cu126` 等へ）。

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -U ultralytics
```

導入確認:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print('cuda:', torch.cuda.is_available())"
```

> ドライバが CUDA 12.2 対応でも cu128/cu126 が動作する場合があります（CUDA 12 系はマイナー互換）。

---

## テスト（スモーク）

バックエンドの各サービスは、一時ディレクトリ + TestClient で動く**スモークテスト**を備えています
（`YTS_*_DRY_RUN` 環境変数で学習/推論の重い処理をダミー化）。

```powershell
.\.venv\Scripts\python.exe backend\tests\smoke_dataset_builder.py
.\.venv\Scripts\python.exe backend\tests\smoke_analysis.py
.\.venv\Scripts\python.exe backend\tests\smoke_video_inference.py
# ... backend/tests/ 配下の各 smoke_*.py
```

フロントエンドは型チェック込みビルドで検証します。

```powershell
cd frontend
npm run build
```

---

## データと安全性に関する注意

- **モデル重み（`*.pt` / `*.onnx` 等）と `projects/`（案件データ）は Git 管理外**です（`.gitignore` 参照）。
- 画像回転などの編集を除き、`raw` 画像は原則非破壊で扱います（前処理は `processed` へ別出力）。
- **クラス ID は追加順（append-only）** が前提です。学習・データセット作成後に並び替えると、
  既存ラベル・学習済みモデル・作成済みデータセットとの整合が崩れるため、既存クラスの並びは変更しないでください。

---

## ドキュメント

- [`docs/architecture.md`](docs/architecture.md) — システム構成・データレイアウト・ワーカー方式・設計方針
- [`docs/api-reference.md`](docs/api-reference.md) — REST API エンドポイント一覧
- [`docs/development.md`](docs/development.md) — 開発セットアップ・規約・テスト・拡張手順
