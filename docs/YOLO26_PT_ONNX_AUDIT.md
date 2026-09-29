# YOLO26 PT/ONNX 追加監査（Issue #24 事後監査）

Issue #24「YOLO26n再学習・ONNX比較」の完了後、比較条件とPT/ONNX推論整合性を独立に監査した記録。
**本監査は再学習を行っていない。既存モデル・ONNX・データ・production設定は無変更。**
本ドキュメントは新規作成であり、既存の `docs/YOLO26_RETRAIN_ONNX_COMPARISON.md` と
`data_manifests/yolo26_*_provenance.md` は書き換えていない。旧記録への訂正指摘はすべて本文書内に記載する。

**最終決定（ユーザー承認済み）**: digital・drumともに現行YOLOv8n production（`meter_src002` /
`production_combined_v2_5z:best` conf=0.60、`meter_src004` / `candidate_roi_v3_5:best` conf=0.80）を維持する。
YOLO26nのPT/ONNX成果物（`yolo26_digital`, `yolo26_dram_crop`）は比較候補として保管し、本番へは切り替えない。
既存の全画面前処理（digital）・固定ROI/前処理（drum）もそのまま維持する。src003は引き続き運用対象外。
この決定を裏付ける詳細な検証結果は本文書の各章、および関連文書（末尾「関連文書」参照）に記録する。

---

## 監査結果の要約（最初に結論）

1. **Issue #24のPT/ONNX不一致9枚（digital4・drum5）は、原因が完全に特定できた。** 唯一の原因は
   Ultralyticsの`Model.predict()`が predict モード既定値として `rect=True` を内部的に設定していたことによる
   letterbox条件の不一致であり、PT/ONNXの数値精度やheadロジックの欠陥ではない。**この条件を統一すると、
   digital165枚・drum58枚の全件でPT/ONNXのreading完全一致（100%）を確認した。**
2. Issue #24の指標「Exact Match」は実際には本監査でいう`localized_exact`（位置対応ベース）であり、
   本監査が新たに定義した`reading_exact`（7個検出かつ文字列完全一致）とは異なる。両者は今回ほぼ同値だが、
   定義が異なる指標であることを明記する。
3. 統一条件で再集計した結果、**digitalはYOLO26n候補がbaselineよりわずかに改善**（主対象src002のみでは
   63/75→65/75）、**drumはYOLO26n候補がbaselineより明確に劣化**（55/58→51/58）という、Issue #24と
   **方向性は同じ**結論を維持した。ただし固定conf比較の一部数値はrect修正により変わっている（後述）。
4. **現行アプリ（`predict_worker.py`/`predict_video_worker.py`）は `rect` も `end2end` も指定していない。**
   これは（a）YOLO26候補を採用する場合、コード変更なしでは本監査・Issue #24が評価した
   one-to-many（end2end=False）方式を実運用で再現できないことを意味し、（b）副次的に、現行production
   （YOLOv8n）自体も実運用では`rect=True`（最小矩形letterbox）で推論されている可能性があり、
   過去の評価文書が前提とした正方形640×640letterboxとは条件が異なる可能性がある（本監査のスコープ外、
   別途確認が必要な残存リスクとして記録する）。
5. **ユーザー承認により、digital・drumともに現行YOLOv8n productionを維持する最終決定がなされた**
   （§9）。YOLO26nのPT/ONNXは比較候補として保管し、本番切替は行わない。

---

## 0. 参照資料の確認

- Issue #24本文・完了コメント（1件、closed）を確認済み。
- `docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`、`data_manifests/yolo26_digital_provenance.md`、
  `data_manifests/yolo26_dram_crop_provenance.md` を確認済み（内容は書き換えていない）。
- 元split manifest（`meter_digital_combined_split_v2.csv`, `meter_src004_split_v3.csv`,
  `meter_src004_hard_val_v1.csv`）を確認済み。
- Issue #24で実際に使用したローカル評価スクリプト（`step0_baseline.py`〜`step8_latency.py`、
  scratchpad配下、Git非管理）を全件確認済み。評価JSON（`eval_digital.json`, `eval_drum.json`,
  `onnx_verify_digital.json`, `onnx_verify_drum.json`）、`export_metadata.json`、`infer.py`、train.logも確認済み。
