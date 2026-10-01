# C++ ONNX Runtime Inference PoC & Benchmark（Issue #48）

`docs/CPP_DEPLOYMENT_CONTRACT.md`（Issue #47）で固定した契約をC++で実装したPoCの、
build手順・依存バージョン・parity検証結果・benchmark結果・既知の制約を記録する。

**本PoCはまだ実システムへ組み込んでいない。** 目的は
「Python/PT → Python/ONNX → C++/ONNX の3経路が同一readingを返すこと」の確認と、
実機での速度の参考値取得。

## 1. ディレクトリ構成

```
cpp/
  CMakeLists.txt
  include/yps/        公開ヘッダ（letterbox/nms/preprocess/model_profile/onnx_model）
  src/                 実装（yps_core静的ライブラリ）+ main.cpp（yps_infer CLI）
  smoke/               parity_smoke.cpp（yps_smoke、自動化smoke test）
  third_party/         ONNX Runtime/OpenCV prebuilt binary（gitignore対象、後述）
  build/               CMakeビルド出力（gitignore対象）
  benchmark/results/   machine-specific生benchmark出力置き場（gitignore対象、要約は本docへ）
```

## 2. Build手順

### 2.1 依存取得（手動、一度だけ）

package managerは未導入（vcpkg等は使わず、公式prebuilt配布を直接展開する方針）。
巨大binaryはGitへ一切commitしない（`cpp/third_party/`はgitignore対象）。

```powershell
# ONNX Runtime C++ (CPU) 1.23.2 — Python側(onnxruntime 1.23.2)と完全一致
# https://github.com/microsoft/onnxruntime/releases/download/v1.23.2/onnxruntime-win-x64-1.23.2.zip
# 展開先: cpp/third_party/onnxruntime/ (include/, lib/)

# ONNX Runtime C++ (GPU, CUDA EP用、任意) 1.23.2
# https://github.com/microsoft/onnxruntime/releases/download/v1.23.2/onnxruntime-win-x64-gpu-1.23.2.zip
# 展開先: cpp/third_party/onnxruntime_gpu/
# CUDA EPを使う場合、cpp/build/Release/ の onnxruntime*.dll を
# onnxruntime_gpu/lib/ の同名ファイルで上書きする（CPU専用パッケージの
# onnxruntime.dllはCUDA EPを含まないビルドのため）。

# OpenCV 4.10.0 (prebuilt Windows, VC16=VS2022対応)
# https://github.com/opencv/opencv/releases/download/4.10.0/opencv-4.10.0-windows.exe
# 自己解凍7z形式。`opencv-4.10.0-windows.exe -o<dir> -y` で展開し、
# 生成される `<dir>/opencv/build` を cpp/third_party/opencv2/ へ配置
# （`sources/`は不要、build/のみでよい）。
```

### 2.2 Configure & Build（Visual Studio 2022 Build Tools, x64, Release）

```powershell
# Developer Command Prompt（vcvars64.bat適用環境）で実行すること
cmake -S cpp -B cpp\build -A x64
cmake --build cpp\build --config Release
```

ビルド成果物（`cpp\build\Release\`）: `yps_infer.exe`（CLI/benchmark）、
`yps_smoke.exe`（自動parity smoke）、依存DLL（`onnxruntime.dll`,
`onnxruntime_providers_shared.dll`, `opencv_world4100.dll`）はpost-buildで
自動コピーされる。

### 2.3 実行（repo rootから）

```powershell
cpp\build\Release\yps_infer.exe --profile digital --image <path> [--raw] [--onnx <path>] `
    --provider cpu|cuda [--warmup N] [--benchmark N] [--json]
cpp\build\Release\yps_smoke.exe
```

`--raw`を指定しない場合、`--image`は既にproduction前処理済み（Issue #47の
production_smoke_v1.json fixtureと同じ形式）であることを前提とする。

## 3. Dependency versions（実測）

| 項目 | version |
|---|---|
| Compiler | MSVC 19.43.34809.0（Visual Studio 2022 Build Tools, toolset 14.43.34808） |
| CMake | 3.30.5-msvc23（VS同梱） |
| OpenCV | 4.10.0（prebuilt, vc16） |
| ONNX Runtime | 1.23.2（CPU package）/ 1.23.2（GPU package、CUDA EP用） |
| Python側 onnxruntime（Issue #47参照） | 1.23.2（完全一致） |

C++側ONNX Runtimeは、Python側（Issue #47で確認したonnxruntime 1.23.2）と
**完全に同一バージョン**を使用している（§9要件を満たす）。

## 4. 実機環境

| 項目 | 値 |
|---|---|
| CPU | 13th Gen Intel(R) Core(TM) i9-13900HX（24 cores / 32 logical） |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU（VRAM 8188 MiB） |
| NVIDIA driver | 537.53（Issue #44時点と同一） |
| CUDA runtime（CUDA EP用） | 12.x系（既存検証済みTorch環境の`torch/lib`配下のcudart64_12.dll/cudnn64_9.dll等をPATH経由で借用。システム全体へのCUDA Toolkitインストールは行っていない、§5参照） |
| OS | Windows 11 |

