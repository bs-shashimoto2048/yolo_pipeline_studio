# yolo26_dram_crop Provenance（Issue #24 — YOLO26n比較候補）

Issue #24「Retrain yolo26_digital and yolo26_dram_crop under matched conditions and verify ONNX exports」の
drum側成果物の記録。**production採用ではなく比較候補**。既存production（`meter_src004`,
`candidate_roi_v3_5:best`, conf=0.80）は本Issueで無変更。

詳細な評価条件・結果・ONNX検証は [`docs/YOLO26_RETRAIN_ONNX_COMPARISON.md`](../docs/YOLO26_RETRAIN_ONNX_COMPARISON.md) を参照。
本ファイルは drum 側の再現・復元に必要な事実の記録に特化する。project名は指定どおり **`yolo26_dram_crop`**
（`drum`ではなく`dram`表記を維持）。

## 1. Source（現行productionと同一のデータ条件）

- source project: `meter_src004`
- source dataset: `projects/meter_src004/datasets/meter_src004_roi_v3/`
- source manifest: `data_manifests/meter_src004_split_v3.csv`（＋独立Hard-Val: `meter_src004_hard_val_v1.csv`、
  今回も学習・評価に不使用）
- source run（比較baseline）: `projects/meter_src004/runs/train/candidate_roi_v3_5/`
  - best.pt SHA256: `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db`
  - モデル: yolov8n（既存production、詳細は[`meter_src004_roi_v3_provenance.md`](meter_src004_roi_v3_provenance.md)）
- Train 339 / Val 58（v3 primary split、旧full-frame・旧ROI v1・却下済みROI v4のデータは使用していない）
- 画像はraw ROI由来640×131（ROI crop→resize→grayscale→sharpen済み）

## 2. 新規project

- project名: `yolo26_dram_crop`（`project_service.create_project()`で作成、task=detect、class 0〜9）
- dataset名: `matched_source_v1`（source datasetのtrain/valをバイト単位で直接コピー。二重前処理・
  再split・再annotationなし。画像サイズ640×131を維持）
- run名: `candidate_yolo26n_v1`

## 3. データコピーの検証

- コピー元/先のSHA256一致: 397/397件（train339+val58、画像+label）
- missing/orphan/duplicate stem: 0件
- 7bbox・class0-9範囲・座標範囲: 全件正常
- 保護対象（source manifestのTest + 独立Hard-Val、計68 stem）の漏洩: 0件
- source dataset自体への書き込み: なし（読み取り専用で複製）

## 4. 学習

- base weight: `yolo26n.pt`
  - 取得元: `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt`
  - SHA256: `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef`（digital側と同一の公式配布物。
    project間で共有せず、それぞれ独立にダウンロードして同一hashであることを確認済み）
- 学習条件: epochs=50, imgsz=640, batch=8, device=0, workers=2, patience=20, seed=42
- augmentation（既存run実測値を明示指定、アプリのbuiltin "standard" presetは使用せず）:
  `degrees=0.0, translate=0.1, scale=0.5, shear=0.0, perspective=0.0, flipud=0.0, fliplr=0.5, mosaic=1.0, mixup=0.0, copy_paste=0.0, hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, close_mosaic=10`
- optimizer: `auto`指定 → 実解決値 `AdamW(lr=0.000714, momentum=0.9)`
- 完走: 50/50 epoch（early stopping未発動）、所要時間 約22.5分、OOM/NaN/inf なし
- **best.pt SHA256: `18bd80b6ac9b74e2c89a7d3df3b64727fc14edad0a82e59b7c4c5a6510a400e6`**
- 最終Val: P=0.911 R=0.892 mAP50=0.955 mAP50-95=0.872

## 5. Val比較（vs baseline `candidate_roi_v3_5`, Val58限定, Test/Hard-Val不使用）

| | baseline(best conf=0.50) | candidate(best conf=0.40) | baseline@現行conf0.80 | candidate@現行conf0.80 |
|---|---|---|---|---|
| Exact Match | 56/58 (96.6%) | 52/58 (89.7%) | 46/58 (79.3%) | 47/58 (81.0%) |

