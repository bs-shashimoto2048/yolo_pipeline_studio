# Torch Stack Policy

Issue #31で新規作成。`torch`/`torchvision`/`torchaudio`と、これらが結びつくCUDA runtime・
NVIDIA driver・GPU architecture・PyTorch wheel indexについて、production
（[`docs/PRODUCTION_INFERENCE_CONTRACT.md`](PRODUCTION_INFERENCE_CONTRACT.md)）で
検証済みの組み合わせと、その再現手順を1箇所にまとめる。

> 本ドキュメントの目的は「exact pinをすること」自体ではない。
> 「再installしても同じTorch/CUDA組合せを確実に再現できること」と
> 「CPU-onlyの一般的な開発環境の可搬性を壊さないこと」の両立が目的。

## 1. Purpose

`torch`/`torchvision`/`torchaudio`はPythonパッケージ単体の互換性だけでなく、

- Python version（ABIタグ、例: `cp310`）
- CUDA runtime（wheelにbundleされたバージョン）
- NVIDIA driver（対応するCUDA APIバージョン）
- GPU architecture（compute capability）
- PyTorch wheel index（`download.pytorch.org`の`whl/cuXXX`）

が強く結びついている。`torch==2.11.0`のようなバージョン文字列だけを
requirements.txtへ書いても、**どのindexから取得するか**を指定しない限り、
CUDA対応wheelが確実に入るとは限らない（詳細は§5「CUDA wheel入手経路」）。

## 2. Current validated stack

`scripts/capture_upgrade_snapshot.py`の実行結果（2026-09-30、Issue #31作成時点、
git HEAD `97de08393e6c8fdbf17712835a8afddb5c4df230`）:

| Component | Validated version |
|---|---|
| torch | 2.11.0+cu128 |
| torchvision | 0.26.0+cu128 |
| torchaudio | 2.11.0+cu128（**未使用**。§4参照） |
| Ultralytics | 8.4.83（`requirements-train.txt`/`backend/requirements-sam.txt`でexact pin済み、Issue #28） |
| Python | 3.10.11（wheel ABIタグ`cp310`） |
| CUDA runtime（torch wheelにbundled、`torch.version.cuda`） | 12.8 |
| NVIDIA driver | 537.53（driver自身が報告する対応CUDA API上限: 12.2。§6参照） |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU（Ada Lovelace、compute capability 8.9） |
| production-inference-contract | production-inference-contract-v1 |

## 3. Dependency inventory（現状棚卸し）

| Component | Installed | Declared（requirements-train.txt） | Install source/index | Required? |
|---|---|---|---|---|
| torch | 2.11.0+cu128 | `torch`（unpinned） | README「GPU（NVIDIA + CUDA）で学習する場合」節の明示コマンド（`--index-url https://download.pytorch.org/whl/cu128`） | **Yes** — 推論・学習の中核。ultralyticsが`torch>=1.8.0`（Windows: `torch!=2.4.0,>=1.8.0`）を要求 |
| torchvision | 0.26.0+cu128 | `torchvision`（unpinned） | 同上 | **Yes** — ultralyticsが`torchvision>=0.9.0`を要求。torchvision自体も`torch(==2.11.0)`を要求（局所バージョン`+cu128`を除いた完全一致。PEP 440のlocal version比較規則により、`==2.11.0`はlocal segmentを持たない候補側の"public version"のみと比較されるため`2.11.0+cu128`を満たす） |
| torchaudio | 2.11.0+cu128 | `torchaudio`（unpinned） | 同上（同一コマンドに含まれる） | **No** — コードベース内で`import torchaudio`は一切なく（`backend/`・`scripts/`を全探索して0件）、ultralyticsのRequires-Distにも含まれない（`torch`/`torchvision`のみ要求）。従来の"torch triplet"導入コマンドの慣例でインストールされていただけ |
| ultralytics | 8.4.83 | `==8.4.83`（Issue #28でexact pin） | 通常PyPI（`requirements-train.txt`経由） | **Yes** |

`import torch`自体も、アプリケーションコードでは`backend/`配下で一切使われていない
（`backend/workers/inference_contract.py`が観測用に使うのみ）。すべての推論・学習は
`ultralytics.YOLO`経由であり、torch/torchvisionはultralyticsの推移的依存として
間接的に必要という位置づけ。

## 4. torchaudioについて

**本Issueの結論: torchaudioはrequirements-train.txtから削除する**（§10参照）。

- コードベース内で未使用（grep 0件）
- ultralytics 8.4.83のメタデータにも依存として現れない
- torchaudio自体のパッケージメタデータにも`Requires-Dist`が1件もない（torchとの
  結合はビルド時のみで、pipのdependency解決には現れない）

