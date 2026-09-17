# meter_src004 ROI Training Dataset v3 Provenance (FINAL — Production Adopted)

Issue #15（drum meter (`meter_src004`) 2/8 class confusion対応）Checkpoint 2〜7の成果物。
**Checkpoint 7時点でproduction採用済み**（`projects/meter_src004/models/selected_model.json`
を `candidate_roi_v3_5:best` / conf=0.25 へ更新）。

## 1. Source

- Issue: #15 "Production model policy" — drum meter専用モデルの2/8 hard-example改善
- source v2 manifest: `data_manifests/meter_src004_split_v2.csv`
  - sha256: `bf26ab20e935ca1a91f1535c2305a2a12205aa9516a24b3d53167eb8dde1276e`
  - source_git_commit: `2fd8af6eda3d3e0e2d7d815b69ecd714702048b4`（"data: freeze corrected v2 meter splits"）

## 2. Hard-example annotation（Checkpoint 2/3）

- 127 atomic unit（時間/perceptual-hash clusterで重複排除済み候補）を全件目視確認
- **primary（7桁確定・実annotation化）: 96件** = Train追加69 + Hard-Val27
- **ambiguous（遷移中/非digit形状/優劣判定不可により除外）: 31件**（未annotation、`projects/meter_src004/annotations/labels/`には書き込んでいない）
- Checkpoint 3のmaterialize前再確認で9件の誤読を検出・修正（6件は値修正、3件はrescue失敗と判明し除外→最終96件に反映済み）

## 3. v3 manifest構成

- `data_manifests/meter_src004_split_v3.csv`（v2の全369行 + 新規Train69行、sha256: `aac20d4bea4ab98ece219956297751cacd41c74dda771415124fd9b660e8dde0`）
- `data_manifests/meter_src004_hard_val_v1.csv`（Hard-Val 27件、独立ファイル。sha256: `5735cf3b577bc74f54aca92d4ecd37918a6f50ce8b6e6978e724356ef833175b`）

| split | v2 | v3 |
|---|---|---|
| train | 270 | **339**（270 + Checkpoint3新規69） |
| val | 58 | 58（変更なし） |
| test | 41 | 41（変更なし、Checkpoint2〜7を通じ一切predict/evaluateに使用していない） |
| hard_val | — | **27**（新設、独立manifest、training対象外として凍結） |

既存v2 manifestは無変更（`git diff`で確認済み）。

## 4. leakage/integrity監査（Checkpoint 4、全項目0件）

- Train339/Val58/Hard-Val27/Test41の全ペアstem重複: 0
- 新規Train69とHard-Val27のatomic-unit重複: 0
- Hard-Valと既存Train/Val/Testの時間近接（300秒以内）: 0
- Train339+Val58+Hard-Val27の全label（424件）: bbox=7・class/coords妥当性エラー0

## 5. ROI / 前処理パラメータ（既存5AC方式と完全一致、production採用値）

- raw pixel ROI: x=[835, 1354), y=[374, 480)（1920x1080基準）
- 処理順: `roi_crop → resize(width=640, aspect維持, LANCZOS) → grayscale(L→RGB) → sharpen(UnsharpMask radius=2, percent=100, threshold=2, strength=1.0)`
- crop_size_raw_px: [519, 106] / output_size_px: [640, 131]
- bbox変換式は既存`datasets/meter_src004_roi_v1`（5AC実績）とbit-for-bit完全一致を確認済み

## 6. Training（Checkpoint 5）

- run: **`candidate_roi_v3_5`**（`projects/meter_src004/runs/train/candidate_roi_v3_5/`、既存run非上書き）
- base: yolov8n.pt / epochs=50（完走、early stopping未発動）/ imgsz=640 / batch=8 / workers=2 / patience=20 / seed=42 / Ultralytics既定augmentation
- 学習データ: Train339 / Val58のみ（Hard-Val27・Test41は学習に一切不使用）
- **best.pt SHA256: `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db`**

## 7. Standard Val58結果（conf=0.25, production標準）

