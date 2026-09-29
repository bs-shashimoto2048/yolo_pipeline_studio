# yolo26_digital Provenance（Issue #24 — YOLO26n比較候補）

Issue #24「Retrain yolo26_digital and yolo26_dram_crop under matched conditions and verify ONNX exports」の
digital側成果物の記録。**production採用ではなく比較候補**。既存production（`meter_src002`/`meter_src003`,
`production_combined_v2_5z:best`, conf=0.60）は本Issueで無変更。

詳細な評価条件・結果・ONNX検証は [`docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`](../docs/YOLO26_RETRAIN_ONNX_COMPARISON.md) を参照。
本ファイルは digital 側の再現・復元に必要な事実の記録に特化する。

## 1. Source（現行productionと同一のデータ条件）

- source project: `meter_digital_combined`
- source dataset: `projects/meter_digital_combined/datasets/meter_digital_combined_split_v2/`
- source manifest: `data_manifests/meter_digital_combined_split_v2.csv`
- source run（比較baseline）: `projects/meter_digital_combined/runs/train/candidate_v2_5z/`
  - best.pt SHA256: `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61`
  - モデル: yolov8n（既存production）
- Train 769（src002 349 + src003 420）/ Val 165（src002 75 + src003 90）
- **重要**: digitalの元モデルはsrc002単独ではなくsrc002+src003のcombinedモデル。src003が運用対象外に
  なったことを理由に、本Issueの学習データからsrc003由来データを除外していない（同一条件維持のため）。

## 2. 新規project

- project名: `yolo26_digital`（`project_service.create_project()`で作成、task=detect、class 0〜9）
- dataset名: `matched_source_v1`（source datasetのtrain/valをバイト単位で直接コピー。二重前処理・
  再split・再annotationなし。画像サイズ640×360を維持）
- run名: `candidate_yolo26n_v1`

## 3. データコピーの検証

- コピー元/先のSHA256一致: 934/934件（train769+val165、画像+label）
- missing/orphan/duplicate stem: 0件
- 7bbox・class0-9範囲・座標範囲: 全件正常
- 保護対象（source manifestのTest等156 stem）の漏洩: 0件
- source dataset自体への書き込み: なし（読み取り専用で複製）

## 4. 学習

- base weight: `yolo26n.pt`
  - 取得元: `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt`
  - SHA256: `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef`
- 学習条件: epochs=50, imgsz=640, batch=8, device=0, workers=2, patience=20, seed=42
- augmentation（既存run実測値を明示指定、アプリのbuiltin "standard" presetは使用せず）:
  `degrees=0.0, translate=0.1, scale=0.5, shear=0.0, perspective=0.0, flipud=0.0, fliplr=0.5, mosaic=1.0, mixup=0.0, copy_paste=0.0, hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, close_mosaic=10`
- optimizer: `auto`指定 → 実解決値 `AdamW(lr=0.000714, momentum=0.9)`
- 完走: 50/50 epoch（early stopping未発動）、所要時間 約41分、OOM/NaN/inf なし
- **best.pt SHA256: `5901299432f098cb5dbcdb1bd3aa2f1cc22ab172cc507d23935c996abaa994b7`**
- 最終Val: P=0.958 R=0.906 mAP50=0.972 mAP50-95=0.869

## 5. Val比較（vs baseline `candidate_v2_5z`, Val165限定, Test/Hard-Val不使用）

| | baseline(best conf=0.60) | candidate(best conf=0.50) | baseline@現行conf0.60 | candidate@現行conf0.60 |
|---|---|---|---|---|
| Exact Match | 151/165 (91.5%) | 153/165 (92.7%) | 151/165 | 148/165 |

conf grid全体・character accuracy・missing/extra/wrong_class・2→8/8→2等の詳細は比較文書§6.3参照。

## 6. ONNXエクスポート

- 対象: `projects/yolo26_digital/runs/train/candidate_yolo26n_v1/weights/best.pt`（上記5901...のみ、
  `yolo26n.pt`本体や既存production modelは出力していない）
- 仕様: ONNX / FP32 / batch=1 / static `[1,3,640,640]` / opset=17 / `end2end=False` / `nms=False`（グラフ外NMS）/ simplify=False
- 出力: `projects/yolo26_digital/exports/candidate_yolo26n_v1/yolo26_digital.onnx`
  - SHA256: `c14c58f23592f3b4ad5f75300ae7a0ed4babb7f3f73234bdd947d6f4d461a346`
  - サイズ: 9,754,603 bytes
  - 入出力: `images[1,3,640,640]fp32` → `output0[1,14,8400]fp32`（one-to-many生ヘッド、NMSなし）
- 同梱ファイル: `preprocess_profile.json`（ROI無効、resize/grayscale/sharpen＋letterbox仕様）,
  `classes.json`, `export_metadata.json`, `README.md`, `infer.py`（外部NMS実装込みCPU推論スクリプト、
  実データで動作確認済み: `src_002_20260818_110000`で7/7検出・reading `0214943`がGTと一致）

## 7. ONNX Runtime検証

- `onnx.checker.check_model`: 成功
- ONNX Runtime (CPUExecutionProvider) load + 実推論: 成功
- PT(end2end=False) vs ONNX tensor比較（8サンプル、letterbox後生forward）: shape全件一致、NaN/inf無し、
  max abs diff 0.0014〜0.0043、mean abs diff 約1.3〜1.5×10⁻⁵、`allclose(rtol=1e-3, atol=1e-4)`全件True
- Val全件でのPT対ONNX reading一致率（conf=0.50）: 161/165 (97.6%)、差分4stemはいずれもconf境界での
  1box分の増減（詳細は比較文書§8.3）
- CPU推論レイテンシ参考値: 平均16.03ms/image（batch=1, imgsz=640, forward呼び出しのみ）

## 8. 復元・再現手順

1. `projects/yolo26_digital`（project定義・classes.yaml・dataset・run・export一式）はGit管理外のため、
   本文書のhashを用いてbit-for-bit照合すること。
2. 新規環境での再現: `project_service.create_project("yolo26_digital", ..., "detect")` →
   class 0〜9を保存 → source dataset（§1）のtrain/valをバイト単位で複製し`data.yaml`（train/valのみ）を生成 →
   `training_service.start_job()`を上記§4のパラメータで実行 → `model.export(format="onnx", imgsz=640, batch=1,
   dynamic=False, simplify=False, opset=17, end2end=False, half=False)`でONNX出力。
3. 既存アプリの`dataset_service.create_dataset()`（random re-split）や`onnx_export_service`
   （`end2end`制御不可）はこの再現には使用できない。専用スクリプトでの直接呼び出しが必要。

## Safety Gate（本Issueを通じ遵守）

- 既存production（digital/drum selected_model.json・best.pt）は無変更（作業前後でSHA256/内容完全一致を確認）
- 既存v2 manifestは無変更
- Test/Hard-Valは学習・評価・ONNX検証のいずれにも使用していない（漏洩0件を機械検証済み）
- 本番モデルへの自動切替は行っていない（`yolo26_digital`に`selected_model.json`は作成していない）
- Git管理はこの3ファイル（本ファイル・drum側provenance・比較文書）のみ
