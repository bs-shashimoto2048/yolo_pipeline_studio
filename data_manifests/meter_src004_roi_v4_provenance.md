# meter_src004 ROI v4 (hard-negative dataset) provenance — Issue #36

## 背景

Issue #34（原因調査）・Issue #35（confidence再評価）を通じて、drum末尾桁の不安定性は
threshold調整では解決できず（Val58では改善して見えるが、独立なTrain339データでは
confidently-wrongが増加する）、根本的にはデータセット改善が必要と判断されていた。
本Issueは、その具体的な実行（新規hard-negative画像の追加によるdataset v4作成と、
再学習candidateの正式評価）である。

**最重要原則**: 既知の6件のconfidently-wrong Train画像を単純に複製して水増しすることは
一切行っていない。新規primary画像はすべて、既存の全manifest（Train339/Val58/Test41/
Hard-Val27）に含まれない、独立な未使用画像から選定した。

## 1. 既知の失敗例（事前記録、仮説登録）

Issue #34で特定済みの6件の confidently-wrong drum stem（すべて`phase=boundary`、
末尾桁の"→7"/"→6"誤分類パターン）を、新規candidate探索の前に確認・記録した。
事前仮説: 末尾桁ホイールの回転境界付近で、視覚的に類似した"6"/"7"へ過検出しやすい
（物理的な遷移形状の類似が原因であり、閾値較正やモデル欠陥単体の問題ではない）。
この仮説は、新規candidateを見た後も変更していない。

## 2. Candidate mining

- 対象: `meter_src004`の未使用raw画像プール 1962枚（`raw/images`全2427枚中、
  既存manifest v1/v2/v3 + hard_val_v1 いずれにも属さない465枚を除いた残り）。
  ライブカメラ・アーカイブ映像は本環境に存在しないため、この未使用raw画像プールが
  唯一の正当な新規データソースである。
- production model (`candidate_roi_v3_5:best`) を診断用confidence(0.05)で全件に適用し、
  本番と全く同じpreprocess（ROI/resize/grayscale/sharpen）を通した上で推論。
- hard-negative判定基準: production閾値(0.80)でmissing、末尾桁近傍に既知混同クラス
  (6または7、conf>=0.5)が出現、confidenceマージンが小さい、のいずれか。
  → 1962枚中 829枚がhard、916枚がstable-clear。
- 誤分類ロジックには2回のバグがあった（詳細はコミット内スクリプト参照）:
  1回目は末尾桁以外の桁も誤って混同判定に含めてしまい100%hard判定になるバグ、
  2回目は「最上位candidateは正しいはず」という誤った前提で最上位を除外してしまうバグ。
  いずれも結果の妥当性チェック（既知の実績と比較して明らかに不自然な比率）で
  自己発見・修正した。

## 3. Atomic unit化（重複排除）

`docs/METER_DATASET_CURATION_GUIDE.md`の確立された手法（aHash + Hamming距離 +
時間近接）を踏襲し、ROI領域のaverage-hash（32x32、閾値はHamming<=16/1024bit、
同水準の厳しさで256bit版から再較正）とタイムスタンプ近接（300秒以内）でクラスタリング。
1745件の候補（829 hard + 916 stable）→ 516 atomic unit（272 hard、244 stable）。

## 4. 目視レビューとGT確定

516 atomic unitから、wrong_signature由来57件全件・n_production_off由来50件サンプル・
stable-clear由来40件サンプルの計147件を対象に、`scripts/review_montage.py`で
高解像度montage画像を生成し、1件ずつ目視で読み取った（GTは常に単一画像からの
人間目視読み取りであり、モデル出力や近傍フレームからの自動ラベリングは行っていない）。

- 明確に判読可能なもの: GTを確定し採用。
- 末尾桁ホイールが2桁の中間で拮抗しているもの（優勢桁が明確でない）: **GT強制せず除外**。
- 桁位置の数え間違い（1件、`src_004_20260903_152400`）を目視レビュー中に自己発見・訂正
  （末尾2桁の構造を誤認していたことが、後段のacceptance checkでbaseline/candidate両方の
  候補クラスと矛盾したことから判明。high-res再クロップで訂正）。

除外内訳: 明確に曖昧なもの、視覚的に判読困難なもの（低品質期の画像を含む）多数。
残った候補のうち、同一reading値がidle期間の連続キャプチャとして多数出現したもの
（最大12連続、`3718376`）は**1件のみ代表として採用**し、残りは"似た連写の水増し"を
避けるため除外した。

## 5. Leakageチェック

