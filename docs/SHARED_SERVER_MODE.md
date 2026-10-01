# Shared Server Mode（複数ユーザー共有 + FIFO GPU学習キュー）

Issue #49。このPCをLAN内の学習サーバーとして使い、複数ユーザーが同時にWeb UIを
利用しながら、GPU（RTX 4070 Laptop想定、1台）での学習だけは先着順(FIFO)で1件ずつ
安全に処理できるようにする機能。

**既定では無効（opt-in）。** 有効化しない限り、既存の1ユーザー利用の挙動は一切
変わらない。

## 有効化方法

```powershell
$env:YTS_SHARED_SERVER_MODE = "true"
uvicorn app.main:app --app-dir backend --port 8000
```

```powershell
cd frontend
npm run dev
```

`frontend/vite.config.ts` の開発サーバーは元から `host: true`（全インターフェース
でリスン）であり、既にLAN上の他端末からアクセス可能（Issue #12）。`/api` への
リクエストはVite dev serverが同一マシンの`http://localhost:8000`へプロキシする
ため、**backend自体（uvicorn）はLAN向けに`--host 0.0.0.0`等へ変更する必要がない**
（backendはこのPCのループバックのみで待ち受けたままでよい）。

LAN内の他端末からは、サーバーPCのIPアドレスを使って
`http://<サーバーPCのIP>:5173` へアクセスする。ブラウザはVite dev serverの
オリジンとしか通信しないため、backend側のCORS設定（`cors_origins`）は
localhost/127.0.0.1のままで変更不要。

## User identity（認証ではない）

Phase 1ではAD/Microsoft Entra ID/LDAP/SSO等のenterprise authenticationは導入
していない。初回アクセス時に名前入力ダイアログが表示され、入力した表示名は
`localStorage`（`yts_user_id`: ランダムUUID、`yts_display_name`: 入力した名前）
に保存される。これは**ジョブ/プロジェクトの所有者表示用であり、ログイン認証では
ない**。ブラウザを閉じても同じidentityとして復帰する。

- `crypto.randomUUID()`はsecure context（https/localhost）でのみ利用可能で、
  LAN経由のhttpアクセスでは使えないため、`frontend/src/api/identity.ts`は
  非secure context向けのフォールバック生成ロジックを持つ。
- user_id/display_nameはHTTPヘッダ（`X-YTS-User-Id` / `X-YTS-Display-Name`）で
  backendへ送られる。display_nameはASCII以外を含み得るため
  `encodeURIComponent()`で符号化して送る（backend側で`unquote()`する、
  `backend/app/core/identity.py`）。
- 将来enterprise authenticationへ差し替える場合は`get_current_user()`
  （`backend/app/core/identity.py`）の中身だけを置き換えればよい設計。

**Security boundary: trusted LAN use onlyが前提。** なりすまし防止の仕組みは
無い（誰でも任意のuser_idを名乗れる）。社内LAN等の信頼できるネットワークでの
利用に限定すること。インターネットへの公開は想定していない。

## Project ownership

プロジェクト作成時の`owner_user_id`/`owner_display_name`/`created_at`を
`project.yaml`に保持する。shared server mode導入前に作成された既存プロジェクト
は`owner_user_id: null`（legacy扱い）のまま。プロジェクト一覧画面では
shared server mode時のみ「作成者」列が表示され、自分のプロジェクトには
「自分」バッジが付く。

同名プロジェクトの作成競合は、`project_dir(name).mkdir(exist_ok=False)`に
よる原子的な排他生成で防いでいる（Issue #49 §44）。2ユーザーがほぼ同時に
同じ名前で作成しようとした場合、後勝ちで上書きすることはなく、片方が
「作成者: ○○」付きの409エラーになる。

プロジェクトの安定IDは導入していない（引き続き名前＝ディレクトリ名）。
`backend/app/core/paths.py`の約30個のヘルパー関数すべてが`project_dir(name)`
に依存しており、ID導入は大規模なmigrationになるため見送った。上記の原子的
排他生成だけで実用上十分な衝突安全性を確保できていると判断している。

## FIFO学習キュー + single GPU lock

- `backend/app/services/training_queue_service.py`がキュー状態を
  `projects_root/.shared_server/training_queue.json`へ永続化する
  （`.`始まりのためプロジェクト名とは絶対に衝突しない予約ディレクトリ）。
- GPU学習の同時実行数は常に1。空いていれば即起動、埋まっていればFIFOで
  キューへ積む。
- 学習ジョブ投入は`prepare_job()`（検証＋job.json作成）と`launch_job()`
  （実際のPopen起動）に分離されており、キュー待機中のジョブも
  job.json（`status=queued`）としてAPI/UIから見える。
- キュー内の順序変更や昇格は、既存の`_acquire_file_lock`/`_release_file_lock`
  （Issue #30で確立した排他生成方式ロックファイル）で保護されている。
- 実行中ジョブの終了検知は、backend起動中に動く軽量なbackground task
  （3秒間隔、shared server mode時のみ起動）が行う。local modeではこの
  taskそのものを一切生成しないため、追加の負荷は発生しない。

