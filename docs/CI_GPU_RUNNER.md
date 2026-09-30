# CI / GPU Runner 設計（Issue #38）

本ドキュメントは、production integration smoke（Layer C）を含むbackend smoke suiteを、
人手のローカルGPU環境実行だけでなく、将来的にCI上でも安全・再現可能に実行できるようにする
ための設計を記録する。**GPU CIを無理に本番導入すること自体を目的にしない。** 実現可能性・
コスト・private artifact取扱いを踏まえ、安全に運用できる方式を確定することが目的である。

本Issue時点では、`.github/workflows/`は存在せず、GitHub Actionsは未導入だった
（`allowed_actions: all`だが実際のworkflowファイルは0件）。また本リポジトリは**public repo**
であることを確認した。この事実は、self-hosted runnerを使う場合のtrigger設計に直接影響する
（§5参照）。

---

## 1. Purpose

- `smoke_inference_contract.py` / `smoke_inference_observability.py` /
  `smoke_production_integration.py` / backend smoke suite 39ファイルを、CI上でも
  再現可能な形で実行できるようにする。
- production weight（`*.pt`）・fixture画像を一切Gitへcommitしない前提を維持したまま、
  GPU実推論を伴うLayer B/Layer Cを安全に実行できる方式を確立する。
- CPU CIとGPU CIを明確に分離し、コストと安全性のバランスを取る。

## 2. CPU/GPU gate 設計

### Gate 1 — CPU/default（`.github/workflows/backend-smoke.yml`）

- **対象**: import/syntax、Layer A（contract定数のソースレベル検査）、
  observability schema、production artifact非依存のunit/smokeロジック全般。
- **実行環境**: GitHub-hosted `ubuntu-latest`（GPUなし、self-hosted不要）。
- **依存**: `requirements.txt`（軽量） + `onnx onnxruntime onnxslim`
  （下記§4の依存棚卸しの通り、`backend/app/routers/model_export.py`が
  `model_export_service.py`経由で`onnxruntime`をモジュールレベルでimportしており、
  `app.main`のFastAPI appオブジェクト構築自体にonnxruntimeが必要なため。torch/ultralytics/
  cv2はapp起動には不要であることをgrep監査で確認済み）。
- **production weight/fixture**: 存在しない（`projects/`はgitignore対象のため、CI
  checkoutには含まれない）。既存のSKIP設計により、Layer B/Layer Cの該当部分は
  自動的にSKIPされ、それ以外はPASSする。
- **trigger**: push（全ブランチ）・pull_request・workflow_dispatch。GitHub-hosted runnerの
  みを使うため、fork PRからの実行も安全（self-hosted productionリソースに一切触れない）。

### Gate 2 — GPU production（`.github/workflows/production-gpu-smoke.yml`）

- **対象**: Layer B（golden fixture比較）、Layer C（production integration smoke、
  real weight・real YOLO推論・real worker subprocess）、production artifact hash検証。
- **実行環境**: self-hosted GPU runner（§5〜§8参照）。**現時点では実runnerは未登録**
  （後述）。
- **trigger**: 現時点では`workflow_dispatch`のみ（§12/§37参照。public repoでの
  self-hosted runner使用のため、pull_request/pull_request_targetは絶対に使わない）。
- **必須実行mode**: `YTS_PRODUCTION_SMOKE_REQUIRED=1`を設定し、production artifact
  欠落時にSKIPではなくFAILさせる（silent success防止、§9参照）。

両者は同一workflowへ統合しない。Gate 1は毎push/PRで安価に実行でき、Gate 2は高コストな
GPU jobとして必要な時のみ手動実行する。

## 3. 現在のCI監査結果

- `.github/workflows/`: 存在しない（本Issueで初めて作成）。
- GitHub Actions: `allowed_actions: all`、`has_actions: true`だが実workflowは0件。
- self-hosted runner: 登録なし。
- リポジトリ可視性: **public**（`visibility: public`, `private: false`）。
- cache/Python setup: 未設定（本Issueで新規設計）。
- OS前提: production運用はWindows + NVIDIA GPU（Issue #30/#33でWindows固有の
  multiprocessing spawn・file locking・PermissionErrorが実際に問題になった実績あり）。

## 4. Production smoke 依存棚卸し

`smoke_production_integration.py`（Layer C）が実際に必要とするもの:

| 依存 | 必須性 | 備考 |
|---|---|---|
| Python 3.10.11 | 必須 | Issue #31で検証済みバージョン |
| FastAPI/uvicorn/pydantic等（`requirements.txt`） | 必須 | app boot自体に必要 |
| **onnxruntime**（+onnx/onnxslim） | **app boot自体に必要** | `model_export_service.py`の
  モジュールレベルimportのため、`from app.main import app`の時点で必要。CPU版で可、GPU不要 |
