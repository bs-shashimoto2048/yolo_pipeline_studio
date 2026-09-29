# Meter Dataset Curation Checklist

固定カメラ・OCR/数字認識・物体検出案件向けの実務チェックリスト。
詳細な考え方は [METER_DATASET_CURATION_GUIDE.md](METER_DATASET_CURATION_GUIDE.md) を参照する。

## 1. Raw inventory

- [ ] source / session / project単位でraw枚数を実測した
- [ ] 画像サイズ・形式・破損有無を確認した
- [ ] stem重複を確認した
- [ ] source境界が説明できる
- [ ] 「だいたい○千枚」で済ませず実数を記録した

記録:

| Project | Source / Session | Raw count | Image size | Notes |
|---|---|---:|---|---|
| | | | | |

## 2. Representative sampling

- [ ] timestamp近接frameを確認した
- [ ] perceptual hash等でnear-duplicate候補を確認した
- [ ] cluster単位を定義した
- [ ] freeze block / same readingを確認した
- [ ] sampling閾値・比率を推測で決めていない

## 3. Annotation QA

- [ ] 画像単独でGTを確定できる
- [ ] bbox数が期待値と一致する
- [ ] class範囲が妥当
- [ ] bbox座標が画像範囲内
- [ ] duplicate bbox / multiple classがない
- [ ] 遷移中digitを無理に確定していない
- [ ] ambiguous / unresolvedを分離した
- [ ] confirmed_error修正時に根拠を記録した

## 4. Exclusion audit

| Reason | Count | Rule | Evidence |
|---|---:|---|---|
| ambiguous | | | |
| transition / partial | | | |
| duplicate | | | |
| leakage-adjacent | | | |
| unresolved GT | | | |
| other | | | |

- [ ] annotationされなかったraw全件の理由が分かる、と誤記していない
- [ ] 除外実体を必要に応じてreferenceとして保持した

## 5. Leakage-free split

- [ ] random image splitをそのまま使っていない
- [ ] cluster_idを確認した
- [ ] reading_group_idを確認した
- [ ] same readingがsplitを跨いでいない
- [ ] Test固定方針を決めた
- [ ] Train/Val/Test間のstem overlap = 0
- [ ] cluster overlap = 0
- [ ] reading_group overlap = 0
- [ ] reading_gt overlap = 0
- [ ] raw/processed/label存在整合を確認した

## 6. Split freeze

| Manifest | Rows | Train | Val | Test | Hash | Fixed at |
|---|---:|---:|---:|---:|---|---|
| | | | | | | |

- [ ] Test stem集合を記録した
- [ ] GT revisionはversionを分離して記録した
- [ ] historical benchmarkと最新GT評価を混同しない
- [ ] consumed Testをconfidence tuningへ戻さない

## 7. Baseline training gate

- [ ] Train/Valだけで学習する
- [ ] Test / Hard-Valを学習へ入れない
- [ ] seed / epochs / imgsz / batch / preprocessingを記録した
- [ ] NaN / inf / OOM有無を記録した
- [ ] best/last artifactを識別できる
- [ ] baseline評価を残した

## 8. Failure analysis

- [ ] wrong class
- [ ] missing
- [ ] extra
- [ ] ordering
- [ ] bbox localization
- [ ] GT error
- [ ] ambiguous physical state
- [ ] preprocessing mismatch
- [ ] ROI mismatch
- [ ] confidence mismatch
- [ ] camera/domain shift
- [ ] display artifact reuse
- [ ] runtime config mismatch

「モデルが悪い」と結論する前に、上記を切り分けた。

## 9. Hard-example mining

- [ ] candidate件数を記録した
- [ ] atomic unitへdedupした
- [ ] human reviewを実施した
- [ ] primary / ambiguousを分けた
- [ ] Train追加と独立Hard-Valへ分離した
- [ ] Hard-Valをtraining/conf tuningへ使用していない
- [ ] Standard Val gateを先に通した

## 10. ROI / preprocessing

- [ ] ROI座標系がraw frame基準である
- [ ] cropサイズを記録した
- [ ] resize後サイズを記録した
- [ ] processing orderを記録した
- [ ] trainingとruntimeの前処理が一致する
- [ ] ROI有効時に対象が欠けない
- [ ] ROIだから必ず精度が上がる、と一般化していない

## 11. Confidence threshold

- [ ] offline model-selection confを記録した
- [ ] production operational confを別に記録した
- [ ] confidenceをaccuracyと表現していない
- [ ] live昇格したthresholdをVal最適値と誤記していない

## 12. Live acceptance

- [ ] clean live frameで確認した
- [ ] annotated display frameをrawとして再利用していない
- [ ] resolved modelを確認した
- [ ] resolved confidenceを確認した
- [ ] resolved preprocessingを確認した
- [ ] 7桁検出/readingを確認した
- [ ] rejection条件も記録した

## 13. Production provenance

- [ ] model/run名
- [ ] weight hash
- [ ] selected confidence
- [ ] preprocessing
- [ ] ROI
- [ ] dataset/split provenance
- [ ] commit
- [ ] runtime stateの保存場所
- [ ] restore方法
- [ ] rollback方法
- [ ] residual risk

## 14. Stop criteria

- [ ] 追加学習を止める条件を満たしていないか確認した
- [ ] 問題がpreprocess/runtimeなら再学習していない
- [ ] augmentation/oversamplingを惰性で続けていない
- [ ] Test/Hard-Valへ過適合していない
- [ ] 新モデルだからという理由だけで採用していない
