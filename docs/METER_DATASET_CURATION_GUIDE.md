# メーターデータセット選定ガイド — 少数・高情報量データで学習するための実践知

本ガイドは、本リポジトリのメーター読み取りモデル（`meter_src002`/`meter_src003`/`meter_src004`）開発で実際に行った
データセット選定・分割・hard example（モデルが誤りやすい、判定の難しい具体例）追加の手法を、**今回固有の作業日誌
としてではなく、次の画像認識案件でも再利用できる実践知**として整理したものである。

数値・件数は原則としてすべて一次資料（`data_manifests/`配下のREADME・CSV・provenance文書、および
GitHub Issue #1 / #15 / #16 / #18 / #19のコメント）から確認したものであり、断定できない箇所は
「事実」と「推論」を明示的に分けて記載する。曖昧な記憶や一般論から数値を作ることはしていない。

---

## 1. このガイドで伝えたいこと

固定カメラで連続撮影した画像は、**枚数が多いこと自体には意味がない**。近接するフレームはほぼ同じ内容を
繰り返し記録しているだけであり、それを大量に学習へ投入しても実質的な情報量は増えない。

本ガイドの中心メッセージは次の一文に集約される。

> **データを減らすことが目的ではない。冗長性・曖昧さ・評価リークを減らし、独立性・教師（GT）品質・
> failure-mode coverage（想定される失敗パターンをどれだけ網羅できているか）を高めることが目的である。**

これを実務上の4原則として言い換えると次のようになる。

1. **画像枚数ではなく独立情報単位を見る**: 「何枚あるか」ではなく「重複を除いた後、何通りの状況・値が
   独立に含まれているか」を基準にする（第2〜4章）。
2. **GT品質を優先する**: 枚数を確保するために曖昧なGTを無理に確定しない。確信の持てないデータは
   除外する（第3章、第10章）。
3. **評価データを学習判断へ戻さない**: Test（最終評価用）を一度でも調整に使ったら、以後の判断根拠に
   再利用しない（第6章）。
4. **failure mode改善ではholdout（学習に使わず評価専用に取っておくデータ）を残す**: 誤りを見つけたら
   類似画像を無差別に追加するのではなく、独立した改善確認用データを別途確保する（第6〜7章）。

今回の代表例（すべて実測値）:

| | raw画像 | annotation | 正式split採用数 |
|---|---|---|---|
| raw合計（src002+003+004） | **7,177枚** | — | — |
| src002（digital, production採用） | 2,299 | 501 | **490**（v2 split） |
| src004（drum, production採用） | 2,427 | 605（v2時点）→701（hard-example追加後） | v2: **369** → v3: **438**（Train339/Val58/Test41）+ 独立Hard-Val**27** |

「約500枚」という表現は曖昧なので、本ガイドでは常に**「1台あたり数百枚規模へ絞った」**という言い方を使う。
raw 7,177枚に対し、最終的にモデル学習・評価へ使ったのはsrc002で490件、src004で438+27=465件であり、
raw全体を学習に投入したわけではない。

`meter_src003`は途中まで同じ手法（cluster/reading_group単位split）で分割・annotationされたが、
**最終的なproduction対象からは外れた**（live acceptanceが別Issueへ分離されている）。そのため本ガイドでは
src003を「同じ手法を適用した参考事例」として扱い、成功事例の中心には据えない。

---

## 2. なぜ全画像を使わなかったのか

固定カメラによる連続撮影データには、次の特徴がある。

- **時系列近接フレームはほぼ同じ内容**: メーターの数字表示は数秒〜数十秒単位でしか変化しない。連写間隔がそれより
  短ければ、隣接フレームは実質的に同一画像に近い。
- **同一reading（同じ表示値）のフレームが連続して大量に存在する**（本ガイドでは「freeze block」と呼ぶ）。
  同じ値を100枚学習させても、モデルが学ぶ情報は1枚分とほとんど変わらない。
- **見た目がほぼ同じ画像が大量にある状態でrandom image split（画像単位でランダムにTrain/Val/Testへ振り分ける）を行うと、
  ほぼ同一の画像がTrainとValの両方に入ってしまう**。この場合Valでの精度は「未知データへの汎化性能」ではなく
  「見たことのある画像を覚えているかどうか」を測ってしまい、見かけ上の精度が実力より高く出る
  （＝near-duplicate leakage）。

これらを踏まえ、本プロジェクトでは**「画像の枚数」ではなく「独立した情報単位（reading・状態・条件）の数」を
基準にデータを見る**という考え方を採用した。この考え方の詳細な実装が第4章のleakage-free splitである。

---

## 3. データを残す/除外する判断基準

今回実際に用いた判断軸を、目的別に整理する。以下のテーブルには初出の専門語があるため、先に簡単に説明する。

- **bbox**（bounding box）: 画像中の対象（今回は各桁の数字）を囲む矩形のラベル。1画像あたりの期待bbox数が
  決まっていれば、その数と一致するかで欠損・過剰ラベルを検知できる。
- **cluster / cluster_id**: 見た目がほぼ同じ近接フレームをひとつの束にまとめた単位。同じ束に属する画像には
  同じ`cluster_id`を割り当てる。