| 指標 | v3 | baseline(`candidate_roi_v1_5ac`) |
|---|---|---|
| Exact Match | 52/58 (89.7%) | 52/58 (89.7%) |
| P / R / mAP50 / mAP50-95 | .987 / .988 / .987 / .910 | .971 / .971 / .980 / .894 |
| 7-detection rate | 91.4% | 94.8% |
| character accuracy | 98.77% | 98.52% |
| missing/extra/wrong_class | 0/6/5 | 0/3/6 |
| 2→8 / 8→2 | 0 / 0 | 0 / 0 |

conf=0.50はVal58参考値として記録するのみ（Exact 56/58だがmissing=2）。Frozen Hard-Valは0.25でのみ凍結評価しており、0.50へは合わせ込んでいない。

## 8. Frozen Hard-Val27結果（Checkpoint 5、学習完了後の一回のみ評価、conf=0.25固定）

| 指標 | v3 | baseline（同一Hard-Val27で新規評価） |
|---|---|---|
| Exact Match | **23/27 (85.2%)** | 16/27 (59.3%) |
| class2 accuracy | **18/18 (100%)** | 15/18 (83.3%) |
| class8 accuracy | **22/22 (100%)** | 22/22 (100%) |
| 2→8 / 8→2 | 0 / 0 | 0 / 0 |
| missing/extra/wrong_class | 0/2/3 | 2/6/5 |

## 9. 実運用報告フレームでの確認（Checkpoint 6、制約あり）

- 対象: `projects/meter_src004/video/video_0/live/latest.jpg`（2026-09-17ライブ映像推論、旧候補`candidate_v2_5z`使用、Test/Train/Val/Hard-Valいずれにも非属の独立非Test画像）
- 目視確認: 3桁目の実際の文字は"2"だが、当時の推論オーバーレイは緑ラベル"8"を表示 — ユーザー報告と一致する事象を直接確認
- **制約**: 当該フレームは保存時点で既にROI無効・640×360へダウンスケール済みで、生の1920×1080相当画像が存在しない。ROI領域を逆算crop すると実質173×35pxしかなく、baseline/v3のROIモデル同士を同一条件で定量比較するには解像度不足（両モデルとも3/7しか検出できず不成立）。**この制約は採否判断に隠さず記録する。**
- 定量的な「改善確認」は本フレーム単独では不可能だったため、同種の失敗モード（3桁目 2誤認）を狙って構築したFrozen Hard-Val27の結果（§8）を実質的な改善根拠として採用。

## 10. Production採用（Checkpoint 7）

- `projects/meter_src004/models/selected_model.json` を更新:
  - train_job_id: `candidate_roi_v3_5` / weight_type: `best` / conf: **0.25**
  - preprocess_profile: ROI x=[835,1354), y=[374,480) / resize width640 / grayscale / sharpen 1.0（変更なし、既存と同一）
- runtime smoke（selected-model fallback経路、Train所属の非Test画像1枚）で正常動作を確認:
  - resolved model=`candidate_roi_v3_5:best` / resolved conf=0.25（すべてselected_model由来）
  - processing_order=`roi_crop → resize → grayscale → sharpen` / output size=640x131
  - 7/7 detection、reading="3709726"（GTと一致）

## 11. Production architecture（2 model構成）

- **Digital** (`meter_src002`, `meter_src003`): `production_combined_v2_5z`（本Issue全体を通じ変更なし）
- **Drum** (`meter_src004`): `candidate_roi_v3_5`（本Checkpointで採用）

## Safety Gate（Checkpoint 2〜7を通じ遵守）

- digital src002/src003のmodel/configは無変更
- 既存v2 manifestは無変更
- 既存605 labelは無変更
- Hard-Val27はtraining/conf tuningに一切使用していない（学習完了後の一回評価のみ）
- Test41はpredict/evaluateしていない（manifest上のstem集合比較のみ）
- Git stage/commit/pushは実行していない（本ファイル含め3件のuntracked manifestファイルはローカルのまま）
