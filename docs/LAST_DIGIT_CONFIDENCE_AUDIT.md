# Last-Digit Confidence Instability Audit

Issue #34で新規作成。digital右端桁・drum赤サブ桁のconfidence低下・missing・extraが
「遷移中の物理状態」「モデル性能」「threshold設定」「frame単位の揺れ」のどれに
起因するかを、非Testデータで定量化する。

> 本Issueは**production threshold/model/ROI/preprocessを変更しない**。診断のみ。
> 数値はmodel精度評価（Val/Test accuracy）ではなく、production runtime条件下での
> **統合診断（production smoke同様の位置づけ）**として扱う。

## 1. Scope

| | Digital | Drum |
|---|---|---|
| project | `meter_src002` | `meter_src004` |
| model | `production_combined_v2_5z:best` | `candidate_roi_v3_5:best` |
| production conf | 0.60 | 0.80 |
| weight SHA256 | `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61` | `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db` |
| 対象桁 | reading文字列の右端1桁 | reading文字列の右端1桁（赤サブ桁） |

対象データ: `data_manifests/meter_digital_combined_split_v2.csv` /
`meter_src004_split_v3.csv` の `split=="train"` 行のみ（Test/Hard-Valは一切使用しない。
stem overlap確認はIssue #25/#26/#27/#32で既に実施済みの一覧を再利用）。

## 2. データ源の制約（重要）

Issueで想定していた「同一meterの連続frame系列（桁変化前後数秒程度、video FPS相当）」は、
本環境では取得できなかった。実際に存在するのは、2〜10分間隔の**periodic snapshot
capture**（`projects/<project>/raw/images/`、ライブカメラへのアクセス・アーカイブ済み
高FPS映像は本環境に存在しない）のみである。

このため、真の"ambiguous-middle"フレーム（デジット回転途中の物理形状）は取得できず、
以下の**近似proxy**を用いた:

- **stable**: 前後どちらの隣接captureとも末尾桁のground truthが一致する
- **boundary**: 前後いずれかの隣接captureと末尾桁のground truthが異なる
  （＝この時間帯のどこかでtransitionが起きたことを示す近似指標。真の遷移中フレームそのものではない）

この制約は結果の解釈に影響する（§9参照）。Closeせず停止する条件
（「非Test連続frameを十分確保できない」）に該当するかも検討したが、上記proxyでも
Case A/B/C/Dの定量的な切り分けに十分な情報が得られたため、この近似の下で分析を継続した。

## 3. Methodology

`scripts/analyze_last_digit_stability.py`（新規、diagnostic専用、production非変更）:

1. 対象プロジェクトの`selected_model.json`をread-onlyで読み、production重み（train_job_id/
   weight_type/SHA256）が想定通りであることを確認（不一致ならエラー停止）
2. 生画像（`raw/images/<stem>.jpg`）へ実際のproduction preprocess_profile
   （ROI/resize/grayscale/sharpen）を適用（`preprocess_service.apply`を直接呼び出し、
   productionと同じ変換ロジックを使用）
3. production重みで`model.predict(conf=0.05, iou=0.7, imgsz=640, rect=True, max_det=300,
   agnostic_nms=False, augment=False, batch=1, quantize=None)`を実行
   （**pinned argsはproductionと同一、confのみdiagnostic用に0.05へ下げる**。Issue #25/#26で
   固定したcontractを踏襲）
4. 返ってきた全candidate（conf>=0.05、NMS後）をx_center順にソートし保存
5. "clean"フレーム（production conf適用時にdetection_count==7かつreading完全一致）から
   末尾桁スロットのx_center分布を求め、末尾桁領域の境界を較正
6. 全フレームについて、末尾桁領域内のcandidateからGT一致クラスの最良confidenceと、
   不一致クラスの最良confidenceを算出し、production閾値・sweep閾値でのpass/fail判定を集計

**Threshold sweepの近似**: 各閾値での再判定は、conf=0.05で1回だけ実行したNMS後の
candidate confidenceをそのまま閾値でフィルタして行った（各閾値ごとにNMSを再実行
していない）。デジットのbox同士は空間的に十分離れているため、この近似による
NMS挙動差は無視できると判断した（production conf・diagnostic confの両方を実際に
実行し、production conf側の結果が実際のsweep結果内の同じ閾値の行と一致することを
確認済み）。

## 4. Report table

