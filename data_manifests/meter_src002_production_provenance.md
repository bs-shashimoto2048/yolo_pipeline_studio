# meter_src002 (digital) production provenance — Issue #39監査

本ドキュメントは、`production_combined_v2_5z`（digital production、conf=0.60）について、
dataset lineage・split integrity・model provenance・独立acceptanceをDrum v4
（`meter_src004_roi_v4_provenance.md`）と同水準で再監査した記録である。

**本Issueは再学習Issueではない。** retraining・threshold変更・model promotion・
ROI/preprocess変更・Test66での再評価は一切行っていない。production weight
（sha256 `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61`）・
selected_model.json・conf(0.60)・preprocess_profile・contract(v1)は本Issueを通じて
一切変更していない。

**Test66 predictions/evaluation were not performed.**（manifest structure・stem
overlap・hash監査のみ実施）

## 1. Dataset lineage

```
raw 2,299
  → annotation 501
    → v2 split 490（train349 / val75 / test66）
        excluded 11 = test-adjacent leakage 8 + reading-group collision 1 + unresolved GT 2
```

機械確認結果（本Issueで実測、`docs/METER_DATASET_CURATION_GUIDE.md`の既存summary
countと完全一致）:
- raw画像数: `projects/meter_src002/raw/images/*.jpg` = **2,299**（一致）
- annotation数: `projects/meter_src002/annotations/labels/*.txt` = **501**（一致）
- v2 split（`data_manifests/meter_digital_combined_split_v2.csv`のproject=meter_src002行）
  = **490**（train349/val75/test66、一致）
- excluded = 501 - 490 = **11**（一致）

## 2. Excluded 11の内訳（stem単位で本Issue新規に再構成）

既存ドキュメントはsummary count（8+1+2=11）のみを記録しており、stem単位の内訳は
残っていなかった。本Issueで、test-adjacency（timestamp+perceptual hash近接）・
annotation内容・目視確認により再構成した（確証度: 高、ただし原典記録がないため
最終的な断定ではなく最有力な再構成である旨を明記する）。

### test-adjacent leakage 8（Test66とtimestamp 600秒以内かつperceptual hash近接）
| stem | nearest Test66 stem | hamming | Δt(秒) |
|---|---|---|---|
| src_002_20260819_155000 | src_002_20260819_154500 | 3 | 300 |
| src_002_20260901_164000 | src_002_20260901_163600 | 3 | 240 |
| src_002_20260901_175600 | src_002_20260901_174800 | 0 | 480 |
| src_002_20260901_183600 | src_002_20260901_182800 | 0 | 480 |
| src_002_20260907_121200 | src_002_20260907_120800 | 1 | 240 |
| src_002_20260908_063200 | src_002_20260908_063600 | 0 | 240 |
| src_002_20260908_072400 | src_002_20260908_072800 | 3 | 240 |
| src_002_20260908_080800 | src_002_20260908_080400 | 0 | 240 |

### unresolved GT 2（annotationとraw画像の目視読み取りが不一致）
- `src_002_20260903_095200`: annotationは`0215234`だが、目視（高解像度crop）では
  **`0215229`**と明確に判読できる（末尾2桁が食い違う）。
- `src_002_20260904_102800`: annotationは`0215257`だが、目視では**`0215252`**と
  判読できる（6桁目が食い違う）。

両者とも、annotationに誤りがある可能性が高く、原curatorが同様の不一致に気づいて
unresolvedとしてprimaryから除外したと推定される。**本Issueではこれらのannotation
ファイル自体は変更していない**（primary splitに含まれない孤立した行であり、
production学習・評価に一切影響しないため、修正の要否は本Issueの範囲外とする）。

### reading-group collision 1
- `src_002_20260819_143000`: annotation(`0214968`)はraw画像と一致（目視確認済み、
  不一致なし）。このreading値は v2 split内に既に8件存在しており（同一
  reading_groupの重複）、split構成上のredundancyとして除外されたと推定される。