- 存在しないログ・情報（例: 旧YOLOv8n runのoptimizer実解決値ログ）は「未確認」のまま扱い、推測で補っていない。

### 比較対象モデルのhash確認（作業前後で再確認、変化なし）

| 対象 | SHA256 |
|---|---|
| digital現行 `candidate_v2_5z/best.pt` | `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61` |
| **同一性確認**: `meter_src002/production_combined_v2_5z/best.pt` | 上記と完全一致（確認済み） |
| **同一性確認**: `meter_src003/production_combined_v2_5z/best.pt` | 上記と完全一致（確認済み） |
| digital候補 `yolo26_digital/candidate_yolo26n_v1/best.pt` | `5901299432f098cb5dbcdb1bd3aa2f1cc22ab172cc507d23935c996abaa994b7` |
| digital候補ONNX | `c14c58f23592f3b4ad5f75300ae7a0ed4babb7f3f73234bdd947d6f4d461a346` |
| drum現行 `candidate_roi_v3_5/best.pt` | `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db` |
| drum候補 `yolo26_dram_crop/candidate_yolo26n_v1/best.pt` | `18bd80b6ac9b74e2c89a7d3df3b64727fc14edad0a82e59b7c4c5a6510a400e6` |
| drum候補ONNX | `e0fd59ffd11528a8cd5ee32ed08c5732df70ff7a872f3dfca401d5e73140df20` |

`meter_src002`/`meter_src003`/`meter_src004`の`selected_model.json`、上記全best.pt/ONNX、
`meter_digital_combined_split_v2.csv`/`meter_src004_split_v3.csv`/`meter_src004_hard_val_v1.csv`は
本監査の作業前後で内容・SHA256が完全一致することを確認済み（無変更）。

---

## 1. 比較条件・指標の事前固定

監査開始前に `protocol.json`（scratchpad配下）を作成し、対象モデル・環境・前処理・head・confidence grid・
指標定義・許容差を先に固定した。confidence gridはIssue #24と同一 `[0.25, 0.40, 0.50, 0.60, 0.70, 0.80]`
を使用し、追加の閾値探索は行っていない。

### 指標定義（Issue #24との異同を明記）

| 指標 | 定義 | Issue #24との関係 |
|---|---|---|
| **reading_exact**(新設) | 検出数が7個で、x中心昇順の予測文字列がGT7桁と完全一致 | Issue #24には存在しなかった指標 |
| **localized_exact** | GT7boxそれぞれにIoU≥0.3で1対1貪欲割当てし、missing=0/extra=0/wrong_class=0 | **Issue #24の「Exact Match」はこの定義だった**（本監査で確認・訂正） |
| 7-detect | 検出box数がちょうど7個 | Issue #24と同じ |
| **false_confirmed_reading**(新設) | 7個検出したがreading文字列がGTと不一致（「誤確定候補」、アプリの確定処理とは無関係） | Issue #24には無かった集計軸 |
| 6個以下／8個以上 | under-detect / over-detect画像数 | 新設（Issue #24は7-detect以外を明示区分していなかった） |
| character accuracy | 分母=画像数×7（digit単位）、分子=matchedかつclass一致の数 | Issue #24と同一定義（本監査で数値・分母分子を明記） |

GT/predictionの対応は同一pred boxを複数GTへ重複割当てしない1対1貪欲割当て（`audit_lib.py::match_and_score`）で実装。

---

## 2. 旧評価コードの監査（発見事項）

### 2.1 `rect` 条件 — **未確認のまま断定していたことが判明し、実際には食い違っていた**

Issue #24の評価コード（`step4_eval.py::evaluate_model`、`step6_onnx_verify.py`の一部）はいずれも
`model.predict(str(img_path), conf=conf, iou=0.7, imgsz=640, ...)` の形で呼び出しており、**`rect`を一度も
明示していなかった**。

学習時のargs.yamlは`rect: false`だが、これは**train モードの値**であり、**predict モードの既定値とは別**
であることが今回のコード追跡で判明した。具体的には `ultralytics/engine/model.py:528`:

```python
custom = {"conf": 0.25, "batch": 1, "save": is_cli, "mode": "predict", "rect": True, "embed": None}
```