- **reading_group_id**: 離れた時間帯でも同じ`reading_gt`（読み取り値）を持つ`cluster`同士を統合した、
  さらに上位の単位（詳細は第4章）。
- **perceptual hash（aHash等）**: 画像の見た目の近さを数値（ハッシュ値）として表現する手法。値同士が近いほど
  見た目も近いとみなせる。
- **Hamming距離**: 2つの値がビット単位でどれだけ異なるかを表す指標。perceptual hash同士のHamming距離が
  小さいほど、画像の見た目が近いと判定できる。
- **union-find**: 互いに連結している要素同士をひとつの集合にまとめるアルゴリズム。今回は同じreadingを持つ
  clusterを1つの`reading_group_id`へ統合するために使った。
- **holdout**: 学習には使わず、評価専用に取っておくデータ。Val/Test/Hard-Valはいずれもholdoutの一種。

| 判断軸 | 目的 | 判定方法 | 今回の例 | 何を防ぐか |
|---|---|---|---|---|
| GTが明確か | 誤った教師信号を学習させない | 目視で7桁すべてが確定できるか | src004 v2: 7桁確定画像のみprimary採用（369件）、遷移中は除外 | ラベルノイズによる学習の劣化 |
| bbox数/label完全性 | 欠損・過剰ラベルを除外 | 期待bbox数（7個）と一致するか | src004: bbox=6（遷移中で1桁欠損）を「B」として175件除外 | 部分的なGTによる誤学習 |
| 遷移中digit | 物理的に読み取り不能な状態を除外 | 桁が回転中で数字が確定できない画像か | src004 B分類175件、C分類（main桁側も遷移疑い）4件 | 「正解が本当は何か分からない」画像の教師化 |
| ambiguous/unresolved | 判定不能なGTを無理に確定しない | 目視で確信を持てない場合は除外 | src004 ambiguous/partial-label 55件、src002 unresolved GT 2件 | 誤ったGTの混入 |
| near duplicate | 情報量のない重複を圧縮 | perceptual hash（aHash256、Hamming距離≤4）で近接判定 | 全project共通でcluster_id付与に利用 | 実質的に同一の画像の水増し |
| same reading（freeze block） | 同一状態の大量重複を1単位に集約 | 同一`reading_gt`を持つ画像群をunion-findで統合 | `reading_group_id`として集約 | 同一状態の暗記 |
| test-adjacent | Testへの情報漏洩を防ぐ | Test画像とtimestamp/perceptual hashが近接するTrain/Val候補を検出 | src002: 8件除外 | Testの汚染（見かけ上の精度上昇） |
| class/failure-mode diversity | 精度が低いクラス・失敗パターンを個別に補強 | 既存Val/Testでの誤検出パターンを分析 | src004の2↔8混同に対するhard-example追加（第7章） | 特定クラス・特定失敗モードの学習不足 |

---

## 4. Leakage-free split（漏洩のない分割）の仕組み

今回採用した分割手順は、**random image split（画像単位のランダム分割）を一切使っていない**点が最大の特徴である。
代わりに、次の手順を踏んだ。

1. **ほぼ同じ写真を同じ箱にまとめる**: perceptual hash（aHash256）でフレーム間の類似度を計算し、
   Hamming距離が4以下（≒ほぼ同一）の連続フレーム群に`cluster_id`を割り当てる。
2. **同じreadingの箱もまとめる**: 離れた時間帯に撮影された画像でも、同じ`reading_gt`（読み取り値）を
   持つ`cluster_id`同士はunion-find（互いに連結している集合をまとめるアルゴリズム）で統合し、
   より大きな単位である`reading_group_id`を作る。
3. **その箱（reading_group_id）を丸ごとTrain/Valへ割り当てる**: 個々の画像ではなく`reading_group_id`単位で
   LPT（Longest Processing Time：件数が多い単位から、目標比率に対して最も不足しているsplitへ順に割り当てる
   greedy法）によりTrain 70%/Val 15%/Test 15%を目標に配分する。
4. **Testは一度確定したら固定する**: Test setのstem集合はv1で確定した後、v2以降も変更していない
   （GTの数値訂正のみ実施し、画像の入れ替え・追加・削除は行っていない）。

この設計により、**「同じメーター値のほぼ同じ写真がTrainとValの両方に入る」状況を構造的に防いでいる**。
これが起きると、Valでの評価は未知データへの汎化性能ではなく暗記能力を測ることになり、
本番投入後に初めて精度低下が発覚するリスクがある。

leakage検証（機械的チェック、v1/v2いずれも異常0件）:

- Train/Val/Test間のstem（ファイル名）重複 = 0
- `cluster_id`重複 = 0 / `reading_group_id`重複 = 0 / `reading_gt`重複 = 0
- raw/processed/labelの存在整合性 = 100%
- bbox数7個・class/座標範囲違反 = 0
- src004のB/C/D/ambiguous画像のsplit混入 = 0

---

## 5. 実際の件数推移

### src002（digital, production採用）

```
raw 2,299
  → annotation 501
    → v1 split 443（train310 / val67 / test66）
    → v2 split 490（train349 / val75 / test66）
        excluded 11 = test-adjacent leakage 8 + reading-group collision 1 + unresolved GT 2
```

