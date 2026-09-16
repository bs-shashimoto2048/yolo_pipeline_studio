# Production Meter Model Provenance v1（Checkpoint 5AI〜5AJ、runtime_date=2026-09-16）

`meter_src002` / `meter_src003` / `meter_src004` の3projectについて、実運用でのselected model・
confidence・前処理設定と、その根拠となったVal評価・再現手順を記録するprovenance文書です。
**weight本体（*.pt）はGit管理しません**（`.gitignore`方針どおり）。本文書はweight/local
runtime設定が消失した場合の監査・再現用の記録専用ファイルです。

## Provenance元情報

| 項目 | 値 |
|---|---|
| source git commit（backend/frontend実装、Checkpoint 5AH） | `8c763cde21b2d37fb02618e35c7a51ca60f9a6c3` |
| dataset/split provenance commit（v2 manifest freeze、Checkpoint 5X） | `2fd8af6eda3d3e0e2d7d815b69ecd714702048b4` |
| runtime配線・非Test smoke実施日（Checkpoint 5AI） | 2026-09-16 |
| 本provenance文書作成日（Checkpoint 5AJ） | 2026-09-16 |

## 最終採用構成

### meter_src002
- train_job_id: `production_combined_v2_5z`（`meter_digital_combined/runs/train/candidate_v2_5z`のproject-local copy、Checkpoint 5AI）
- weight_type: `best`
- model sha256: `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61`
- conf: **0.60**
- preprocessing: ROI disabled / width640 / grayscale / sharpen(strength=1.0)

### meter_src003
- train_job_id: `production_combined_v2_5z`（同上、`meter_src002`とは別ファイルとしてcopy、内容は同一）
- weight_type: `best`
- model sha256: `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61`（**src002と完全一致**）
- conf: **0.70**
- preprocessing: ROI disabled / width640 / grayscale / sharpen(strength=1.0)

### meter_src004
- train_job_id: `candidate_roi_v1_5ac`（project-local、copy不要、`meter_src004`内で学習済み・Checkpoint 5AC）
- weight_type: `best`
- model sha256: `f9b7a735e80e58d2eee8e66b53798f093d342035cc387bec51e8f40d890deca5`
- conf: **0.25**
- preprocessing: ROI enabled、raw pixel座標 x=[835,1354), y=[374,480) → width640 → grayscale → sharpen(strength=1.0)
  （処理順は `roi_crop → resize → grayscale → sharpen`。5AC学習時の画素処理と一致させたもの）

### src002/src003 production slotの同一性
`meter_src002/runs/train/production_combined_v2_5z/weights/best.pt` と
`meter_src003/runs/train/production_combined_v2_5z/weights/best.pt` は、いずれも
`meter_digital_combined/runs/train/candidate_v2_5z/weights/best.pt`（Checkpoint 5Z学習の原本）
からの**copy**（move/delete不使用）であり、sha256が原本・2コピーとも完全一致することを
Checkpoint 5AIで確認済みです。

### local-only性の明記
`models/selected_model.json`、上記`runs/train/production_combined_v2_5z/`配下のweight copy・
job.json、および非Test runtime smokeで生成された`predictions/prod_smoke_5ai/`配下の推論結果は、
いずれも`projects/`配下（`.gitignore`によりGit管理対象外）にのみ存在するローカル専用の設定・
成果物です。**本provenance文書以外、Gitにはweight本体・selected_model.json・推論結果を
一切追加していません。**

## 評価の位置づけ

- 最終採用判断は**Valのみ**で行いました（Test split画像・GTは採用判断に一切使用していません）。
- Checkpoint 5AA: `meter_digital_combined` candidate_v2_5z の同一Val 165件を、src002由来75件・
  src003由来90件に分解して評価。
  - src002 subset Val Exact Match = **63/75（84.0%）** @ conf=0.60
  - src003 subset Val Exact Match = **90/90（100%）** @ conf=0.70
- Checkpoint 5AC: `meter_src004` candidate_roi_v1_5ac の同一Val 58件で評価。
  - ROI Val Exact Match = **52/58（89.7%）** @ conf=0.25
  - 7桁目（赤サブ桁）position accuracy = **0.931**、missing = **0**件
    （現行full-frame v2の同一Val・同一confでは0.276・missing=22件、Checkpoint 5AAとの比較で確認）
- **Testについて**: Checkpoint 5Nで既にconsumed済みのhistorical benchmarkであり、v2の
  tuning・confidence選定・モデル採用判断には一切使用していません。加えて、Test ground truth
  v1にはCheckpoint 5S・5Uで訂正が入っている（`meter_src002_split_v1_testgt_v2.csv`参照）ため、
  **5Nの評価結果はv1 GT基準のhistorical/reference扱い**とし、v2以降の判断根拠にはしていません。

## 再現手順（weight本体をGit管理しない前提での復旧手順）

local環境（`projects/`配下）が失われた場合、以下の手順でこのprovenance文書から採用構成を
再現できます。

1. **対象best.ptの配置**
   - `meter_src004`: 当該project内で`candidate_roi_v1_5ac`のyolov8n学習を再現し、
     `runs/train/candidate_roi_v1_5ac/weights/best.pt`を生成する
     （dataset provenance: `data_manifests/meter_src004_split_v2.csv`、commit `2fd8af6...`、
     `projects/meter_src004/datasets/meter_src004_roi_v1/`のROI dataset仕様。学習条件は
     yolov8n / epochs=50 / imgsz=640 / batch=8 / seed=42 / true Ultralytics default augmentation）
   - `meter_src002`・`meter_src003`: `meter_digital_combined`で`candidate_v2_5z`を再現し、
     生成された`best.pt`を各projectの`runs/train/production_combined_v2_5z/weights/best.pt`へ
     **copy**する（move禁止、原本は`meter_digital_combined`側に残す）
2. **sha256照合**
   - 上表に記載した3つのsha256値と、生成/配置したファイルのsha256が完全一致することを
     確認する（一致しない場合は採用構成として扱わない）
3. **selected model API/UIでの設定**
   - 既存API（`PUT /api/projects/{name}/models/selected`）またはModel Registry UIから、
     project毎に `train_job_id` / `weight_type` / `conf` / `preprocess_profile` を上表の
     とおり設定する
4. **非Test smokeでの確認**
   - 各projectでTest split以外（Train/Valまたは専用fixture）の画像1枚を用い、
     `preprocess_mode="selected"`のpredict jobを実行し、job.json記録の
     `resolution_source`（すべて`selected_model`由来であること）・`processing_order`
     （src002/003は`grayscale→sharpen→resize`、src004は`roi_crop→resize→grayscale→sharpen`）・
     resolved conf・出力画像サイズ（src004は640×131）を確認する
   - **この確認はconfiguration/runtime配線の検証のみを目的とし、精度評価・GT比較は行わない**

## 変更していないもの
`data_manifests/*_split_v1.csv`・`*_split_v2.csv`・annotation・raw/processed画像・dataset・
アプリケーションコードは本Checkpointで一切変更していません。
