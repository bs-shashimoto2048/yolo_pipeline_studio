# プロジェクト概要

## プロジェクト概要

YOLO Tuning Studio は、Ultralytics YOLO を用いたコンピュータビジョンモデル開発を、
**アノテーションから学習・評価・ONNX エクスポートまで一気通貫**で行うローカル Web アプリケーションです。
物体検出（BBOX）と**インスタンスセグメンテーション**の両タスクに対応します（`README.md`）。

- バックエンド: FastAPI（Python）
- フロントエンド: React + Vite + TypeScript + Konva（アノテーション描画）
- 学習・推論・映像処理は別プロセスのワーカーとして実行され、実行中も API は応答する（`README.md`, `docs/architecture.md`）

## 解決する課題

`README.md` の記述に基づく。

- 重い ML ライブラリ（ultralytics / torch）を起動必須の依存に含めないことで、アノテーション等の作業を GPU/学習環境なしでも行えるようにする。
- 画像取り込みから学習・評価・モデル配布・ONNX エクスポートまでを 1 つのローカル Web アプリで一気通貫に行う。

## 主な機能（ワークフロー）

`frontend/src/workflow.ts` の `WORKFLOW_STEPS` に定義された全 12 工程（すべて `implemented: true`）。

| No | path | ラベル |
|---|---|---|
| 1 | `setup` | プロジェクト準備 |
| 2 | `selection` | 画像選別 |
| 3 | `preprocess` | 前処理 |
| 4 | `annotate` | アノテーション |
| 5 | `dataset` | データセット作成 |
| 6 | `train` | 学習 |
| 7 | `eval` | 評価 |
| 8 | `infer` | 推論テスト |
| 9 | `analysis` | 誤検出分析 |
| 10 | `experiments` | 実験履歴 |
| 11 | `models` | モデル管理 |
| 12 | `reports` | レポート |

`README.md` に記載された各工程の内容:

1. **プロジェクト準備** — 概要 / クラス設計（色付き）/ 画像取り込み（フォルダ一括・個別・カメラ/ネットワークカメラURLからの撮影）
2. **画像選別** — 低品質（暗い・明るい・ブレ・小さい）・重複を検出し included/excluded/review 管理（非破壊）
3. **前処理** — リサイズ・明るさ/コントラスト・グレースケール・2値化・シャープ・CLAHE（`raw`→`processed`、非破壊）
4. **アノテーション** — BBOX / ポリゴン（輪郭）作成・編集、SAM 補助、ズーム/パン、EXIF 対応
5. **データセット作成** — train/val/test 分割・`data.yaml` 生成（作成前にラベル品質チェック）
6. **学習** — Ultralytics YOLO 学習（データ拡張プリセットを同画面で設定）
7. **評価** — results.csv サマリー・推移グラフ・成果物画像・メトリクス表
8. **推論テスト** — 画像推論、映像（ローカルカメラ/ネットワークカメラURL）へのリアルタイム推論
9. **誤検出分析** — GT と予測の IoU 比較（TP/FP/FN/class_mismatch）、クラス別統計
10. **実験履歴** — 学習ジョブ単位で条件と結果を比較
11. **モデル管理** — best/last の一覧・採用設定・配布パッケージ・ONNX エクスポート
12. **レポート** — 全工程を集約した JSON / Markdown レポート出力

## 使用技術

詳細は [`03_TECH_STACK.md`](03_TECH_STACK.md) を参照。

- バックエンド: FastAPI, Pydantic v2, uvicorn（`requirements.txt`）
- フロントエンド: React 18, Vite, TypeScript, Konva / react-konva, react-router-dom, recharts（`frontend/package.json`）
- 学習: Ultralytics YOLO, PyTorch（`requirements-train.txt`、別管理）
- SAM 補助アノテーション: Ultralytics, opencv-python（`backend/requirements-sam.txt`、別管理）

## ディレクトリ概要

詳細は [`02_DIRECTORY_STRUCTURE.md`](02_DIRECTORY_STRUCTURE.md) を参照。

```text
yolo_pipeline_studio/
├── backend/        FastAPI アプリ（app/）・ワーカー（workers/）・スモークテスト（tests/）
├── frontend/       React + Vite + TS + Konva の SPA
├── docs/           設計・仕様ドキュメント
├── projects/       案件データ（画像/ラベル/学習結果/モデル）※Git 管理外
├── scripts/        運用補助スクリプト（Git 未追跡。`apply_readings_*.py` 等）
├── requirements.txt        バックエンド起動に必要な軽量依存のみ
└── requirements-train.txt  学習/ONNX 用の重い依存（別管理）
```
（`README.md` のディレクトリ構成節、および実際のディレクトリ走査結果より）

## 実行方法

`README.md` QuickStart 節より（詳細は [`04_BUILD_AND_RUN.md`](04_BUILD_AND_RUN.md)）。

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
- フロントエンド開発サーバー: `http://localhost:5173`（`/api` は Vite dev proxy で 8000 へ転送。`frontend/vite.config.ts`）

## ビルド方法

`frontend/package.json` の `scripts` より。

```powershell
cd frontend
npm run build   # 実体: tsc -b && vite build。出力先: frontend/dist/
```

バックエンドに専用のビルドコマンドは確認できない（Python はビルド不要でそのまま実行）。

## テスト方法

`README.md` / `docs/development.md` より。

```powershell
# バックエンド: backend/tests/ 配下のスモークテストを個別に実行する
.\.venv\Scripts\python.exe backend\tests\smoke_dataset_builder.py
.\.venv\Scripts\python.exe backend\tests\smoke_video_inference.py
# ... backend/tests/ 配下の他の smoke_*.py も同様（全32ファイル）

# フロントエンド: 型チェック込みビルドで検証
cd frontend
npm run build
```

学習/推論などの重い処理は `YTS_*_DRY_RUN` 環境変数でダミー化して疎通確認する（詳細は [`08_CONFIGURATION.md`](08_CONFIGURATION.md)）。
