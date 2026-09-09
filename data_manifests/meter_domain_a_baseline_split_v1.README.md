# Domain A Provisional Baseline Train/Val Split v1（`meter_domain_a_baseline_split_v1.csv`）

Issue #1 Checkpoint 2A〜2Bで設計した、`meter`プロジェクトDomain Aの**暫定Baseline**Train/Val split manifestです。

## 構成

- Train: 165 images（`src_003` 163 + `src_001` 1 + `meter_004` 1）
- Val: 12 images（`capture_001` 8 + `src_003_v3` 4）
- 合計: 177 images、Domain Aのみ

## 重要な制約（必読）

- **これは正式Dataset Readyではなく暫定Baselineです。** Issue #1本文の目標（Domain A 500+ images / 5+ physical meters）は未達のまま学習傾向を見るための仮split です。
- **Train/Valは同一physical meter「個体X」のみで構成されています。** 現在Domain Aで確認できている物理個体はX・Y・Zの3つのみで、Y・Zは[`meter_domain_a_fixed_test_v1.csv`](meter_domain_a_fixed_test_v1.csv)のFixed Test v1専用として完全に温存しているため、Train/Valに使える個体はXしか残っていません。
- **したがってValは「未知の物理個体への汎化」を評価するものではありません。** Valに割り当てた`capture_001`/`src_003_v3`は個体Xの別capture pipeline・別sessionであり、あくまで同一個体内の撮影経路差・時系列差に対する頑健性を見るための暫定指標です。
- Fixed Test v1の21画像・Test個体Y（`src_002*`, `src_002_v3*`, `meter_001`）・Test個体Z（`meter_002`）は本splitから完全除外しています。
- Domain B（`src_004*`, `meter_003`）も完全除外しています。
- 500+ images / 5+ physical meters未達である以上、本splitで得られる学習結果は参考値であり、Production採否の根拠にはできません。