| Project | Events (GT末尾桁変化数) | Stable frames | Boundary frames | Stable missing | Boundary missing | Confidently-wrong | Extra(重複pass) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Digital | 21 | 314 | 35 | 0 (0.0%) | 1 (2.9%) | 1 (0.29% of all) | 1 (0.29% of all) |
| Drum | 273 | 41 | 298 | 0 (0.0%) | 62 (20.8%) | 6 (1.77% of all) | 0 |

「Confidently-wrong」= 誤ったクラスがproduction閾値を超え、正しいクラスは超えない
（productionが**確信を持って誤読を表示する**最も懸念すべきパターン）。
「Extra(重複pass)」= 正誤どちらもproduction閾値を超える（重複box）。

## 5. Digital — 詳細

- Stable frame（314件）: **100% recall、0% missing、0% extra**。production conf=0.60は
  安定範囲では全く問題ない。
- Boundary frame（35件）: missing 1件（2.9%）、confidently-wrong 1件、duplicate 1件。
- Threshold sweep（0.40〜0.70）: stable_pass=100%で完全に一定。boundary_passも
  0.40〜0.65の範囲でほぼ一定（97.1%）、0.70で初めて91.4%まで低下。
  **→ thresholdをこの範囲でどう動かしても実質的な差が出ない = Case C（threshold過剰）
  ではない。**

代表例（`src_002_20260903_075600`、GT末尾桁=9、前後のreading_gtは
`...228→229(該当フレーム)→229→229`）: diagnostic conf=0.05でも正しいクラス"9"の
candidateは一切検出されず（best_correct_conf=0.000）、代わりに"8"が0.841で検出された。
前フレームのGTは末尾桁8であり、このフレームでGTは9へ切り替わったばかりだが、
物理的な桁の形状がまだ8に近い状態だった可能性が高い（人間の目視判定でも
確定が難しい境界例、§9のambiguous proxyの限界と整合する）。

**→ Digitalの末尾桁不安定性はCase A（物理transition起因）が支配的。実害は349フレーム中
2件（0.57%）と極めて小さい。**

## 6. Drum — 詳細

- Stable frame（41件）: **100% recall、0% missing、0% extra**（digitalと同様、安定時は
  完全に信頼できる）。
- Boundary frame（298件）: missing **62件（20.8%）**。うち8件（13%）はconf>=0.05でも
  正しいクラスのcandidateが一切存在しない真の検出漏れ、残り54件（87%）は正しいクラスの
  candidateが存在するがproduction閾値0.80未満（confidence分布: min=0.000, p25=0.267,
  **median=0.521**, p75=0.724, max=0.800）。
- **confidently-wrong（6件、1.77%）**: 正しいクラスは検出されないか低confidenceのまま、
  誤ったクラスが0.80を超えて表示される最も懸念すべきパターン。6件中4件で誤クラスが
  **"7"**（`src_004_20260818_170200`(GT5→7)、`20260904_185200`(GT1→7)、
  `20260907_082800`(GT0→7)、`20260907_114400`(GT1→7)）、残り2件は**"6"**
  （`20260818_143800`・`20260818_164800`、いずれもGT4→6）という**再現性のある
  混同パターン**が見つかった。
- Consecutive missing streak: 最大**5フレーム連続**（capture間隔からおよそ10〜20分相当）。

### Threshold sweep（drum）

| conf | stable_pass | boundary_pass | all_pass |
|---:|---:|---:|---:|
| 0.50 | 100% | 90.6% | 91.7% |
| 0.60 | 100% | 87.2% | 88.8% |
| 0.70 | 100% | 85.2% | 87.0% |
| 0.75 | 100% | 82.6% | 84.7% |
| 0.80（production） | 100% | 79.2% | 81.7% |
| 0.85 | 100% | 75.5% | 78.5% |

boundary_pass率はthresholdに対して**滑らかに連続的**に変化しており、急峻な段差は無い。
これは「正解候補のconfidenceが閾値の直下に集中している」（Case C的な鋭いパターン）
というより、「transitionに応じてconfidenceが連続的に低下する」（Case A的なパターン）に
近い。ただし、0.80→0.50まで下げるとboundary missingは20.8%→9.4%まで改善するため
（約11.4ポイント分は閾値変更で回収可能）、**Case Cの実質的な寄与も無視できない**。

**→ Drumの末尾桁不安定性はCase A（主）+ Case C（副、閾値変更で一定量回収可能）+
Case B（軽微だが再現性あり、"7"・"6"への混同）の混合。**

## 7. Temporal stabilization PoC（offline replay、production非変更）

drumの実データ（339フレーム、時系列順）を用い、現行相当（raw）・
last-known-good hold（1〜3フレーム）・consecutive confirmation（2〜3フレーム確認、
max_hold=3）をオフライン再生比較した。