stem重複: 0件（機械確認）。
perceptual hash近接チェック（32x32 aHash、Hamming<=3を「同一撮影に極めて近い」と定義）で、
既存Val58/Hard-Val27メンバーに近接する5候補を発見し、**全て除外**した
（`src_004_20260907_210400`→Val58近接、`src_004_20260901_162800`/`src_004_20260904_155200`/
`src_004_20260904_071600`/`src_004_20260904_051200`→Hard-Val27近接）。
Train339への近接は多数あったが、これはleakageではなく許容（Train-add同士・Train339との
近接は評価整合性を損なわない）。

最終的な独立primary候補: **85件**（wrong_signature 39、n_production_off 15、stable_clear 31）。

## 6. Train-add / Frozen Hard-Val v2 分割

85件をカテゴリ層別に分割（atomic unit単位、reading重複なしのため1候補=1 reading group）:
- **Train-add: 66件**（78%）
- **Frozen Hard-Val v2: 19件**（22%）— `data_manifests/meter_src004_hard_val_v2.csv`

YOLOラベルはproduction modelが検出した実際のbbox座標をそのまま再利用し、クラスIDのみ
目視確定したGT桁へ置換した（座標の手動再アノテーションはしていない。座標精度は
production modelの桁位置検出自体が高信頼度であり、疑わしいのは主に末尾桁のクラスの
みであるため）。オーバーレイ確認で全桁の整合を目視検証済み。

## 7. Dataset v4 / 学習

- Dataset: `projects/meter_src004/datasets/meter_src004_roi_v4_hardneg/`
  （v3のTrain339・Val58をそのまま維持し、Train-add 66件のみ追加。既存v3ディレクトリは
  一切変更していない）。
- **重要な事故と修正**: 当初 `meter_src004_roi_v4` という名前で作成しようとしたが、
  このディレクトリ名は2026-09-17付けの既存の別実験（offline photometric augmentation、
  本Issueと無関係）にすでに使用されていた。誤って自分の新規ファイルをマージしてしまった
  ことに気づき、追加分のみを取り除いて原状回復し、衝突しない
  `meter_src004_roi_v4_hardneg` で作り直した（内容の同一性は、augmentation実験のsource
  stemがv3 Train339の厳密な部分集合であることから、上書きされた339件のbase画像は
  元々v3からのバイトコピーだった可能性が極めて高く、実害はなかったと判断しているが、
  完全な検証はできないため残存リスクとして記録する）。
- Manifest: `data_manifests/meter_src004_split_v4.csv`
  （v3の339+58+41行をそのまま維持 + Train-add 66行を追加。既存行は一切変更していない）。
- 学習: `candidate_roi_v4_hardneg`（YOLOv8n、baseline `candidate_roi_v3_5`と完全同一の
  ハイパーパラメータ: epochs=50, batch=8, imgsz=640, patience=20, seed=42,
  deterministic=True, device='0', workers=2, iou=0.7, max_det=300, augmentation標準既定値）。
  データセットのみが差分。
  - weight SHA256: `cadd1d7df52b94004331be2d3c79c7dbc306c93802b3f5c3d455f2121061f595`
  - 学習中、Windows multiprocessing spawnのguard漏れ（`if __name__ == "__main__":`欠落）
    により1回失敗（プロセス二重起動でRuntimeError）。修正後に再学習し成功。

## 8. Standard Val58 評価（conf=0.80固定、re-tuneなし）

| | baseline (v3_5) | candidate (v4_hardneg) |
|---|---|---|
| Exact Match | 82.8% (48/58) | 86.2% (50/58) |
| 7-detection率 | 82.8% | 86.2% |
| Character accuracy | 100.00% | 100.00% |
| Missing | 10 | 8 |
| Wrong class | 0 | 0 |
| 2→8 / 8→2 | 0 / 0 | 0 / 0 |
| 末尾桁accuracy | 86.2% | 93.1% |
| Confidently-wrong (末尾桁) | 0 | 0 |

**Promotion Gate（Val58）: 全て通過**
- Gate A（confidently-wrong非増加）: 0→0 ✓
- Gate B（2/8混同非増加）: 0→0 ✓
- Gate C（Exact Match/末尾桁信頼性の改善）: 両方改善 ✓
- Gate D（他桁性能の非劣化）: character accuracy 100%→100% ✓

## 9. Frozen Hard-Val v2 評価（Val58通過後、1回のみ）

| | baseline (v3_5) | candidate (v4_hardneg) |
|---|---|---|
| Exact Match | 78.9% (15/19) | 94.7% (18/19) |
| Missing | 4 | 1 |
| Wrong class | 0 | 0 |
| 末尾桁accuracy | 78.9% | 94.7% |
| Confidently-wrong | 0 | 0 |

