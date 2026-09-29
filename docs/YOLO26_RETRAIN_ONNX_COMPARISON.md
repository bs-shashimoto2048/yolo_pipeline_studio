# YOLO26n再学習・ONNXエクスポート比較（Issue #24）

現行production採用の2モデル（digital: `production_combined_v2_5z`, drum: `candidate_roi_v3_5`、いずれもYOLOv8n）と
同一のデータ分割・画像・前処理・学習予算を維持したまま、YOLO26nで新規学習した候補モデルを作成し、
Val限定で比較、ONNXエクスポート・ONNX Runtime実推論検証まで行った記録。

**本Issueは比較候補の作成・評価・ONNX納品が目的であり、本番モデルの自動切替は行っていない。**
既存productionの`selected_model.json`・model artifact・conf設定はいずれも無変更（本文末尾で再確認済み）。

> **【事後訂正】** 本文書作成後に実施した追加監査（[`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md)）により、
> §6.1のletterbox条件（rect）に関する記述に誤りがあったこと、§6.3/§6.4「Exact Match」の指標定義、
> §6.5の固定conf比較値の一部が判明・訂正された。該当箇所に個別の訂正注記を付す。
> **最終決定（ユーザー承認済み）: digital・drumともに現行YOLOv8n productionを維持し、YOLO26n候補への
> 切替は行わない。** 詳細は監査文書§9を参照。

---

## 1. 対象と新規project

| | digital | drum |
|---|---|---|
| 新規project名 | `yolo26_digital` | `yolo26_dram_crop` |
| 現行production参照 | `meter_src002` / `meter_src003` / `production_combined_v2_5z:best` | `meter_src004` / `candidate_roi_v3_5:best` |
| 新規run名 | `candidate_yolo26n_v1` | `candidate_yolo26n_v1` |
| 新規dataset名 | `matched_source_v1` | `matched_source_v1` |
| source dataset | `projects/meter_digital_combined/datasets/meter_digital_combined_split_v2/` | `projects/meter_src004/datasets/meter_src004_roi_v3/` |
| source manifest | `data_manifests/meter_digital_combined_split_v2.csv` | `data_manifests/meter_src004_split_v3.csv` |

両projectとも本Issueで`project_service.create_project()`（アプリの実サービス、単なるmkdirではない）で作成し、
class定義は既存project（`meter_src002`等）と同一の0〜9（10クラス）を`class_service.save_classes()`で設定した。

---

## 2. 環境（実測値、Issue本文の参考値との対応）

| 項目 | 実測値 | Issue本文の参考値 |
|---|---|---|
| Python | 3.10.11 | — |
| torch | 2.11.0+cu128 | 2.11.0+cu128（一致） |
| CUDA / GPU | CUDA利用可能、NVIDIA GeForce RTX 4070 Laptop GPU (8188MiB) | RTX 4070 Laptop GPU（一致） |
| Ultralytics | 8.4.83 | 8.4.83（一致） |
| OpenCV | 4.13.0 | — |
| NumPy | 2.2.6 | — |
| Pillow | 12.2.0 | — |
| onnx | 1.22.0 | — |
| onnxruntime | 1.23.2（providers: AzureExecutionProvider, CPUExecutionProvider。CUDA provider未導入） | — |

既存環境（`.venv`）がYOLO26n学習・ONNX出力に既に対応していたため、専用仮想環境の新規作成は不要だった。
新規pip installは行っていない（後述§7で発生した`onnxruntime-gpu`自動インストール試行は失敗して自動的にCPUへ
フォールバックしただけであり、明示的なpip操作は行っていない）。

YOLO26n事前学習済みweight:
- 取得元: `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt`（Ultralytics公式が
  `YOLO("yolo26n.pt")`実行時に自動ダウンロード）
- SHA256: `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef`
- サイズ: 5,544,453 bytes
- 両project（`projects/yolo26_digital/yolo26n.pt`, `projects/yolo26_dram_crop/yolo26n.pt`）で独立にダウンロードし、
  上記と完全に同一のSHA256であることを確認済み（＝2モデルとも同一の公式pretrained weightから独立にfine-tuneした）。

---

## 3. 既存production weightの同一性確認（作業開始時・終了時の双方で再確認、いずれも一致）

| weight | SHA256 |
|---|---|
| digital production best.pt (`meter_digital_combined/runs/train/candidate_v2_5z/weights/best.pt`) | `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61` |
| drum production best.pt (`meter_src004/runs/train/candidate_roi_v3_5/weights/best.pt`) | `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db` |

いずれもIssue本文記載の値と一致。本Issue作業前後で無変更（読み取り専用）。
`meter_src002`/`meter_src003`/`meter_src004`の`selected_model.json`もIssue開始前後で内容完全一致（無変更）。

---

## 4. データセット複製・QA

既存の`dataset_service.create_dataset()`はプロジェクト自身のraw/annotationからのrandom re-splitを行う実装であり、
**既に確定済みのsplitをそのまま複製する**という本Issueの要件（再split・再annotation・二重前処理の禁止）には
適合しないため使用しなかった。代わりに、専用スクリプトでsource datasetのtrain/val画像・labelをバイト単位で
直接コピーする方式を採った（`dataset_service`のrandom shuffle splitを一切経由しない）。

### 4.1 件数

| | digital train | digital val | drum train | drum val |
|---|---|---|---|---|
| コピー件数 | 769 | 165 | 339 | 58 |
| 内訳 | src002 349 + src003 420 | src002 75 + src003 90 | src004 339 | src004 58 |
| 画像サイズ | 640×360 | 640×360 | 640×131 | 640×131 |

### 4.2 QA結果（全件、read-only検証スクリプトで確認）

- 全コピー元/先の画像・labelバイト列SHA256一致: digital 934/934件、drum 397/397件（不一致0）
- missing/orphan/duplicate stem: 0件（digital/drum とも）
- 全label: 7bbox・class 0〜9範囲内・座標0〜1範囲内であることを確認（違反0件）
- 保護対象（既存Test/Hard-Val）のstem漏洩: 0件（digital 156件、drum 68件の保護対象stemと突合、漏洩なし）
- source dataset側（`meter_digital_combined_split_v2`, `meter_src004_roi_v3`）は読み取りのみで一切変更なし

### 4.3 data.yaml

新規`data.yaml`は`train`/`val`のみを設定し、`test`キーは設定していない（source manifestのTest/Hard-Valは
画像・ラベルともコピーしていない）。

---

## 5. 学習条件（同条件の根拠と差分）

### 5.1 固定した主条件（既存run `args.yaml`実測値との一致確認）

| 項目 | 値 | 既存run(YOLOv8n)との一致 |
|---|---|---|
| model | `yolo26n.pt`（意図的な差分。モデル世代交代が本Issueの目的） | 既存: `yolov8n.pt` |
| epochs | 50 | 一致 |
| imgsz | 640 | 一致 |
| batch | 8 | 一致 |
| device | `0`（明示） | 一致 |
| workers | 2 | 一致 |
| patience | 20 | 一致 |
| seed | 42 | 一致 |
| deterministic | True（既定） | 一致 |
| rect | False（既定） | 一致 |
| augmentation（14項目、後述） | 既存run実測値をそのまま明示指定 | 一致 |
| optimizer | `auto`指定を維持（既存も`auto`） | 指定そのものは一致。解決値は§5.2参照 |

**augmentation 14項目の明示指定**（既存2runのargs.yamlが完全に一致していたため、その実測値をそのまま使用。
アプリのbuiltin "standard" preset は`degrees=5.0`で本来の既定値`0.0`と食い違うため、preset解決には頼らず
14キー全てを`augmentation_params`として明示上書きした）:

```
degrees=0.0, translate=0.1, scale=0.5, shear=0.0, perspective=0.0, flipud=0.0, fliplr=0.5,
mosaic=1.0, mixup=0.0, copy_paste=0.0, hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, close_mosaic=10
```

これ以外のハイパーパラメータ（lr0/lrf/momentum/weight_decay/warmup_*/box/cls/dfl/auto_augment/erasing/bgr/nbs等）は
学習ワーカー（`train_worker.py`）が一切上書きしないため、Ultralytics既定値がそのまま適用される。
既存2runのargs.yamlに記録された値もこれら既定値と一致しており、既存runとの差分はない。

### 5.2 同一化できなかった点（モデル世代固有の差、事実として記録）

- **YOLO26のアーキテクチャはend2end（NMS-free one2one）ヘッドと一致（one2many）ヘッドを併用する設計**
  （`reg_max=1`、YOLOv8の`reg_max=16`のDFLとは異なる）。学習自体は既定のend2end構成のまま行い、
  Val比較・ONNXエクスポートの時点で`end2end=False`を明示指定し、YOLOv8と比較しやすいone-to-many + 外部NMS
  方式の出力を使用した（詳細は§6）。
- **optimizer実解決値**: 両runとも`optimizer=auto`から`AdamW(lr=0.000714, momentum=0.9)`が自動選択された
  （train.logに記録、114 params weight(no-decay)/126 weight(decay=0.0005)/126 bias(decay=0.0)のparameter group）。
  既存YOLOv8n runのoptimizer実解決値はログが保存されておらず不明（args.yamlには設定値`lr0=0.01`
  `momentum=0.937`のみ記録されており、実際にauto解決された値ではない）。この点は既存run側の記録限界であり、
  今回の値との直接比較はできない。

### 5.3 学習run結果

| | digital | drum |
|---|---|---|
| run path | `projects/yolo26_digital/runs/train/candidate_yolo26n_v1/` | `projects/yolo26_dram_crop/runs/train/candidate_yolo26n_v1/` |
| 完走epoch | 50/50（early stopping未発動） | 50/50（early stopping未発動） |
| 所要時間 | 0.688時間（約41分） | 約22.5分 |
| OOM/NaN/inf | なし | なし |
| best.pt SHA256 | `5901299432f098cb5dbcdb1bd3aa2f1cc22ab172cc507d23935c996abaa994b7` | `18bd80b6ac9b74e2c89a7d3df3b64727fc14edad0a82e59b7c4c5a6510a400e6` |
| 最終Val (全体) | P=0.958 R=0.906 mAP50=0.972 mAP50-95=0.869 | P=0.911 R=0.892 mAP50=0.955 mAP50-95=0.872 |
| 推論速度(GPU, val時) | 1.3ms preprocess / 5.2ms inference / 0.8ms postprocess | 1.0ms preprocess / 13.0ms inference / 1.4ms postprocess |

学習は`training_service.start_job()`（アプリの実サービス、`backend/app/routers/training.py`のAPIと同一コードパス）を
Python経由で呼び出して実行した。学習ジョブ/モデル一覧への表示を確認済み（§8）。

---

## 6. Val限定の比較評価

### 6.1 方式

- 主比較・主ONNXは**one-to-many + 外部NMS**方式を使用（`model.predict(..., end2end=False)`で明示指定）。
  YOLO26既定のend2end（NMS-free one2one, top-k=300出力）ではなく、YOLOv8と同じ生ヘッド出力
  `(1, 14, 8400)`で比較・エクスポートしている。
- 比較は新規Valコピーのみで実施。baselineの既存best.ptは読み取り専用で同一入力に適用。
- confidence grid: `[0.25, 0.40, 0.50, 0.60, 0.70, 0.80]`。iou=0.7固定。imgsz=640。
- letterbox条件: 本プロジェクトは元々`rect=False`（既定letterbox、正方形640×640へアスペクト維持パディング）を
  学習・評価の両方で使用しており、ONNX static入力640×640とこの条件は既に一致するため、追加のrect比較は
  行っていない（rect=Trueは元runで一度も使われていない）。
  > **【事後訂正】この記述は不正確だった。** 学習時（`rect: false`）とpredict時は別であり、
  > Ultralyticsの`Model.predict()`はpredictモードの既定値として`rect=True`を内部的に設定する
  > （`DEFAULT_CFG.rect=False`とは別。`engine/model.py:528`）。本文書のPT側評価（本セクション以降の
  > baseline/candidate数値）は実際には`rect=True`（最小矩形letterbox、digital640×384相当・drum640×160相当）
  > で行われており、ONNX側（常に正方形640×640）と入力shapeから一致していなかった。詳細・訂正後の値は
  > [`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md)§2.1・§5を参照。