| Ultralytics 8.4.83 | Layer B/Cのみ | `production-inference-contract-v1`の検証済み依存 |
| Torch stack (2.11.0+cu128 / torchvision 0.26.0+cu128) | Layer B/Cのみ | Issue #31 pin方針 |
| production weight（`*.pt`） | Layer B/Cのみ | Git管理外、runner local配置が必要（§5） |
| Train/non-Test fixture image | Layer B/Cのみ | `production_smoke_v1.json`が参照するstem、Git管理外 |
| selected_model.json | Layer B/Cのみ | production側と同一、read-onlyでtemp projectへコピー利用 |
| GPU（CUDA） | 推奨だがcode上は必須ではない | CPU fallbackも技術的には動くが、production parityの
  観点からGPU runnerを推奨（§14/§15） |
| OS | Windows推奨 | production parity（multiprocessing/file locking挙動） |

grep監査の結果、`backend/`配下のいずれのrouter/serviceも`torch`/`ultralytics`/`cv2`を
モジュールレベルではimportしていない（`model_export_service.py`内の
`from ultralytics import YOLO`はexport済みサンプルコードの文字列テンプレート内であり、
実行時importではない）。したがってGate 1はonnxruntime系のみを追加すれば動作する。

## 5. Weight取扱い（比較・決定）

| 方式 | Security | Reproducibility | Setup cost | Rotation | Hash検証 |
|---|---|---|---|---|---|
| **A. self-hosted runner上に既存weightを配置** | ◎（外部露出なし、runner local読み取り専用） | ○（runnerの状態に依存するが、hash検証で担保） | 低（既存environment/production dirをread-only参照するだけ） | 手動（promotion時にrunner側もコピー更新） | 容易（既存smoke testのSHA256比較をそのまま利用） |
| B. GitHub Actions artifact / Release asset | △（Release assetは公開repoでは誰でもDL可能になりうる。private artifactでも保持期間・アクセス制御の追加設計が必要） | ○ | 中（upload/download workflow追加） | Release/artifact差し替えの度に運用が必要 | 可能だが二重管理 | 
| C. 社内storageから取得 | ○（アクセス制御は社内storage側に依存） | ○ | 高（外部storage連携・認証情報管理が新規に必要） | storage側で一元管理可 | 可能 |
| D. 手動配置済みpersistent runner | ◎ | ○ | 最低（Aとほぼ同じ、永続runnerに一度配置すれば良い） | 手動 | 容易 |

**採用: A（実質的にDと同じ運用になる永続self-hosted runner）。** 理由:

- production weightをGitHub側（Actions artifact・Release asset含む）へ一切アップロード
  しない。public repoである本リポジトリでは、Release assetは実質公開されるため特に不適。
- 既存のproduction環境（Windows + NVIDIA GPU + Issue #31検証済みTorch stack）に最も近い
  形で再現できる。
- 追加のsecrets/外部storage連携が不要（setup costが最小）。
- 既存smoke test群がすでにSHA256 hash比較でweight一致を検証する設計になっており
  （`smoke_inference_contract.py`・`smoke_production_integration.py`）、そのまま流用できる。

## 6. Fixture画像の取扱い

production smoke用fixture画像（`production_smoke_v1.json`が参照する2 stem/project）も、
Git管理しない現在方針を維持する。

- **runner-local fixture（採用）**: weightと同じ理由で、runnerのローカルディスクへ
  読み取り専用で配置する。既存のIssue #25/#26/#27/#32で選定済みのstemをそのまま使う。
- secure artifact: 前述の理由でGitHub側への追加アップロードは避ける。
- synthetic replacement: 却下。Layer Cは「real weight × real preprocessing × real
  worker」の統合動作検証が目的であり、synthetic画像では末尾桁の実際の視覚的挙動
  （Issue #34〜#37で扱った rotation/transition artifact）を再現できず、Layer Cの代替に
  ならない。

## 7. 第一候補の確定

**self-hosted GPU runner（Windows + NVIDIA GPU） + runner-local read-only production
fixtures** を第一候補として採用する。理由は§5と同じ（weightをGitHubへ出さない、
production環境に近い、fixture privacyを維持）。社内運用条件が変わった場合は再検討可能。

## 8. Runner isolation

- runner専用のuser/serviceアカウントで実行し、開発者の日常作業アカウントと分離する
  （物理的に同一マシンであっても、runnerが動作するプロセス・ディレクトリは分離する）。