## 3. Split integrity

- Train(349)/Val(75)/Test(66) 間の**exact stem overlap: 0件**（機械確認）。
- 各split内でのstem重複: 0件。
- **cross-split near-duplicate監査（新規実施、重要な発見）**: perceptual hash
  （32x32 aHash、Hamming<=3）+ timestamp近接（600秒以内）で、official split内に
  **5件のcross-split近接ペア**を検出した:

| stem A | split A | stem B | split B | hamming | Δt(秒) |
|---|---|---|---|---|---|
| src_002_20260901_162800 | train | src_002_20260901_163600 | test | 3 | 480 |
| src_002_20260901_163200 | train | src_002_20260901_163600 | test | 3 | 240 |
| src_002_20260908_062000 | train | src_002_20260908_062800 | val | 1 | 480 |
| src_002_20260908_062400 | train | src_002_20260908_062800 | val | 0 | 240 |
| src_002_20260908_062800 | val | src_002_20260908_063600 | test | 1 | 480 |

これは「excluded 11」の除外処理（annotationされた501件のうち11件を除外）では
捕捉されなかった、**official split自体に残存する軽微なleakageリスク**である。
490件中5ペア（約1%）と規模は小さいが、Test66の一部がTrain/Valと極めて近い撮影
条件を共有している可能性があり、残存リスクとして記録する（本Issueでは split
自体の変更は行わない）。

## 4. Test66（構造確認のみ、predictionは一切行っていない）

- 行数: 66、unique stem: 66（重複なし）
- 全行に`reading_gt`・`relative_path`が存在
- 参照raw画像ファイルの欠落: 0件

## 5. Model provenance

| 項目 | 値 | 備考 |
|---|---|---|
| train_job_id | `production_combined_v2_5z` | `meter_src002`内はread-onlyコピー |
| 実学習場所 | `projects/meter_digital_combined/runs/train/candidate_v2_5z/` | job.jsonに明記、args.yaml実在 |
| base architecture | YOLOv8n (`yolov8n.pt`) | args.yamlで確認 |
| dataset | `meter_digital_combined_split_v2`（src002 490 + src003 600 = 1090件、train769/val165/test156） | combined datasetで学習、src002単独ではない |
| seed | 42 | deterministic=true |
| epochs | 50 | patience=20 |
| imgsz | 640 | batch=8 |
| augmentation | ultralytics標準既定値（hsv/translate/scale/fliplr/mosaic等、override kwargsなし） | job.jsonの`augmentation_preset`欄に明記 |
| device/workers | '0' / 2 | |
| weight path | `runs/train/production_combined_v2_5z/weights/best.pt`（src002内のコピー） | 原本は`meter_digital_combined/runs/train/candidate_v2_5z/weights/best.pt` |
| weight SHA256 | `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61` | **両ファイルで完全一致を確認（本Issueで実測）** |
| promotion理由 | job.json記載: 「Checkpoint 5AI: 読み取り専用コピー、src002/src003が同一best.ptをconfidenceだけ変えて共有するための配置」 | |

**重要な発見**: `meter_src002/runs/train/production_combined_v2_5z/`には
`args.yaml`が存在しない（job.jsonのみ）。これは学習がこのディレクトリで直接
行われたのではなく、`meter_digital_combined`プロジェクトでの学習結果を
読み取り専用コピーしたものだからである。完全なargs.yaml（全ハイパーパラメータ）は
**`projects/meter_digital_combined/runs/train/candidate_v2_5z/args.yaml`に実在する**
ことを本Issueで確認した。したがって provenance情報は**不足していない**が、
2つのプロジェクトディレクトリにまたがって保存されているため、`meter_src002`側
だけを見ると不完全に見える、という構造的な分かりにくさがある（この事実自体を
本ドキュメントで明記することで解消する）。

## 6. Training reproducibility

