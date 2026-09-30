# Ultralytics依存 更新手順（Upgrade Procedure）

Issue #28で新規作成。Issue #24〜#27で構築した production inference contract
（[`docs/PRODUCTION_INFERENCE_CONTRACT.md`](PRODUCTION_INFERENCE_CONTRACT.md)）を守ったまま、
Ultralytics（および密結合する torch/torchvision/torchaudio/onnx/onnxruntime 等）を
安全に更新するための標準手順。

> 本ドキュメントは「いつ更新すべきか」を決めるものではない。
> 「更新する際に何を確認しなければならないか」だけを定義する。

## 1. Purpose

Ultralytics依存の更新によって、production inferenceのreading / detection /
tensor shape / resolved argsが**意図せず**変わることを防止する。

> **Issue #31追記**: 本手順（pre-upgrade snapshot・Gate A〜E・failure classification・
> 採否/rollback基準）は、Ultralytics自体の更新に限らず、**torch/torchvision/torchaudioの
> バージョンやCUDA wheel（`cuXXX`）を変更する場合にも同様に適用する**。Torch stackの
> 検証済み構成・pin方針・インストール手順は
> [`docs/TORCH_STACK_POLICY.md`](TORCH_STACK_POLICY.md)を参照。

判断の原則:

```text
最新版だから更新 ではなく、
current contract取得 → dependency変更 → contract regression → 差分監査 → 採否判断
```

contract差分が出た場合、**goldenを新結果へ書き換えてtestを通す行為は禁止**。
差分の原因を先に説明すること（詳細は §11 / §12）。

## 2. Current validated stack

`scripts/capture_upgrade_snapshot.py` の実行結果（2026-09-30、Issue #28作成時点、
git HEAD `c9dee3ba1e286d16178df88ba2dd02f6a9be135f`）:

| Component | Validated version |
|---|---|
| ultralytics | 8.4.83 |
| torch | 2.11.0+cu128 |
| torchvision | 0.26.0+cu128 |
| torchaudio | 2.11.0+cu128 |
| numpy | 2.2.6 |
| opencv-python (cv2) | 4.13.0 |
| Pillow | 12.2.0 |
| onnx | 1.22.0 |
| onnxruntime | 1.23.2 |
| onnxslim | 0.1.94 |
| Python | 3.10.11 |
| CUDA (torch.version.cuda) | 12.8 |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU |
| production-inference-contract | production-inference-contract-v1 |

この表と `backend/tests/fixtures/production_inference_contract_golden_v1.json` の
`generation_environment` は常に一致していなければならない
（不一致は §「実行不可条件」に該当し、作業を止める）。

## 3. Dependency inventory（現状棚卸し）

frontend（`frontend/package.json` 等）は本手順の対象外
（Ultralytics runtimeとは無関係のため除外）。

| Dependency | Current installed | Declared constraint | Production relevance | Upgrade coupling |
|---|---|---|---|---|
| ultralytics | 8.4.83 | `ultralytics==8.4.83`（本Issueでexact pin、`requirements-train.txt` / `backend/requirements-sam.txt`） | **high** — production inference contractの直接対象 | torch APIに強く依存。torchのmajor/minor更新と合わせて検証が必要 |
| torch | 2.11.0+cu128 | `torch`（unpinned、`requirements-train.txt`） | **high** — 推論バックエンド本体、CUDA結合 | torchvision/torchaudioは同一cuXXXビルド・対応バージョンでなければならない。ホストのCUDA driverとの互換も必要 |
| torchvision | 0.26.0+cu128 | `torchvision`（unpinned） | high（ultralytics内部のops/NMS関連で使用） | torchとのバージョン対応表に従う必要あり（torch単体のみ更新するとimport不整合のリスク） |
| torchaudio | 2.11.0+cu128 | `torchaudio`（unpinned） | low（本アプリの画像/映像推論経路では直接使用しないが、torchエコシステムの一貫性のため同梱） | torchと同時更新が前提 |
| numpy | 2.2.6 | 明示宣言なし（ultralytics/torch/opencvの推移的依存） | **high** — preprocess/postprocessの配列演算全般 | torch/opencv/ultralyticsそれぞれのnumpy対応レンジに拘束される（1系→2系のようなmajor跨ぎは特に注意） |
| opencv-python | 4.13.0.92 | `opencv-python`（unpinned、`backend/requirements-sam.txt`） | **high** — LetterBox・ROI・resize等、preprocessパイプラインで直接使用 | numpy ABIと連動 |
| Pillow | 12.2.0 | `Pillow>=10.0`（`requirements.txt`、軽量側） | medium — 軽量側（アノテーション等）の画像処理。production inference contractの直接対象ではない | 独立性が高く単独更新の影響は小さい |
| onnx | 1.22.0 | `onnx`（unpinned、`requirements-train.txt`） | medium — ONNXエクスポート・PT/ONNX parity検証（Issue #24）で使用。現行productionはPT運用のためruntime推論の直接対象ではない | onnxruntimeのopset対応と連動 |
| onnxruntime | 1.23.2 | `onnxruntime`（unpinned） | medium — 同上（CPU版、`onnxruntime-gpu`ではない） | onnxのopset・torch export側のopset指定と連動 |
| onnxslim | 0.1.94 | `onnxslim`（unpinned） | low — export時の最適化のみ | onnx/onnxruntimeの互換範囲に追従 |

