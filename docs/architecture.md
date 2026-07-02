# アーキテクチャ / 設計仕様

YOLO Tuning Studio の内部構成・データレイアウト・設計方針をまとめたコーディング仕様書です。

## 1. 全体構成

```
ブラウザ (React SPA, :5173)
   │  /api/* を Vite dev proxy 経由で :8000 へ
   ▼
FastAPI (:8000)  ── routers → services → (schemas / core)
   │  学習・推論・ONNX・映像は subprocess で別プロセス起動
   ▼
workers/*.py（独立スクリプト）── Ultralytics / OpenCV を使用
   │
   ▼
projects/<name>/ 配下のファイル（画像・ラベル・data.yaml・runs・predictions 等）
```

- **フロントエンド**: React 18 + Vite + TypeScript + Konva（アノテーション描画）、recharts（グラフ）。
- **バックエンド**: FastAPI + Pydantic v2。ルーターは工程別に分割。
- **重い処理は別プロセス化**: 学習/推論/ONNX変換/映像推論は `subprocess.Popen` でワーカーを起動し、
  FastAPI 本体はノンブロッキングを保つ。進捗は `job.json` とログファイルをポーリングして反映。

## 2. バックエンドのレイヤー

| 層 | 位置 | 役割 |
|---|---|---|
| routers | `backend/app/routers/` | HTTP エンドポイント。入力検証と例外→HTTPステータス変換のみ。 |
| services | `backend/app/services/` | ドメインロジック本体（ファイル入出力・集計・ジョブ起動）。 |
| schemas | `backend/app/schemas/` | Pydantic の入出力モデル。 |
| core | `backend/app/core/` | `config.py`（設定）、`paths.py`（プロジェクト配下のパス解決とトラバーサル防止）。 |
| workers | `backend/workers/` | app に依存しない独立スクリプト。絶対パス引数のみで動く。 |

**例外方針**: services は `XxxValidationError`(400) / `XxxNotFoundError`(404) / `XxxConflictError`(409) を投げ、
routers が対応する HTTP ステータスへ変換する。

## 3. ワーカー方式（学習・推論・ONNX・映像）

- services が `job.json`（status=queued）を書き、`subprocess.Popen` でワーカーを起動、
  標準出力/エラーをログファイルへリダイレクト。
- ワーカーは処理の進行に応じて `job.json` の status を `running`→`completed`/`failed`/`stopped` に更新。
- フロントは 2 秒間隔でポーリングして状態・ログ・結果を取得（完了/失敗で停止）。
- **ドライラン**用環境変数（テストや依存未導入時の疎通確認）:
  `YTS_TRAIN_DRY_RUN` / `YTS_PREDICT_DRY_RUN` / `YTS_VIDEO_DRY_RUN` / `YTS_ONNX_DRY_RUN` /
  `YTS_SAM_DRY_RUN` / `YTS_SAM_SIMULATE_NO_DEP`。
- 文字化け対策: ワーカー起動時に `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`、
  出力を `utf-8` へ reconfigure、ログ読込は `utf-8-sig` + `errors="replace"`。

## 4. データレイアウト（`projects/<name>/`）

```
projects/<name>/
├── project.yaml              # 概要・task(detect|segment)・created_at
├── classes.yaml              # classes: [{id, name, color}]（id は 0 始まり・追加順）
├── raw/images/               # 取り込んだ元画像（原則非破壊）
├── processed/                # 前処理出力（images / thumbnails / metadata.json / preview）
├── annotations/labels/       # YOLO 形式ラベル（*.txt, utf-8-sig で読む）
├── selection/selection.json  # 画像選別の結果（included/excluded/review）
├── datasets/<dataset>/       # train/val/test 分割コピー + data.yaml + metadata.json
├── runs/train/<job_id>/      # 学習ラン（job.json, train.log, weights/best.pt|last.pt, results.csv 等）
├── predictions/<id>/         # 推論（job.json, results.json, outputs/, preprocessed_inputs/）
├── video/<id>/               # 映像推論（job.json, live/latest.jpg, stop.flag）
├── exports/onnx/<id>/        # ONNX エクスポート（model.onnx, metadata.json）
├── exports/packages/<id>/    # 配布パッケージ（zip）
├── reports/                  # レポート（JSON / Markdown）
├── sam/settings.json         # SAM 補助アノテーション設定
└── models/selected_model.json# 採用モデル（参照パスのみ保存。コピーしない）
```

- 案件データのルートは `YTS_PROJECTS_ROOT`（未指定時 `<repo>/projects`）。`core/paths.py` が全パスを解決し、
  ファイル名指定は resolve 後に親ディレクトリ内かを検証して**パストラバーサルを防止**する。

## 5. ラベル形式

- **detect**: `class_id x_center y_center width height`（正規化 0〜1、5 列）。
- **segment**: `class_id x1 y1 x2 y2 ...`（正規化・頂点 3 点以上、奇数列）。
- 誤検出分析では segment のポリゴンを**外接 bbox に変換**して IoU 比較する。
- ラベル読込は `utf-8-sig`（外部ツール由来の BOM 対策）。

## 6. クラス ID の一貫性（重要な設計制約）

- クラス ID は `classes.yaml` の**並び順で 0 始まり自動採番**。`data.yaml` の `names` も同順で出力。
- **append-only 運用**: 学習・データセット作成後に既存クラスの並びを変えると、
  ラベルの `class_id`・学習済みモデルの出力 ID・作成済みデータセットとの整合が崩れる。
  新規クラスは末尾に追加し、既存の並びは変更しない。

## 7. 依存分離の方針

| ファイル | 内容 | 用途 |
|---|---|---|
| `requirements.txt` | fastapi / uvicorn / pydantic / Pillow / PyYAML / python-multipart | API 起動・作業（アノテ等） |
| `requirements-train.txt` | ultralytics / torch 系 / onnx 系 | 学習・ONNX エクスポート |
| `backend/requirements-sam.txt` | ultralytics / opencv-python | SAM 補助アノテーション |

軽量な `requirements.txt` に重い ML ライブラリを含めないことで、作業だけなら GPU/学習環境なしで動く。

## 8. フロントエンドの方針

- ルーティングは `frontend/src/App.tsx`、工程定義は `frontend/src/workflow.ts`。
- API 呼び出しは `frontend/src/api/client.ts` に集約（`/api` 相対、dev は Vite proxy）。
- スタイルは `frontend/src/styles.css` の CSS 変数（カラートークン・影・角丸）と共通クラスで一元管理。
- 画像プレビューは `HoverImagePreview`（`createPortal` で body 直下に描画し、祖先の transform/overflow の影響を回避）。
