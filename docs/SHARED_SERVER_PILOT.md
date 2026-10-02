# Shared Server Mode — Internal Pilot（Issue #51）

Issue #49/#50で実装・検証したshared server mode（複数ユーザー共有 + FIFO GPU
学習キュー）を、実際の複数ユーザーに使ってもらい、新機能の追加を前提とせず
「次に本当に必要な改善だけ」を特定するための社内pilot。

## ステータス

```text
Phase 1（本ドキュメント整備・環境準備）: 完了
Phase 2（実ユーザーによるpilot実施）: 未実施（実テスター確保後に実施）
```

**本ドキュメントの「findings」「severity」「次Issue候補」等の節は、Phase 2
実施後に実際の観察結果・アンケート結果で埋める。現時点では空欄のテンプレート
のみ。** 実テスターが用意できない状態でこれらを埋めることは、pilotという
調査手法の前提（実際の人間の主観的反応）を損なうため行わない。

自動ブラウザ操作によるtechnical pre-check（後述）は、環境が実際に稼働する
ことの確認に過ぎず、real pilotの代替ではない。

---

## Phase 1: Pilot運用条件

### 参加者

- 人数: 最低2人、推奨3人
- 構成: 最低1人は開発内容を詳しく知らない初見ユーザーが望ましい
  （例: User A=開発者、User B=初見ユーザー、User C=初見/準初見ユーザー）
- GitHub等への記録は匿名化する（`Pilot User A` / `Pilot User B` / `Pilot User C`）。
  実名・社内個人情報・機密データはpublic repoへ記載しない。

### データ規模・環境

| 項目 | 推奨値 |
|---|---|
| dataset規模 | 20〜50枚程度（実運用に近い範囲） |
| model | 軽量YOLO系（例: yolov8n.pt） |
| epochs | training時間を短く保てる値（例: 30〜50） |
| GPU | 実RTX 4070 Laptop GPU、FIFO queueを実利用 |
| browser | 社内で実際に使うChrome/Edge等 |
| shared server mode | `YTS_SHARED_SERVER_MODE=true` で起動 |

PC sleepはpilot中無効化しておく（Windows電源設定）。server restartは今回
あえてテストしない（Issue #50で確認済み）。

### 起動手順（進行役が事前に準備）

```powershell
# backend
$env:YTS_SHARED_SERVER_MODE = "true"
uvicorn app.main:app --app-dir backend --port 8000

# frontend（別ターミナル）
cd frontend
npm run dev
```

参加者には `http://<サーバーPCのIP>:5173` （または同一PC上で検証する場合は
`http://localhost:5173`）へアクセスしてもらう。詳細は
[`docs/SHARED_SERVER_MODE.md`](SHARED_SERVER_MODE.md) 参照。

### 操作説明の方針

最初から細かく教えすぎない。各ステップの「最低限の目的」だけ伝え、UI自体で
操作可能かを確認する（例: 「名前を入力してください」とだけ伝え、入力欄の
見つけ方・送信方法は教えない）。

---

## Phase 1: Scenarioスクリプト（進行役用）

各参加者に以下を順に実施してもらう。各ステップで**目的のみ**を伝える文例を
右側に示す。

| # | ステップ | 伝える目的（例） |
|---|---|---|
| 1 | 名前入力 | 「このサーバーは複数人で使うので、名前を登録してください」 |
| 2 | project作成 | 「自分用のプロジェクトを1つ作ってください」 |
| 3 | 画像upload | 「お手元の画像（20〜50枚程度）を取り込んでください」 |
| 4 | annotation | 「取り込んだ画像に対象物の枠を付けてください」 |
| 5 | dataset確認 | 「学習用データセットを作成してください」 |
| 6 | training開始 | 「学習を開始してください」 |
| 7 | queue状態確認 | 「自分の学習が今どういう状態か確認してください」 |
| 8 | training完了確認 | 「学習が終わったか確認してください」 |
| 9 | inference/result確認 | 「学習結果（モデル）を確認してください」 |

---

## Phase 1: 観察項目チェックリスト（進行役が各参加者ごとに記録）

```text
[ ] どこで止まったか（画面名・操作名）
[ ] 何を質問したか（発言をそのまま記録）
[ ] 操作を誤った箇所（誤クリック・誤入力等）
[ ] 分かりにくかった表示（スクリーンショット可）
[ ] 理解できなかった用語
[ ] 待ち時間への反応（queue待ち時の発言・態度）
[ ] training結果の理解度（何が出力されたか説明できるか）
[ ] developerの口頭補助が必要になった回数
[ ] 完遂 / 未完遂（どのステップまで到達したか）
```

### 特に確認する項目

