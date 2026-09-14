# Per-Meter Training Split v1（Checkpoint 5K, fixed_at=2026-09-14）

`meter_src002_split_v1.csv` / `meter_src003_split_v1.csv` / `meter_src004_split_v1.csv` / `meter_digital_combined_split_v1.csv` の共通READMEです。Issue #1 Checkpoint 5G〜5Kの監査・設計プロセスを経て確定した、4構成（src002単独 / src003単独 / src002+src003共通デジタルモデル / src004単独ドラムモデル）を公平に比較するためのTrain/Val/Test split境界を固定します。

## 対象4manifest

| ファイル | 対象 | 件数 | 用途 |
|---|---|---|---|
| `meter_src002_split_v1.csv` | `meter_src002`全annotation | 443 | src002単独モデル |
| `meter_src003_split_v1.csv` | `meter_src003`全annotation | 600 | src003単独モデル |
| `meter_src004_split_v1.csv` | `meter_src004`のA分類（7桁すべて画像単独で明確）のみ | 277 | src004単独ドラムモデル |
| `meter_digital_combined_split_v1.csv` | 上記src002+src003を単純結合 | 1043 | src002+src003共通デジタルモデル |

各行の列: `image_stem, project, split, reading_gt, cluster_id, reading_group_id, relative_path, fixed_at`

## 前処理

3projectとも同一設定（`processed/metadata.json`より確認済み）:
- `resize_mode=width, resize_width=640`（アスペクト比維持+黒padding）
- `grayscale_enabled=true`
- `sharpen_enabled=true, sharpen_strength=1.0`

## Split設計方針（Checkpoint 5G→5J→5K）

- **random image splitは使用していません。**
- Checkpoint 5G-3のcluster/freeze解析（`aHash256`＋Hamming距離≤4によるnear-duplicate/freeze検出、digit領域crop使用）を再利用し、各画像に`cluster_id`（時系列で連続する同一/類似フレーム群）を割当てました。
- さらに、同一`reading_gt`（7桁の実測値）を持つ画像が離れた時間帯の複数`cluster_id`にまたがって出現するケース（特にsrc002で顕著）をunion-findで統合し、`reading_group_id`という上位の原子単位を作成しました。**split割当てはこの`reading_group_id`単位で行っており、`cluster_id`・`reading_group_id`・`reading_gt`のいずれについても、Train/Val/Test間で重複が生じないことを機械検証済みです。**
- `reading_group_id`単位でのgreedy（LPT: 件数が大きい単位から、目標比率に対する不足量が最大のsplitへ割当て）によりTrain 70% / Val 15% / Test 15%を目標に配分しました。

## src002の希少class 6/7に関する評価上の制約

`meter_src002`はproject全体でclass 6=13件、class 7=142件（他classに比べ少ない）という母集団自体の偏りがあり、Val splitではclass 6=1件・class 7=1件と非常に薄くなっています（ゼロにはなっていません）。これはsplit設計の欠陥ではなく、**src002の実際の読み取り範囲（0214xxx〜0215xxx台）がこれらの数字をほとんど含まない物理的特性**によるものです。src002単独モデルでこれらのclassに関する評価指標を見る際は、サンプル数が極端に少ない参考値として扱ってください。`meter_digital_combined_split_v1.csv`ではsrc003側の寄与によりVal内のclass 6=30件・class 7=73件まで改善するため、これらのclassの評価が重要な場合はcombinedモデルでの評価を推奨します。

## src004: A分類277件のみ採用、B/C/Dは除外・reference保持

Checkpoint 5Iの監査により、`meter_src004`の全458annotationは以下に分類されています。

- **A（277件）**: 7桁すべて画像単独で明確 → 本splitで採用
- **B（175件）**: 赤サブ桁など1桁が遷移中で、その桁をlabelせず残り6桁のみ明確 → **本splitから除外**（未annotationの遷移digitがYOLO学習上background/negative扱いになり、体系的なlabelノイズを生むため）
- **C（4件）**: メイン桁側にも遷移の疑いがあり、画像単独では現在付与されているclassを確定できない（前後の時系列から逆算した値） → **本splitから除外**（時系列から逆算したclassをground truthにしない方針）
- **D（2件）**: 同一digit位置に複数class/bboxを持つ特殊annotation（`src_004_20260818_125000`, `src_004_20260818_131600`） → **本splitから除外**（同一位置への矛盾した教師信号を許可しない方針）

B/C/Dのannotation実体（`projects/meter_src004/annotations/labels/`配下）は**削除・修正せず保持**しており、将来のtransition handling方針が定まった際の再検討用referenceとします。`meter_src004_split_v1.csv`にはA分類277件のみが行として含まれ、B/C/Dの371stemはこのmanifestに一切出現しません（stem集合で混入0件を検証済み）。

## combinedについて

`meter_digital_combined_split_v1.csv`は、`meter_src002_split_v1.csv`と`meter_src003_split_v1.csv`の行を**単純結合しただけ**です。結合にあたって新たなshuffleや再split計算は一切行っておらず、各project内で既に確定したTrain/Val/Test境界（image_stemごとのsplit値）は完全に維持されています（境界一致を機械検証済み: mismatch=0）。

## Freeze前の機械検証結果(2026-09-14実施)

4manifestすべてについて以下を確認し、いずれも異常0でした。

- 件数がCheckpoint 5J報告値と一致（443/600/277/1043）
- Train/Val/Test間のstem重複=0
- Train/Val/Test間のcluster_id重複=0
- Train/Val/Test間のreading_group_id重複=0
- Train/Val/Test間のreading_gt重複=0
- raw/processed/label存在=100%（全件）
- bbox数=7（全件、src004もA分類のみのため7で統一）
- class範囲違反=0、座標範囲違反=0
- `meter_src004_split_v1.csv`へのB/C/D混入=0
- combinedにおけるsrc002/src003の元split境界の維持（mismatch=0）
