# Per-Meter Training Split v2（Checkpoint 5S〜5W, fixed_at=2026-09-15）

`meter_src002_split_v2.csv` / `meter_src004_split_v2.csv` / `meter_digital_combined_split_v2.csv` の共通READMEです。v1（Checkpoint 5K, [`meter_split_v1.README.md`](meter_split_v1.README.md)）で確定したannotationのうち、Checkpoint 5R以降の監査で発見・訂正されたground truth誤りを反映し、leakage-freeな状態を維持したままTrain/Val/Test境界を再設計・正式凍結したものです。**v1は一切変更していません**（本v2は別ファイルとして新規作成）。

## 対象3manifest

| ファイル | 対象 | 件数(train/val/test) | 用途 |
|---|---|---|---|
| `meter_src002_split_v2.csv` | `meter_src002` | 349/75/66 | src002単独モデル |
| `meter_src004_split_v2.csv` | `meter_src004`のclean 7-digit primaryのみ | 270/58/41 | src004単独ドラムモデル |
| `meter_digital_combined_split_v2.csv` | src002(v2) + src003(v1境界維持) | 769/165/156 | src002+src003共通デジタルモデル |

各行の列: `image_stem, project, split, reading_gt, cluster_id, reading_group_id, relative_path, fixed_at`（v1と同一スキーマ）

`meter_src003`はv2化の対象外です。src003自体のannotationにground truth疑義は発見されておらず、`meter_digital_combined_split_v2.csv`ではv1の`meter_src003_split_v1.csv`由来の420/90/90件をそのまま(shuffleなし)引き継いでいます。

## 前処理（v1と同一、変更なし）

- `resize_mode=width, resize_width=640`（アスペクト比維持+黒padding）
- `grayscale_enabled=true`
- `sharpen_enabled=true, sharpen_strength=1.0`

## v1 Test GT訂正履歴（2stem、Checkpoint 5S・5U）

`meter_src002_split_v1_testgt_v2.csv`（v1からTest行のreading_gtのみ訂正した記録ファイル、[対応表](meter_src002_testgt_v1_v2_correspondence.md)参照）で確定した2件の訂正を、本v2 manifestのTest行にも反映しています。v1 Test manifest自体（`meter_src002_split_v1.csv`のtest行）は変更していません。

| stem | v1 reading_gt | v2 reading_gt | 訂正根拠 |
|---|---|---|---|
| `src_002_20260819_150000` | 0214960 | 0214968 | Checkpoint 5S: 画像単独crop再判定で7桁目が figure-eight(二重ループ)であることを確認、旧値の単一ループ"0"は誤り |
| `src_002_20260908_072000` | 0215302 | 0215301 | Checkpoint 5U: 同一Test cluster(C162)内の既知"1"/"2"参照サンプルとの字形比較により、7桁目が疎な単線形状("1")であることを確認 |

Test split自体のstem構成・画像は66件とも**v1から一切変更していません**（機械検証済み: v1↔v2でstem集合完全一致）。

## Checkpoint 5N評価結果との関係（重要）

- Checkpoint 5N で報告済みの全4プロジェクトの評価結果（confidence grid評価）は、**v1のTest ground truthに基づくhistorical benchmark**です。
- 本v2 Test GTは上記2stemで異なる値を持つため、**v1ベースの5N結果とv2ベースの将来評価結果を直接比較・混同してはなりません**。
- **Test 66 stems（画像そのもの）はCheckpoint 5Nで既にconsumed済み**（推論・スコア確認に使用済み）です。今後、このTest setを再度confidence選択やハイパーパラメータ調整に使うことは、Test setの中立性を損なうため**禁止**とします。今後のTest利用は最終評価目的に限定してください。
- 本v2 freeze自体では実際のモデル再評価は行っていません。

## unresolved / ambiguous / B・C・D の除外方針

### src002: 3stem除外(349+75+66=490 ≠ annotation総数501。差分11件の内訳は以下)
v2 manifestの490件はsrc002の全annotation数501件と一致しません。差分11件の内訳:

| 区分 | 件数 | 理由 |
|---|---|---|
| Test-adjacent leakage除外(Checkpoint 5R確定) | 8 | 旧Testと近接timestamp/perceptual hash(Hamming≤4)で近接一致、または同一reading freeze block内に位置するためTrain/Val候補から除外 |
| 衝突reading-group除外(Checkpoint 5V/5W確定) | 1 (`src_002_20260908_063200`) | 訂正後Test reading(0215301)と数値上reading一致(reading_group=`src_002_C158`)。Val→Testのground-truth leakageを回避するためTrain/Valから除外(Testへの追加移動も行っていません) |
| unresolved GT除外(Checkpoint 5S/5T確定) | 2 (`src_002_20260903_095200`, `src_002_20260904_102800`) | 画像単独では該当桁のclassを確信できず、正式split(Train/Val/Test)の評価対象に採用しない方針(annotationファイル自体は保持、削除はしていません) |