### 6.2 指標定義（本Issue固有に定義、透明性のため明記）

- **GT reading**: labelファイルの7bboxをx中心昇順ソートしclass idを連結した7桁文字列。
- **予測box**: 各confでの検出box群をx中心昇順ソート。
- **位置対応**: GTの7boxそれぞれについて、IoU≥0.3のpredicted boxのうちIoU最大のものを貪欲に割当て。
  対応なし→missing、対応ありでclass不一致→wrong_class、対応先の無いpred box→extra。
- **7-detect**: 検出box数がちょうど7個の画像数。
- **Exact Match**: missing=0 かつ extra=0 かつ wrong_class=0（7桁とも正しく1個ずつ検出）の画像数。
  > **【事後訂正】** 追加監査により、この指標は監査文書でいう`localized_exact`（位置対応ベース）に
  > 相当し、監査文書が新たに定義した`reading_exact`（7個検出かつx昇順文字列がGTと完全一致）とは
  > 別の指標であることが判明した。両者は本Issueの評価では近い値になったが、概念上区別する
  > （[`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md)§1参照）。
- **character accuracy**: 全画像・全7位置に対する正解数の割合。
- **edit distance**: 予測文字列とGT7桁文字列のLevenshtein距離（補助値）。
- **2→8 / 8→2**: wrong_classのうちGT class=2をclass=8と誤った件数、およびその逆。
- **best conf選定規則**: 7桁Exact Match最大 → character accuracy最大 → 7-detect最大 → 低conf。

### 6.3 Digital結果（Val165、内訳src002=75/src003=90）

| conf | モデル | Exact Match | 7-detect | char acc | missing | extra | wrong | 2→8 | 8→2 |
|---|---|---|---|---|---|---|---|---|---|
| 0.25 | baseline(v8n) | 136/165 | 138/165 | 0.9784 | 0 | 31 | 25 | 0 | 0 |
| 0.40 | baseline | 146/165 | 149/165 | 0.9844 | 0 | 16 | 18 | 0 | 0 |
| **0.50** | baseline | 150/165 | 158/165 | 0.9870 | 0 | 7 | 15 | 0 | 0 |
| **0.60** | **baseline(採用conf, best)** | **151/165** | **160/165** | **0.9870** | 3 | 2 | 12 | 0 | 0 |
| 0.70 | baseline | 151/165 | 158/165 | 0.9861 | 7 | 0 | 9 | 0 | 0 |
| 0.80 | baseline | 140/165 | 141/165 | 0.9758 | 25 | 0 | 3 | 0 | 0 |
| 0.25 | candidate(YOLO26n) | 141/165 | 143/165 | 0.9870 | 0 | 23 | 15 | 0 | 0 |
| 0.40 | candidate | 152/165 | 154/165 | 0.9913 | 1 | 10 | 9 | 0 | 0 |
| **0.50** | **candidate(best)** | **153/165** | **157/165** | **0.9887** | 5 | 3 | 8 | 0 | 0 |
| 0.60 | candidate(現行production conf) | 148/165 | 152/165 | 0.9844 | 12 | 1 | 6 | 0 | 0 |
| 0.70 | candidate | 141/165 | 142/165 | 0.9775 | 23 | 0 | 3 | 0 | 0 |
| 0.80 | candidate | 131/165 | 132/165 | 0.9671 | 35 | 0 | 3 | 0 | 0 |

- **各モデルのbest conf同士の比較**: baseline 151/165 (91.5%) → candidate 153/165 (92.7%)。**YOLO26nがわずかに改善**。
- **現行production固定conf=0.60での比較**: baseline 151/165 (91.5%) → candidate 148/165 (89.7%)。
  **固定conf=0.60ではYOLO26nがやや劣化**（YOLO26nの最適confは0.50側にあるため）。
- 2→8/8→2混同はいずれのconf・モデルでも0件。

### 6.4 Drum結果（Val58）

| conf | モデル | Exact Match | 7-detect | char acc | missing | extra | wrong | 2→8 | 8→2 |
|---|---|---|---|---|---|---|---|---|---|
| 0.25 | baseline(v8n) | 52/58 | 53/58 | 0.9877 | 0 | 6 | 5 | 0 | 0 |
| 0.40 | baseline | 52/58 | 54/58 | 0.9877 | 0 | 4 | 5 | 0 | 0 |
| **0.50** | **baseline(best)** | **56/58** | **56/58** | **0.9926** | 2 | 0 | 1 | 0 | 0 |
| 0.60 | baseline | 54/58 | 54/58 | 0.9877 | 4 | 0 | 1 | 0 | 0 |
| 0.70 | baseline | 51/58 | 51/58 | 0.9803 | 7 | 0 | 1 | 0 | 0 |
| **0.80** | **baseline(現行production conf)** | 46/58 | 46/58 | 0.9655 | 13 | 0 | 1 | 0 | 0 |
| 0.25 | candidate(YOLO26n) | 48/58 | 49/58 | 0.9852 | 0 | 10 | 6 | 0 | 0 |
| **0.40** | **candidate(best)** | **52/58** | **56/58** | **0.9852** | 1 | 1 | 5 | 0 | 0 |
| 0.50 | candidate | 51/58 | 55/58 | 0.9828 | 2 | 1 | 5 | 0 | 0 |
| 0.60 | candidate | 51/58 | 55/58 | 0.9803 | 3 | 0 | 5 | 0 | 0 |
| 0.70 | candidate | 49/58 | 52/58 | 0.9704 | 7 | 0 | 5 | 0 | 0 |
| **0.80** | **candidate(現行production conf)** | 47/58 | 49/58 | 0.9655 | 11 | 0 | 3 | 0 | 0 |

- **各モデルのbest conf同士の比較**: baseline 56/58 (96.6%) → candidate 52/58 (89.7%)。**YOLO26nが劣化**。
  candidateはwrong_classが0.40〜0.60全体で5件と、baselineの1件より一貫して多い（2→8/8→2ではない別のclass混同、
  本Issueでは原因の深掘りは範囲外とし、劣化の事実のみ報告する）。
- **現行production固定conf=0.80での比較**: baseline 46/58 (79.3%) → candidate 47/58 (81.0%)。
  固定conf=0.80では**candidateがわずかに上回る**（両者ともbest confから離れた高conf側であるため、
  本来の実力差を反映した数値ではない点に注意）。
- 2→8/8→2混同はいずれのconf・モデルでも0件。

### 6.5 総括

- **digital**: 両モデルのbest conf同士ではYOLO26nがわずかに改善（91.5%→92.7%）。ただし現行運用conf(0.60)を
  そのまま使うと悪化する（91.5%→89.7%）。YOLO26n採用にはconfの見直しが前提になる。
- **drum**: YOLO26nはbaselineより明確に劣化（96.6%→89.7%、best conf同士）。wrong_classが増加している。
- 精度が劣化していても学習・ONNX出力・検証はいずれも完了させている（後述）。**本番採用は行っていない。**

> **【事後訂正】** 上記の固定conf比較値（digital: baseline151/candidate148、drum: baseline46/candidate47）は、
> §6.1の訂正注記のとおりPT側が`rect=True`で評価されていた影響を受けている。統一条件（rect=False）で
> 再集計した値は digital: baseline152/candidate149（combined165枚）、drum: baseline48/candidate44（58枚）
> であり、特にdrumはbaselineとcandidateの差がより明確になった。src002由来75枚単独ではbaseline63→candidate65、
> src004の58枚（選定conf同士）ではbaseline55→candidate51。**方向性（digital微改善・drum劣化）は変わらない。**
> 詳細は[`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md)§5・§6を参照。
>
> **最終決定（ユーザー承認済み）: digital・drumともに現行YOLOv8n productionを維持する。**

