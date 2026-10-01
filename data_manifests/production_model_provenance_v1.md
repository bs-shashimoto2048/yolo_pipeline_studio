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

> **Issue #39追記**: dataset lineage・split integrity・独立acceptanceの詳細監査は
> [`meter_src002_production_provenance.md`](meter_src002_production_provenance.md)
> を参照。Case B判定（4桁目`4→5`混同、Train内極端なクラス不均衡2 vs 347が原因）。
> production設定（weight/conf/preprocess/contract）は本Issueで変更していない。

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

## Production runtime letterbox condition（Issue #25、2026-09-29追記）

**注意**: 本節は現行runtimeの推論条件についての追記であり、上記「最終採用構成」節の
`meter_src004`情報（`candidate_roi_v1_5ac`、conf=0.25）を現在の状態へ書き換えるものではない。
`meter_src004`の現在の採用状態（`candidate_roi_v3_5`、conf=0.80）とruntime letterbox条件の
詳細は [`meter_src004_roi_v3_provenance.md`](meter_src004_roi_v3_provenance.md) を参照。

- 現行image predict / video inferenceは、`backend/workers/predict_worker.py` /
  `backend/workers/predict_video_worker.py` の `model.predict()` 呼び出しに **`rect=True`を明示**する
  （Issue #25で実装）。
- これは**挙動変更ではない**。Issue #25以前から、Ultralytics 8.4.83の`Model.predict()`は
  predictモードの既定値として`rect=True`をハードコードしており（`rect`未指定時点で実際には
  既にrect=Trueが使われていた）、Issue #25はこの既存条件をコード上に明示して固定しただけである。
- project preprocessing出力サイズと、YOLOへの実際の入力tensor sizeは**別概念**である:
  - `meter_src002`/`meter_src003`のproject preprocessing出力: **640×360**
  - 上記画像がrect=Trueで letterbox された後のYOLO input tensor: **384×640**（stride=32単位の
    最小矩形padding。正方形640×640ではない）
- Ultralyticsの標準validation（`model.train()`終了時の自動validationを含む）は、`mode=="val"`のとき
  常にrectangular validation（rect=Trueのバッチ内aspect比グルーピング）を使用する（Ultralytics全体の
  標準仕様）。そのため、本文書記載のP/R/mAP系のVal評価数値とruntimeのrect条件は、整合している
  可能性が高い。
- 一方、historicalなExact Match系custom evaluation（本文書§「評価の位置づけ」記載のExact Match数値）が
  実際にどのrect条件で計算されたかは、当時の評価scriptが現存しないため**確認不能**である。
- Issue #25では、production weightそのものを用いた非Test・非Hard-Val画像によるrect=True/False診断
  （digital 45枚、Checkpoint 2参照）を実施した。prediction差は一部確認されたが、一貫した優劣は
  見られなかった。この診断値はTrain画像由来の**参考値**であり、Val精度・production精度としては
  扱わない。
- 上記の結果、既存のrect=True相当の挙動を維持することとし、production設定（selected_model.json・
  conf・ROI・preprocess・weight）は変更していない。

## Production inference contract — remaining defaults（Issue #26、2026-09-29追記）

Issue #25でrect=Trueを固定した後、残りのUltralytics暗黙default依存パラメータを棚卸しし、
現行production挙動と完全同値であることを実測確認できたものだけをコード上へ明示固定した。

> **Issue #27追記**: 本節に記載のcontractは、以後
> [`docs/PRODUCTION_INFERENCE_CONTRACT.md`](../docs/PRODUCTION_INFERENCE_CONTRACT.md)
> （人間向け仕様の正本、strict/tolerance・skip/fail規則・contract version bumpルールを集約）と
> `backend/tests/smoke_inference_contract.py`（回帰検知test）で継続的に維持・検証する。
> 本節は判断根拠・時系列の記録として残す。

> **Issue #28追記**: Ultralytics依存（および密結合するtorch/torchvision/torchaudio等）の
> 更新手順は[`docs/ULTRALYTICS_UPGRADE_PROCEDURE.md`](../docs/ULTRALYTICS_UPGRADE_PROCEDURE.md)
> に標準化した。`ultralytics`は本Issueで`requirements-train.txt`/`backend/requirements-sam.txt`上
> `==8.4.83`へexact pinした（判断根拠は同docの「実施したrequirements変更」節）。

> **Issue #29追記**: 実際に実行されたjobがどのcontract version・model・resolved argsで
> 推論したかは、job.jsonの`inference_contract`（predict/video両workerがmodel load直後に記録）
> から事後監査できる。詳細・schema・privacy方針は
> [`docs/PRODUCTION_INFERENCE_CONTRACT.md`](../docs/PRODUCTION_INFERENCE_CONTRACT.md)の
> 「Runtime observability」節を参照（推論挙動自体は変更していない）。

