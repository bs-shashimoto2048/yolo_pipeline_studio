# meter_src002 Test Ground-Truth v1 → v2 対応表 (Checkpoint 5S)

## 経緯
Checkpoint 5R の全データセット時系列(monotonicity)再チェックで、
`src_002_20260819_150000`(Test split)の既存annotation/manifest reading_gtに
疑義が生じた。Checkpoint 5S にて、当該stemの7桁each digitについて
**画像単独**(crop拡大、周辺フレームを見ない状態)で独立再判定した結果、
最後の桁(7桁目, x≈0.702762の位置)が figure-eight(二重ループ)形状であり、
現状annotationの class 0(単一ループ)とは明確に異なることを確認した。

補助情報として前後annotation済みフレームのreadingを参照したが(判定の根拠にはしていない):
- 直前 `src_002_20260819_143000`(30分前): reading=0214968
- 対象 `src_002_20260819_150000`: 画像単独再判定 reading=0214968
- 直後 `src_002_20260819_151000`(10分後): reading=0214971

いずれも本判定と整合し、旧値 0214960 は monotonicity 違反(直前比 -8)を起こしていたことが
補助的に裏付けられた(ただしこの一致は判定の根拠ではなく、あくまで独立判定後の確認材料)。

## 変更内容
| 項目 | v1 (旧, 監査保存用に凍結・変更なし) | v2 (本Checkpointで新規作成) |
|---|---|---|
| ファイル | `meter_src002_split_v1.csv` | `meter_src002_split_v1_testgt_v2.csv` |
| sha256 | `eff0f396a6457d6450903967ad2696648350fbf0407efc6668a65dd94373e5a4` | `86df9ed0e639b40b50468c51e89779e4aa2a5bd9d82b8f90be6ea130eaebd173` |
| 対象行 | `src_002_20260819_150000,...,test,0214960,...,2026-09-14` | `src_002_20260819_150000,...,test,0214968,...,2026-09-15` |
| split | test (変更なし) | test (変更なし) |
| cluster_id / reading_group_id | src_002_C005 / src_002_C005 (変更なし) | 同左 (変更なし) |
| 画像・stem | 変更なし・削除追加なし | 変更なし・削除追加なし |
| 対応するannotationファイル | `projects/meter_src002/annotations/labels/src_002_20260819_150000.txt`(7行目 `0 ...` → `8 ...` に修正済み) | 同上 |

上記1行以外、v1とv2は完全に同一(diff確認済み、他443行に差分なし)。

## 重要な注意(Checkpoint 5N評価結果との関係)
- Checkpoint 5N で報告済みの評価結果(全4プロジェクトのconfidence grid評価)は
  **v1のTest ground truthに基づく**。今回のv2作成により、v1とv2は異なるground truthを
  意味することになるため、**v1ベースの評価結果とv2ベースの評価結果を直接比較・混同しては
  ならない**。
- 本Checkpoint 5Sでは実際の再評価(モデル推論・スコア再計算)は一切行っていない。
  v2は「今後、Test再評価を行う場合は必ずv2を使用し、v1とv2の数値を混在させない」という
  ことを明示するために作成した記録用ファイルである。
- v2は現時点で **正式なmanifestとして採用されていない**(データセット生成・学習・評価の
  入力として使用されていない、gitにもstage/commitされていない)。正式採用は別途の
  Checkpointでの明示的な指示を要する。

## 追記(Checkpoint 5U): cluster C162 監査による2件目の訂正

Checkpoint 5Uにて、Test cluster `src_002_C162`(`_070000`/`_070800`/`_072000`/`_072800`、
いずれもv1 reading_gt=0215302)の全4stemについて、7桁目(idx6, x≈0.702762)を
画像単独で再確認した。対象時期と無関係な既知の"1"参照サンプル3件・"2"参照サンプル3件を
テンプレート(字形辞書)として用い、各stemの当該crop形状と比較した(前後時系列の
reading値そのものは判定根拠にしていない)。

