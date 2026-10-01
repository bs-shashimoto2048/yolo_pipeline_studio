# C++ Deployment Contract（Issue #47）

本ドキュメントは、現production Digital/Drumモデルを**C++ deployment用baselineとして固定**し、
C++実装（次Issue #48以降）がPython productionと同一挙動を再現するために必要な契約を定義する。

**本Issueの時点ではC++コードは一切書いていない。** 目的は「C++側へ渡すONNX artifactが現在の
Python production inferenceと同一挙動であることを正式に固定する」ことのみ。

参照: `data_manifests/production_deployment_baseline_v1.json`（hash/export条件の正式記録）、
`backend/workers/inference_contract.py`（`production-inference-contract-v1`の定義元）。

## Model artifact

| | Digital | Drum |
|---|---|---|
| model_id | `production_combined_v2_5z:best` | `candidate_roi_v4_hardneg:best` |
| project | `meter_src002` | `meter_src004` |
| PT weight SHA256 | `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61` | `cadd1d7df52b94004331be2d3c79c7dbc306c93802b3f5c3d455f2121061f595` |
| conf | 0.60 | 0.80 |
| iou | 0.70 | 0.70 |
| num_classes | 10（digit 0〜9） | 10（digit 0〜9） |
| ONNX opset | 12 | 12 |
| ONNX input shape | (1,3,384,640) | (1,3,160,640) |

PT/ONNX実体はGit管理外（`projects/`はgitignore対象）。weight/ONNXの実ファイルは
`data_manifests/production_deployment_baseline_v1.json`が指すパスにread-onlyで配置される。

Digitalのdigit position 3 / class=4は収集データ不足という既知の制約があるが、production自体は
独立acceptance（Issue #36/#37/#39/#40）で高精度であり、本baselineの採用とは独立の問題である。
rare-classデータが揃って再学習された場合の更新手順は「Model交換可能性」節を参照。

## Input preprocessing（C++側が再現する、カメラ→YOLO入力テンソルまでの全工程）

fixedなprocessing order。実コード: `backend/app/services/preprocess_service.py`
（`processing_order()` / `_process_one`相当のロジック）。

### Digital（`roi_enabled=false`）

```
raw image（カメラそのまま）
  → grayscale（L変換 → RGB 3ch化。R=G=Bの疑似グレースケール）
  → sharpen（strength=1.0, PIL ImageFilter.SHARPEN相当の強調）
  → resize（mode=width, size=640。アスペクト比維持、高さは比例計算）
  → YOLO letterbox（下記「Tensor input」参照）
```

### Drum（`roi_enabled=true`）

```
raw 1920x1080
  → ROI crop: x=[835, 1354), y=[374, 480)  (519x106)
  → resize（mode=width, size=640 → 約640x131）
  → grayscale（L変換 → RGB 3ch化）
  → sharpen（strength=1.0）
  → YOLO letterbox（下記「Tensor input」参照）
```

**順序はproject設定（`roi_enabled`）で分岐する**（`preprocess_service.py`参照）。
ROI有効時は「crop→resize→grayscale→sharpen」、ROI無効時は「grayscale→sharpen→resize」で、
**resizeの位置が逆**になる点に注意（既存project・既存呼び出しとの後方互換のため、後者が
既存の処理順）。

## Color / channel

- カメラ/raw画像: BGR（OpenCV慣習）またはRGB（デコーダ依存）。Python実装はPillowで
  `Image.open(...).convert("RGB")`から開始する（`ImageOps.exif_transpose`でEXIF回転補正込み）。
- grayscale適用後も**常に3channel**（`img.convert("L").convert("RGB")`、R=G=Bの3ch画像）。
  1channel画像がYOLOへ渡ることはない。
- 保存形式: JPEG quality=88、RGB 3channel。
- YOLO入力直前の正規化: `0〜255 uint8` → `0.0〜1.0 float32`（255で除算するのみ、平均/標準偏差の
  centering・scalingは行わない）。