### Single-process backend前提

本実装のロック機構はファイルロック方式のため**複数プロセス間でも安全**だが、
キュー状態のbackground task（昇格処理）は現状`uvicorn`を単一プロセス
（`--workers`未指定、または1）で動かす前提で設計している。将来`uvicorn
--workers N`等でマルチプロセス運用する場合は、background taskの重複起動を
防ぐ追加の仕組みが必要になる（Issue #49 §75/§76）。

## Restart recovery

backend起動時（shared server mode時のみ）、`training_queue_service.recover()`
が呼ばれる:

- **queued**（まだ起動していない）ジョブ: queue.json自体が永続化されている
  ため、特別な復元処理なしでそのまま維持される。
- **running**だったジョブ: 記録済みPIDの生存を確認する。
  - PIDが生きていれば何もしない（backendだけ再起動し、子プロセスは
    生き続けているケース。Windowsでは親プロセス終了時に子プロセスが
    自動終了しない）。
  - PIDが消えていれば、**同じoutput directoryへは絶対に自動再開しない**。
    `status=failed`、メッセージに中断された旨を明示するのみ。ユーザーが
    内容を確認した上で必要なら手動で再投入する。

ホストPCの強制シャットダウン自体をバグの原因と決めつけず、再起動後に
production artifact（SHA256等）・job.json・queue.jsonが壊れていないかを
確認してから復旧する、という方針（Issue #47/#48/#37と同じ考え方）。

## Browser close

ジョブのlifecycleはbackend側（OSプロセス + job.json/queue.json）だけに
依存し、フロントエンドには一切依存しない。待機中/実行中にブラウザを
閉じても、学習は継続し、キューも進行する。

## Limits（config化）

| 設定 | 既定値 | 環境変数 |
|---|---|---|
| 1ユーザーあたり同時投入・待機上限 | 2 | `YTS_MAX_QUEUED_JOBS_PER_USER` |
| キュー全体の待機上限 | 20 | `YTS_MAX_QUEUED_JOBS_GLOBAL` |

上限超過時は409 Conflictを返す。

## Cancel

- **queued中**のジョブ: 即座にキューから除去され、`status=cancelled`になる。
- **running中**のジョブ: Ultralyticsの`model.train()`はブロッキング呼び出しで
  協調的停止の仕組みを持たないため、`taskkill /PID <pid> /T /F`
  （Windows、子プロセスツリーごと終了）で強制終了し、`status=cancelled`に
  した上で次のqueued jobを自動的に昇格させる。
- 所有者チェックは**セキュリティ境界ではなくUX境界**（§33）:
  他ユーザーのjobをcancelしようとすると403になるが、これはなりすまし
  防止ではなく誤操作防止が目的。

cancel失敗時にcpp_onnx等のengine選択が黙って変わることはない（学習
engineの自動fallbackという概念自体がこの機能には存在しない）。

## GPU/CPU使用率

- backend本体（training_service.py/training_queue_service.py）はtorch等の
  重量依存をimportしない（既存の軽量/重量依存分離を維持）。学習開始前の
  資源チェックは空きディスク容量（stdlib `shutil.disk_usage`のみ）に留め、
  GPU空き容量そのものは確認していない。
- shared server modeのbackground taskは3秒間隔のポーリングのみで、
  実行中ジョブが無ければ即returnする軽量な作りのため、アイドル時に
  追加のCPU/GPU負荷は発生しない。
- GPU学習そのものは常に同時1件のみ。

## Windows sleepについて

Windowsがスリープ状態に入った場合、実行中の学習プロセスの継続は保証
されない（OSのスリープ中はすべてのプロセスが一時停止する一般的な制約）。
長時間学習を行う場合は、サーバーPCの電源設定でスリープを無効化すること。

## 実機acceptance結果（Issue #50）

Issue #49の実装を、実ブラウザ(Chrome×2プロファイル + Edge)・実RTX 4070 Laptop
GPU・実uvicorn/Vite dev serverで検証した（TestClientではない、実プロセス2つ
+ 実ネットワーク経由）。

### 実GPU sequential training確認

3ユーザー(日本語表示名含む、橋本/テストB/テストC)がそれぞれ別プロジェクトから
実際にUltralytics学習ジョブを投入し、FIFO順で自動的に1件ずつ実行されることを
確認した。ログに`CUDA:0 (NVIDIA GeForce RTX 4070 Laptop GPU, 8188MiB)`が実際に
出力され、本物のGPU学習であることを確認済み。

- 投入順どおりのFIFO実行、3件同時キュー状態(running 1件+queued 2件)のAPI
  スナップショットおよび実ブラウザのqueue widgetで同一状態を確認