**YOLO26n候補はbest conf同士の比較でbaselineより明確に劣化している**（wrong_classがconf 0.40〜0.60帯で
一貫して5件、baselineの1件より多い。2→8/8→2の混同ではない）。現行production conf=0.80に固定した場合は
候補がわずかに上回るが、両モデルともbest confから離れた条件での数値であり実力差を反映したものではない。
精度が劣化しているという事実を隠さず記録する（本Issueの完了条件は学習・ONNX出力・検証の完了であり、
精度改善そのものではない）。conf grid全体の詳細は比較文書§6.4参照。

## 6. ONNXエクスポート

- 対象: `projects/yolo26_dram_crop/runs/train/candidate_yolo26n_v1/weights/best.pt`（上記18bd...のみ、
  `yolo26n.pt`本体や既存production modelは出力していない）
- 仕様: ONNX / FP32 / batch=1 / static `[1,3,640,640]` / opset=17 / `end2end=False` / `nms=False`（グラフ外NMS）/ simplify=False
- 出力: `projects/yolo26_dram_crop/exports/candidate_yolo26n_v1/yolo26_dram_crop.onnx`
  - SHA256: `e0fd59ffd11528a8cd5ee32ed08c5732df70ff7a872f3dfca401d5e73140df20`
  - サイズ: 9,754,605 bytes
  - 入出力: `images[1,3,640,640]fp32` → `output0[1,14,8400]fp32`（one-to-many生ヘッド、NMSなし）
- 同梱ファイル: `preprocess_profile.json`（**ROI有効、raw 1920×1080基準 x=[835,1354), y=[374,480)**、
  crop→resize→grayscale→sharpen＋letterbox仕様。640×131画像へこのROIを再適用しないことを明記）,
  `classes.json`, `export_metadata.json`, `README.md`, `infer.py`（外部NMS実装込みCPU推論スクリプト、
  実データで動作確認済み: `src_004_20260818_110000`で7/7検出・reading `3709703`がGTと一致）

## 7. ONNX Runtime検証

- `onnx.checker.check_model`: 成功
- ONNX Runtime (CPUExecutionProvider) load + 実推論: 成功
- PT(end2end=False) vs ONNX tensor比較（8サンプル、letterbox後生forward）: shape全件一致、NaN/inf無し、
  max abs diff 0.0022〜0.0046、mean abs diff 約1.1〜1.2×10⁻⁵、`allclose(rtol=1e-3, atol=1e-4)`全件True
- Val全件でのPT対ONNX reading一致率（conf=0.40）: 53/58 (91.4%)、差分5stemはいずれもconf境界での
  1box分の増減（詳細は比較文書§8.3）
- CPU推論レイテンシ参考値: 平均15.61ms/image（batch=1, imgsz=640, forward呼び出しのみ）

## 8. 復元・再現手順

1. `projects/yolo26_dram_crop`（project定義・classes.yaml・dataset・run・export一式）はGit管理外のため、
   本文書のhashを用いてbit-for-bit照合すること。
2. 新規環境での再現: `project_service.create_project("yolo26_dram_crop", ..., "detect")` →
   class 0〜9を保存 → source dataset（§1）のtrain/valをバイト単位で複製し`data.yaml`（train/valのみ）を生成 →
   `training_service.start_job()`を上記§4のパラメータで実行 → `model.export(format="onnx", imgsz=640, batch=1,
   dynamic=False, simplify=False, opset=17, end2end=False, half=False)`でONNX出力。
3. 既存アプリの`dataset_service.create_dataset()`（random re-split）や`onnx_export_service`
   （`end2end`制御不可）はこの再現には使用できない。専用スクリプトでの直接呼び出しが必要。

## Safety Gate（本Issueを通じ遵守）

- 既存production（`meter_src004`のselected_model.json・best.pt、conf=0.80）は無変更
  （作業前後でSHA256/内容完全一致を確認）
- 既存v3 split manifest・独立Hard-Val27は無変更、いずれも学習・評価に不使用
- Test/Hard-Valは学習・評価・ONNX検証のいずれにも使用していない（漏洩0件を機械検証済み）
- 本番モデルへの自動切替は行っていない（`yolo26_dram_crop`に`selected_model.json`は作成していない）
- Git管理はこの3ファイル（本ファイル・digital側provenance・比較文書）のみ