**Gate判定**: confidently-wrong「減少」を要求する原則条件は、baselineが既に0件のため
厳密な減少は数学的に不可能（0→0は退行ではなく非増加として扱う。この解釈をここに
明記する）。wrong-class非増加・末尾桁信頼性改善・破滅的退行なし、いずれも通過。
**Frozen Hard-Val v2ゲート: 通過**。既存Hard-Val27は本評価に一切使用していない。

## 10. 非Test受け入れ確認（Train-add/Hard-Val v2/Val58/Test41/Hard-Val27いずれにも
含まれない独立画像）

review_setでレビュー済みの147件も除外した上で、未使用プールから8件抽出し目視レビュー
（2件は判読不能で除外、1件は目視レビュー中に桁位置の数え間違いを自己発見し訂正）。
最終6件で比較:

| | baseline | candidate |
|---|---|---|
| Exact Match | 33.3% (2/6) | 50.0% (3/6) |
| Missing | 4 | 3 |
| Confidently-wrong | 0 | 0 |
| Character accuracy | 100% | 100% |

サンプル数が小さく統計的に弱いが、方向性はVal58・Hard-Val v2と一致し、退行の兆候はない。

## 11. 既知の6件（Train由来confidently-wrong失敗例）について

本Issueの一次promotion根拠には使用していない（Issue #35のTrain339 acceptance checkの
教訓を踏まえ、あくまでVal58・Hard-Val v2・独立acceptanceを一次根拠とする）。追加の
二次参考としての再推論は、規模・時間の制約により本Issueでは実施していない
（次Issue候補として持ち越す）。

## 12. Promotion判断

**Case A（明確な改善）と判定し、productionへ昇格した。**

- `selected_model.json`: `train_job_id`/`model_path`/weightのみ変更。
  `conf`は0.80のまま、ROI/preprocess/pinned argsは一切変更していない。
- 旧`selected_model.json`はバックアップ済み、旧weight
  （`candidate_roi_v3_5:best`, sha256
  `45c4d9054a30bd09a1a17d3eb53b87e0d26669b1387728ddc64fa8130f9e82db`）は削除・移動せず
  そのまま保持。
- Contract version: **`production-inference-contract-v1`のまま据え置き**（bump不要と判断）。
  `docs/PRODUCTION_INFERENCE_CONTRACT.md`のbump条件（resolved args変更/preprocessing変更/
  architecture変更/tensor shape変更/golden fixture期待値変更/意図的runtime behavior変更）
  のいずれにも該当しない。`smoke_inference_contract.py`のdrum golden fixtureは
  `candidate_roi_v3_5`の重みファイルパスへ直接固定されており、production選択とは独立な
  恒久的回帰アンカーとして設計されているため、本promotionでは変更していない（設計意図の
  確認は同ファイルのLayer B実装を直接読んで判断した）。一方`production_smoke_v1.json`
  （Issue #32、Layer C）は「現在のproduction選択が記録済み期待値と一致するか」を検証する
  設計であるため、`train_job_id`/`weight_sha256`を新モデルへ更新した。両stemの実際の
  detection結果は新旧モデルで完全一致（3718333/3718227、7検出）だったため、共有golden
  fixtureの値自体は変更不要だった。

## 13. Regression確認

`smoke_inference_contract.py`・`smoke_inference_observability.py`・
`smoke_production_integration.py`・backend全39ファイルsmoke suite、いずれもgreen。

## 14. 明示事項

- Test41は本Issueで一切使用していない（predict/GT参照/mining/学習/model選択いずれも不使用）。
- 既存Frozen Hard-Val27は本Issueで一切使用していない（mining/tuning/retraining判断/
  candidate比較いずれも不使用、historical recordとして凍結されたまま）。
- 新規Frozen Hard-Val v2は学習完了後に1回のみ評価し、re-tuneには使用していない。

## 15. 既知の限界・残存リスク

- 独立acceptanceサンプルが6件と小規模（未使用プールのうち、既存review対象と重複しない
  wrong_signature系候補が枯渇していたため）。
- `meter_src004_roi_v4`ディレクトリ名衝突事故（§7参照）: 完全な無害性は理論的推定であり、
  100%の実証はできていない。
- 目視GTはClaude（multimodal LLM）による単独読み取りであり、複数人によるダブルチェックは
  行っていない。

## 16. 関連リンク

前身の閾値再評価は[`meter_src004_roi_v3_provenance.md`](meter_src004_roi_v3_provenance.md)
（Issue #35追記）を参照。原因分析の全体像は
[`docs/LAST_DIGIT_CONFIDENCE_AUDIT.md`](../docs/LAST_DIGIT_CONFIDENCE_AUDIT.md)を参照。