**`Model.predict()`はpredictモードの`custom`既定値として`rect=True`をハードコードしている。**
`DEFAULT_CFG.rect`はFalseだが、`.predict()`呼び出し時にはこの`custom`でTrueに上書きされる。

`predictor.pre_transform()`のLetterBox `auto`判定:
```python
auto = same_shapes and self.args.rect and (self.model.format == "pt" or (dynamic and format != "imx"))
```
単一画像推論では`same_shapes`は常にTrueになるため、`rect=True`だと**PTモデル（`format=="pt"`）でのみ**
`auto=True`（最小矩形letterbox、stride=32単位で切り詰め）が有効になる。**ONNX（`format=="onnx"`、
`dynamic=False`）では常に`auto=False`（正方形640×640）** になる（format/dynamicガードにより`rect`の値に
関わらず）。

**実測結果**: `predictor.args.rect`を実際に読み取ったところ`True`であり、digital画像（640×360）をPTへ渡すと
letterbox後の高さが640ではなく**384**になっていた（`640-360=280`, `280 mod 32 = 24`, `360+24=384`）。
これはONNX Runtimeの`Got invalid dimensions...index 2 Got: 384 Expected: 640`というエラーで最初に発覧した
（監査スクリプト側でPT/ONNXへ同一tensorを渡そうとして発生。詳細は§3）。drum画像（640×131）では同様に
高さ160相当になる（`640-131=509`, `509 mod 32=29`, `131+29=160`）。

**結論**: Issue #24の**PT側**の全評価（baseline/candidate問わず）は、正方形640×640ではなく
最小矩形（digital: 640×384相当、drum: 640×160相当）で行われていた。**ONNX側は常に正方形640×640。**
すなわち **Issue #24のPT対ONNX比較は、そもそも入力shapeからして揃っていなかった。**
Issue #24のドキュメントに書かれた「rect=Falseを一貫して使用した」という記述は誤りであり、
実測で覆った（本監査の`protocol.json`にこの発見を明記し、以降の監査主経路では`rect=False`を明示している）。

### 2.2 end2end設定の実際の伝播 — コード追跡により確定（推測ではない）

`engine/predictor.py::setup_model()`:
```python
if hasattr(model, "end2end"):
    if self.args.end2end is not None:
        model.end2end = self.args.end2end
    ...
self.model = AutoBackend(model=model or self.args.model, ...)
```
ここでの`model`引数は **AutoBackend化される前の生`DetectionModel`**（`.pt`をロードした場合）である。
`nn/tasks.py`の`DetectionModel.end2end`は`@property`で、setterは`self.set_head_attr(end2end=value)`を
呼び出し、実際のDetectヘッドモジュールへ伝播する。**したがってPTでは`end2end=False`は確実に実headへ反映
される（コード追跡で確認、実行結果でも(1,14,8400)の一様な出力shapeを全画像で確認）。**
ONNXは文字列パスとして渡されるため`hasattr(model,"end2end")`がFalseとなりこの分岐自体が適用されない
（ONNXグラフのhead形式はexport時点で固定済みのため妥当）。

Issue #24のstep6では、この伝播を独自のAutoBackend直接呼び出しで再現しようとして最初失敗し
（`(1,300,6)`のend2end出力形状になっていた）、その場で気づいて`YOLO().predict(end2end=False)`経由に
修正していた（Issue #24内のセッションログで確認済み）。本監査ではこの伝播ルートをコードレベルで確定させた。

### 2.3 実測入力条件（本監査で実測、旧コードでは未計測だった項目）