---

## 7. ONNXエクスポート

### 7.1 仕様

| 項目 | 値 |
|---|---|
| format | onnx |
| dtype | FP32（`half=False`） |
| batch | 1（static） |
| input shape | `[1, 3, 640, 640]` NCHW（static、`dynamic=False`） |
| opset | 17（環境のonnx 1.22.0で問題なく成功。フォールバック警告なし） |
| simplify | False（初回無効） |
| end2end | **False**（one-to-many生ヘッド出力を強制。YOLO26既定のNMS-free one2one分岐を無効化） |
| nms（グラフ内蔵NMS） | False（既定のまま。NMSはグラフ外） |

`backend/app/services/onnx_export_service.py`（既存アプリのONNXエクスポートservice）は`opset`/`simplify`/`dynamic`のみ
制御可能で`end2end`を指定できないため、既定のend2end=True（NMS-free one2one分岐）のまま出力されてしまい、
本Issueの要件（one-to-many + 外部NMS方式での主ONNX）を満たせない。そのため既存service/routerは使用せず、
`model.export()`を直接呼び出す専用スクリプトで実施した（アプリのcode変更は行っていない）。

### 7.2 実出力（推測ではなく実グラフから確認）

| | 値 |
|---|---|
| 入力 | `images`: `[1, 3, 640, 640]` float32 |
| 出力 | `output0`: `[1, 14, 8400]` float32 |
| 出力の意味 | `[batch, 4(cx,cy,w,h) + 10(class scores, sigmoid適用後), 8400 anchors(P3+P4+P5: 80×80+40×40+20×20)]` |
| box座標系 | letterbox後640×640ピクセル基準（cx,cy,w,h）。逆変換は`(x-pad)/ratio`（`infer.py`に実装） |