- production app（実際に稼働しているFastAPI/uvicorn等）とは別のディレクトリ・別の
  `projects/`コピーを参照する（本物のjob historyに一切触れない設計は既存smoke testが
  temp project + tempdirで既に担保している。runner isolationはこれをさらに一段階、
  OSレベルの権限で補強するもの）。
- weight/fixtureディレクトリはread-only権限でmountまたは配置する。
- job出力（一時ファイル）はrunnerのtemp dirへ書き、job終了時にcleanupする
  （既存smoke testが`tempfile.mkdtemp`を使う設計を踏襲）。

## 9. Security

CI logへ出さないもの（既存smoke testの出力を確認し、以下がログに出ないことをコード
レベルで確認済み）:

- camera credential（video smokeはmock camera使用、実credential不要）
- internal URL / absolute private network path
- user-specific secrets
- raw production image（fixtureのstem名のみログに出る。画像バイト列は出力しない）
- model weight binary（SHA256のみログに出す）

## 10. Hash verification

- Digital: `630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61`
  （`production_combined_v2_5z:best`、既存smoke testでハードコード済み）。
- Drum: 現行production `candidate_roi_v4_hardneg:best` の
  `cadd1d7df52b94004331be2d3c79c7dbc306c93802b3f5c3d455f2121061f595`
  （Issue #36で`backend/tests/fixtures/production_smoke_v1.json`へ反映済み。
  `scripts/capture_upgrade_snapshot.py`は本Issueで`selected_model.json`の`model_path`から
  動的解決するよう修正し、以後のmodel promotionのたびに手動更新不要にした）。
- runner上のweightがこのhashと異なればFAIL（既存`check()`ロジックがそのまま担保）。

## 11. Trigger（決定）

| workflow | trigger | 理由 |
|---|---|---|
| Gate 1 (`backend-smoke.yml`) | push, pull_request, workflow_dispatch | GitHub-hosted runnerのみ使用、fork PRでも安全 |
| Gate 2 (`production-gpu-smoke.yml`) | **workflow_dispatchのみ（現時点）** | public repo + self-hosted runnerのため、pull_request/pull_request_targetは絶対に使わない（§37）。安定性確認後、main push + path filterへの拡張を検討（§12/§39） |

毎commit必須にはしない（GPU jobは高コストなため）。

## 12. Path filtering（将来のmain push拡張時の候補）

```text
backend/workers/**
backend/app/services/**
backend/tests/smoke_inference_contract.py
backend/tests/smoke_production_integration.py
backend/tests/fixtures/**
data_manifests/**
requirements*.txt
docs/TORCH_STACK_POLICY.md
```

現時点ではworkflow_dispatch中心のため未適用。path filterが複雑になりすぎる場合は
manual dispatch優先の方針を維持する。

## 13. OS（Windows優先の判断）

production運用がWindows中心であり、Issue #30/#33でWindows固有のmultiprocessing spawn・
file locking・PermissionErrorが実際に重要な問題として発見・修正された実績があるため、
**Windows self-hosted GPU runnerを第一候補とする**（Linux GPU runnerでgreenでも
Windows固有raceの保証にはならないため）。

## 14. Torch stack

Issue #31で検証済みの以下を、GPU runnerでも同一条件で再現する:

```text
torch 2.11.0+cu128
torchvision 0.26.0+cu128
Ultralytics 8.4.83
Python 3.10.11
```

Gate 2 workflowはrunner側に事前構築済みの永続venv（`docs/TORCH_STACK_POLICY.md`の
手順で構築）を前提とし、job実行のたびにtorch/CUDA wheelを再インストールしない
（起動コスト削減、pin方針の意図しない上書き防止）。

## 15. Environment snapshot

`scripts/capture_upgrade_snapshot.py`をGate 2 job内で実行し、Python/Ultralytics/Torch/
CUDA runtime/driver/GPU nameをjob logへ出力する（秘密情報は出力しない設計を確認済み）。
新規重複scriptは作成しない（§18の指示通り）。本Issueで、drum production weightの参照を
`selected_model.json`から動的解決するよう修正し、今後のmodel promotionでの手動更新を
不要にした。

## 16. Reusable script

`scripts/capture_upgrade_snapshot.py`を再利用（上記§15）。

## 17. CI専用env flag

`YTS_PRODUCTION_SMOKE_REQUIRED=1` を導入した（`smoke_inference_contract.py`・
`smoke_production_integration.py`の`skip()`関数を修正）。

- 未設定（通常local実行）: 従来通りSKIP。
- `1`に設定（Gate 2 workflow内）: production artifact欠落時にFAILする
  （silent success防止、§21/§22要件）。

## 18. Production selected_model