## 4. Ultralytics version pin状況

**確認結果**: `requirements-train.txt` / `backend/requirements-sam.txt` の `ultralytics` は
従来unpinnedだった（`ultralytics` の行のみ）。再installだけでversionが変わるリスクがあったため、
本Issueで **`ultralytics==8.4.83` へexact pin** した（§14「実施したrequirements変更」参照）。

torch/torchvision/torchaudio/onnx/onnxruntime/onnxslim/opencv-python/numpy/Pillowは、
CUDAビルド（`cuXXX`サフィックス）選択がインストール手順（README）側の責務であることと、
torch⇄torchvision⇄torchaudioの相互バージョン拘束があるため、
**本Issueではpinせず、提案のみ**とする（§14参照）。

## 5. Upgrade classification

更新内容によって必要なgateが変わる。semantic versioningの数字だけで安全性を判断しない
（Ultralytics 8.4.83自体、`Model.predict()`のcustom defaultsのような非公開的挙動が
patchバージョン内に混在しうることをIssue #24の監査で確認済み）。

| 分類 | 例 | 必須Gate |
|---|---|---|
| Patch / minor相当 | `8.4.83 → 8.4.x` のようなバージョン番号上の小変更 | A, B, C, D, E（全Gate必須。「patchだから軽微」という前提を置かない） |
| Feature-level change | predict default値・NMS実装・LetterBox実装等に変更がある場合 | A, B, C, D, E + CHANGELOG/release notesの該当箇所を事前確認 |
| Model-generation change | 新YOLO世代（YOLO26等）への対応追加 | 上記に加え、Issue #24と同様の非Test比較診断が必要（本番切替を伴う場合は別途Issue化） |
| Breaking runtime change | API / preprocessing / Result object等の変更 | 上記全て + workers（`predict_worker.py`/`predict_video_worker.py`）のコード修正・影響範囲の individual review |

## 6. Pre-upgrade snapshot（必須）

更新前に必ず記録する。`scripts/capture_upgrade_snapshot.py` で機械的に取得できる:

```bash
.venv\Scripts\python.exe scripts\capture_upgrade_snapshot.py > snapshot_before.md
```

記録内容: git commit（HEAD）、contract version、golden fixtureのgeneration_environment、
インストール済み主要パッケージversion、CUDA/GPU、production model（digital/drum）の
weight SHA256とselected_model.json全内容。

このsnapshotは一時ファイル（scratchpad等）に保存し、Issue/PRコメントに貼り付ける。
リポジトリへの恒久コミットは不要（更新の都度変わるため）。

## 7. Upgrade gate

dependency変更後、以下を**この順序で**実行する。いずれかでFAILしたら次のGateへ進まない。

### Gate A — Import / API

```bash
.venv\Scripts\python.exe -c "from ultralytics import YOLO; m = YOLO('yolov8n.pt'); print('ok')"
```