### src004（drum, production採用）

```
raw 2,427
  → v1 annotation 458 → v1 primary（A分類のみ）277（train194 / val42 / test41）
  → v2 annotation 605 → v2 primary（clean 7-digit）369（train270 / val58 / test41）
        excluded 236 = B(6bbox遷移中)175 + C(main桁側遷移疑い)4 + D(同一位置に複数class/bbox)2 + ambiguous/partial-label 55
  → Issue #15 hard-example追加: 候補382 → atomic unit 127
        → 一次primary 99（Train71 + Hard-Val28）、ambiguous除外28
        → 書き込み前の再確認で誤読9件を検出、うち3件を除外 → 最終primary 96（Train69 + Hard-Val27）
        （127 → 96の差分31件 = ambiguous除外28 + 再確認時の除外3。後続の
        `meter_src004_roi_v3_provenance.md`で、再確認時の誤読9件は6件を値修正、3件をrescue失敗として除外したことを確認済み）
  → v3 annotation 701（605 + 96）
  → v3 primary split 438（Train339[270+69] / Val58 / Test41） + 独立Hard-Val27
```

**注意**: 「annotationされなかったraw画像」（src002: 2299-501=1798件、src004: 2427-701=1726件）の
全件について個別の除外理由が一次資料で確定しているわけではない。これらは主に
「そもそもannotation対象として選ばれなかった（クラスタ内の非代表フレーム等）」ものであり、
本ガイドではこの内訳を推測で埋めない。

---

## 6. Test / Val / Hard-Valの使い分け

| Split | 役割 | 今回のルール |
|---|---|---|
| Train | モデルの学習 | reading_group_id単位でLPT配分された70%相当 |
| Val | モデル選定・confidence閾値選定 | 学習中/学習後の評価に使用可 |
| Test | 最終評価専用 | **一度評価に使ったら（consumed後）、confidence選定・モデル採用・hard-example改善のいずれにも再利用しない** |
| Hard-Val | 特定failure mode改善の効果確認用の独立holdout | 学習・confidence tuningのいずれにも混ぜない。学習完了後の一回評価のみに使う |

src004の2↔8混同対応（第7章）はこのルールの具体例である。

- Hard-example由来のTrain追加69件は通常のTrainに合流させて学習に使用した
- 新設したHard-Val27件は**training/confidence tuningのいずれにも一切使用せず**、学習完了後に一回だけ評価し、
  改善確認（Exact Match 16/27→23/27）の根拠として使った
- Issue #18のv4候補（oversampling/augmentation）はStandard Val58で既にv3を下回ったため、
  **Hard-Val27の評価にすら進まなかった**（Hard-Valを「都合の良い結果が出るまで繰り返し当てる」対象にしないため）

---

## 7. Hard-example miningのケーススタディ（src004 2↔8混同対応）

src004では、本番運用中に3桁目の「2」を「8」と誤認識する事例が確認された。これに対する対応の流れ:

```
raw全体から候補抽出 382件
  → 目視により atomic unit（重複排除済み候補単位） 127件に整理
  → 全件annotation → primary 99件（Train71 + Hard-Val28） / ambiguous除外28件
  → 書き込み前の再確認で誤読9件を検出 → 3件を除外
  → 最終96件（Train69 + Hard-Val27）、ambiguous計31件除外
```

ここでの原則は、**「誤認識した画像を見つけたら、似た画像を大量にTrainへ追加する」のではない**という点にある。
代わりに次を行った。

1. 候補を独立したatomic unitへ整理し、重複や連続フレームをまとめてから初めて枚数を数える
2. 目視で確信の持てる画像のみprimary採用し、ambiguousは無理に教師化しない
3. 改善したかどうかを判定するための**独立したholdout（Hard-Val27）**を確保し、Trainには混ぜない
4. 学習後、Hard-Val27で一度だけ評価し、改善（16/27→23/27、class2 accuracy 83.3%→100%）を確認する

Issue #18では、このHard-Val27でさらに改善しないか検証する目的で、class2を3.5倍・class8を1.0倍で
oversamplingし、軽微なaugmentationを加えたv4候補（yolov8n/yolov8s）を学習した。しかし
**Standard Val58の時点でv3を下回った**（v3: Exact 56/58@conf0.50 に対し、v4A: 51/58、v4B: 53/58）ため、
事前に定めた判断基準に従いHard-Val27の評価にすら進まず、v4は不採用とした。

ここから得られる教訓: **データ量を人工的に増やす（oversampling/augmentation）ことは、必ず改善につながるとは
限らない**。今回のケースでは、独立したhard-exampleの丁寧な選定（127→96）の方が、機械的な水増しよりも
有効だった。

---

## 8. ROIとデータ効率

**事実**（`meter_src004_roi_v3_provenance.md`および関連Issueコメントより）:

| 指標 | full-frameモデル | ROIモデル |
|---|---|---|
| 赤サブ桁の実効幅 | 約7.54px | 約27.91px（約3.70倍） |
| Val58 Exact Match | 10/58 (17.2%) | 52/58 (89.7%) |
| missing（未検出digit数） | 22 | 0 |
| 7桁目 accuracy | 0.276 | 0.931 |