- dtype: `float32`。
- layout: `NCHW`（batch, channel, height, width）。batch=1固定。
- channel順序: YOLO入力は**RGB**（Ultralyticsの既定、OpenCVのBGRから変換が必要。
  `img[:, :, ::-1]`相当）。

## Tensor input（ONNX, 正式契約）

| | Digital | Drum |
|---|---|---|
| input name | `images` | `images` |
| shape | `[1, 3, 384, 640]` | `[1, 3, 160, 640]` |
| dtype | float32 | float32 |

**rectと正方形letterboxの関係（重要）**: production推論は`rect=True`で実行されており、
Ultralyticsが入力画像のaspect比に応じて「長辺=640、短辺は最も近いstride(32)の倍数へpad」した
**非正方形**の固定shapeを使う（Digitalは640x360入力→384x640、Drumは640x131入力→160x640。
本Issueで`AutoBackend.forward`をフックして実測し確定した値。Issue #25の"approximately"記載を
確定値へ更新した）。

**letterboxはONNXグラフの内部には含まれない。** C++側（またはこのIssueのPython parity検証では
Ultralytics自身の`LetterBox`クラス）が、ONNX Runtime呼び出し**前**に以下を行う:

1. 入力画像（preprocess後、resize済みの最終画像）を受け取る。
2. `new_shape=(384,640)`（Digital）または`(160,640)`（Drum）、`auto=False`、`stride=32`、
   `center=True`、`padding_value=114`でletterbox。
   - `auto=False`で固定shapeへ（productionのrect=True auto-computedと同一shapeになるよう、
     本Issueで事前に確定済みのshapeを静的に使う）。
   - `center=True`: 上下左右均等にpadding。
   - `padding_value=114`: Ultralytics既定のグレー padding（RGB各ch 114）。
3. BGR→RGB変換、HWC→CHW変換、0〜1正規化、batch次元追加。

## ONNX output（正式契約）

| | Digital | Drum |
|---|---|---|
| output name | `output0` | `output0` |
| shape | `[1, 14, 5040]` | `[1, 14, 2100]` |
| dtype | float32 |
| layout | `[batch, 4+num_classes, num_anchors]`（channel-first、Ultralytics export既定） |

14 = 4（bbox: cx, cy, w, h、letterbox後のpixel単位）+ 10（class 0〜9のlogit/確率相当）。
5040 / 2100 はそれぞれのinput shapeに対するYOLO 3スケール（stride 8/16/32）の
anchor-free grid cell合計（例: Digital 384x640 → (48×80)+(24×40)+(12×20)=5040）。

**NMSはONNXグラフに含まれていない**（`nms_included: false`、export時に`nms=True`を指定して
いないため）。**C++側で外部実装が必要**（次項）。

## NMS / postprocess（C++が再現する）

Python側の参照実装: `ultralytics.utils.nms.non_max_suppression`
（本Issueの`scripts/onnx_parity_check.py`がこの関数をそのまま呼んで検証に使っている）。

固定パラメータ（`production-inference-contract-v1`、`backend/workers/inference_contract.py`
の`PINNED_ARGS`と同一）:

```
conf_thres   = project固有（Digital=0.60, Drum=0.80）
iou_thres    = 0.70
agnostic     = False
max_det      = 300
classes      = None（全クラス対象）
multi_label  = False
rotated      = False
end2end      = False（YOLO26で問題になったend2end方式は現production YOLOv8nでは使わない）
```

NMS出力（letterbox座標系の xyxy, conf, cls）を、`ultralytics.utils.ops.scale_boxes`相当の
ロジックで元画像座標系へ逆変換する（letterboxのscale/pad量から算出。`scale_boxes`は
`ratio_pad`省略時、shapeの比較から自動推定する。letterbox適用時の実際のscale/padを
C++側で保持しておき、直接渡す実装でもよい）。

## Reading construction

```
detections を bbox中心x座標（元画像座標系、昇順）でソートし、
各detectionのclass_idを文字列として左から右へ連結する。
```