- backend import成功（`uvicorn app.main:app --app-dir backend` の起動確認、または
  `python -c "import app.main"` 相当）
- worker import成功（`python -c "import sys; sys.path.insert(0,'backend'); import workers.predict_worker"` 等）
- production weightのYOLO model load成功（`YOLO(<production weight path>)`）

### Gate B — Layer A contract（production weight不要）

```bash
.venv\Scripts\python.exe backend\tests\smoke_inference_contract.py
```

Layer A部分（worker kwargsの構造検査・image/video parity・contract doc整合）が
全件PASSすること。

### Gate C — Layer B contract（production weightが手元にある場合のみ）

同じ `smoke_inference_contract.py` のLayer B部分。production weight・fixture画像が
存在する環境では**skipせず必ず実行**し、strict fields完全一致・tolerance fields範囲内を確認する。

### Gate D — backend regression

```bash
for f in backend/tests/smoke_*.py; do .venv/Scripts/python.exe "$f" || echo "FAIL: $f"; done
```

既知flaky（§9）を除き新規failureがないこと。

### Gate E — non-Test smoke（production経路の統合確認）

> **Issue #32追記**: Gate Eは以下の恒久testで実行する（以前は手動/scratchpadでの
> 都度実行だったものを恒久化した）。

```bash
.venv\Scripts\python.exe backend\tests\smoke_production_integration.py
```

`backend/tests/fixtures/production_smoke_v1.json`で定義したdigital/drum各2枚の
non-Test fixtureに対し、`smoke_inference_contract.py`の直接`model.predict()`呼び出しでは
なく、**実際のworker経路**（image: API `/api/projects/{name}/predict-jobs` →
`prediction_service.start_job()` → `predict_worker.py`のsubprocess起動、video:
`predict_video_worker.py`をmock cameraで直接起動）でjob完了・reading出力・
`inference_contract`（contract version/model SHA256/resolved args/observability）が
正常であることを確認する。これはcontract doc内のstrict/tolerance比較の代替ではなく、
「実運用経路（subprocess起動・job.jsonポーリング・selected model resolution・
preprocess適用・observability記録）が壊れていないか」の統合的な健全性確認である。
production weight・fixture画像がローカルに無い環境ではSKIPする。

## 8. Contract failure時の分類

Gate B/C/D/EでFAILした場合、原因を以下へ分類してから対応方針を決める。
goldenを書き換える前に必ずこの分類を行うこと。

| Type | 内容 | 例 |
|---|---|---|
| 1. Default変更 | predict呼び出しの暗黙default値が変わった | `rect`/`max_det`/NMS関連。現在は主要値を明示固定済み（Issue #25/#26）のため通常は影響しないはずだが、明示していないパラメータ（`classes`/`device`/`end2end`/`half`/`verbose`等、`docs/PRODUCTION_INFERENCE_CONTRACT.md`のDecision Record参照）でdefaultが変わった場合はここに該当 |
| 2. Preprocessing変更 | letterbox / resize / dtype等、前処理の実装が変わった | `LetterBox`のresize/pad挙動、`preprocess()`が返すtensorのdtype/shape変化 |
| 3. Postprocess変更 | NMS / class ordering / bbox座標系等が変わった | `non_max_suppression`の実装変更、box座標の丸め方変更 |
| 4. Model loading差 | シリアライズ・レイヤー挙動の差 | `.pt`ロード時のstate_dict互換性・重み量子化挙動の変化 |
| 5. Numeric-only差 | tolerance範囲内外の数値差のみ | confidence/bboxの浮動小数点差（`docs/PRODUCTION_INFERENCE_CONTRACT.md`のtolerance定義参照） |
| 6. API break | Result object / メソッドシグネチャ等の変更 | `model.predict()`の戻り値構造変更、`predictor.args`の属性名変更 |

Type 5（tolerance内）のみ許容範囲内として扱ってよい。Type 1〜4, 6はいずれも
**「差分原因の説明」が採否判断の前提**であり、原因不明のままgoldenを書き換えて
testを通すことは禁止する。

## 9. 採用基準 / 採用不可条件