### 7.3 納品先・ハッシュ

| project | ONNXパス | SHA256 | サイズ |
|---|---|---|---|
| yolo26_digital | `projects/yolo26_digital/exports/candidate_yolo26n_v1/yolo26_digital.onnx` | `c14c58f23592f3b4ad5f75300ae7a0ed4babb7f3f73234bdd947d6f4d461a346` | 9,754,603 bytes |
| yolo26_dram_crop | `projects/yolo26_dram_crop/exports/candidate_yolo26n_v1/yolo26_dram_crop.onnx` | `e0fd59ffd11528a8cd5ee32ed08c5732df70ff7a872f3dfca401d5e73140df20` | 9,754,605 bytes |

各exportフォルダには`preprocess_profile.json`（ROI/resize/grayscale/sharpen + letterbox仕様、drumはraw座標系ROIの
再適用禁止を明記）、`classes.json`（0〜9対応）、`export_metadata.json`（上記入出力仕様・座標復元式）、
`README.md`、実行可能な`infer.py`（外部NMS実装込みのONNX Runtime CPU推論スクリプト）を同梱した。
学習run自体の`best.pt`/`last.pt`は変更・削除していない。

---

## 8. ONNX Runtime動作・PT整合検証

### 8.1 checker / Runtime load

| project | onnx.checker.check_model | ONNX Runtime (CPUExecutionProvider) load+推論 |
|---|---|---|
| yolo26_digital | 成功 | 成功（dummy入力`[1,3,640,640]`でエラーなし、出力shape `(1,14,8400)`確認） |
| yolo26_dram_crop | 成功 | 成功（同上） |

