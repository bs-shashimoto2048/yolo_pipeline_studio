# Domain A Leakage-Free Train/Val Split v2（`meter_domain_a_train_val_v2.csv`）

Issue #1 Checkpoint 3F〜3Iで、画像単位のphysical meter identity再監査（Checkpoint 3E）を踏まえて再設計・固定した、`meter`プロジェクトDomain AのTrain/Val split manifestです。

## 固定内容（v2、fixed_at=2026-09-10）

- **Train: 500 images**（`physical_meter_id=meter_Z`のみ。`src_003` 496 + `src_003_v3` 4）
- **Val: 9 images**（`physical_meter_id=meter_W`のみ。`src_001` 1 + `src_001_v3` 7 + `meter_004` 1）
- **Train/Valはphysical-meter-disjoint**（meter_Z と meter_W は別物理個体、Checkpoint 3Eで確認済み）
- `capture_001`（8枚）は、単一物理個体ではなくmeter_W/meter_Y/meter_Z/Domain Bが1セッション内に混在したデータであるため、**Train/Valいずれからも完全除外**しています。
- Domain B（`src_004*`, `meter_003`）も完全除外しています。
- `meter_002`（Fixed Test v2の個体、真のmeter_Z）はTrainに含まれておらず、Test v2との重複はありません。

## physical meter構成

- 確認済みphysical meter数: **3台（meter_W / meter_Y / meter_Z）**
- Issue #1本文の目標「physical meter 5台以上」は**引き続き未達**です（本v2固定は既存3台の範囲内での再設計であり、この不足を解消するものではありません）。

## 重要な制約

- Valの`meter_W`は9枚と少なく、統計的信号は弱いですが、**physical-meter-disjointであることを優先した設計**です（同一個体内session holdoutの限界を再発させないため）。
- この分割は今後の学習・評価に使用可能ですが、Fixed Test v2（`meter_domain_a_fixed_test_v2.csv`）とは物理個体が完全に独立しています。
- 追加annotationは`meter_Z`のraw未annotationプールから継続拡張可能です（Checkpoint 3C/3H参照）。