ROI（対象領域のみをcrop→resize width640）を導入した結果、同じVal58データセット・同じannotation件数のもとで
上記のような大幅な精度改善が確認された。

**ここからの解釈（推論、事実と分けて記載）**: 「ROIによって対象領域の実効解像度が上がったことで、
少ないデータ量でもモデルが対象情報に集中的に学習容量を割けるようになった」という説明は直感的には妥当だが、
この因果関係そのものを直接検証した一次資料はない。確認できている**事実**は、あくまで
「実効pixelサイズが約3.7倍になった」ことと、「同一データ・同一annotation件数で精度が大きく向上した」ことの
2点であり、両者の間の因果メカニズムの詳細（モデル内部でどう学習容量が再配分されたか等）は検証していない。

なお、ROIを使う場合は**学習時とruntime（推論実行時）で同一の前処理（crop→resize→grayscale→sharpenの順序と
パラメータ）を再現する必要がある**。本プロジェクトでは学習・image predict・video推論のいずれも同一の
`preprocess_service.apply()`を経由することでこれを担保している。

---

## 9. 今回うまくいった要因

| 確認できた事実 | 考えられる理由（推論） |
|---|---|
| leakage-free split（cluster_id/reading_group_id単位のLPT配分、leakage検証0件） | 見かけ上の精度と実際の汎化性能の乖離を防げた |
| ambiguous/遷移中画像の除外（src004で236+31件） | 誤ったGTによる学習の混乱を避けられた |
| Testの固定・非再利用 | Testの評価値が「一度も調整に使っていない」という意味で信頼できる指標になった |
| Hard-Valという独立holdoutの新設 | 特定failure mode（2↔8混同）の改善を、Trainに混ぜた画像で自己評価する誤りを避けられた |
| ROI導入（実効解像度3.7倍） | 対象情報の相対的なサイズが増え、少数データでも学習が成立しやすくなった（詳細な因果は未検証） |
| 学習時とruntimeの前処理を完全一致させたこと | 学習で評価した性能とruntimeでの実際の性能の乖離を防げた |
| live acceptance（実カメラでの受入確認）を最終ゲートにしたこと | オフライン指標だけでは見えない実運用条件（照明・カメラ揺れ等）のギャップを検出できた |

---

## 10. 失敗・やらなかったことからの教訓

- **random image splitを使わない**: 近接フレーム・同一readingがTrain/Valに分散し、見かけ上の精度が
  実力より高く出るリスクがある。
- **ambiguous GTを無理に教師化しない**: 確信の持てない画像を無理にラベル付けすると、誤った教師信号として
  学習を汚染する。
- **Testを繰り返しtuningに使わない**: 一度でもconfidence選定やモデル採用の判断根拠に使うと、
  それ以降のTest評価値は「未知データへの性能」ではなくなる。
- **hard例を見つけたら全部Trainへ投入しない**: 類似画像を大量に追加するのではなく、独立したunitとして
  精査し、改善確認用のholdoutを別途残す。
- **augmentation/oversamplingを万能視しない**: 今回のv4候補はoversampling+augmentationを行ったにもかかわらず
  baseline（v3）を下回った。データを人工的に増やせば必ず改善するとは限らない。
- **trainingとruntimeの前処理をずらさない**: 前処理（ROI/resize/grayscale/sharpen）が学習時とruntimeで
  異なると、オフライン評価とライブ性能が乖離する。
- **annotation済み（オーバーレイ描画済み）の表示用画像を、raw診断画像として再利用しない**: 描画・JPEG再圧縮済みの
  画像をモデルに再入力すると、信頼度が実際より大きく劣化して見え、誤った原因診断につながる
  （本プロジェクトのIssue #17で実際に確認された事象）。

---

## 11. 次回案件用チェックリスト（12ステップ）