- 各jobの出力ディレクトリ(`runs/train/<job_id>`)は衝突せず独立
- GPU training processは常に1件のみ(`training_queue_service`のファイルロックに
  より保証。nvidia-smiの`--query-compute-apps`はこの環境のWDDMドライバでは
  CUDAプロセスを確実に列挙できない既知の制約があり、代わりにログの`CUDA:0`
  出力と、training_queue_service自体のrace test(8並列launch_job呼び出しでも
  同時実行数が常に1であることを確認する自動テスト)で検証した

### 50枚規模の参考training時間

| 項目 | 値 |
|---|---|
| dataset images | 50枚(train 40/val 10) |
| model | yolov8n.pt |
| epochs | 50 |
| imgsz/batch | 640 / 16 |
| GPU | RTX 4070 Laptop |
| queued時間 | 約27秒(先行2ジョブの完了待ち) |
| running時間 | 約41秒 |
| 合計(投入→完了) | 約68秒 |

参考スループット: 1 job(50枚, 50 epochs)あたり約40秒前後。3 job連続実行でも
GPU使用率/単体時間に劣化は見られなかった。この環境特有の極小datasetのため、
実際の社内利用（より大きいdataset・より多いepochs）ではこれより長くなる点に
注意（将来のqueue ETA設計時は、この値をそのまま流用せず別途実測すること）。

### tested browsers

- Google Chrome（プロファイル分離2窓、User A/User C相当）
- Microsoft Edge（User B相当）
- 日本語display name（橋本/テストB/テストC、および24文字の長い表示名）が
  文字化けなく往復することを確認（`encodeURIComponent`/`unquote`の実通信経路）
- 1920px/1366px幅でプロジェクト一覧・学習キュー表示のレイアウト崩れ無し
  （長い表示名は1366px幅でセル内折り返し、テーブル自体は崩れない）

### restart behavior（実クラッシュで確認）

1. backendプロセスのみkill（学習プロセスは生存） → 再起動後、`running`状態
   ・PIDとも維持され、誤ってfailed化されないことを確認
2. backendプロセス+実学習プロセスの両方をkill（PC電源断相当） → 再起動後、
   該当jobは`failed`、メッセージに中断された旨が明示され、**同じoutput
   directoryへの自動再開は一切発生しない**ことを確認（新規プロセスが
   0件であることをプロセス一覧で確認済み）

### idle CPU/GPU

shared server mode起動したまま、学習ジョブが無い状態で約5.5分間放置して測定。

| | 開始時 | 約5.5分後 |
|---|---|---|
| backend working set | 59.0MB | 59.9MB |
| backend 累積CPU時間 | 0.8秒 | 1.78秒(差分約1秒) |
| GPU使用率 | 0% | 0% |
| GPU memory | 298MiB | 298MiB |
| GPU電力 | 2.63W | 2.66W |

3秒間隔のqueue監視background taskによる追加負荷は実測上ごくわずか(5.5分で
CPU時間+1秒程度)。メモリ増加・スピンループは観測されなかった。

### training中のVRAM/RAM（実測）

- VRAM: 約1.9〜1.94GB（yolov8n, imgsz=640, batch=16, 50枚datasetの場合）
- GPU使用率: 約29%、電力約35W（同条件）
- 学習worker process(実インタプリタ側)の working set: 約5.9GB
  （PyTorch/CUDAランタイム込み。backend本体は61MB程度のままで重量依存を
  importしない設計が実測でも維持されている）

### Issue #50で発見・修正した実バグ（2件）

実HTTP経由の同時リクエストテストで、Issue #49時点のTestClientベースのテスト
では検出できなかった、以下2件のTOCTOU(check-then-act)レースを発見・修正した。
いずれも「ディレクトリ存在チェック→(exist_ok=True)でのmkdir」という同じ
アンチパターンで、`project_service.create_project()`は既にexist_ok=False化
済みだったが、以下2箇所に同種の問題が残っていた。

1. **project名衝突**: `project_service.create_project()`の自己修復ロジック
   (「project.yamlが無ければ過去の残骸とみなす」)が、mkdir成功から
   project.yaml書き込み完了までの間に来た別リクエストを誤って通してしまい、
   5並列requestで5件とも201になる実害を確認。ディレクトリのmtime年齢で
   stale判定するよう修正（5秒以内はactive race、5秒超は過去の残骸）。
2. **training job名衝突**: `training_service.prepare_job()`の
   `run_dir.mkdir(parents=True, exist_ok=True)`が非原子的だった(GILの影響で
   再現確率は低いが、10並列requestで複数回201が出ることを確認)。
   `exist_ok=False` + `_is_job_active()`再判定方式へ修正。

両方とも実HTTP経由で修正後に複数回(各3回以上)再検証し、安定して1件のみ成功・
残りは409になることを確認した。自動回帰テスト
(`smoke_project_creation_race.py`/`smoke_training_job_race.py`)を追加済み。

## 既知の制約

- フロントエンドのengine選択等と同様、プロジェクトACL（アクセス制御）は
  未実装。Phase 1では「自分のプロジェクト/他ユーザーのプロジェクトが
  識別できる」までで、他ユーザーのプロジェクトを閲覧・編集すること自体は
  制限していない。
- 同一プロジェクトを複数ユーザーが同時編集する高度なcollaboration
  （リアルタイム共同編集等）は対象外。
- `uvicorn --workers`によるマルチプロセス運用は前提にしていない
  （上記「Single-process backend前提」参照）。