| 項目 | 実測値 |
|---|---|
| RGB/BGR | cv2.imread→BGR uint8 → Predictor.preprocessでRGBへ変換（実装追跡・実測とも一致） |
| 正規化 | 0.0〜1.0（÷255）、FP32 |
| letterbox補間 | `cv2.INTER_LINEAR`。ただし**digital/drumともに画像幅が既に640のため、letterboxのratioが1.0となりcv2.resizeの補間自体が実行されない**（`get_params`のnew_unpad==元shapeでresizeがスキップされることをコードで確認）。padding(色114)のみが適用される。 |
| padding色/量 | 114固定。digital: 上下に(640-360)/2=140ずつ（正方形時）。drum: 上下に(640-131)/2=254.5→254/255。rect時は上記2.1参照 |
| grayscale/sharpen二重適用 | なし。val画像は既にROI/resize/grayscale/sharpen適用済み保存画像であることを確認し、追加適用していない |
| CPU/GPU・FP32/FP16 | 本監査はPT CPU FP32・ONNX Runtime CPUExecutionProvider FP32で統一（`half`/`fp16`指定なし） |
| 推論オブジェクト再利用による設定残留 | AuditBundle内で1回だけpredictor構築後、同一predictor/backendをVal全件で使い回す設計のため、**画像間での設定残留は無い**（rect/end2endは構築時に1度だけ固定）。ただし**confごとの繰り返しNMSでは重大な自作バグが発生**（§2.4参照）。 |

### 2.4 監査スクリプト自身の不具合（自己発見・修正）

本監査の実装過程で2件の実装不備を自己発見し、監査用コピー側で修正した（元のIssue #24スクリプト・
元ONNX・同梱`infer.py`は一切変更していない）。

1. **rect未指定バグ**（§2.1）: `AuditBundle`初期化時の1回限りの`predict()`呼び出しで`rect=False`を
   明示するよう修正。
2. **NMSのin-place破壊バグ**: `ultralytics.utils.nms.non_max_suppression`は入力tensorを破壊的に変更する
   ため、同一confグリッドを繰り返し評価する際に生forward出力`raw`をそのまま渡すと、2回目以降のconf
   （0.40以上）で全画像が`missing=7`（全GT未検出）という明らかに異常な結果になった。原因を特定し、
   `raw.clone()`してから`non_max_suppression`へ渡すよう修正した。修正前後の結果は本文書の付録用JSON
   （`analyze.py`実行ログ）に両方残している。

いずれも「監査用コピー側で最小修正し、再検証した」の指示に従い、元コード・成果物は無変更。

---

## 3. PT対ONNXのVal全件比較（統一条件、rect=False）

digital165枚・drum58枚の**全件**で、画像ごとに一度だけ構築したFP32テンソルをPT（`predictor.model`経由の
生forward）とONNX Runtime（`onnxruntime.InferenceSession`直接、CPUExecutionProvider明示）の両方へ渡した。
`onnxruntime-gpu`等の自動インストールは`YOLO_AUTOINSTALL=False`で禁止し、共有環境を更新していない。

### 3.1 生出力（NMS前）のtensor比較 — **全件**（Issue #24は8サンプルのみ、本監査は全件）

| project | 画像数 | shape一致 | NaN/inf | max abs diff（範囲） | mean abs diff（範囲） | allclose(rtol=1e-3,atol=1e-4) |
|---|---|---|---|---|---|---|
| digital | 165 | 全件一致 (1,14,8400) | 無し | 0.00128〜0.01898 | 0.0000126〜0.0000162 | **全件True** |
| drum | 58 | 全件一致 (1,14,8400) | 無し | 0.00192〜0.00513 | 0.0000110〜0.0000124 | **全件True** |

box座標部分・class score部分を分離して集計した結果も許容差内（class score側の誤差は最大でも約1.5×10⁻⁵、
box座標側はletterbox後ピクセル単位で最大0.019程度）。digitalの一部画像でbox座標の最大差がIssue #24の
8サンプル調査時（最大0.0043）より大きい0.019程度のケースが全件調査で見つかったが、依然として
`allclose(rtol=1e-3,atol=1e-4)`の範囲内であり、座標誤差の大きさをそのままconfidenceの差と説明していない
（別軸の指標として扱う）。

### 3.2 後処理後（NMS後）のreading一致率 — 全conf・全件

| project | conf | 一致率 |
|---|---|---|
| digital | 0.25〜0.80（6水準） | **165/165 (100%) 全水準** |
| drum | 0.25〜0.80（6水準） | **58/58 (100%) 全水準** |

**「8サンプルの全件」ではなく「Val全件」で検証し、全conf水準で完全一致を確認した。**