| # | ステップ | やること | 完了条件 | やってはいけないこと |
|---|---|---|---|---|
| 1 | raw inventory | project別にraw画像の実枚数を数える | 実測件数（推定ではない）を記録した | 「だいたい○千枚」で済ませる |
| 2 | annotation audit | どの画像にannotationが存在するか、bbox数・class妥当性を確認する | annotation総数と、bbox数異常・class範囲違反の件数を実測した | annotation済みかどうかを確認せず全raw画像を学習対象とみなす |
| 3 | duplicate/temporal cluster | perceptual hash等でnear-duplicate/連続フレームを検出し`cluster_id`を付与する | 全annotation画像に`cluster_id`が付与され、重複0件を機械検証した | クラスタ化せずrandom splitへ進む |
| 4 | GT確定可否 | 各画像のGTが目視で確信を持てるか判定する | 確信可否の判定結果（primary/ambiguous）を全件記録した | 確信の持てない画像を推測でラベル確定する |
| 5 | primary/excluded分類 | 除外カテゴリ（遷移中・ambiguous・重複ラベル等）ごとに件数を記録する | 除外理由別の件数集計が一次資料として残っている | 除外理由を後から思い出せない状態にする |
| 6 | leakage-free split | `reading_group_id`単位でTrain/Val/Testへ配分する | stem/cluster_id/reading_group_id/reading_gtの重複が全て0であることを機械検証した | 画像単位のrandom splitを使う |
| 7 | Train/Val/Test freeze | Test setのstem集合を確定し、以後変更しない | Test固定後の変更履歴がGT訂正のみであることを確認した | Testの構成画像を後から追加・削除する |
| 8 | baseline | 最初のモデルを学習し、Val/Testで評価する | baseline指標（Exact Match等）を記録した | baseline評価をスキップしていきなりチューニングする |
| 9 | failure analysis | Val/Test/実運用での誤検出パターンを分析する | 具体的な失敗モード（例: 特定class間の混同）を特定した | 「なんとなく精度が低い」で終わらせる |
| 10 | hard-example追加 | 失敗モードに対応する独立候補を抽出・annotationしTrainへ追加する | 候補→atomic unit→primary採用の各段階の件数を記録した | 類似画像を無差別に大量追加する |
| 11 | independent Hard-Val | hard-example対応の効果確認用に、Trainに混ぜない独立holdoutを新設する | Hard-Valがtraining/tuningのいずれにも使われていないことを確認した | 改善確認をTrainに混ぜた画像や既存Valの使い回しで行う |
| 12 | production live acceptance | 実運用環境（実カメラ等）で最終受入確認を行う | live環境での検出結果（件数・confidence）を記録した | オフライン指標のみで本番投入を判断する |

---

## 12. 今回の限界

- **「少数枚なら常に十分」という一般化はしない**: 今回の手法は「重複・曖昧GT・leakageを減らせば、
  相対的に少ない枚数でも有効な学習セットになり得る」ことを示したものであり、「データは少ない方が良い」
  という一般則ではない。class diversity（クラス種類の網羅性）やcondition diversity（照明・角度等の条件の
  網羅性）が不足している場合は、追加のデータ収集が必要になる。
- **camera/domainが変わる場合は再評価が必要**: 本ガイドの数値（ROI効果、必要annotation件数等）は
  今回の固定カメラ・数字表示メーターという条件に基づくものであり、異なるカメラ・異なる対象では
  同じ枚数・同じ閾値で十分とは限らない。
- **src003はproduction対象外になった**: src003は同じsplit手法・annotation手法を適用したが、
  最終的にlive acceptanceの対象から外れている（別Issueへ分離）。したがって
  **「digital機種向けの共通モデルが成功した」という結論を、src003にまで一般化しない**こと。
  src002の成功事例のみが実運用での受入確認まで完了している。
- **一次資料で断定できない事項は断定しない**: 後続provenanceで確認できた事項は更新する一方、以下は
  現時点でも一次資料から明確に確認できないため、推測で埋めない。
  - annotationされなかったraw画像（src002 1,798件、src004 1,726件）の個別の除外理由の全件記録
  - 初期の物理個体（Domain A、W/X/Y/Z）からsrc002/003/004という現在の命名体系への移行を
    1対1で明記した記録

---

## 13. End-to-end workflow — raw取得からproduction acceptanceまで

この章は、次回案件で「何から始め、どこで止まり、失敗したらどこへ戻るか」を再現するための実行順である。
個別案件の数値は異なっても、**データの独立性・GT品質・評価分離・runtime整合を順番に確認する**という考え方は再利用できる。