`projects/meter_digital_combined/runs/train/candidate_v2_5z/args.yaml`に
全パラメータ（task/data/epochs/patience/batch/imgsz/device/workers/seed/
deterministic/augmentation全項目/optimizer/lr0等）が完全に記録されている。
データセット（`meter_digital_combined_split_v2`の769 train + 165 val、画像/ラベル
双方の実体）も`projects/meter_digital_combined/datasets/meter_digital_combined_split_v2/`
に現存することを確認した（train 769枚、val 165枚、件数一致）。

**「同一dataset + 同一args → 理論上再現可能」と言える条件は満たされている。**
不足している情報: なし（完全な再学習は本Issueでは実施しない）。

## 7. Production preprocessing / runtime args

| 項目 | 値 |
|---|---|
| ROI | disabled |
| resize | width=640（アスペクト比維持） |
| grayscale | enabled |
| sharpen | enabled, strength=1.0 |
| 実測 preprocess output size | 640x360 |
| 実測 YOLO input tensor shape | (1, 3, 384, 640) |
| conf | **0.60**（固定、変更なし） |
| iou | 0.7 |
| rect | True |
| max_det | 300 |
| agnostic_nms | False |
| augment | False |
| batch | 1 |
| quantize | None |

`backend/tests/fixtures/production_inference_contract_golden_v1.json`の
digital section（3 fixture stem）と完全一致を確認（本Issueで再実行、
`smoke_inference_contract.py`参照）。Issue #25の実測（640x360→(1,3,384,640)）とも
一致する。

## 8. 独立acceptance評価

### データソース・独立性
Train349/Val75/Test66（=v2 split 490件）+ excluded11、計501件（全annotation済み
stem）を機械的に除外した未使用raw画像**1,798件**から、production model
（conf=0.60診断的confidence0.05でmining）でstable/hard/低confidence/明暗を分類し、
aHash+timestamp近接でatomic unit化（180 unit）した上で、多様性を優先して
**86件**を抽出した（stable 40・dark 20・bright 20・hard 3・low_conf 3。hard/low_conf
母数が小さいのは、digital自体がIssue #34同様stableなデータセットであるため）。

全86件についてTrain/Val/Test/excluded11いずれとも重複しないことを機械確認済み。
GTは全件、montage画像による目視読み取りで確定した（digital LCDは可読性が高く、
86件中ambiguousとして除外した画像は0件）。

### Current production評価（conf=0.60固定、re-tuneなし）

| 指標 | 値 |
|---|---|
| n | 86 |
| Exact Match | 83/86 (96.5%) |
| 7-detection率 | 86/86 (100.0%) |
| Character accuracy | 599/602 (99.50%) |
| Missing | 0 |
| Extra | 0 |
| Wrong-class frame | 3 |
| Duplicate-bucket frame | 1 |
| 末尾桁accuracy | 85/86 (98.8%) |
| 末尾桁missing | 1 |
| Confidently-wrong(末尾桁) | 1 |

### Failure taxonomy

- missing: 0件
- extra: 0件
- **wrong-class: 3件、全て同一の "4→5" confusion（4桁目、position index 3）**
- duplicate: 1件（同一x位置に複数box、末尾桁近傍、生成ロジック上のbucket統合で解消）
- boundary-transition: 該当なし（digital LCDは物理的な遷移アーティファクトがdrumの
  回転ホイールと異なり、7segment表示が確定的に切り替わるため、Issue #34同様
  "stable"が支配的）
- confidently-wrong: 1件（末尾桁、下記参照）
- low-confidence: mining時点で3件該当（うち2件が上記wrong-classと重複）

### 重点所見: 4桁目(position 3)の "4→5" confusion（Case B判定の主根拠）

3件のwrong-class frame（`src_002_20260819_150500`, `src_002_20260819_160000`,
`src_002_20260819_143500`）は、いずれも4桁目のGTが`4`であるにもかかわらず
production modelが`5`を高confidenceで誤検出した（missingではなく
confidently-wrong）。