**重要な区別**: ここでの「PT/ONNX reading一致率100%」は、あくまで**PTとONNXが互いに同じ値を出力した割合**
であり、**その値がGT（正解）と一致しているか（認識精度）とは別の指標である**。実際、§5の`reading_exact`
（GTとの一致）はconfに応じて84〜94%程度であり、100%ではない。またこの「一致」は生tensorのbit-for-bit一致
ではなく、§3.1に示した許容差（rtol=1e-3, atol=1e-4）内での近似一致に基づく後処理結果の一致である
（生ロジット自体には最大0.019程度の差が残っている）。
これはIssue #24が報告した「97.6%」「91.4%」という一致率を**上回る結果**であり、§4で述べる通り
差分の原因（letterbox不一致）を修正した結果である。

---

## 4. 旧不一致9枚の個別診断

Issue #24で報告された不一致（digital4枚・drum5枚、いずれもconf=0.50/0.40の推奨conf時点）を
全件特定し、統一条件（rect=False）で再評価した。

| project | stem | GT | 旧PT | 旧ONNX | 統一後PT | 統一後ONNX | 統一後一致 |
|---|---|---|---|---|---|---|---|
| digital | src_002_20260901_134800 | 0215189 | 021518 | 0215189 | 0215189 | 0215189 | ✅ |
| digital | src_002_20260901_140400 | 0215189 | 02151898 | 0215189 | 0215189 | 0215189 | ✅ |
| digital | src_002_20260901_143600 | 0215189 | 0215188 | 02151898 | 02151898 | 02151898 | ✅ |
| digital | src_002_20260901_150000 | 0215189 | 0215188 | 02151898 | 02151898 | 02151898 | ✅ |
| drum | src_004_20260818_130400 | 3709842 | 3709842 | 370984 | 370984 | 370984 | ✅ |
| drum | src_004_20260901_142800 | 3716760 | 37167590 | 3716759 | 3716759 | 3716759 | ✅ |
| drum | src_004_20260907_081600 | 3718400 | 371840 | 3718408 | 3718408 | 3718408 | ✅ |
| drum | src_004_20260907_113200 | 3718566 | 3718566 | 37185663 | 37185663 | 37185663 | ✅ |
| drum | src_004_20260907_113600 | 3718570 | 3718576 | 37185760 | 37185760 | 37185760 | ✅ |

**原因区分**: 全9枚とも「**入力テンソル不一致**」（letterbox shape不一致、§2.1のrect=True/False混在）が
原因であり、PT側が統一条件下で一貫してONNX側の値（=正方形640×640で推論した値）に収束することを確認した。
NMS実装差・decode/座標変換差・score/IoU閾値境界・同点score選択差はいずれも原因ではなかった
（統一後は完全一致するため、これらの要因は寄与していない）。**全件「解明済み」。未解明事項なし。**

なお、いずれのケースもGTと完全一致する読み値は得られておらず（7桁未満または8桁超の誤検出）、
これは**PT/ONNX整合性の問題ではなくモデル自体の検出精度の限界**（confidence境界付近での検出漏れ/過検出）
であることを付記する。

---

## 5. YOLOv8n対YOLO26n 性能再集計（統一条件、rect=False、両モデルPT）

digital/drumとも baseline(YOLOv8n)・candidate(YOLO26n) いずれもPTモデルへ統一条件（rect=False,
end2end=False相当、同一NMS関数）を適用して再集計した。

### 5.1 Digital — 3区分

**A. 現行運用conf=0.60固定**

| | reading_exact | localized_exact | char acc |
|---|---|---|---|
| baseline | 152/165 (92.1%) | 152/165 | 0.9879 |
| candidate | 149/165 (90.3%) | 149/165 | 0.9844 |

**B. 各モデルのVal選定conf（本採用判断の主対象=src002由来75枚で選定）**

| | 選定conf | src002のみ(75) reading_exact | char acc(src002) |
|---|---|---|---|
| baseline | 0.50 | 63/75 (84.0%) | 0.9752 |
| candidate | 0.50 | **65/75 (86.7%)** | 0.9771 |

→ **src002のみで見ると候補がわずかに改善**（+2画像）。改善した8画像・悪化した6画像の内訳は次項。

参考: src003由来90枚（運用対象外、参考値）はbaseline/candidateともに選定conf次第で**100%（90/90）**を
達成しており、区別に有用な情報を持たない（両モデルとも既に飽和）。