CUDA Execution Providerは本環境に`onnxruntime`（CPU版）のみ導入されており未検証。実行時に
Ultralytics側が`onnxruntime-gpu`への自動更新を試行したが、DLLファイルの権限エラーで失敗し、
CPUExecutionProviderへ自動フォールバックした（既存環境への意図しない変更は生じていない。
`.venv`のonnxruntimeパッケージ構成は本Issue開始前と同一であることを確認）。

### 8.2 tensor-level比較（PT vs ONNX、NMS前の生ヘッド出力、各project 8サンプル）

PT側は`YOLO(best.pt).predict(..., end2end=False)`実行後の`predictor.model`（正しくend2end=False伝播済みの
AutoBackend）から生forward、ONNX側は同様に`YOLO(onnx).predictor.model`から生forwardを取得し、同一の
letterbox前処理済みtensorを入力して比較した。

| project | shape一致 | NaN/inf | max abs diff | mean abs diff | allclose(rtol=1e-3, atol=1e-4) |
|---|---|---|---|---|---|
| yolo26_digital (8サンプル) | 全件一致 (1,14,8400) | なし | 0.0014〜0.0043 | 約1.3〜1.5×10⁻⁵ | 全件True |
| yolo26_dram_crop (8サンプル) | 全件一致 (1,14,8400) | なし | 0.0022〜0.0046 | 約1.1〜1.2×10⁻⁵ | 全件True |