| Step | 入力 | 主な作業 | 人が判断すること | 機械検証 | 完了条件 | 次へ進めない条件 / 戻り先 |
|---|---|---|---|---|---|---|
| 1. raw inventory | raw画像 | source/session/project別の実枚数を数える | source境界が妥当か | 重複stem・破損・画像サイズ | 実測件数とsource対応が記録済み | source不明 → 収集/整理へ戻る |
| 2. representative sampling | raw | 時系列近接・見た目類似をまとめ代表候補化 | 同一状態とみなせるか | timestamp/aHash/Hamming距離 | representative候補とclusterが説明可能 | 閾値根拠不明 → sampling設計へ戻る |
| 3. annotation | 代表候補 | bbox/class/reading GT作成 | 7桁が画像単独で読めるか | bbox数・class・座標 | annotation作成済み | ambiguous → 除外/保留 |
| 4. annotation audit | annotation | GT再確認 | transition/partialを確定できるか | duplicate bbox、範囲、reading整合 | primary/ambiguous等が分類済み | unresolved → reviewへ戻る |
| 5. temporal/visual grouping | primary | near-duplicateをcluster化 | cluster境界の妥当性 | cluster_id欠損/重複 | 全対象にcluster_id | 連続重複が残る → samplingへ |
| 6. reading grouping | cluster | 同一readingを上位groupへ統合 | GTが同一と確定できるか | reading_group overlap候補 | reading_group_id確定 | GT疑義 → annotation auditへ |
| 7. ambiguous除外 | audit済みデータ | primary/excludedを確定 | 教師化してよいか | 除外カテゴリ件数 | 除外理由が記録済み | 無理な推定GT → auditへ |
| 8. split設計 | primary groups | group単位でTrain/Val/Test配分 | 物理的境界に問題ないか | stem/cluster/reading overlap | leakage=0 | overlap有 → grouping/splitへ |
| 9. split freeze | split draft | Testを固定・hash記録 | 評価用として妥当か | row数/hash/存在整合 | freeze記録完成 | GT未確定 → auditへ |
| 10. baseline training | Train/Val | baseline学習 | 学習が成立しているか | loss/NaN/OOM/成果物 | baseline指標記録 | dataset不備 → split/annotationへ |
| 11. Val評価 | Val | 指標・confidence比較 | 失敗がモデルかデータか | reading/7-detect/class等 | failure modeを説明可能 | 原因不明 → failure analysisへ |
| 12. failure analysis | Val/非Test実画像 | 誤り分類 | GT/物理状態/前処理を目視 | missing/extra/wrong class等 | 原因仮説と証拠 | 診断不成立 → clean input取得へ |
| 13. hard-example mining | failure candidates | 候補抽出・dedup・review | primary/ambiguous | atomic-unit overlap | Train追加と独立holdout確保 | holdout無し → split再設計 |
| 14. independent Hard-Val | Hard-Val | 一回評価 | failure mode改善を確認 | baseline/candidate比較 | 改善/非改善を記録 | tuningに使った → holdout再設計 |
| 15. ROI/preprocess検討 | failure analysis | crop/resize等の候補比較 | ROIが対象を安定包含するか | 座標・出力サイズ・処理順 | training/runtime仕様が固定 | runtime不一致 → preprocess実装へ |
| 16. candidate比較 | Val | baseline対candidate | 実用上の差があるか | 同一条件の指標 | 採否根拠が説明可能 | 条件不一致 → 評価設計へ |
| 17. runtime wiring | candidate | selected model/conf/preprocess配線 | 設定が意図どおりか | resolved model/conf/order | runtime解決値確認 | fallback誤り → runtime実装へ |
| 18. live acceptance | 実カメラ | clean liveで受入 | 実運用で7桁が妥当か | resolved設定・ログ | accepted/rejected記録 | offlineとの差 → failure analysisへ |
| 19. provenance | 採用構成 | hash/設定/根拠を記録 | 残存リスク | hash/commit参照 | 復元可能な記録 | artifact所在不明 →永続化設計へ |
| 20. production | provenance済み構成 | 運用開始 | 変更の妥当性 | smoke/監視 | rollback可能 | 再現不能 → production化しない |

### 13.1 戻り先を先に決める

このworkflowで重要なのは、各stepを直線的に「完了させる」ことではない。
たとえばValでmissingが多い場合、すぐモデルサイズを上げるのではなく、**ROI・前処理・bbox/GT・対象pixelサイズ**を先に確認する。
GT疑義が見つかった場合はtrainingへ進まずannotation auditへ戻る。runtimeだけ精度が落ちる場合はtrainingではなく
preprocessing/runtime wiringへ戻る。この戻り先を明示しておくことで、「とりあえず再学習」を減らせる。

## 14. Representative sampling — 連続1000枚を1000独立サンプルと数えない