**根本原因を特定した**: `Train349`における4桁目の値分布を確認したところ、
**`5`が347件、`4`がわずか2件**という極端なクラス不均衡が判明した
（digital gas meterの累積カウンタは単調増加するため、`4`から`5`への遷移が
データ収集期間の早期に一度だけ起き、収集期間の大半は既に`5`の状態だったことに
起因する自然な現象）。これと符合する形で、**v2 split全体の0819日付stem20件は
全てTest66に割り当てられ、Trainには0件**だった（`reading_group_id`ベースの
split配分が、この稀少な遷移期間をたまたま丸ごとTest側へ配分してしまった）。

この結果、Trainはこの4桁目`4`パターンをほぼ学習しておらず（2件のみ）、独立
acceptanceで同じ時期・同じreading帯の画像を評価すると高確信度で`5`に誤認識する
という、再現性のある具体的な弱点が実証された。raw画像ベースでは同日付
（20260819）の画像が全体で31枚存在する（Test66に20枚、本Issue acceptanceで3枚
使用、残り8枚は他のexcluded/未使用）。

### Stable / boundary-proxy

snapshot間隔が大きい（連続videoでない）ため、Issue #34の定義を**boundary-proxy**
として踏襲する。本acceptanceセットでは、86件中、物理的な遷移中と判断できる
フレームは0件（LCD表示は確定的であり、drumのような回転中アーティファクトが
存在しないため）。性能劣化は上記4桁目confusionのみで、transitionに起因しない。

## 9. 既存6件の一次参考（該当なし）

Digitalには Issue #34時点で「既知の失敗exemplar」としてリストされた確定済み
stem群は存在しない（Issue #34時点でDigitalはconfidently-wrong 1件のみ）。本Issueで
新たに発見した3件（実質1つの根本原因）が、今後の改善Issueの主要な参照材料となる。

## 10. 健康診断としての判定

**Case B: 限定的なfailure modeあり → 次Issueでhard-negative/rebalancing改善を推奨**

判定根拠:
- 全体性能は引き続き高水準（Exact Match 96.5%、文字精度99.5%、Issue #34の
  「Case A支配的」という評価と矛盾しない）。
- しかし、独立acceptanceによって、Train339の既存データだけでは発見できなかった
  **具体的・再現性のある・根本原因まで特定可能な弱点**（4桁目`4→5`混同、
  Train内極端なクラス不均衡2 vs 347が原因）を新たに検出した。
- さらに、official split自体にcross-split near-duplicateが5ペア残存している
  ことも判明した（§3）。
- これらは「production即rollback」を要する規模ではないが、「現状維持のみで
  良い」と判定するにも該当しない、まさにCase Bの典型（限定的だが実在する
  failure mode）。

## 11. Promotion/変更有無

**本Issueでproduction設定は一切変更していない。** selected_model.json・weight・
conf(0.60)・preprocess・contract(v1)、いずれも変更なし。

## 12. 次Issue推奨

1. （優先）digital 4桁目`4`クラスのhard-negative/rebalancing: 同日(20260819)周辺の
   raw画像（追加で最大8枚程度）と、可能であれば同様の遷移期間が他にないか
   `reading_gt`の桁別分布を全桁・全プロジェクトで事前監査した上でTrain-add。
2. official split内のcross-split near-duplicate 5ペアの解消検討（re-split or
   対象stemの移動）。
3. Issue #38で確立したCI Gate 2 (self-hosted GPU runner) の実機activation。
4. dataset mining/annotation workflowの自動化。

## 13. 既存production_model_provenance_v1.mdとの役割分担

`production_model_provenance_v1.md`のmeter_src002節はサマリ（train_job_id/weight
sha256/conf/preprocessの要点）のみを維持し、詳細はすべて本ドキュメントに委譲する
（重複を避けるため、同節には本ドキュメントへのリンクのみ追記した）。