### 採用してよい条件（すべて満たすこと）

- strict contract fieldsが全fixtureで完全一致
- tolerance fields（confidence/bbox）が定義範囲内
- backend test suiteに新規regressionがない（既知flakyの区別は下記）
- Gate E（non-Test smoke）が正常
- dependency解決にconflictがない
- 重大なパフォーマンス悪化がない（実測して確認する。「大丈夫だろう」で済ませない）

### 採用しない条件（いずれか一つでも該当したら不採用）

- reading / detection count / class sequenceの変化
- tensor shapeの変化
- production runtime例外（クラッシュ・タイムアウト等）
- confidence/bboxがtolerance超過
- preprocess挙動の変化
- worker側のコード修正が必要なのに影響評価が未完了

### 既知flakyと新規regressionの区別

> **Issue #30追記**: 以前ここに記載していた`smoke_prediction_selected_model_fallback.py`の
> job.json読み書き競合、および`smoke_video_inference.py`の`test_settings_lock_no_lost_update`
> のlock steal raceは、いずれもIssue #30で根本原因を修正済み（job.jsonのatomic書き込み化・
> ロック奪取判定のfile age基準化）。現時点で本プロジェクトに既知flakyとして扱うtestは無い。
> 以下の判定手順は、将来新たなflakyが見つかった場合の一般的な運用ルールとして残す。

upgrade gate実行時にテストが断続的に失敗した場合の判定手順:

1. 単体で3回連続再実行する。
2. 3回とも同じ `JSONDecodeError`（同じ発生箇所）であれば、既知flakyとして記録し、
   gate自体は継続してよい（このtestに限り、既知flaky理由をcompletion recordに明記）。
3. エラー内容・発生箇所が異なる、または3回中1回でも別の失敗モードが出た場合は、
   **新規regressionとして扱い**、Type 1〜6のいずれかに分類してから採否判断する。

この区別ルールにより、「知っているflakyだから」を理由に本当の新規regressionを
見逃すことを防ぐ。

## 10. Rollback procedure

dependency upgrade失敗時のrollback手順:

1. `requirements-train.txt` / `backend/requirements-sam.txt` を更新前の内容へ戻す
   （git管理下のため `git diff` / `git checkout -- <file>` で復元可能。ただし
   作業中の他の変更を巻き込まないよう、対象ファイルのみを明示的に指定すること）
2. 仮想環境を再構築するか、対象パッケージのみ明示バージョンで再インストールする。例:
   ```bash
   pip install ultralytics==8.4.83
   ```
   ただし **torch/torchvision/torchaudioを含む変更だった場合、ultralyticsだけ戻せば
   必ず安全とは限らない**（バージョン間のAPI・ops互換性がtorch側にも依存するため）。
   torch系を含む更新だった場合は、torch/torchvision/torchaudioも本手順の
   「Current validated stack」（§2）の値へ揃えて戻すこと。README記載のcu128
   インデックスURLを使う点も含めて更新前と同一の手順で再導入する。
3. `pip list --format=freeze | grep -iE "ultralytics|torch|numpy|opencv|onnx"` 等で
   実際にインストールされたバージョンを確認する。
4. `backend/tests/smoke_inference_contract.py` を実行し、Layer A/B が全てPASSする
   ことを確認する。
5. Gate E（non-Test smoke）を再実行し、production経路が正常であることを確認する。

## 11. Contract version bump policy（意図的な変更の場合のみ）

将来、意図的にruntime behaviorを変える場合のみ、
`production-inference-contract-v1` → `v2` のようにversionをbumpする。

手順（`docs/PRODUCTION_INFERENCE_CONTRACT.md`のcontract version bump基準と同一。
重複を避けるためここでは要点のみ記載し、詳細は同docを参照）:

1. change reason（なぜ変えるか）
2. old/new比較（本ドキュメントのGate B/Cで検出した差分そのもの）
3. non-Test診断（Issue #25 Checkpoint 2のような定量診断）
4. 必要ならVal評価
5. user decision（ユーザーの明示承認）
6. golden更新
7. provenance記録

