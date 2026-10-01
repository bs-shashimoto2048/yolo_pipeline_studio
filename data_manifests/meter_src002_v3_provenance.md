# meter_src002 split v3 — Issue #40

本ドキュメントは、Issue #39で発見したdigital production (`production_combined_v2_5z`)
の2つの課題（4桁目`4→5`誤認識、official split内のcross-split near-duplicate 5ペア）に
対する調査・対応の記録である。

**結論を先に述べる: 本Issueではmodelのretraining・promotionを行っていない。**
Split integrity修正（near-duplicate 5ペアの解消）のみを実施し、production
（weight/conf/preprocess/contract/selected_model.json）は一切変更していない。
理由は後述する通り、新規hard-negative（4桁目class=4）画像を安全に確保できな
かったためである（Issue #40 §44の明示的停止条件に該当）。

**Test66 predictions/evaluation were not performed.**

## 1. Issue #39 findings（背景）

- independent acceptance 86件でException Match 96.5%、character accuracy 99.5%。
- 4桁目(position 3)に再現性ある`4→5`誤認識3件を発見。
- Train349の4桁目クラス分布: `5`=347件、`4`=わずか2件という極端な不均衡。
- この希少な`4`期間（2026-08-19周辺）の画像20件が全てTest66へ配分され、Trainには
  0件（Issue #39時点のTrain349には別途2件の`4`があったが、それらはこの期間とは
  無関係のVal/Train既存データ）。
- official split内にcross-split near-duplicate 5ペアが残存。

## 2. Cross-split near-duplicate 5ペアの精査と処理

| stem A | split A | GT A | stem B | split B | GT B | hamming | Δt(秒) |
|---|---|---|---|---|---|---|---|
| src_002_20260901_162800 | train | 0215195 | src_002_20260901_163600 | test | 0215198 | 3 | 480 |
| src_002_20260901_163200 | train | 0215197 | src_002_20260901_163600 | test | 0215198 | 3 | 240 |
| src_002_20260908_062000 | train | 0215297 | src_002_20260908_062800 | val | 0215300 | 1 | 480 |
| src_002_20260908_062400 | train | 0215297 | src_002_20260908_062800 | val | 0215300 | 0 | 240 |
| src_002_20260908_062800 | val | 0215300 | src_002_20260908_063600 | test | 0215302 | 1 | 480 |

全5ペアとも、GT値自体は異なる（完全な重複画像ではなく、短時間で連続撮影された
視覚的に酷似するフレーム）。**Test側（162800/163600/062800/063600の各Test member）
は一切変更していない。** 処理方針（Issue #40 §11に従う）:

- Testを含むペア（4ペア）: Train/Val側のcounterpart、すなわち
  `src_002_20260901_162800`・`src_002_20260901_163200`（train）・
  `src_002_20260908_062800`（val）をv3から除外。
- 残るTrain-Valペア（`908_062000`/`908_062400` vs `908_062800`）は、`908_062800`
  自体が上記処理で既に除外対象のため、連鎖的に解消済み。ただし`908_062000`・
  `908_062400`（train）もTest側`908_063600`とhamming<=1という近さであるため、
  同一クラスタとして扱い、**両方ともv3から除外**した。

結果: Train349→345（4件除外）、Val75→74（1件除外）、**Test66は66件のまま完全凍結**。

## 3. 新規hard-negative（4桁目class=4）mining

### 3.1 初回の誤り（自己発見・訂正済み）

当初、`raw/images`内の"20260818"日付プレフィックス全8枚を未annotated/未使用と
誤認し、hard-negative候補として採用しようとした。しかし
`meter_digital_combined_split_v2.csv`と照合した結果、**8枚全てが既にv2 split
（Val 6枚 + Train 2枚）に含まれていた**ことが判明した。Issue #39で確立した
正しい`used_stems()`照合（annotation label + split stem の和集合との照合）を
本Issueで最初省略したことが原因である。v3データセットディレクトリへの誤った
上書き・重複追加（6枚がtrain/valへ重複配置される状態）を発見し、作業中に
全て復元・削除した（production本体・v2オリジナルファイルへの影響はなし、
全て本Issue用の新規`meter_digital_combined_split_v3`ワークディレクトリ内での
事故であったことを確認済み）。

### 3.2 正しい照合による再mining

Issue #39の`digital_pool_mining.json`（正しい`used_stems()`チェック済みの
未annotated raw 1798件）と照合した結果、4桁目=4の真に新規な候補は
**src_002_20260819_144000（GT=0214968）とsrc_002_20260819_161000（GT=0214971）
の2件のみ**だった。目標（20-30件、理想40-60件）を大幅に下回るが、これは
以下の理由により物理的に確保可能な全量である:
- gas meterの累積カウンタは単調増加するため、4桁目が`4`を示す期間は
  データ収集期間中に一度（2026-08-19周辺）だけ存在した。