**C. Issue #24 combined165枚ベース（歴史的参考値、Bと選定対象が異なるため混同しない）**

| | 選定conf | reading_exact(combined165) |
|---|---|---|
| baseline | 0.60 | 152/165 (92.1%) |
| candidate | 0.50 | 155/165 (93.9%) |

Cの数値はIssue #24の報告値（151/165, 153/165）と近いが完全には一致しない
（rect修正・NMS関数の統一・reading_exact/localized_exact定義分離による差、後述§7）。

### 5.2 Drum — src004単一区分

**A. 現行運用conf=0.80固定**

| | reading_exact | localized_exact | char acc |
|---|---|---|---|
| baseline | **48/58 (82.8%)** | 48/58 | 0.9704 |
| candidate | 44/58 (75.9%) | 44/58 | 0.9606 |

（本表は`final_numbers.py`で保存済みJSONから再集計し確定した値。ドラフト段階で
baseline=44/58と誤記していた箇所を訂正済み。固定conf=0.80では**baselineがcandidateを明確に上回る**
——Issue #24が報告した「固定conf=0.80ではcandidateがわずかに上回る(46→47)」という記述も、
本監査の統一条件では再現しない。）

**B. 各モデルのVal選定conf（src004の58枚で選定）**

| | 選定conf | reading_exact | char acc |
|---|---|---|---|
| baseline | 0.50 | **55/58 (94.8%)** | 0.9926 |
| candidate | 0.50 | 51/58 (87.9%) | 0.9852 |

→ **選定conf同士ではcandidateが明確に劣化**（-4画像）。Issue #24の結論（56/58→52/58）と方向性は同じ。

---

## 6. 正読・誤確定候補・under/over-detect・改善/悪化対応表

### 6.1 Digital（src002-only 75枚、baseline@conf0.5 vs candidate@conf0.5）

| | 件数 |
|---|---|
| 両方正読 | 57 |
| baselineのみ正読（candidate悪化） | 6 |
| candidateのみ正読（candidate改善） | 8 |
| 両方誤読/検出不足 | 4 |

**改善した8画像**（baseline誤読→candidate正読）: いずれも`0214xxx`という正しいGTを、baselineが
`0215xxx`（4桁目を4→5と誤認）と読み違えていたケース（例: `src_002_20260818_110000`
GT=0214943, baseline=0215943, candidate=0214943）。8画像中6画像がこのパターン、残り2画像は
`0215210`という8桁目手前の余分検出をbaselineがしていたケース。

**悪化した6画像**（baseline正読→candidate誤読）: いずれもGT=`0215189`または`0215210`という、
末尾桁が遷移中とみられる画像で、candidateが6桁または8桁の検出になっていた（検出数不安定、
class誤りではない）。6画像中4画像がGT=0215189の同一近傍reading、2画像がGT=0215210の同一近傍reading
であり、**特定の2つのreading_group近辺に悪化が集中している**（既存manifestのreading_group_idで確認）。
「1〜2枚改善した」レベルの単発事象ではなく、pattern的な集中が見られるため、統計的優位性の主張は避けるが、
**偶然のばらつきとも言い切れない**、特定reading帯での挙動差として記録する。

### 6.2 Drum（58枚、baseline@conf0.5 vs candidate@conf0.5）

| | 件数 |
|---|---|
| 両方正読 | 51 |
| baselineのみ正読（candidate悪化） | 4 |
| candidateのみ正読（candidate改善） | 0 |
| 両方誤読/検出不足 | 3 |

**改善画像は0件。悪化4画像**はいずれも検出数不安定（6桁/8桁化）で、reading_group
`src_004_C006`, `C088`, `C144`, `C145`の4つの異なるgroupに分散しており、特定reading帯への集中は
見られない（digitalほど明確なパターンではない）。

平均値（char accuracy等）の増減だけで改善/悪化を断定せず、上記の画像単位対応表を根拠として提示する。

---

## 7. 現行アプリでの再現可能性

### 7.1 コード確認結果（read-only）

- `backend/workers/predict_worker.py`: `model.predict(**kwargs)`の`kwargs`に`rect`も`end2end`も
  含まれていない（`backend/app/schemas/prediction.py`の`PredictJobCreate`にも該当フィールドなし）。