dependency updateを通すためだけにこの手順をショートカットしてはならない
（§12「Golden更新ルール」参照）。

## 12. Golden更新ルール

Golden更新は禁止ではないが、**contract変更の結果としてのみ**行う。
依存更新をpassさせるためだけのgolden更新は禁止。

Golden更新時は以下を必須記載する:

- old value（更新前のgolden値）
- new value（更新後の実測値）
- reason（§8のType分類のどれに該当し、なぜ変更が正当か）
- evidence（差分を検出したGate実行ログ・非Test診断結果へのリンク）
- contract version bump（§11に従い `v1 → v2` 等）

## 13. 実行用check / script

既存の仕組みで大部分をカバーできるため、重複実装は避けた。

| 目的 | コマンド |
|---|---|
| Layer A + Layer B contract確認 | `.venv\Scripts\python.exe backend\tests\smoke_inference_contract.py` |
| backend全体regression | `backend/tests/smoke_*.py` を順次実行（既存の使い捨てrunner同等の内容。固定scriptとしては本Issueで新規追加しない） |
| pre/post-upgrade snapshot記録 | `.venv\Scripts\python.exe scripts\capture_upgrade_snapshot.py`（本Issueで新規追加） |

`scripts/capture_upgrade_snapshot.py` のみ新規スクリプトとして追加した。理由:
既存test群はいずれも「pass/failの判定」が目的であり、
「更新前後の生の環境情報を人間が読める形で記録して比較する」ための出力を
持つスクリプトが存在しなかったため。read-only（production artifactやgit状態への
書き込みは一切行わない）。

## 14. 実施したrequirements変更

本Issueで実施した変更:

```diff
- ultralytics
+ ultralytics==8.4.83  # production-inference-contract-v1 の検証済み依存として固定
```

対象ファイル: `requirements-train.txt`, `backend/requirements-sam.txt`
（両ファイルとも `ultralytics` を宣言しているため、両方に適用した）。

判断根拠（§24の実施条件を満たすことを確認済み）:

- installed validated versionが `8.4.83` であることを確認済み（`scripts/capture_upgrade_snapshot.py`、
  golden fixtureの`generation_environment`と一致）
- `pip install --dry-run "ultralytics==8.4.83"` でdependency解決がconflictなく成功することを確認済み
- pin後、`backend/tests/smoke_inference_contract.py` が72 passed/0 failed/0 skippedで成功（§16）
- backend smoke suite全体でも新規regressionなし（§16）
- production smoke（Gate C相当のLayer B）正常

torch/torchvision/torchaudio/onnx/onnxruntime/onnxslim/opencv-python/numpy/Pillowは
**このIssueではpinしない**（提案のみ）。理由:

- torch/torchvision/torchaudioはCUDAビルド（`cuXXX`）選択がインストール手順（README）側の
  責務であり、`requirements-train.txt`に固定バージョンを書くと、CPU環境・異なるCUDA
  バージョン環境での`pip install -r requirements-train.txt`が失敗する可能性がある
- torchvision/torchaudioはtorch本体との組み合わせ制約が強く、torch単体の更新と
  切り離してpinすると却って組み合わせミスを誘発するリスクがある
- numpy/opencv-python/onnx/onnxruntime/onnxslimは他ライブラリの推移的要求により
  実際のインストールバージョンが決まる場合が多く、単独pinの効果が薄い

これらをpinする場合は、torch公式インデックスURLの指定方法も含めた
インストール手順全体の見直しが必要になるため、**別Issueとして提案する**
（§16「次Issue候補」参照）。

> **Issue #31追記**: torch/torchvision/torchaudioの方針は
> [`docs/TORCH_STACK_POLICY.md`](TORCH_STACK_POLICY.md)で確定した。
> `requirements-train.txt`の`torch`/`torchvision`はCPU-only環境の可搬性を保つため
> 引き続きunpinnedのまま維持し、production再現に必要な正確なバージョン・indexは
> README「GPU（NVIDIA + CUDA）で学習する場合」節の明示コマンドで管理する
> （Plan B。requirements自体へのexact pinはCUDA版wheelが通常PyPIに存在しないため
> 不採用）。`torchaudio`はコードベース内で一切使用されていないことを確認の上、
> `requirements-train.txt`から削除した。