小さな数値差（opset変換・グラフ融合由来）はあるが、事前に固定した許容差（rtol=1e-3, atol=1e-4）内に収まっている。

### 8.3 Val全件でのPT対ONNX一致率（推奨confで比較、post-process後のreading一致）

| project | conf | PT Exact Match | ONNX Exact Match | reading一致 | 差分stem数 |
|---|---|---|---|---|---|
| yolo26_digital | 0.50 | 153/165 | 155/165 | 161/165 (97.6%) | 4 |
| yolo26_dram_crop | 0.40 | 52/58 | 50/58 | 53/58 (91.4%) | 5 |

差分stemはいずれも「7個検出のはずが8個検出（または6個検出）」というconf境界付近での1box分の増減であり
（例: digital `src_002_20260901_134800`はPT `021518`(6桁)対ONNX `0215189`(7桁,GT一致)）、上記tensor-level差分
（0.001〜0.005程度の生ロジット差）がconf閾値をまたぐborderline caseで生じたものと説明できる。NaN/inf・大きな
数値乖離・説明不能なreading差はない。**7桁とも完全に一致しない差分stemが少数存在する**ことを隠さず報告する
（「完全一致」とは言わない）。

> **【事後訂正】** 上記は現象面の記述に留まっていた。追加監査でこの9件（digital4・drum5）の**根本原因を
> 完全に特定した**: conf境界の数値差ではなく、PT側とONNX（static export）側で**入力テンソルの形状自体が
> 一致していなかったこと**（§6.1訂正参照）が原因だった。統一条件下では、digital165枚・drum58枚の
> **全件・全6conf水準でPT/ONNXのreadingが完全一致（100%）** することを確認した。ただしこれは
> 「PTとONNXが互いに一致した割合」であり、GTに対する認識精度（reading_exact、84〜94%程度）とは別の指標
> である点に注意。詳細は[`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md)§3・§4を参照。

### 8.4 FPS/latency（参考値、ONNX Runtime CPU、`onnxruntime.InferenceSession.run()`のみの時間）

| project | provider | batch | imgsz | warmup | N | 平均レイテンシ |
|---|---|---|---|---|---|---|
| yolo26_digital | CPUExecutionProvider | 1 | 640 | 3 | 30 | 16.03 ms/image |
| yolo26_dram_crop | CPUExecutionProvider | 1 | 640 | 3 | 30 | 15.61 ms/image |

前処理（letterbox等）・後処理（NMS等）は含まない、forward呼び出しのみの時間。このVal試験結果を
実運用のlive受入とは呼ばない（live受入は別途実施が必要、本Issueの範囲外）。

---

## 9. アプリでの可視性

`training_service.list_jobs()` / `model_registry_service.list_models()` を実行し、以下を確認した
（既存の外部run検出機構を経由せず、`job.json`を伴う正規の学習ジョブとしてネイティブに表示されている）。

```
yolo26_digital jobs: [('candidate_yolo26n_v1', 'completed')]
yolo26_digital models: ['candidate_yolo26n_v1:best', 'candidate_yolo26n_v1:last']
yolo26_dram_crop jobs: [('candidate_yolo26n_v1', 'completed')]
yolo26_dram_crop models: ['candidate_yolo26n_v1:best', 'candidate_yolo26n_v1:last']
```

いずれのprojectも`selected_model.json`は作成していない（本番選定・自動切替は行っていない）。

---

## 10. 保護対象の最終確認

| 対象 | 結果 |
|---|---|
| `meter_src002`/`meter_src003`/`meter_src004`の`selected_model.json` | 作業前後で内容完全一致（無変更） |
| digital/drum production best.pt のSHA256 | 作業前後で完全一致（無変更） |
| 既存v2/v3 split manifest（CSV） | 無変更（読み取りのみ） |
| Test/Hard-Val画像・ラベル | 新規datasetへコピーしていない（漏洩0件、§4.2で確認済み） |
| 既存raw/annotations/processed/runs | 無変更（読み取りのみ） |

---

## 11. Git管理境界

本Issueでリポジトリに新規追加したのは以下3ファイルのみ:

- `data_manifests/yolo26_digital_provenance.md`
- `data_manifests/yolo26_dram_crop_provenance.md`
- `docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`（本ファイル）

`projects/yolo26_digital/`・`projects/yolo26_dram_crop/`配下（新規project・dataset・weight・ONNX・ログ等）は
既存方針どおりGit管理外（`.gitignore`の`projects/`規則）であり、force addしていない。

> **【事後追記】** 事後監査により4ファイル目 `docs/YOLO26_PT_ONNX_AUDIT.md` が追加された
> （別commitで管理、詳細はそちらのcommit記録を参照）。`projects/yolo26_digital/`・
> `projects/yolo26_dram_crop/`配下の成果物は削除・移動されていない（保管継続）。

---

## 12. 結論・今後の判断材料

- **技術的完了条件はdigital/drumとも達成**: 学習完了・ONNX出力・checker/Runtime検証・PT整合検証いずれも成功。
- **精度**: digitalはbest conf同士でYOLO26nがわずかに改善、drumはYOLO26nが明確に劣化。
  現行運用confを固定した場合の結果は上記と傾向が異なる箇所がある（§6.5）。
- 本番採用は行っていない。採用を検討する場合、少なくとも drumのwrong_class増加要因の追加調査と、
  digital/drumともにVal以外（Hard-Val・live acceptance）での再評価が必要（いずれも本Issueの範囲外、
  Test/Hard-Valは本Issueで一切使用していない）。

> **【最終決定・事後追記】** 上記の判断材料に加え、事後監査（[`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md)）
> でletterbox条件の不一致を修正した上で再評価した結果も踏まえ、**ユーザーはdigital・drumともに
> 現行YOLOv8n productionを維持することを決定した**。YOLO26nのPT/ONNX成果物は比較候補として保管し、
> 本番へは切り替えない。

## 関連文書

- [`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md) — 事後監査・訂正・最終決定の記録
- [`../data_manifests/yolo26_digital_provenance.md`](../data_manifests/yolo26_digital_provenance.md)
- [`../data_manifests/yolo26_dram_crop_provenance.md`](../data_manifests/yolo26_dram_crop_provenance.md)