| 方式 | missing率 | 誤表示率（wrong_shown） | 備考 |
|---|---:|---:|---:|
| A) raw（現行相当） | 16.5% | 1.77% | |
| B) hold（max=1frame） | 5.0% | 12.09% | |
| B) hold（max=2frame） | 2.7% | 14.45% | |
| B) hold（max=3frame） | 1.8% | 15.04% | |
| C) confirmation（n=2, hold=3） | 13.6% | 64.90% | |
| C) confirmation（n=3, hold=3） | 53.7% | 32.45% | |

**重要な発見（安全上、production非採用を推奨する根拠）**: drumの末尾桁はGTが隣接
captureの81%（273/338）で変化するほど高頻度に変化するため、hold/confirmationは
「missingを減らす」代わりに「古い値をそのまま表示し続けることでGTと食い違う」
頻度を**大幅に増やす**（誤表示率が1.77%→12〜15%、confirmationでは最大65%まで悪化）。
これは§24の安全上の注意（「見た目を滑らかにするために古い値を長時間保持するのは
禁止」）が具体的な数値で裏付けられた形であり、**単純なhold/confirmation方式は
このIssueで採否検討する対象から除外する**（Recommendation Cは不採用）。

（注: この結果はdrumの末尾桁が非常に高頻度で変化するために生じるものであり、
変化頻度が低いdigitalの右端桁に同じ結論が当てはまるとは限らない。ただしdigitalは
missing自体が極めて稀（0.57%）のため、そもそも温度感のあるPoCの必要性が薄い）。

## 8. Case判定（まとめ）

| Project | 判定 | 根拠 |
|---|---|---|
| Digital | **Case A（支配的）** | stable 100%、boundary missing 2.9%のみ、sweepが実質フラット、実害0.57% |
| Drum | **Mixed: Case A（主）+ Case C（副、実測で回収可能）+ Case B（軽微、再現性のある"7"/"6"混同）** | stable 100%だがboundary missing 20.8%、sweepは滑らかに連続変化（Case A的）だが閾値変更で有意に回収可能（Case C的）、confidently-wrong 1.77%かつ混同先に偏り（Case B的） |

## 9. Recommendation

### Digital
**Recommendation A（現状維持）**。実害が極めて小さく（0.57%）、追加対応の優先度は低い。

### Drum
複数のRecommendationを提案する（すべて別Issueでの実施を想定、本Issueでは実装しない）:

- **Recommendation B（Issue #35で正式実施済み・結論: 不採用/0.80維持）**: production
  threshold（0.80）の正式な再評価をIssue #35で実施した。Standard Val58（58件）単独
  ではthreshold引き下げにより明確な改善が見えたが、独立な非Test acceptanceデータ
  （本IssueのTrain339フレーム）で検証したところ、**confidently-wrong件数がむしろ
  増加する**ことが判明し（0.80: 6件→0.70: 7件→0.60: 9件）、最優先基準（Gate A:
  confidently-wrongを増やさない）に反するため、**0.80を維持**することとした。
  詳細は[`data_manifests/meter_src004_roi_v3_provenance.md`](../data_manifests/meter_src004_roi_v3_provenance.md)
  のIssue #35節を参照。
- **Recommendation D（推奨・優先度高へ引き上げ）**: 末尾桁の"→7"・"→6"・"→8"混同に対する
  hard-negativeデータセット改善候補。Issue #35でRecommendation Bが不採用となったため
  （thresholdでは解決不能と判明）、現時点で最も有望な改善経路はこちらのみとなった。
  該当stemを起点にhard-negative収集・annotation改善を別Issueで検討する。
- **Recommendation C（不採用）**: 単純なtemporal hold/confirmationは§7のPoC結果により
  誤表示率を大幅に悪化させるため、この形での production化は推奨しない。より高度な
  手法（confidence-weighted fusion等）を将来検討する場合も、必ず本Issueと同じ
  offline replay評価を先に行うこと。

## 10. 関連文書

- [`docs/PRODUCTION_INFERENCE_CONTRACT.md`](PRODUCTION_INFERENCE_CONTRACT.md) — 本診断が
  前提とするproduction runtime条件（rect=True等）の正本
- [`data_manifests/production_model_provenance_v1.md`](../data_manifests/production_model_provenance_v1.md) /
  [`meter_src004_roi_v3_provenance.md`](../data_manifests/meter_src004_roi_v3_provenance.md) —
  現行production model採用の経緯（rect差分・末尾桁の既知課題、Issue #25）