## 15. Provenance

本ドキュメントは `docs/PRODUCTION_INFERENCE_CONTRACT.md` からリンクされる
（同docの「関連文書」セクションに追記）。情報の重複を避けるため、
contract自体の内容（pinned args・tolerance定義等）はここでは再掲せず、
同docを参照する形にしている。

## 16. Upgrade checklist

実際の更新作業で使うチェックリスト。

```text
[ ] current git SHA recorded（scripts/capture_upgrade_snapshot.py の出力に含まれる）
[ ] production model hashes verified（digital / drum 両方）
[ ] current contract test passes（更新前のbaselineとして）
[ ] dependency diff reviewed（requirements差分・pip freeze差分）
[ ] upgraded environment versions recorded（scripts/capture_upgrade_snapshot.py を更新後に再実行）
[ ] Gate A (Import/API) passes
[ ] Gate B (Layer A contract) passes
[ ] Gate C (Layer B contract) passes
[ ] Gate D (backend regression) passes（既知flakyは§9の区別手順で判定）
[ ] Gate E (non-Test smoke) passes
[ ] no Test/Hard-Val used
[ ] adoption / rollback decision recorded
```

## 17. Completion record template

Issueコメント等に貼り付ける完了記録の雛形:

```text
## Ultralytics upgrade completion record

- Upgrade対象: <package>==<old_version> -> <new_version>
- Classification: <Patch/minor | Feature-level | Model-generation | Breaking>
- Pre-upgrade snapshot: <snapshot_before.md へのパス or 貼り付け>
- Post-upgrade snapshot: <snapshot_after.md へのパス or 貼り付け>
- Gate A: <PASS/FAIL + 詳細>
- Gate B: <PASS/FAIL + 詳細>
- Gate C: <PASS/FAIL + 詳細>
- Gate D: <PASS/FAIL + 詳細、既知flakyの扱い>
- Gate E: <PASS/FAIL + 詳細>
- Contract差分: <あり/なし。ありの場合はType分類 (§8) と原因説明>
- 採否判断: <採用 / 不採用 + 理由>
- Golden更新: <あり/なし。ありの場合はold/new/reason/evidence/version bump>
- Rollback実施: <あり/なし>
```

## 18. Historical context

- Issue #24: YOLO26再学習・ONNX比較の過程で、`Model.predict()`の暗黙default
  （`rect=True`が実はpredict-mode defaultであること等）を発見
- Issue #25: `rect=True`を明示固定
- Issue #26: 残りのinference default（`max_det`/`agnostic_nms`/`augment`/`batch`/`quantize`）を固定
- Issue #27: `production-inference-contract-v1` regression test導入
  （`smoke_inference_contract.py` + golden fixture + `docs/PRODUCTION_INFERENCE_CONTRACT.md`）
- Issue #28（本ドキュメント）: dependency upgrade procedureの標準化
- Issue #29: job.jsonへproduction inference contractのobservability metadataを追加
- Issue #30: job.json書き込みraceとロック奪取raceを修正（flaky test解消）
- Issue #31: Torch stack（torch/torchvision/torchaudio）のpin方針を確定
  （[`docs/TORCH_STACK_POLICY.md`](TORCH_STACK_POLICY.md)）
- Issue #32: Gate E（non-Test smoke）を`backend/tests/smoke_production_integration.py`
  として恒久化

## 19. 関連文書

- [`docs/PRODUCTION_INFERENCE_CONTRACT.md`](PRODUCTION_INFERENCE_CONTRACT.md) — contractの正本
  （pinned args・tolerance定義・contract version bump基準）
- [`docs/YOLO26_PT_ONNX_AUDIT.md`](YOLO26_PT_ONNX_AUDIT.md) — `rect`暗黙default発見の経緯
- [`data_manifests/production_model_provenance_v1.md`](../data_manifests/production_model_provenance_v1.md)
- [`data_manifests/meter_src004_roi_v3_provenance.md`](../data_manifests/meter_src004_roi_v3_provenance.md)
