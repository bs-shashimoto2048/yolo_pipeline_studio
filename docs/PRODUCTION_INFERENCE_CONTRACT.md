# Production Inference Contract

`meter_src002`（digital）・`meter_src004`（drum）のproduction推論が満たすべき条件を記録する
仕様書。**source of truthの整理は以下のとおり**（同じ情報を独立管理しない）:

- **Code**（`backend/workers/predict_worker.py` / `predict_video_worker.py`）: 実runtime contract
- **Test**（`backend/tests/smoke_inference_contract.py`）: 回帰検知
- **本ファイル**: 人間向け仕様（contractの内容・strict/tolerance・skip/fail規則を1箇所に集約）
- **provenance**（`data_manifests/production_model_provenance_v1.md` /
  `meter_src004_roi_v3_provenance.md`）: モデル採用履歴・判断根拠。本ファイルへ相互リンクする

---

## Contract version

**`production-inference-contract-v1`**（Issue #27で導入）

### Version bumpルール

以下のいずれかに該当する変更を行う場合のみversionを上げる。単なるcomment修正・
リファクタリング（挙動不変）ではbumpしない。

- resolved inference args（下記「Runtime args」）の変更
- production preprocessing（ROI・resize・grayscale・sharpen等）の変更
- production model architecture・採用modelそのものの変更
- YOLO input tensor shapeが変わる変更
- expected reading contract（golden fixtureの期待値）が変わる変更
- その他、意図的なruntime behaviorの変更

---

## Model identity

| | digital | drum |
|---|---|---|
| project | `meter_src002` | `meter_src004` |
| model | `production_combined_v2_5z:best` | `candidate_roi_v3_5:best` |
| conf | 0.60 | 0.80 |
| weight SHA256 | `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61` | `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db` |

weight本体は`.gitignore`により Git管理外（`projects/`配下）。テスト環境に存在しない場合は
Layer Bをskipする（下記「Skip / Fail規則」参照）。

## Preprocessing contract

### Digital
project preprocessing output: **640×360**
YOLO input tensor（letterbox後）: **(1,3,384,640)**

### Drum
project preprocessing:
```
raw 1920×1080
  → ROI x=[835,1354), y=[374,480)
  → crop 519×106
  → resize width640 → 640×131
  → grayscale
  → sharpen(strength=1.0)
```
YOLO input tensor（letterbox後）: **(1,3,160,640)**

project preprocessing output sizeとYOLO input tensor sizeは別概念であり、両方を独立して確認する
（Issue #25/#26で確立した区別）。

## Runtime args（`rect`はIssue #25、それ以外はIssue #26で明示固定）

```
rect=True
max_det=300
agnostic_nms=False
augment=False
batch=1
quantize=None
```
上記に加え、`conf`/`iou`/`imgsz`は元々明示済み。

### 意図的に固定していないparameter（Decision Record）

```
classes: default unrestricted (None)、no explicit pin（noiseになるだけで保護価値が薄い）
device: intentionally dynamic（"auto"時はUltralyticsの自動選択に委ねる、環境依存のため固定しない）
end2end: model-dependent, not pinned for YOLOv8 production（現行YOLOv8nでは無害だが
  model依存のためYOLO26等採用時に個別再評価が必要）
half: 非推奨引数のため使わず、代わりにquantize=Noneを固定（内容は同じ意図）
verbose: prediction結果に無関係（ログ詳細度のみ）のため対象外
```

詳細な実測根拠・時系列（#24→#25→#26）は
[`data_manifests/production_model_provenance_v1.md`](../data_manifests/production_model_provenance_v1.md)
を参照。

---

## Test構造（`backend/tests/smoke_inference_contract.py`）

### Layer A — 常時実行（production weight不要）
- image worker（`predict_worker.py`）のkwargsにruntime args全項目が明示されていることをソースレベルで確認
- video worker（`predict_video_worker.py`）の**初期生成・live settings refresh再生成の両方**に
  同一のruntime argsが明示されていることを確認（片方だけ漏れる回帰をIssue #25/#26で経験済み）