固定カメラでは、時間的に近いフレームほど同じreading・照明・姿勢を共有しやすい。
そのため本プロジェクトでは、timestamp近接とperceptual hashを使って連続フレームの類似性を調べ、
near-duplicate群を\`cluster_id\`として扱った。

今回の一次資料で確認できる実装要素は以下である。

- digit領域のaHash256
- Hamming距離 \`<=4\` をnear-duplicate判定に使用
- 時系列で連続する類似frameをcluster化
- 同じ\`reading_gt\`が離れたclusterにも出現する場合は、さらに\`reading_group_id\`で統合
- 同一readingが長く継続する状態をfreeze blockとして扱う

ここでの一般化した実務原則は、**「1000枚ある」ではなく、「独立したreading/状態/条件がいくつあるか」を数える**
ことである。1秒間隔で1000枚撮影しても、表示値・照明・角度がほぼ変化しなければ、1000の独立情報ではない。

一方、samplingの比率や時間閾値を本案件の値から他案件へそのまま移植してはいけない。
撮影周期、対象物の変化速度、シャッター条件が異なれば適切な閾値も異なるため、次案件では
「どの条件なら同一状態とみなせるか」を先に観察して決める。

## 15. Annotation QA protocol — GTを学習データより先に疑う

### 15.1 目視reviewの順序

1. 画像単独で7桁すべてが読めるか
2. bboxが期待数7個あるか
3. classが0〜9の範囲か
4. bbox座標が画像内にあるか
5. x順で7桁のreadingとして整合するか
6. 回転中・遷移中digitがないか
7. 同一位置に複数bbox/classがないか
8. 周辺フレームを見なければ決められないGTになっていないか

**周辺時系列から逆算しないと確定できないdigitを、画像単独GTとして確定しない**ことが重要である。
src004ではB/C/D/ambiguousをprimaryから除外した。

### 15.2 review結果の状態

| 状態 | 意味 | 処置 |
|---|---|---|
| confirmed_current | 現annotationが画像単独で妥当 | 維持 |
| confirmed_error | 現annotationが誤りと確認 | 根拠を記録して修正 |
| unresolved | 画像単独で確信できない | primary評価/学習から除外 |
| rescue | 再reviewで明確なGTを確定可能 | 修正後に再監査 |
| reject | 物理的曖昧さ等で教師化不適 | annotation対象外/除外 |

src004 hard-exampleでは127 atomic unitを目視し、一次primary 99件から再確認を経て最終96件へ絞った。
後のprovenanceで、再確認時に見つかった誤読9件は**6件を値修正、3件をrescue失敗として除外**したことが確定している。
このように、annotation後にも「書いたラベルを正しい前提で扱わない」工程を置く。

## 16. Split freeze / Test hygiene — TestをVal化させない

Testの本質は「一度しか推論してはいけない」ことではなく、
**採用判断・confidence選定・hyperparameter調整へ繰り返し使うと、Testが実質的にValへ変わる**ことである。

src002ではv1 Testの2stemについて後からGT誤りが確認された。
対応は「Test画像を入れ替える」ことではなく、v1をhistorical benchmarkとして保存したまま、
v2側でreading_gt訂正履歴を明示する方式を取った。

重要な区別:

- **v1 Test画像集合**: freeze済み、stem構成維持
- **v1 GT**: 当時のhistorical benchmarkに使われた
- **v2 GT**: 2stem訂正後の正しいGT
- **5N評価**: v1 GT基準のhistorical result
- **以後の採用判断**: consumed Testをtuningへ戻さずVal中心で実施

GT訂正によって新たなreading-level leakageが見つかった場合は、古い結果を無理に「最新版」として扱わず、
どのGT versionで評価したかを明示する。

## 17. Confidence threshold — confidenceはaccuracyではない

confidence thresholdは「モデルの正しさ」そのものではなく、**検出候補を残すためのfilter条件**である。
したがって、thresholdを0.25から0.80へ上げたことを「モデル精度が上がった」と表現してはいけない。

### 17.1 offline thresholdとoperational threshold

- **offline Val threshold**: Val上のreading/検出件数等を比較し、モデル選定のために使う
- **operational threshold**: 実カメラでノイズやfalse detectionを抑えつつ必要桁を維持できる運用値

src004のproduction confは最終的に0.25から0.80へ変更された。
この0.80は、selected video inference経路で実カメラ受入を行い、7/7 detectionとサブ桁変化を確認したことによる
**運用設定の昇格**である。Standard Val58 / Hard-Val27をconf=0.80で再評価して選んだ値ではない。

したがって文書上は、\`model accuracy\`、\`offline model-selection conf\`、\`production operational conf\`
を別欄で記録する。

## 18. Offline validation / live validation / display artifactを混同しない

| 種別 | 主な目的 | 注意 |
|---|---|---|
| Standard Val | model/conf選定 | tuningに使用可 |
| Hard-Val | failure mode改善確認 | Train/conf tuningへ混ぜない |
| Test | 最終評価 | consumed後のtuning再利用を避ける |
| saved clean real image | runtimeに近い診断 | 保存前処理の有無を確認 |
| clean live frame | 実カメラ受入 | raw/cleanであることを確認 |
| annotated display frame | UI表示 | **再推論入力にしない** |
| true runtime inference | 実運用経路 | resolved model/conf/preprocessを確認 |

Issue #17で重要だったのは、\`live/latest.jpg\`が**表示用annotation済みartifact**だった点である。
これをraw camera frameとみなして再推論すると、overlay・再圧縮等が追加された画像をモデルへ入れることになり、
confidence低下などを「本番workerの問題」と誤診しうる。

これは「workerがannotated画像を再帰的に入力していた」という意味ではない。
**診断者がdisplay artifactをraw相当として再利用したことが問題**であり、この区別を明記する。

## 19. Failure analysis taxonomy — 「モデルが悪い」の前に切り分ける

| Failure | 見え方 | 最初に確認するもの | 短絡してはいけない判断 |
|---|---|---|---|
| wrong class | 桁数は合うが数字が違う | crop/GT/confusion | すぐデータ増量 |
| missing | 6桁以下 | 対象pixelサイズ、ROI、conf | モデルサイズ不足と断定 |
| extra | 8桁以上 | NMS/conf/背景誤検出 | GT誤りと断定 |
| ordering | 数字はあるがreading順が違う | x中心・bbox | class精度問題と混同 |
| bbox localization | classは正しいが位置不安定 | label bbox/IoU | class学習だけを疑う |
| GT error | predictionが正しそうに見える | 元画像単独review | predictionを誤り扱い |
| ambiguous physical state | 遷移digit | raw frame | 無理に正解を1つ決める |
| preprocessing mismatch | offline良・runtime悪 | processing_order | 再学習で解決しようとする |
| ROI mismatch | 対象欠け/縮尺異常 | raw基準座標 | model劣化と断定 |
| confidence mismatch | missing/extraが閾値依存 | resolved conf | accuracy値と混同 |
| camera/domain shift | 新条件だけ悪い | 照明/角度/機種 | 既存Valだけで判断 |
| display artifact reuse | 再保存画像でconfidence低下 | input provenance | runtime worker不具合と断定 |
| runtime config mismatch | UIと実推論が違う | selected_model/job resolved値 | 学習runの再現性を疑う |

failure analysis logは companion template
[\`METER_DATASET_REVIEW_TEMPLATE.md\`](METER_DATASET_REVIEW_TEMPLATE.md) を使う。

## 20. Decision record — 採用しなかった案も残す

重要な判断は、結果だけでなく次の4項目で残す。

- **Decision**: 何を選んだか
- **Evidence**: 何を根拠にしたか
- **Rejected alternative**: 何を採用しなかったか
- **Residual risk**: 何が未検証のまま残るか

本案件の代表例:

| Decision | Evidence | Rejected alternative | Residual risk |
|---|---|---|---|
| random image splitを使わない | near-duplicate/freeze構造 | 画像単位random split | grouping閾値は案件依存 |
| ambiguousをprimaryから除外 | 画像単独GTを確定不能 | 時系列から逆算してlabel | transition認識は未対応 |
| fixed Testを維持 | leakage/評価中立性 | tuningへ再利用 | consumed Testの将来利用制約 |
| Hard-Val新設 | 2↔8 failure改善を独立評価 | 全hard例をTrainへ投入 | Hard-Val自体の規模は27 |
| ROI採用 | 同一Val58で10/58→52/58、missing22→0 | full frame継続 | camera位置変更時の再調整 |
| v3採用/v4不採用 | v4がStandard Valでv3未満 | oversampling/augmentation継続 | 別手法の余地 |
| src004 conf0.80 | live acceptanceで7/7維持 | conf0.25継続 | 0.80でVal/Hard-Val再評価なし |
| src003をproduction対象外 | live acceptance未完了 | digital共通成功として扱う | 将来再評価可能 |
| selected_model.jsonはlocal-only | weight/runもprojects配下でGit外 | JSONだけGit管理 | clone単体ではruntime復元不可 |

## 21. Practical "when to stop" criteria

改善を続けるほど良いわけではない。停止条件を先に持つことで、Test/Hard-Valへの過適合や無限再学習を防ぐ。

### 21.1 追加学習を止める

- candidateがStandard Valでbaselineを下回り、改善仮説も説明できない
- failure-specific candidateが通常Valを犠牲にしている
- 追加augmentation/oversamplingが再現性のある改善を示さない
- 既に問題がmodelではなくpreprocess/runtimeにある

src004 v4はStandard Valでv3を下回ったため、Hard-Valへ進めず停止した。

### 21.2 データを追加する

- 特定class/状態が実際に不足している
- liveで新しいfailure modeが確認された
- camera/domain shiftがあり現datasetに代表例がない
- ambiguousではなく、明確なGTを持つ独立例を収集できる

「精度が低いから何でも追加」はしない。

### 21.3 preprocess/ROIを疑う

- missingが多い
- 対象pixelサイズが小さい
- runtimeだけ悪い
- full-frame内で対象が極端に小さい
- 学習時とruntimeのprocessing orderが異なる

src004ではモデル大型化より先にROIで対象の実効幅を約7.54px→27.91pxへ増やし、同一Val58で
Exact 10/58→52/58、missing22→0を確認した。

### 21.4 モデル世代を変える

- dataset/GT/preprocess/runtimeの問題を先に除外した
- 同一条件比較が可能
- 新モデルの改善が運用リスクを上回る

YOLO26比較ではdigitalに小幅な改善場面があった一方、drumは悪化し、最終的に両方とも現行YOLOv8nを維持した。
**新しいモデルだから採用する、という判断はしない。**

### 21.5 運用対象から外す

- live acceptanceを完了できない
- domain条件が未定義
- productionで再現可能なmodel/conf/preprocess構成を固定できない
- 評価根拠がTestへの過度な合わせ込みに依存している

src003はsplit/学習履歴があっても、production成功例として扱わない。

## 22. Reusable templatesの使い分け

本文は「なぜ・どう判断するか」を説明し、実作業で埋めるフォームは別文書に分離する。

- [\`METER_DATASET_CURATION_CHECKLIST.md\`](METER_DATASET_CURATION_CHECKLIST.md)
  - raw inventory
  - annotation audit
  - split integrity
  - training/Val/live acceptance前のgate
- [\`METER_DATASET_REVIEW_TEMPLATE.md\`](METER_DATASET_REVIEW_TEMPLATE.md)
  - exclusion reason
  - model candidate比較
  - failure analysis log
  - hard-example review
  - live acceptance
  - production provenance
  - decision record

これにより、本ガイドを読み物として維持しつつ、次回案件ではtemplateだけをコピーして作業記録に使える。


---

## 最小実践ルール

長文を読む時間がない場合は、最低限これだけ守る。

- rawをそのままrandom splitしない
- 近接フレーム・同一readingをgroup化してからsplitする
- 曖昧なGTは無理に学習へ入れない
- Testは一度使ったらtuningへ戻さない
- 誤認識の改善用データは、学習に使うTrainと効果確認用のHard-Valに分ける
- trainingとruntimeの前処理を一致させる
- live acceptance（実運用環境での受入確認）まで確認して、初めてproduction扱いにする

---

*本文書は`docs/METER_DATASET_CURATION_GUIDE.md`として作成された（Issue #22 Checkpoint 2で作成、Checkpoint 3で
内容監査・締めを実施、Checkpoint 4でcommit・push・レビュー完了）。*