| stem | idx6クロップの形状 | 判定 | 処置 |
|---|---|---|---|
| `src_002_20260908_070000` | 密な形状("2"参照と一致) | confirmed_current | 変更なし |
| `src_002_20260908_070800` | 密な形状("2"参照と一致) | confirmed_current | 変更なし |
| `src_002_20260908_072000` | 疎な単線形状("1"参照と一致、"2"参照とは明確に異なる) | **confirmed_error** | reading_gt: 0215302→0215301(annotation・testgt_v2とも訂正) |
| `src_002_20260908_072800` | 密な形状("2"参照と一致) | confirmed_current | 変更なし |

### 変更内容(2件目)
| 項目 | v1(変更なし) | v2(本追記で更新) |
|---|---|---|
| 対象行 | `src_002_20260908_072000,...,test,0215302,src_002_C162,src_002_C159,...,2026-09-14` | `src_002_20260908_072000,...,test,0215301,src_002_C162,src_002_C159,...,2026-09-15` |
| split/cluster_id/reading_group_id | 変更なし | 変更なし |
| annotationファイル | `projects/meter_src002/annotations/labels/src_002_20260908_072000.txt`(7行目 class `2`→`1`) | 同上 |

v1は本追記でも一切変更していない(sha256: `eff0f396a6457d6450903967ad2696648350fbf0407efc6668a65dd94373e5a4`のまま)。
v2はv1に対し現在2行の差分のみ(`_20260819_150000`行、`_20260908_072000`行)。

### evaluation_status(excluded_unresolved)の設計方針
Checkpoint 5U時点で、C162監査の結果unresolvedとして残ったTest stemは0件だった
(4件全てconfirmed_current/confirmed_errorのいずれかに確定)。そのため今回は
testgt_v2 CSVへの列追加は行っていない。ただし将来、Test stemにunresolvedな
GT疑義が残る場合に備え、以下の方針を設計・記録する:

- testgt_v2に `evaluation_status` 列(値: `confirmed` / `excluded_unresolved`)を追加する。
- `excluded_unresolved` を持つTest stemは、stem・split・画像そのものは一切変更・削除せず
  (Test構成は不変)、正式なモデル評価を行う際の**分母からのみ除外**する
  (対象画像自体をTestから外すのではなく、集計対象から除外するフラグとして扱う)。
- 現時点でこの状態に該当するTest stemはない。Train側の `_0903_095200` / `_0904_102800`
  はunresolvedのままだが、いずれもTrain split(評価分母には無関係)であり、5R draftの
  reading-group統合根拠としても使用しない方針を維持する。

### 5R draft impactへの新たな懸念(要エスカレーション、本Checkpointでは未対応)
`_072000` のreading_gtを0215301に訂正した結果、**既存(v1凍結済み)のVal split stem
`src_002_20260908_063200`(cluster_id=reading_group_id=`src_002_C158`、reading_gt=0215301)
と数値上のreading一致が新たに生じた**。この2stemはcluster_idが異なり(C162 vs C158)、
物理的には別クラスタとして扱われてきたが、訂正後のGTでは同一reading_groupに
統合されるべき関係になった可能性がある。

- これはv1凍結時点(Checkpoint 5K)では存在しなかった懸念であり、**今回のGT訂正によって
  新たに顕在化した**ものである。
- v1のsplit構成(Train/Val/Test)は本Checkpointでは一切変更していない
  (Safety Gateにより変更禁止)。
- 5R draft(train=351/val=76/test=66)自体への影響はない
  (C162は既にTrain/Val候補プールから除外済み、`_063200`はdraftでもval無変更)。
- ただし、**正式なTest再評価を行う際は、この`_072000`↔`_063200`間のreading一致が
  Val→Test方向のground-truth level leakageに相当する可能性がある**ことを明示する。
  解決(reading-group再設計、split再割当等)には別途のCheckpointでの明示的な指示と
  manifest変更権限が必要であり、本Checkpointの権限では対応できない。

## Test split構成への影響
なし。stem・画像・split所属(train/val/test)は一切変更していない。変更されたのは
`_20260819_150000`と`_20260908_072000`の2件のreading_gt値のみ。