「torch/torchvision/torchaudioを3点セットで入れる」という一般的な慣習に従っていた
だけであり、本プロジェクトでの実利用実績はない。削除しても機能への影響はない
（§4「使っていないdependencyを慣例だけでpinしない」の判断基準に基づく）。

## 5. CUDA wheel入手経路

torch/torchvisionの`+cu128`ローカルバージョン付きwheelは、**通常のPyPIには存在しない**。
PyTorch公式が別立てで運用する専用index（`https://download.pytorch.org/whl/cu128`）
にのみ存在する。したがって:

```bash
pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 --index-url https://download.pytorch.org/whl/cu128
```

のように**明示的にindexを指定した単独コマンド**でのみ、確実にCUDA版が入る。

### なぜrequirements-train.txtへ直接exact pin（`torch==2.11.0+cu128`）しないか（Plan A不採用の理由）

`requirements-train.txt`自体は特定indexを強制しない（`pip install -r requirements-train.txt`は
既定でPyPIのみを見る）。もし`torch==2.11.0+cu128`をそのままrequirements-train.txtへ書くと:

- GPU環境: `--extra-index-url https://download.pytorch.org/whl/cu128`を追加で
  指定しない限り、PyPI側に存在しないバージョン指定として**解決自体が失敗する**
- CPU-only環境（GPU無しPC）: そもそもこのバージョン文字列に一致するwheelがPyPIに
  存在しないため、`pip install -r requirements-train.txt`単体が失敗し、
  軽量な開発（アノテーション等、学習を伴わない作業）の可搬性を損なう

このため、**requirements-train.txtの`torch`/`torchvision`は汎用的にunpinnedのまま
維持し**、production再現に必要な正確なバージョン・indexの組み合わせは、本ドキュメントと
READMEの明示コマンドという形で分離して管理する（Plan B。詳細は§7参照）。

## 6. CUDA用語の区別

以下は別々の概念であり、混同しない。

| 用語 | 意味 | 現在の値 |
|---|---|---|
| NVIDIA driver version | GPUドライバ自体のバージョン | 537.53 |
| driverが報告する対応CUDA API上限（`nvidia-smi`の"CUDA Version"欄） | そのdriverが対応する**最大**のCUDA APIバージョン（システムにCUDA toolkitがinstallされているという意味ではない） | 12.2 |
| `torch.version.cuda` | torch wheelに**bundleされた**CUDA runtimeのバージョン（wheel内に静的/動的リンクされたライブラリ由来、システムCUDA toolkitとは独立） | 12.8 |
| system CUDA toolkit（`nvcc --version`） | CUDAカーネルのソースビルドに必要なtoolkit（本プロジェクトでは不要。prebuilt wheelのみ使用） | 未インストール（不要） |

**driverの対応上限(12.2) < wheelがbundleするruntime(12.8)という一見の不整合は、
NVIDIAのCUDA minor version互換性（同一メジャーバージョン12.x内での前方互換）により
正常に動作する**（本機のRTX 4070 Laptop GPU、compute capability 8.9で実測確認済み:
`torch.cuda.is_available()==True`、GPU名も正しく認識）。README既存の脚注
「ドライバがCUDA 12.2対応でもcu128/cu126が動作する場合があります」と整合する。

特定のdriver versionを本ドキュメントで必須要件として固定することはしない
（環境依存性が高く、推測でdriver要件を課すと将来の環境で誤ってブロックし得るため）。

## 7. 採用したpin戦略（Plan比較）

### Plan A — requirements exact pin（不採用）
`requirements-train.txt`へ`torch==2.11.0+cu128`等を直接書く。
理由: §5の通り、単体では解決不能・CPU-only環境の可搬性を損なう。

### Plan B — documented install command（**採用**）
`requirements-train.txt`の`torch`/`torchvision`は汎用的にunpinnedのまま維持し、
production再現に必要な正確なバージョン・indexは、README（実行手順）と本ドキュメント
（根拠・詳細）に明記する。既存のREADME「GPU（NVIDIA + CUDA）で学習する場合」節が
既にこの形（Torch stackを先に明示installしてからrequirements-train.txtを実行する
2段階手順）を採用しており、本Issueではその**バージョン文字列を正確な検証済み値へ更新**
するだけで、既存の運用パターンと自然に整合する。

### Plan C — 専用constraints file（不採用）
`constraints-production.txt`のような新規pip機構を導入する案。
理由: 本repoに前例のない新しい仕組みを追加することになり、`--extra-index-url`の
明示が結局必要な点はPlan Bと変わらない。既存のdocs集約パターン
（`docs/PRODUCTION_INFERENCE_CONTRACT.md`等）で十分に表現できるため、
追加のツール・ファイル形式を持ち込まない。