- その期間のraw画像は大半が既にTest66（20件）・excluded11（test-adjacent/
  unresolved/collisionとして2件）・Issue #39 independent acceptance（3件）に
  既に割り当てられている。

### 3.3 新split integrity監査ツールによる追加発見（最終的に0件採用）

本Issueで新規作成した`scripts/audit_dataset_split.py`（再利用可能なsplit
integrity checker、§6参照）で上記2件を含めたv3候補を監査したところ、
**両方ともTest66メンバーと視覚的にほぼ同一（同一readingのアイドル期間内）**
であることが判明した:
- `src_002_20260819_144000`（GT=0214968）は、Test66の`src_002_20260819_150000`
  （同一GT=0214968）と同一アイドル期間内であり、1200秒離れていてもhamming=0。
- `src_002_20260819_161000`（GT=0214971）は、Test66の`160500`/`161500`
  （同一GT=0214971）に挟まれた同一アイドル期間内であり、300秒離れていても
  hamming=0。

固定の時間窓（600秒）だけに頼る判定では、このような「長時間アイドル期間」を
見逃すことが分かった（アイドル中は値が変化しないため、物理的なシーンが
長時間にわたりほぼ完全に同一であり続ける）。この2件を採用すると、本Issueが
解決しようとしているleakageを新たに作り出すことになるため、**最終的に
両方とも不採用**とした。

### 3.4 結論

**新規hard-negative（4桁目class=4）primaryは最終的に0件。** Train345の4桁目
class4は2件のまま（v2から変化なし、ただしv2のTrain349から4件除外した345が
base）。Issue #40 §44「新規class4画像を十分確保できない」の停止条件に該当する
と判断した。

## 4. Annotation QA

新規追加画像が0件のため、annotation QAの対象はない。参考情報として、
Issue #39で発見したannotation不一致2件（excluded11内、primaryには含まれない）を
再掲する:
- `src_002_20260903_095200`: annotation`0215234` vs 目視`0215229`（不一致）。
- `src_002_20260904_102800`: annotation`0215257` vs 目視`0215252`（不一致）。

いずれも本Issueでは修正していない（primaryに影響しない孤立行のため、
修正の要否は引き続き範囲外とする）。

## 5. Position-3 class histogram（v2 vs v3）

| split | v2: class5 / class4 | v3: class5 / class4 |
|---|---|---|
| train | 347 / 2 | 343 / 2 |
| val | 69 / 6 | 68 / 6 |
| test | 46 / 20 | 46 / 20（変更なし） |

v3のtrain減少（347→343）は、near-duplicate解消で除外した4件が全て`class5`
だったため（除外4件のGT: 0215195, 0215197, 0215297, 0215297、いずれも4桁目`5`）。
**class4の絶対数（Train=2）は本Issueでは改善できなかった。**

## 6. 新規split integrity checker

`scripts/audit_dataset_split.py`を新規追加した（exact stem overlap・
perceptual near-duplicate・timestamp近接・class分布を機械確認する汎用ツール、
production weight/real inference不要・read-only）。v2で実行すると既知の5ペアを
正しく検出し、v3で実行すると0ペアとなることを確認済み（本ドキュメント§2/§3の
検証に使用）。GPU/production artifact不要な軽量designのため、将来Gate 1 CIへの
組み込みが可能（本Issueでは即時組み込みまでは行っていない）。

## 7. Training / Promotion

**実施していない。** 理由: 新規hard-negative primaryが0件であり、v3 Train
（345件、v2から near-duplicate 4件を除外したのみ）で再学習しても、
意味のある"hard-negative改善"の実験にならないため（単なるsplit整合性修正後の
再学習であり、dataset-only比較としての主旨に合致しない）。Issue #40 §44の
停止条件（新規class4画像を十分確保できない）に正式に該当する。

## 8. Production決定

**production変更なし。** `production_combined_v2_5z:best`（conf=0.60）を維持する。
旧weight（sha256 `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61`）・
selected_model.json・preprocess・contract(v1)、いずれも本Issueで一切変更していない。

## 9. 残存リスク・次Issue推奨

- 4桁目class=4の根本的な改善には、既存raw画像プールでは対応できない
  （物理的にデータが枯渇している）。将来的な改善には、(a) 実際のメーターが
  将来再び同様の桁遷移を起こすタイミングでの新規live capture、または
  (b) 別個体のdigital meterから同様の遷移期間を収集する、のいずれかが必要。
- `scripts/audit_dataset_split.py`を他プロジェクト（src003/src004）にも
  定期適用し、同様のnear-duplicate問題がないか確認することを推奨する。
- Issue #38で確立したCI Gate 2 (self-hosted GPU runner) の実機activation。

## 10. Test66

**Test66 predictions/evaluation were not performed.** manifest structure・
stem overlap・hash監査のみを実施した（§2参照）。Test66のGTをmodel改善判断へ
使用していない。Test66由来の画像を新規primaryやhard-negativeとして学習に
使用していない。
