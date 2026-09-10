# Domain A Internal Development Set v1（`meter_domain_a_dev_v1.csv`）

Issue #1 Checkpoint 4C〜4Fで、Train v2（`meter_domain_a_train_val_v2.csv`）に未使用のmeter_Z raw画像から選定・annotationし、固定した`meter`プロジェクトDomain Aの内部development set manifestです。

## 固定内容（v1、fixed_at=2026-09-10）

- **100 images**（`physical_meter_id=meter_Z`のみ）
- Train v2（500枚）との**image overlap=0、exact duplicate(sha256)=0**
- Domain B（`src_004*`, `meter_003`）= 0件、`capture_001` = 0件
- raw画像・annotationとも**100/100存在**、**bbox=7が100/100**（機械QA・実Annotate UI層化サンプルQA済み、Checkpoint 4C参照）
- meter_Zの55クラスタ中、Train選定後も未annotation rawが残っていた**11クラスタ**から水位法（water-filling）で選定
- `purpose=dev`

## 重要な位置づけ

- **meter_ZはTrain v2と同一物理メーターです。したがって本Dev setはunseen-meter（未知個体）benchmarkではありません。**
- Fixed Test v2（`meter_domain_a_fixed_test_v2.csv`、meter_Y、Train/Valとphysical-meter-disjoint）とは性質が異なります。
- 本Dev setは、**Test=meter_Yを再利用せずに改善作業（inference設定調整・将来的なtraining改善等）を進めるための内部validation set**として設計・使用します。
- Test=meter_Yは、本Dev setによるcandidate selection/threshold tuningには**使用していません**（Checkpoint 4A承認コメントの制約を継続遵守）。

## Baseline / Candidate 評価結果（参考記録、Checkpoint 4C・4E）

`baseline_v2_leakage_free/weights/best.pt` によるDev(100枚)評価:

| 設定 | Full Reading Exact Match | 7-detection率 | character accuracy | extra detection |
|---|---|---|---|---|
| Baseline conf=0.25, iou=0.7 | 94/100 (94.0%) | 94/100 (94.0%) | 100.0% | 6件 |
| Candidate conf=0.60, iou=0.7 | **100/100 (100.0%)** | **100/100 (100.0%)** | 100.0% | **0件**（新規missing detectionも0件） |

- `conf=0.60`はDev上のcandidate inference settingとして採用されましたが、Fixed Test v2（meter_Y）は既にBaseline評価（Checkpoint 4B、conf=0.25）で開封済みのため、**meter_Yへ`conf=0.60`を再適用して最終性能を主張することは禁止**されています（Checkpoint 4E承認コメント参照）。
- 評価artifact（per_image_results.csv, summary.json）は`projects/meter/evaluations/baseline_v2_dev_v1/`および`projects/meter/evaluations/baseline_v2_dev_v1_conf060/`配下（Git管理外）に保存されています。

## 制約・注意

- meter_Zの55クラスタのうち、Train選定後に残っていたのは11クラスタのみ（44クラスタは既に枯渇）。cluster coverageはこの制約内での最大化です。
- physical meter台数（3台: meter_W/meter_Y/meter_Z）は本Dev set固定によっても変わりません。Issue本文の「physical meter 5台以上」目標は引き続き未達です。