- 初回導線: 名前入力／project作成／dataset作成／annotation開始／training開始
- queue UX: 「なぜ今すぐ始まらないか」「自分は何番目か」「今誰のjobが動いて
  いるか」を理解できるか
- project ownership: 「誰が作ったprojectか」が実用上十分分かるか
- 他ユーザーproject: 誤操作（他人のprojectを開く・削除しようとする等）が
  起きそうか
- 同一project共同編集: 必要性を感じるか（今回は非推奨、必要性の有無だけ記録）
- training history: 「前に何を学習したか分からない」と感じるか
- storage: project/image/run増加による容量懸念を感じるか（感じた場合のみ記録）
- error handling: 実際にエラーが出た場合のUI表示・理解度

### 時間計測（参加者ごと）

| 項目 | 記録欄 |
|---|---|
| 初回操作開始時刻 | |
| training開始時刻 | |
| queue待ち時間 | |
| training実行時間 | |
| training完了確認時刻 | |
| 合計所要時間 | |

### 管理者側観察（進行役がサーバー運用者視点で記録）

```text
[ ] 誰が何を実行中か把握できたか
[ ] queue件数を把握できたか
[ ] failed jobの有無・原因を把握できたか
[ ] disk使用量に懸念が出たか
[ ] server負荷（CPU/GPU/RAM/VRAM）に懸念が出たか
```

参考値（Issue #50実測、同条件の目安）: idle時backend CPU増加は5.5分で約1秒、
50枚/50epochs学習でVRAM約1.9GB・学習process RAM約5.9GB・所要時間約68秒
（queued+running）。実測値は環境により変動するため、pilot実施時に改めて
記録すること。

---

## Phase 1: アンケート（進行役が各参加者へ実施後に確認）

5段階評価だけで終わらせず、自由コメントを重視する。

1. 一人で操作できそうか（はい/いいえ＋理由）
2. 分かりにくかった箇所（自由記述）
3. 一番改善してほしい点（自由記述）
4. training待ち時間は許容できるか（はい/いいえ＋理由）
5. 業務で使えそうか（はい/いいえ＋理由）

---

## Phase 1: 記録フォーマット（Phase 2実施時にこのテーブルを埋める）

### 参加者サマリ

| 参加者 | 属性 | 完遂/未完遂 | 到達ステップ | developer介入回数 | 合計所要時間 |
|---|---|---|---|---|---|
| Pilot User A | | | | | |
| Pilot User B | | | | | |
| Pilot User C | | | | | |

### Findings

| Finding | Severity | Action |
|---|---|---|
| | | |

Severity分類:
- **A. Blocker**: training不可・project破損・queue停止・他userデータ上書き・
  server crash → 即修正
- **B. High**: 初見ユーザーが主要操作を完遂できない・queue状態が理解不能・
  failed job原因が分からない → Issue #51内で最小修正可
- **C. Medium**以下: 原則Issue #51では実装せず、次Issue候補として整理

### 次Issue候補（最大3件、本当に必要なものだけ）

| # | 候補 | 根拠 |
|---|---|---|
| | | |

---

## Phase 1: Technical pre-check（real pilotとしてカウントしない）

進行役が参加者を迎える前に、環境が実際に稼働することだけを確認する。
これはUX調査ではなく、Issue #50で検証済みの機構が今回の環境でも動くことの
技術的な事前確認であり、pilotの代替ではない。

- [x] `YTS_SHARED_SERVER_MODE=true` でbackendが起動する
- [x] frontend(`npm run dev`)からbackendへ接続できる
- [x] `torch.cuda.is_available()` が `True`（実GPU検出: NVIDIA GeForce RTX
      4070 Laptop GPU）
- [x] 20〜50枚規模のdatasetで実際にtraining jobが完了する
- [x] 複数projectを作成しても相互に影響しない

実施日: 2026-10-02。結果（隔離環境、`YTS_PROJECTS_ROOT`を一時ディレクトリへ
差し替えて実施。実repoの`projects/`・production artifactには一切触れていない）:

| 確認項目 | 結果 |
|---|---|
| backend起動(shared mode) | OK |
| frontend→backend接続(Vite proxy) | OK |
| GPU検出 | OK（NVIDIA GeForce RTX 4070 Laptop GPU） |
| 30枚dataset、yolov8n、epochs=40、imgsz=640、batch=16 | OK（完了まで約65秒、
  queued→running→completed、return_code=0、best.pt/last.pt生成確認） |
| 2project同時存在時の相互非干渉 | OK（一方へのimage/training操作がもう一方の
  image_count等に一切影響しないことを確認） |

**この結果はPhase 1のtechnical pre-checkであり、real pilotではない。**
Phase 2（実ユーザー2〜3名によるpilot）は未実施。