> **Issue #31追記**: torch/torchvision/torchaudioのpin方針・検証済みバージョン
> （`torch==2.11.0+cu128` / `torchvision==0.26.0+cu128`）・インストール手順は
> [`docs/TORCH_STACK_POLICY.md`](../docs/TORCH_STACK_POLICY.md)に集約した。
> `requirements-train.txt`自体はCPU-only環境の可搬性維持のためunpinnedのまま
> （exact pinはREADMEの明示コマンド側で管理）。未使用と判明した`torchaudio`は
> `requirements-train.txt`から削除した。

> **Issue #32追記**: Issue #25〜#31で都度手動/scratchpad実行してきたnon-Test production
> smoke（selected model resolution・real worker・inference contract・observability確認）を
> `backend/tests/smoke_production_integration.py`として恒久化した（Gate E相当、詳細は
> [`docs/PRODUCTION_INFERENCE_CONTRACT.md`](../docs/PRODUCTION_INFERENCE_CONTRACT.md)の
> 「Layer C」節参照）。

> **Issue #34追記**: digital右端桁・drum赤サブ桁のconfidence不安定性を非Testデータで
> 定量診断した（`scripts/analyze_last_digit_stability.py`、production非変更）。
> digitalは実害0.57%でCase A（物理transition）が支配的、drumはCase A主体+
> Case C（閾値変更で一部回収可能）+ Case B（"→7"/"→6"混同の再現性）の混合。
> 詳細・threshold sweep・temporal PoC結果は
> [`docs/LAST_DIGIT_CONFIDENCE_AUDIT.md`](../docs/LAST_DIGIT_CONFIDENCE_AUDIT.md)参照。

### 時系列
- Issue #24: YOLO26 auditで、model依存defaults（`end2end`等）の重要性が判明。
- Issue #25: `rect=True`を現行production contractとして明示固定。
- Issue #26（本節）: 残りのdefaultsを監査し、同値確認できたもののみ追加固定。
- Issue #28: Ultralytics依存の更新procedureを標準化し、`ultralytics==8.4.83`をexact pin。
- Issue #29: job.jsonへproduction inference contractのobservability metadataを追加。
- Issue #30: job.json書き込みraceとロック奪取raceを修正（flaky test解消）。
- Issue #31: Torch stack（torch/torchvision/torchaudio）のpin方針を確定、torchaudioを削除。
- Issue #32: non-Test production smokeを`smoke_production_integration.py`として恒久化。
- Issue #33: job.json書き込み/lockの残存raceを他job種別（train/selection/onnx_export/
  capture）へも棚卸し・修正。
- Issue #34: 末尾桁confidence不安定性を非Testデータで定量診断（production非変更）。
- Issue #35: drum production confidenceをStandard Val58で正式再評価。非Test
  acceptanceでconfidently-wrong増加が判明したため0.80維持（production非変更）。

### Pinned（`backend/workers/predict_worker.py` / `predict_video_worker.py` へ明示、
image predict・video inferenceとも同一、非Test画像digital20枚・drum20枚で個別・組合せとも
reading/detection count/class列が100%一致することを実測確認済み）

```text
rect=True
max_det=300
agnostic_nms=False
augment=False
batch=1
quantize=None
```

### Decision Record（固定しなかったもの）

```text
device: intentionally dynamic（"auto"時はUltralyticsの自動選択に委ねる。実測ではcuda:0が
  解決されるが、実行環境依存のため固定しない。現行コードも既にauto以外の時のみ明示する設計）
classes: default unrestricted (None)、no explicit pin（非Test画像で同値確認済みだが、
  10クラス全検出という現状の要件を超える保護的価値が薄く、コードの可読性を下げるだけと判断）
end2end: model-dependent, not pinned for YOLOv8 production（現行production weightは
  YOLOv8nでありDetectヘッド自体にone2one分岐が無い＝`model.end2end`は常にFalse。
  `end2end=False`を明示しても非Test画像で出力は変化しないことを確認済みだが、これはYOLOv8n
  固有の性質であり、YOLO26等end2end対応modelを将来採用する場合は個別に再評価が必要なため、
  共通workerのkwargsへは固定しない）
half: 後方互換の非推奨引数のため使用せず、代わりにquantize=Noneを固定（上記Pinned参照）。
  実測ではdevice（CPU/CUDA）に関わらずpredictor.model.fp16=Falseで一貫しており、
  device依存ではないことを確認済み
verbose: 出力ログの詳細度のみに影響し、prediction結果（reading/検出/confidence等）には
  一切影響しないため、本Issueの監査対象（production挙動）としては対象外
```

### 非Test診断（Train所属画像、digital20枚・drum20枚、結果を見る前にstemをfreeze）

各parameterを個別に明示したcandidateと、現行baseline（rect=Trueのみ）を比較し、
reading一致・detection count一致・class列一致がいずれも20/20（100%）、confidence/bbox差は
全candidateで0（float誤差も含め完全一致）であることを確認した。最終的な組み合わせ
（`max_det`+`agnostic_nms`+`augment`+`quantize`）でも同様に20/20で完全一致。
`batch=1`は、image workerの実際の呼び出し形（`source=<directory>, stream=True`）でも
個別に同値性を確認した。
