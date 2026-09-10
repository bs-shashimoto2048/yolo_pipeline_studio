# Domain A Provisional Baseline Train/Val Split v1（`meter_domain_a_baseline_split_v1.csv`）

## ⚠️ INVALIDATED（Issue #1 Checkpoint 3E/3I時点）

**この`meter_domain_a_baseline_split_v1.csv`はINVALIDATEDです。学習・評価の基準として使用しないでください。**

- **理由**: Checkpoint 3Eの画像単位再監査で、当時「個体X」として扱っていたTrain(`src_003`系)+Val(`capture_001`+`src_003_v3`)の物理メーター識別が誤りだったと判明しました。実際にはTrainの大半（`src_003`）はFixed Test v1の`meter_002`と同一個体（真の個体Z）であり、Valの`capture_001`もW/Y/Z/Domain Bが混在した非単一個体データでした。
- Val内にDomain B画像（機械式ドラム型メーター）が混入していたことも確認されています。
- **Checkpoint 3A（本splitでの学習）・Checkpoint 3B（Fixed Test v1評価）の結果は、historical/reference onlyであり、正式baselineとしては扱いません。**
- 後継: `meter_domain_a_train_val_v2.csv`（Checkpoint 3F〜3Iで再設計・固定、Train=meter_Z 500 / Val=meter_W 9、physical-meter-disjoint）
- このCSVファイル自体は削除・改変していません（監査証跡として保持）。

---

Issue #1 Checkpoint 2A〜2Bで設計した、`meter`プロジェクトDomain Aの**暫定Baseline**Train/Val split manifestです。（**上記のとおり、その後INVALIDATEDと判明**）

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