- image / video間のparity表を出力し、全項目が一致することを確認
- 本ドキュメントの存在とcontract versionの整合を確認

### Layer B — production weight・fixture画像がローカルに存在する場合のみ実行
- weight SHA256をprovenance記載値と照合
- 実際にproduction weightでpredictし、golden fixture値と比較

### Skip / Fail規則

| 状態 | 結果 |
|---|---|
| weightがローカルに存在しない | **SKIP**（"production model artifact not available"） |
| weightが存在し、hashが一致 | 実行 |
| weightが存在し、hashが不一致 | **FAIL** |
| fixture画像がローカルに存在しない（weightは存在） | **SKIP**（fixture画像もGit管理外のため、
  存在しないこと自体はcontract違反の証拠ではない） |

Ultralyticsのversion自体が変わっただけではfailさせない設計とする（推奨方針。現状のtestは
version値そのものをstrict比較対象にしていない）。**version番号ではなく挙動（prediction contract）
を守る**。ただし検証済みversionはgolden fixtureの`generation_environment`に記録する。

---

## Strict / Tolerance

### Strict（完全一致要求）
- model SHA256
- resolved args（rect/max_det/agnostic_nms/augment/batch/quantize/conf/iou/imgsz）
- YOLO input tensor shape
- detection count
- class sequence
- x-sorted reading

### Tolerance（許容差あり）
- confidence: `abs diff <= 1e-3`
- bbox座標（letterbox後pixel座標）: `abs diff <= 1.0px`

同一fixture・同一modelを5回反復predictし、run-to-run variationが0（bit-for-bit同一）である
ことを実測確認した上で上記許容差を設定した（batch=1・FP32・TTA無効という現行contractの下では、
本環境で観測された変動は皆無だったため、環境間の僅かなFP誤差を吸収する程度の保守的な値とした）。

---

## Fixture

Test/Hard-Valは使用しない。Issue #25/#26で既にfreeze・Test/Hard-Val非重複確認済みのstem一覧
から、次の条件で選定した（結果を見てからの選定ではない）:
- production confでの検出が安定して7/7
- 閾値（digital conf=0.60、drum conf=0.80）に対し十分な余裕がある最小confidence（実測で
  digital最小0.965前後、drum最小0.90前後）
- 桁遷移中でない

| project | fixture stem | reading (golden) |
|---|---|---|
| digital | `src_002_20260903_142400` | 0215234 |
| digital | `src_002_20260906_032000` | 0215257 |
| digital | `src_002_20260903_162800` | 0215239 |
| drum | `src_004_20260906_002400` | 3718333 |
| drum | `src_004_20260904_134800` | 3718227 |
| drum | `src_004_20260907_150000` | 3718720 |

fixture画像本体（*.jpg）はGit管理外の`projects/yolo26_digital(dram_crop)/datasets/
matched_source_v1/images/train/`配下から実行時に解決する（Issue #24で作成された比較候補
projectのdataset copy、ユーザー決定によりGit非管理のまま保管継続）。golden JSON
（`backend/tests/fixtures/production_inference_contract_golden_v1.json`）にはstem名・数値の
golden値のみを保存し、画像バイト列・生産設備の機密情報は一切含まない。

**残存リスク**: `projects/yolo26_digital`・`projects/yolo26_dram_crop`が将来削除・移動された
場合、Layer Bのfixture画像解決先が失われる。その場合はfixtureの再選定・golden再生成が必要
（本ファイルの手順に従い、`generate_golden.py`相当のロジックで再生成する）。

---

## 関連文書

- [`data_manifests/production_model_provenance_v1.md`](../data_manifests/production_model_provenance_v1.md) — モデル採用履歴・#24〜#26の判断根拠
- [`data_manifests/meter_src004_roi_v3_provenance.md`](../data_manifests/meter_src004_roi_v3_provenance.md) — drum固有の採用履歴
- [`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md) — rect条件発見の経緯（Issue #24事後監査）