複数桁メーターの読み取り値はこの「左から右」の空間順序のみに依存し、detection順序（モデル出力順）
には依存しない。`backend/tests/smoke_production_integration.py`の`_reading_from_detections`と
同一規約。

## Confidence thresholds

| project | conf | iou |
|---|---|---|
| Digital | 0.60 | 0.70 |
| Drum | 0.80 | 0.70 |

project切替時はconf/iouも含めてdeployment configごと切り替える（C++コードへハードコードしない、
「Model交換可能性」参照）。

## Model hashes

`data_manifests/production_deployment_baseline_v1.json`を正式source of truthとする
（PT SHA256・ONNX SHA256・export条件を一元管理）。

## Allowed tolerances（PT vs ONNX parity合格基準）

| 項目 | 基準 |
|---|---|
| detection count | 100%一致 |
| class sequence（reading） | 100%一致 |
| confidence | 絶対差 <= 1e-3 |
| bbox（元画像座標、各座標の絶対差） | <= 1px |

検証結果（Issue #47、CPUExecutionProvider、各project 30 samples、Test/Hard-Val不使用）:
**Digital 30/30 PASS、Drum 30/30 PASS**（全項目で基準内、confidence最大差は共に1e-3未満、
bbox最大差はDigital 0.108px・Drum 0.010pxで1px未満）。詳細はIssue #47の最終報告を参照。

CUDAExecutionProviderでの検証は本Issueでは未実施（この環境に`onnxruntime-gpu`が
インストールされていないため）。CPUExecutionProviderでのparity成立が本Issueの最低要件であり、
満たしている。

## C++側責務（Python/app側ではなくC++実装が再現するもの）

- ROI crop（Drumのみ）
- resize（width基準、アスペクト比維持）
- grayscale（3ch化）
- sharpen
- YOLO letterbox（非正方形固定shape、`auto=False`相当）
- normalize（0〜1 float32、NCHW）
- ONNX Runtime呼び出し
- output decode（`[1,14,N]` → per-anchor box+class scores）
- NMS（`non_max_suppression`と同一パラメータ・同一ロジック）
- 元画像座標系への逆変換（`scale_boxes`相当）
- left-to-rightのdetection ordering
- reading construction（class_id文字列連結）
- confidence threshold適用（NMS内のconf_thresと同一値、project別）

## Model交換可能性（将来設計）

C++コードへmodel-specific値（conf/iou/ROI座標/resize_size/imgsz/class数等）を直接埋め込まない。
将来は「deployment config（本baseline manifestと同形式のJSON） + ONNX」の組で差し替え可能な
構成を前提とする。

Digitalモデルが将来rare-class追加データで再学習された場合の更新手順:

1. 新weightで再学習・既存のVal/Hard-Val/非Test acceptanceゲートを通過（既存workflow）。
2. 新weightから同一条件（opset=12、imgsz=project固有の静的rect shape、simplify=true）で
   ONNX再export。
3. `scripts/onnx_parity_check.py`でPT vs ONNX parityを再検証（本Issueと同じ合格基準）。
4. `data_manifests/production_deployment_baseline_v1.json`のhash/export条件を更新。
5. C++側は**原則コード変更不要**（deployment config + ONNXの差し替えのみ）。

## 次Issue予告（今回は実装しない）

Issue #48でC++ ONNX Runtime推論PoC + benchmark（CMake、ONNX Runtime C++、OpenCV前処理、
Digital/Drum pipeline、PT/Python parity、CPU/CUDA latency、memory、FPS、warm-up、release build）
を行う。本Issueで固定した契約がそのPoCの仕様書となる。

## Issue #48実装状況（追記）

本契約はC++（`cpp/`、CMake + ONNX Runtime C++ + OpenCV C++）で実装され、
Digital/Drumとも30/30サンプルでC++/ONNX ↔ Python/ONNXの完全一致（conf差<=1e-6、
bbox差<=0.001px）を確認した。詳細なbuild手順・依存バージョン・benchmark結果・
既知の制約は `docs/CPP_INFERENCE_BENCHMARK.md` を参照。