いずれのannotationファイルも**削除・修正はしていません**（訂正した2stemを除く。詳細は上記「v1 Test GT訂正履歴」参照）。将来のGT再確認や別用途での再検討に備え、実体は保持されています。

### src004: B/C/D + 5Q追加分ambiguous(partial-label)を除外(270+58+41=369、annotation総数605のうち236件除外)

| 区分 | 件数 | 理由 |
|---|---|---|
| B(6bbox, 赤サブ桁など1桁遷移中) | 175 | 未annotationの遷移digitがlabelノイズになるため(v1から継続する方針) |
| C(main桁側にも遷移疑い) | 4 | 画像単独でclassを確定できないため(v1から継続する方針) |
| D(同一位置に複数class/bbox) | 2 | 矛盾した教師信号を許可しない方針(v1から継続する方針) |
| ambiguous(5Q追加分、partial-label 6bbox) | 55 | Checkpoint 5Q「7桁すべて明確な画像のみprimary候補」の方針により、確信できない桁を含む新規annotationはprimary splitに不採用 |

B/C/D/ambiguousいずれも、annotation実体は削除・修正せず保持しています(`src_004_20260901_143200`のみCheckpoint 5Sで桁の誤りをconfirmed_error訂正済みですが、ambiguous分類自体は変わらずprimary split対象外のままです)。

## v2 split生成根拠(Checkpoint 5J〜5W)

- **random image splitは使用していません。** v1と同じく、cluster_id(near-duplicate frame群)とreading_group_id(同一readingを持つ複数clusterのunion-find統合)を原子単位とし、この単位でLPT(件数の大きい単位から、目標比率に対する不足量が最大のsplitへ割当て)によりTrain/Valへ配分しました。
- **Testは完全固定**です。v1のTest split(src002: 66件、src004: 41件)のstem集合をそのまま採用し、reading_gtのみ上記2stemを訂正しています。Train/Val候補は、訂正後のTest reading集合と数値上重複するreading-groupおよびunresolved個別stemを除外した残りプールに対してのみLPT配分を行いました(Checkpoint 5Vのdry-run結果をそのまま採用し、本Checkpoint 5Wで新たな設計・再最適化は行っていません)。
- Train-Val間、Train/Val-Test間とも、stem・cluster_id・reading_group_id・reading_gtの4項目でoverlap=0を機械検証済みです(詳細は下記QA参照)。

## Freeze前の機械検証結果(2026-09-15実施)

3manifestすべてについて以下を確認し、いずれも異常0でした。

- ファイル存在・row数・重複stem=0
- raw/processed/label存在=100%(全件)
- bbox数=7(primaryのみ、全件)
- class範囲(0-9)違反=0、座標範囲違反=0
- manifest記載reading_gtとannotation実測値の不一致=0
- Train-Val間、Train/Val-Test間のstem・cluster_id・reading_group_id・reading_gt重複=0(project内部、全8項目×2project)
- src002 Test 66 stemsがv1と完全一致
- src002 v2 Test行のreading_gtが`meter_src002_split_v1_testgt_v2.csv`と完全一致
- src004 v2にB/C/D/ambiguous由来stemの混入=0
- src002-src003間のstem名重複=0(combined manifest)

## sha256(本README作成時点)

| ファイル | sha256 |
|---|---|
| `meter_src002_split_v2.csv` | `5addf6e380a7ee11173389c97a2f096ea74bf0e73cac6549a03134ee42b06df5` |
| `meter_src004_split_v2.csv` | `bf26ab20e935ca1a91f1535c2305a2a12205aa9516a24b3d53167eb8dde1276e` |
| `meter_digital_combined_split_v2.csv` | `19b66123d832f65bba48a627dabed0c28a5d4b5b69ca56c099965a13352631b0` |
| `meter_src002_split_v1_testgt_v2.csv`(参考、既存) | `a255057701a0236d44a5f4968a17f5e1ea7db55d13a26ec7ac6809db400f36a8` |

## 注意: 本v2 manifestは現時点でdataset生成・学習・評価のいずれにも未使用です

`meter_split_v2.README.md`および対象3 manifestの作成(本Checkpoint 5W)をもって、v2 splitの内容は正式に固定(freeze)されました。ただし、これらを用いた物理datasetの生成、モデルの再学習、Test再評価は、いずれも別途の明示的なCheckpointでの指示を要します。