- `backend/workers/predict_video_worker.py`: 同様に`predict_kwargs`に`rect`/`end2end`が無い。
- したがって**現行アプリでYOLO26候補モデルを`selected_model.json`経由で採用しても、`end2end`は
  Ultralyticsの既定値（YOLO26の場合True＝NMS-free one2one分岐）のまま推論される**。本監査・Issue #24が
  比較したone-to-many（end2end=False）方式とは**異なる出力形式・異なる精度特性になる可能性が高い**。
  **YOLO26採用にはアプリ側コード変更（`end2end=False`をpredict/video workerへ追加する等）が前提となる。**
- 副次的な観察（本監査のスコープ外、残存リスクとして記録のみ）: `rect`も同様に指定されていないため、
  **現行production（YOLOv8n）自体も実運用では`rect=True`（最小矩形letterbox）で推論されている可能性がある**。
  これは過去の評価文書（Val58/Hard-Val27等）が前提とした正方形640×640letterboxとは条件が異なりうることを
  意味するが、この点の実運用への影響を定量評価することは本監査の対象外とする。

### 7.2 ONNX同梱`infer.py`との差

`infer.py`（Issue #24の成果物）は依存を減らすためletterboxをPillowで独自再実装している。本監査の
主経路はUltralytics実クラス（`ultralytics.data.augment.LetterBox`、cv2ベース）を直接使用した。
digital/drumの画像は幅が既に640でありresize自体が発生しない（§2.3）ため、この2つの実装の違いは
**現在のデータセットに関しては数値的影響が無い**ことを確認した。ただし将来、幅が640以外の画像を
扱う場合はこの差が顕在化しうる（cv2のINTER_LINEARとPillowのBILINEARは補間アルゴリズムが異なる）。

### 7.3 ONNX未検証の明記

現行YOLOv8n baselineには対応するONNXが存在しない（`weights/`配下に`best.pt`/`last.pt`のみ）。
したがって**本監査・Issue #24の世代間比較（§5）はPT対PTであり、旧YOLOv8nのONNX納品性能は未検証**。
追加のexportは本監査で行っていない（Safety Gate遵守）。

### 7.4 計測条件の区別

推論時間はPT CPU FP32とONNX Runtime CPUExecutionProvider FP32を同一device/provider条件で比較した
（§3、いずれもCPU）。前処理・forward・後処理を区別しており、GPU PT時間とCPU ONNX時間を世代間の
速度差として直接比較していない。今回のVal結果をライブ受入完了とは呼ばない。新規ライブ撮影・
カメラ設定変更は行っていない。

---

## 8. 保護対象hash・git status・変更ファイル一覧

- §0の全hash・selected_model.json内容は、監査フェーズ・本文書最終化フェーズを通じて完全一致（無変更）。
- 読み取り専用の監査フェーズ中は`git status --short`がクリーン（追跡ファイルへの変更なし）で、
  その間は git stage/commit/push を一切行っていなかった。**その後、ユーザーの最終決定を受けて
  本文書を含む指定4文書のみをcommit/pushした（コミットSHA・push結果は本文書冒頭または
  `docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`側の最終報告を参照）。**
- 新規作成物:
  - `docs/YOLO26_PT_ONNX_AUDIT.md`（本ファイル、指定4文書の1つとしてcommit対象）
  - `scratchpad/issue24_audit/`配下（Git非管理、監査ワークファイル）: `protocol.json`,
    `a0_baseline_hashes.py`, `a0_baseline_report.json`, `audit_lib.py`, `audit_main.py`,
    `audit_baseline.py`, `analyze.py`, `analyze2.py`, `final_numbers.py`,
    `audit_yolo26_digital.json`, `audit_yolo26_dram_crop.json`, `audit_baseline_digital.json`,
    `audit_baseline_drum.json`, 各種実行ログ
  - 既存の`projects/**`・weight・ONNX・既存export一式・既存アプリコードへの変更は一切なし
  - Test/Hard-Valは使用していない（既存manifestのIDを除外確認のためだけに参照）

---

## 9. Digital / Drum 最終決定（ユーザー承認済み）

### Digital — 現行維持

