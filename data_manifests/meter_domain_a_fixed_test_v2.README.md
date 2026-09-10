# Domain A Fixed Test Set v2（`meter_domain_a_fixed_test_v2.csv`）

Issue #1 Checkpoint 3F〜3Iで、画像単位のphysical meter identity再監査（Checkpoint 3E）を踏まえて再設計・固定した、`meter`プロジェクトDomain Aの公式Fixed Test Setです。

## 固定内容（v2、fixed_at=2026-09-10）

- **Test: 24 images**（`physical_meter_id=meter_Y`のみ。`src_002` 23 + `meter_001` 1）
- Test individualはmeter_Y **1台のみ**（丸ごとhold-out）です。
- Train/Val（`meter_domain_a_train_val_v2.csv`、meter_Z / meter_W）とは**physical-meter-disjoint**であり、image / physical meter いずれの重複も0件です。
- `capture_001`（8枚）は物理個体が混在するデータのため、Testにも含めていません。
- Domain B（`src_004*`, `meter_003`）も含まれていません。

## physical meter構成

- 確認済みphysical meter数: **3台（meter_W / meter_Y / meter_Z）**
- Issue #1本文の目標「physical meter 5台以上」は**引き続き未達**です。Test個体が1台のみである点は、v1（2個体）からの後退ではなく、v1の2個体目（`meter_002`）が実際にはTrain側個体（meter_Z）と同一だったために生じた必然的な結果です。

## v1からの変更点

- v1のTest（21枚、Y20枚+Z1枚）は、Z側の1枚（`meter_002`）がTrainとleakageしていたため**INVALIDATED**（詳細は`meter_domain_a_fixed_test_v1.README.md`参照）。
- v2は`meter_Y`のみで再構成し、既存24枚（annotation済み）で固定しています。
- 今後の追加はv2を上書きせず、v3等の別versionとして扱ってください。

## 使用ルール

- この24枚は今後の学習・augmentation選定・hyperparameter tuningに使用禁止です（Test専用）。