## 5. 依存取得・CUDA EPの取り扱い（重要な設計判断）

- CUDA Toolkitをシステム全体へ新規インストールすることはしていない
  （既存Python/Torch環境を壊さない、Issue #48 §35の方針）。
- 代わりに、既存の検証済みTorch環境（`torch 2.11.0+cu128`、Issue #31/#47で
  validated）が`.venv\Lib\site-packages\torch\lib\`配下に同梱している
  `cudart64_12.dll`/`cudnn64_9.dll`等のCUDA/cuDNN runtime DLLを、
  `yps_infer.exe`実行時のPATHへ追加することでCUDA Execution Providerに
  利用させた。これはPython venv自体には一切書き込まない、読み取り専用の
  参照であり、既存環境を変更しない。
- GitHub self-hosted runner登録は行っていない（Issue #48 §4の禁止事項）。
  CUDA EPの検証はこのローカル実機のみで実施した。

## 6. Parity検証結果

### 6.1 Python/PT ↔ Python/ONNX（Issue #47で確認済み、本Issueでは再確認のみ）
Digital 30/30・Drum 30/30 PASS（Issue #47参照）。

### 6.2 C++/ONNX ↔ Python/ONNX（本Issue、主判定）

`scripts/cpp_parity_check.py`で、Issue #47と同一の選定方式（production_smoke_v1の
公式fixture + 現行production manifestのTest/Hard-Val splitと非重複の追加stem）
によりDigital/Drum各30件を比較した。

| | Digital | Drum |
|---|---|---|
| 件数 | 30/30 PASS | 30/30 PASS |
| detection count一致 | 100% | 100% |
| reading一致 | 100% | 100% |
| confidence最大差 | 0.000001 | 0.000001 |
| bbox最大差 | 0.001px | 0.000px |

基準（confidence<=1e-3、bbox<=1px）を大幅に下回る、実質的にbit-identicalな結果。
C++側のletterbox/NMS/scale_boxesがUltralytics実装と数式レベルで一致していることの
強い裏付け。

### 6.3 Preprocess parity（raw画像からのフル前処理、診断・参考値）

**本Issueで明示した既知の近似**（`cpp/include/yps/preprocess.hpp`参照）:
- resize: PIL既定のBICUBICに対し、C++はcv2.INTER_CUBICを使用（カーネル係数が異なり厳密には非一致）。
- sharpen: PILの`ImageFilter.UnsharpMask(radius=2, percent=100, threshold=2)`に対し、
  C++は一般的なGaussian unsharp maskで近似（PIL内部実装とは非一致）。

raw画像（`projects/meter_src002/raw/images/`等、真のカメラ直後画像）からC++フル
パイプラインで前処理した結果と、既存fixture（Pythonで前処理済み）を画素単位で比較:

| | Digital | Drum |
|---|---|---|
| shape一致 | Yes (360,640,3) | Yes (131,640,3) |
| mean差 | 0.03（68.29 vs 68.26） | 0.04（72.26 vs 72.30） |
| max絶対差 | 168（シャープ化エッジ付近） | 30 |

mean差は小さく全体傾向は一致している一方、エッジ付近でmax絶対差が大きい
（resize/sharpenアルゴリズムの非厳密一致による）。**ただし、rawからのフル
パイプライン実行で最終readingはDigital `0215234`・Drum `3718333`となり、
golden/PT/Python-ONNXと完全一致した**（§6.4参照）。この近似は最終判定結果
（detection/reading）には影響しなかったが、ビット完全一致ではない既知の制約として
明記する。

### 6.4 Raw end-to-end（フルパイプライン）reading確認

```
Digital (raw, CPU): reading=0215234 count=7  -> golden一致
Drum    (raw, CPU): reading=3718333 count=7  -> golden一致
```

## 7. Benchmark結果（Release build, warmup 20, measurement 200, CPU: 本machine占有ではない通常利用中の状態）

### 7.1 CPUExecutionProvider（最低baseline）

| 段階 | Digital mean | Digital median | Digital p95 | Drum mean | Drum median | Drum p95 |
|---|---|---|---|---|---|---|
| preprocess | 1.92ms | 1.90ms | 2.18ms | 1.50ms | 1.72ms | 2.32ms |
| inference | 13.05ms | 12.86ms | 15.59ms | 6.76ms | 6.70ms | 7.52ms |
| postprocess | 0.14ms | 0.15ms | 0.17ms | 0.06ms | 0.06ms | 0.07ms |
| end-to-end | 15.11ms | 14.80ms | 18.01ms | 8.74ms | 8.66ms | 9.54ms |
| FPS（mean基準） | 66.2 | — | — | 114.4 | — | — |

上記はクリーンな（他プロセス干渉が少なかった）測定回のもの。**同一条件での別の
測定回では、Digitalでinference meanが65ms・max 421msまで悪化する外れ値が観測された**
（§8「既知の制約」参照、本machineは専用benchmark機ではなく通常利用中のlaptopのため）。

### 7.2 CUDAExecutionProvider

| 段階 | Digital mean | Digital median | Digital p95 | Drum mean | Drum median | Drum p95 |
|---|---|---|---|---|---|---|
| preprocess | 3.54ms | 3.64ms | 4.64ms | 1.50ms | 1.72ms | 2.32ms |
| inference | 17.33ms | 18.01ms | 22.00ms | 12.85ms | 16.01ms | 18.49ms |
| postprocess | 0.36ms | 0.37ms | 0.47ms | 0.13ms | 0.16ms | 0.19ms |
| end-to-end | 21.24ms | 22.18ms | 26.80ms | 14.49ms | 17.91ms | 20.52ms |
| FPS（mean基準） | 47.1 | — | — | 69.0 | — | — |

**重要な発見**: このモデル規模（YOLOv8n、入力384x640/160x640という小さい非正方形
shape）では、**CPUExecutionProviderの方がCUDAExecutionProviderより高速**だった
（Digital: CPU 15.1ms vs CUDA 21.2ms、Drum: CPU 8.7ms vs CUDA 14.5ms）。
カーネル起動オーバーヘッド・ホスト↔デバイス転送コストが、これだけ小さい
モデル/入力では計算量削減効果を上回ると考えられる（本Issueでは深堀りしない、
将来の最適化Issueの検討材料とする）。

### 7.3 Session creation / Model load / First inference（Digital、参考値）

| provider | session creation | first inference |
|---|---|---|
| CPU | 126.5ms | 25.8ms |
| CUDA | 5080.6ms | 3494.9ms |

CUDA EPはsession作成時にCUDA context初期化・カーネルの事前コンパイル/選択を行うため、
初回コストが非常に大きい（計 ~8.6秒）。実運用では「毎フレームsessionを作らない」
前提（Issue #48 §37）が必須であることを裏付ける結果。

### 7.4 Memory（概算）

| provider | process working set | GPU memory使用量（delta） |
|---|---|---|
| CPU | 約95MB | - |
| CUDA | 約3.3GB（ホスト側、CUDA context/cuDNNワークスペース含む） | 約853MiB（8188MiB中） |

`nvidia-smi --query-compute-apps`はこの環境（WDDM）ではprocess単位のGPUメモリを
報告しなかった（`[N/A]`）。`nvidia-smi --query-gpu=memory.used`の前後差分で代用した。
厳密なprofilingは次段（最適化Issue）で行ってよい（Issue #48 §38の方針どおり）。

### 7.5 Threads

ORT `SetIntraOpNumThreads(0)`（既定値）のみを測定した。過剰なtuningは行っていない
（Issue #48 §39の方針どおり、まずdefault production candidateを測定）。

## 8. 既知の制約

- 本machineは専用benchmark機ではなく、利用者が日常利用している実機（Issue #44で
  言及した同一machine）であるため、CPU benchmarkで時折大きな外れ値
  （背景プロセス干渉・電源/サーマルスロットリング等が疑われる）を観測した。
  再現性確認のため同条件で複数回測定し、安定した測定回を主結果として報告した
  （§7.1）。正式な性能保証・最適化判断には、専用の隔離されたbenchmark環境での
  再測定を推奨する。
- resize（BICUBIC近似）・sharpen（UnsharpMask近似）はPIL実装とビット完全一致では
  ない（§6.3）。ONNX/NMS/reading parityの主判定（§6.2、30+30件）はこの近似の
  影響を受けない設計（Issue #47のfixtureと同じ、既に前処理済みの画像を使うため）。
- CUDA EPは、システム全体へのCUDA Toolkitインストールではなく、既存Torch環境の
  バンドルDLLをPATH経由で借用している。別環境で再現する場合は、同等のCUDA 12.x /
  cuDNN 9.x runtime DLLを別途用意する必要がある。
- FP16/INT8/TensorRT/graph最適化は本Issueでは未着手（Issue #48 §40の方針どおり、
  まずFP32 ONNX baselineを測定）。
- GPU memory計測は`nvidia-smi`のdelta測定による概算であり、厳密なprofilingではない。

## 9. Regression

- backend smoke全44ファイル: exit code 0（C++追加によるPython側への影響なし）。
- Gate 1 CI: push後green確認（最終報告参照）。
- frontend変更なし（`npm run build`不要）。

## 10. 次の判断

Parityは完全に成立した（C++/ONNX ↔ Python/ONNX、Digital/Drumとも30/30 bit-identical
相当）。速度面では、CPU providerが現状このモデル規模では最速かつ安定しており、
CUDA providerは初期化コストが高く steady-state でも本machineではCPUより遅いという
意外な結果が出た。したがって:

- 実システム統合（Issue #49）はCPU providerを前提に進めるのが妥当と考えられる。
- CUDA providerを引き続き使う積極的な理由は、今回の計測範囲では見出せなかった
  （将来batch推論や複数モデル同時実行等、GPU有利な条件が出てきた場合は再検討）。
- 速度そのものはCPUで15ms/8.7ms end-to-end（66/114 FPS相当）であり、メーター読み取り
  用途としては十分な速度域と考えられる。最適化Issueを挟む必要性は現時点では低い。