## 8. 公式インストール手順（正本）

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements-train.txt
```

**順序が重要**（§13「インストール順序検証」）: 先にTorch stackを検証済みバージョンで
明示installし、その後に`requirements-train.txt`（`ultralytics==8.4.83`等）をinstallする。
`ultralytics`は`torch>=1.8.0`/`torchvision>=0.9.0`しか要求しないため、既にこの手順で
入れた検証済みバージョンで条件を満たし、pipが別バージョンへ置き換えることはない
（`pip install -U ultralytics`のような無条件更新コマンドは使わない。旧README記載の
`pip install -U ultralytics`は、Issue #28のexact pinを意図せず上書きし得るため、
本Issueで`pip install -r requirements-train.txt`へ修正した）。

導入確認:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

期待値: `2.11.0+cu128 12.8 True`

## 9. Fresh install検証（Issue #31実施）

破棄可能な一時venv（production venvとは別、`%TEMP%`直下の短いパスに作成。深いパスだと
Windowsの`MAX_PATH`制限でensurepipが失敗したため、短いパスへ作り直した）で、
上記コマンドの再現性を検証し、検証後にvenv自体を削除した。

1. `pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 --index-url https://download.pytorch.org/whl/cu128`
   → **成功**（torch本体 2753.2MB・torchvision 9.0MBのwheelを取得。依存関係の衝突なし）
2. `python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
   → `2.11.0+cu128 12.8 True NVIDIA GeForce RTX 4070 Laptop GPU`（§8の期待値と完全一致）
3. `pip install ultralytics==8.4.83`
   → **成功**。インストールされたのは`ultralytics`本体とその他の軽量依存
   （`matplotlib`/`opencv-python`/`pyyaml`等）のみで、**torch/torchvisionは
   一切再インストールされなかった**（「Successfully installed」一覧にtorch/torchvisionが
   含まれない＝既存の検証済みバージョンで`torch>=1.8.0`/`torchvision>=0.9.0`の条件を
   満たしたため上書きされなかったことを確認）
4. 再度`python -c "import torch, torchvision; ..."` → `torch: 2.11.0+cu128 / torchvision:
   0.26.0+cu128`（ultralytics install後も変化なし）
5. `from ultralytics import YOLO; import ultralytics; print(ultralytics.__version__)`
   → `8.4.83`（import成功）

以上により、§8「公式インストール手順」の順序（Torch stack先install →
`requirements-train.txt`相当のultralytics install）で、検証済みバージョンが
確実に再現され、かつultralytics installによって上書きされないことを実機で確認した。

## 10. Rollback procedure

Torch stack更新に失敗した場合:

1. `pip uninstall torch torchvision torchaudio -y`
2. 本ドキュメント§8の検証済みバージョンで再インストール:
   ```powershell
   pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 --index-url https://download.pytorch.org/whl/cu128
   ```
3. `python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"`
   で§8の期待値と一致することを確認
4. `backend/tests/smoke_inference_contract.py`を実行し、Layer A/Bが全てPASSすることを確認
5. backend smoke suite全体を実行し、新規regressionがないことを確認

## 11. Known limitations

- torch/torchvisionのCUDA版wheelはPyTorch公式indexにのみ存在し、requirements.txt単体
  では表現できない（§5）。将来的にPyPI本体がCUDA版wheelを標準提供するようになった場合、
  本方針の見直しが可能
- NVIDIA driverの具体的な最低要件バージョンは、GPU世代・CUDAメジャーバージョンの
  組み合わせに強く依存するため、本ドキュメントでは固定しない（§6）
- torchaudioを削除したことで、将来torchaudioの機能（音声処理）が必要になった場合は
  再度individual installが必要（現時点でそのような要件は存在しない）

## 12. 関連文書

- [`docs/PRODUCTION_INFERENCE_CONTRACT.md`](PRODUCTION_INFERENCE_CONTRACT.md) — production
  inference contractの正本（本ドキュメントが対象とするTorch/CUDAはこのcontractが
  実行される土台）
- [`docs/ULTRALYTICS_UPGRADE_PROCEDURE.md`](ULTRALYTICS_UPGRADE_PROCEDURE.md) — Ultralytics
  依存更新の標準手順。Torch stack変更時に必要なgateも同docへ追記（Issue #31）
- [`data_manifests/production_model_provenance_v1.md`](../data_manifests/production_model_provenance_v1.md)