CIはproduction `selected_model.json`を書き換えない。既存smoke testのtemp project
copy方式（`shutil.copy2` + tempdir）をそのまま維持する。

## 19. Job output

- 保存可: environment snapshot、test pass/fail summary、実行時間。
- 保存禁止: raw production image、camera frame、model weight binary
  （既存smoke testの出力にこれらが含まれないことを確認済み）。

## 20. Failure diagnosis

Gate 2 job失敗時に判別可能にする項目（既存smoke testの`check()`メッセージが
すでにこれを満たしている）:

- model hash mismatch（`weight SHA256 matches ...`のFAILメッセージ）
- fixture missing（`YTS_PRODUCTION_SMOKE_REQUIRED=1`時はFAIL、メッセージに path含む）
- CUDA unavailable（`resolved_args.runtime_device populated`等のcheckで顕在化）
- contract mismatch（`contract_version ==`等のcheck）
- prediction mismatch（`reading == golden`等のcheck）
- subprocess failure（`job completed`のcheckが失敗として顕在化）

## 21. Required check化

現時点ではbranch protection側のrequired check化はしない（§27方針通り、まず安定性確認）。

## 22. Performance

Gate 2 job全体のruntimeは、runner起動/setup時間とtest本体時間を分離して記録する
（§28）。ローカル実測（本Issueで計測、GPU: NVIDIA GeForce RTX 4070 Laptop GPU）:
Layer C(`smoke_production_integration.py`)単体で**41.8秒**、backend全39ファイルsuiteは
数分程度。runner起動/setup自体の時間は、実runner未登録のため未計測（§29のrepeat
stability確認と合わせて runner稼働開始後に記録する）。

## 23. Repeat stability

実runner登録後、5〜10 runsで0 failureを確認すること（未実施、次のアクティベーション
手順の一部とする）。

## 24. Secrets

現行設計では、production weight/fixtureをrunnerローカルへ直接配置するため、
**GitHub Secretsは不要**（Option A採用の理由の一つ）。将来Option B/Cへ変更する場合、
使用するsecret名（値は記載しない）をここに追記する。現時点では該当なし。

## 25. Self-hosted label（採用時の想定）

```text
self-hosted, windows, x64, gpu, yolo-production
```

実環境のラベルに合わせて調整する。

## 26. Runner permissions

GitHub Actions token permissionsは両workflowとも`contents: read`のみとする
（不要なwrite権限を与えない）。

## 27. Third-party PR対策

本リポジトリはpublic repoであるため、Gate 2（self-hosted GPU runner）は
**pull_request/pull_request_targetを一切trigger条件に含めない**。fork PRのコードが
self-hosted production runnerで自動実行されることは絶対に避ける。Gate 1のみ
pull_requestを許可するが、こちらはGitHub-hosted runnerでありproduction resourceに
一切アクセスしないため安全。

## 28. Manual dispatch優先

最初は`workflow_dispatch`中心とする。安定後、main push + path filter（§12）への
拡張を検討する。

## 29. Provenance/model promotion連携（将来）

将来のmodel promotion Issueでは、Gate 2 green（production GPU smoke）をpromotion gateの
一つとして組み込めるよう、本設計のjob出力（pass/fail summary）を将来的にIssueコメント等
から参照可能な形にすることを想定する（本Issueでは未実装、次Issue候補）。

## 30. GPU unavailable時の現状（アクティベーション手順）

現時点でself-hosted GPU runnerは未登録。以下がworkflow skeleton稼働開始のための
今後の手順:

1. Windows + NVIDIA GPUマシンにGitHub Actions self-hosted runnerエージェントを
   インストールし、repo adminがrunner登録tokenを発行して登録する。
2. runnerに`self-hosted, windows, x64, gpu, yolo-production`ラベルを付与する。
3. runner上に、Issue #31検証済みTorch stack（`docs/TORCH_STACK_POLICY.md`手順）で
   永続venvを構築する。
4. runner上の`projects/`へ、production weight（digital/drum）・fixture画像
   （`production_smoke_v1.json`参照stem）を手動で読み取り専用配置する。
5. GitHub Actions画面から`production-gpu-smoke.yml`を`workflow_dispatch`で手動実行し、
   green化を確認する。
6. §23の反復安定性確認（5〜10 runs、0 failure）を行う。
7. 安定後、main push + path filterへのtrigger拡張を検討する（§12/§28）。

これらの手順自体は本Issueの範囲内で文書化したが、実際のrunnerマシンの用意・
登録・永続weight配置は、リポジトリ管理者による実インフラ操作が必要なため、
本Issueの完了条件からは除外する（Issue #38 §20の方針に基づく）。
