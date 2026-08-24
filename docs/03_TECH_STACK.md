# 技術スタック

バージョンは `frontend/package.json` / `frontend/package-lock.json` / `requirements.txt` / `requirements-train.txt` / `backend/requirements-sam.txt` に記載の値。ロックファイルに解決済みバージョンがある場合はそれを併記する。

## バックエンド（軽量・常時必須）— `requirements.txt`

| ライブラリ | 用途 | 使用箇所 |
|---|---|---|
| fastapi (>=0.110) | Web APIフレームワーク本体 | `backend/app/main.py`, `backend/app/routers/*.py` |
| uvicorn[standard] (>=0.29) | ASGIサーバー | `README.md` QuickStart（起動コマンド） |
| pydantic (>=2.6) | リクエスト/レスポンスモデル・検証 | `backend/app/schemas/*.py` |
| python-multipart (>=0.0.9) | multipart/form-data（画像アップロード）の解析 | `backend/app/routers/images.py`（画像アップロード系） |
| PyYAML (>=6.0) | `project.yaml`/`classes.yaml`/`data.yaml` の読み書き | `backend/app/core/`, `backend/app/services/*.py` |
| Pillow (>=10.0) | 画像処理（サムネイル生成・前処理・EXIF対応） | `backend/app/services/image_service.py`, `preprocess_service.py` |

## バックエンド（学習・ONNX、別管理）— `requirements-train.txt`

| ライブラリ | 用途 |
|---|---|
| ultralytics | YOLO学習・評価・推論本体 |
| torch / torchvision / torchaudio | 学習・推論の実行基盤（CUDA対応、コメントにインストール手順記載） |
| onnx | ONNXモデル形式の読み書き |
| onnxruntime | ONNXモデルの推論実行 |
| onnxslim | ONNXモデルの最適化・軽量化 |

`README.md` の記載により、GPU/CUDA環境向けの個別インストール手順がコメントとして残されている（バージョン固定のPyTorchビルドをCUDA種別ごとに案内）。

## バックエンド（SAM補助アノテーション、別管理）— `backend/requirements-sam.txt`

| ライブラリ | 用途 |
|---|---|
| ultralytics | SAMモデルの実行 |
| opencv-python | 画像処理（SAM補助アノテーション用） |

## フロントエンド — `frontend/package.json` / `package-lock.json`

### dependencies

| ライブラリ | package.json指定 | ロック解決版 | 用途 |
|---|---|---|---|
| react | ^18.3.1 | 18.3.1 | UIライブラリ本体 |
| react-dom | ^18.3.1 | 18.3.1 | DOMレンダリング |
| react-router-dom | ^6.26.0 | 6.30.4 | SPAルーティング（`frontend/src/App.tsx`） |
| konva | ^9.3.0 | 9.3.22 | Canvas描画エンジン（アノテーション用） |
| react-konva | ^18.2.10 | 18.2.16 | KonvaのReactバインディング |
| recharts | ^2.12.0 | 2.15.4 | グラフ表示（評価/実験履歴画面） |

### devDependencies

| ライブラリ | package.json指定 | ロック解決版 | 用途 |
|---|---|---|---|
| typescript | ^5.5.4 | 5.9.3 | 型チェック・トランスパイル |
| vite | ^5.4.0 | 5.4.21 | 開発サーバー・ビルドツール |
| @vitejs/plugin-react | ^4.3.1 | 不明（ロックファイル未個別確認） | ViteのReactサポート（Fast Refresh等） |
| @types/react | ^18.3.3 | 不明（同上） | React型定義 |
| @types/react-dom | ^18.3.0 | 不明（同上） | react-dom型定義 |
| playwright | ^1.62.1 | 不明（同上） | E2E/スクリーンショット自動化（`frontend/scripts/capture-operator-screenshots.mjs`） |

## ライブラリを使わず自前実装している領域（確認できた範囲）

- 状態管理: Redux/Zustand/Recoil/MobX 等は不使用。React標準の `useState`/`useEffect` のみ（[`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) 参照）。
- HTTP通信: axios等は不使用。標準の `fetch()` を `frontend/src/api/client.ts` に集約。
- CSS: Tailwind/styled-components等のCSSフレームワークは `package.json` に存在せず、単一の `frontend/src/styles.css`（CSS変数によるデザイントークン運用）。

## 確認できなかった項目

- `@vitejs/plugin-react` / `@types/react` / `@types/react-dom` / `playwright` の `package-lock.json` 上の厳密解決バージョン（`package.json` の指定バージョン範囲のみ確認）。