- **決定: 現行YOLOv8n（`meter_src002` / `production_combined_v2_5z:best`、運用conf=0.60、既存の
  全画面前処理）を維持する。YOLO26n候補への切替は行わない。**
- 検証結果の要点: src002由来75枚（本採用判断の主対象）でreading_exactが63→65（+2画像、改善8/悪化6）と
  candidateがわずかに優位だったが、これはconfを0.60→0.50へ変更した場合に限られ、**現行運用conf=0.60を
  維持する前提では152→149（combined165枚）と候補側が悪化する**。また悪化した6画像が`0215189`/`0215210`
  近辺のreadingに集中しているなど、残存リスクが解消されていない。
- 決定の根拠: 上記の通り、conf変更なしでは改善せず、変更する場合も未検証のリスクが残るため、
  ユーザーはconfやアプリコードを変更してまでYOLO26n候補へ切り替える理由がないと判断し、現行維持を選択した。
- YOLO26digital成果物（`projects/yolo26_digital/`一式）は削除・移動せず、比較候補として保管する。

### Drum — 現行維持

- **決定: 現行YOLOv8n（`meter_src004` / `candidate_roi_v3_5:best`、運用conf=0.80、既存の固定ROI・前処理）を
  維持する。YOLO26n候補への切替は行わない。**
- 検証結果の要点: src004の58枚（選定conf同士、いずれも0.50）でreading_exactが55→51と明確に悪化しており、
  改善画像0件・悪化画像4件という非対称な結果。**現行運用conf=0.80に固定した場合も48/58→44/58と
  candidateが明確に劣る**（§5.2A、ドラフト時の誤記「44→44同値」を訂正済み）。
- 決定の根拠: 選定conf同士・固定conf同士のいずれで比較してもcandidateがbaselineを上回る場面がなく、
  採用を正当化する材料がないため、ユーザーは現行維持を選択した。
- YOLO26drum成果物（`projects/yolo26_dram_crop/`一式）は削除・移動せず、比較候補として保管する。

### 共通事項

- src003は引き続き運用対象外（本監査・決定のいずれにも影響しない）。
- `meter_src002`/`meter_src003`/`meter_src004`の`selected_model.json`・production best.ptは
  本監査・本決定を通じて一切変更していない（§0で確認済み）。

---

## 訂正記録: Issue #24既存文書に対する訂正内容

`docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`および両provenance文書（`data_manifests/yolo26_digital_provenance.md`,
`data_manifests/yolo26_dram_crop_provenance.md`）に対し、以下の訂正を実施した
（既存文書側の該当箇所に本文書へのリンク付きで訂正注記を追加。学習条件・モデルhash・ONNX仕様など
訂正の必要がない記録は変更していない）。

1. §6.1「本プロジェクトは元々rect=False（既定letterbox）を学習・評価の両方で使用しており」という記述は
   **不正確だった**。学習は`rect=False`だが、`.predict()`呼び出し時はUltralyticsの既定でrect=Trueとなり、
   PT側は実際には最小矩形letterboxで評価されていた（ONNX側は正方形640×640のまま）。
2. §6.3/§6.4の「Exact Match」という表記は、本監査でいう`localized_exact`を指しており、
   `reading_exact`（7個検出かつ文字列完全一致）とは別概念であることを明記した。
3. §8.3の「差分stemはいずれもconf境界付近での1box分の増減」という説明は、真の原因（letterbox不一致）
   ではなく現象面の記述に留まっていた。本監査で根本原因を特定した（§4）。
4. §6.5の固定conf比較値（digital: baseline151/candidate148、drum: baseline46/candidate47）は、
   rect修正後の値（digital: baseline152/candidate149、drum: baseline48/candidate44）と異なる。
   今後はこの監査文書の値を正とする。

---

## 関連文書

- [`docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`](YOLO26_RETRAIN_ONNX_COMPARISON.md) — Issue #24の元比較記録（訂正注記あり）
- [`../data_manifests/yolo26_digital_provenance.md`](../data_manifests/yolo26_digital_provenance.md) — digital側provenance（訂正注記あり）
- [`../data_manifests/yolo26_dram_crop_provenance.md`](../data_manifests/yolo26_dram_crop_provenance.md) — drum側provenance（訂正注記あり）
