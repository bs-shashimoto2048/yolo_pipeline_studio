# Targeted Data Capture（rare-class収集ワークフロー、Issue #41）

Issue #40で、digital production (`meter_src002`, `production_combined_v2_5z`)の
4桁目(digit position 3) class=4が、既存raw画像プールでは安全に補充不能なほど
枯渇していることが確定した（既存raw画像はnear-duplicateとして使えば
Test66を汚染してしまう）。本ドキュメントは、次回そのようなrare classを
**安全に新規収集**できるcapture workflowの設計・使い方を記録する。

**本Issueではmodelのretraining・promotion・threshold変更は一切行っていない。**
capture infrastructureのみの追加である。

## 1. Purpose

- 既存datasetで不足している特定digit position/classを、計画的に新規収集する。
- 収集した画像がTest/Valと重複（near-duplicate）していないことを、収集後すぐに
  機械確認できるようにする。
- 収集意図（target）を記録しつつ、GTは自動確定せず必ず人手確認を要求する。

## 2. Target capture session

既存の`CaptureSessionCreate`（`backend/app/schemas/capture.py`）へ、全てoptionalな
フィールドを追加した（既存clientとの完全な後方互換。旧job.jsonにこれらのkeyが
無くても問題なく動作する）:

```json
{
  "session_name": "rare_p3_c4_001",
  "source_type": "camera",
  "camera_index": 0,
  "purpose": "rare_class_collection",
  "target": {"digit_position": 3, "target_class": "4"},
  "max_frames": 30
}
```

- `purpose`: 収集目的（自由文字列、例: `"rare_class_collection"`）。
- `target.digit_position` / `target.target_class`: 汎用化されており、position/class
  を問わず任意のrare-class収集に使える。
- `max_frames`: 指定すると、この枚数に達した時点でセッションが自動停止する
  （同一physical transitionの連写水増しを防ぐ、§9）。

## 3. Capture

既存の撮影API（`POST /api/projects/{name}/capture-sessions`、
`POST .../capture-sessions/{sid}/capture`、`.../stop`）をそのまま使う。
`interval_minutes`の既存バリデーション（1〜1440分の整数のみ）は変更していない
ため、rare-class収集時も短すぎるintervalは引き続き拒否される（§9）。

収集session自体のID（session_name）は、既存の命名規約
（`paths.is_valid_project_name`、英数・アンダースコア・ハイフンのみ）に従う。
日時だけに依存しない一意なIDにすること（例:
`rare_p3_c4_<目的や通し番号>`）を推奨する。撮影画像のファイル名は既存規約通り
`{session_id}_{YYYYMMDD_HHMMSS}.jpg`で、`raw/images/`へ既存の画像取り込みと
完全に同じ重複/破損チェックを経て保存される（§19: 出力はsession_idで
自然に分離されるため、新たな専用ディレクトリ階層は設けていない）。

## 4. Metadata（自動GT化はしない）

撮影のたびに、`projects/<name>/capture/<sid>/frames.json`へ以下を記録する
（`backend/workers/capture_worker.py`の`_append_frame_metadata`）:

```json
{
  "stem": "rare_p3_c4_001_20261001_143022",
  "captured_at": "2026-10-01T14:30:22",
  "source": "rare_p3_c4_001",
  "target_digit_position": 3,
  "target_class": "4",
  "frame_index": 1,
  "review_status": "unreviewed",
  "note": null
}
```

**`target_class`はあくまで撮影者の収集意図であり、GTそのものではない**
（§8）。`review_status`は常に`"unreviewed"`から始まる。camera credential/URLは
一切含めない（`source`はsession_idという論理IDのみ、§29）。

## 5. Review

```
GET   /api/projects/{name}/capture-sessions/{sid}/frames
PATCH /api/projects/{name}/capture-sessions/{sid}/frames/{stem}/review
```

`review_status`は以下のいずれか:

- `unreviewed`（初期値）
- `accepted`
- `rejected_duplicate`
- `rejected_ambiguous`
- `rejected_wrong_target`

人手確認でGT（実際の読み取り値）を確定した上で`accepted`にする想定。既存の
annotation/selection workflow（`backend/app/schemas/selection.py`の
`included/review`ステータス）とは別レイヤー（撮影直後のtriage専用）として
設計した。`accepted`になった画像を実際にannotation対象へ進める際は、既存の
annotation workflow（`docs/METER_DATASET_CURATION_GUIDE.md`参照）へ通常通り渡す。

## 6. Duplicate audit（Test保護）

`scripts/audit_dataset_split.py`（Issue #40で作成、本Issueで拡張）を再利用する。

```powershell
# 既存split全体の自己監査（Issue #40と同じ用途）
.venv\Scripts\python.exe scripts\audit_dataset_split.py `
    --manifest data_manifests\meter_src002_split_v3.csv `
    --raw-dir projects\meter_src002\raw\images --gt-position 3

# 新規capture候補 vs 既存manifest（Issue #41で追加したモード）
.venv\Scripts\python.exe scripts\audit_dataset_split.py `
    --manifest data_manifests\meter_src002_split_v3.csv `
    --raw-dir projects\meter_src002\raw\images `
    --candidate-stems-file candidate_stems.txt
```

`--candidate-stems-file`は1行1stem（拡張子なし）のテキストファイルを受け取り、
既存manifestのTrain/Val/Testに対するexact stem overlap・perceptual
near-duplicate（aHash、デフォルトHamming<=3、600秒以内）のみを監査する
（通常のsplit自己監査は実行しない）。**Issue #40で判明した通り、固定time-window
だけでは長時間アイドル期間を見逃す**ため、perceptual similarityを必須とし、
time proximityは補助情報として扱う（§12）。near-duplicateが見つかった候補は、
**新規capture側を除外する（Testは一切動かさない）**。

## 7. Candidate export

```
GET /api/projects/{name}/capture-sessions/{sid}/candidate-manifest
```

CSVを返す（列: `capture_session_id, stem, timestamp, target_position,
target_class, review_status`）。`review_status`が`accepted`の行のみを次の
training issueへ引き継ぐ想定。

## 8. 次training issueへの引継ぎ条件

本Issueでは再学習しない。次のdigital hard-negative改善Issueを開始する最低条件
（Issue #41 §32）:

```
position3/class4 accepted independent primary >= 20（推奨30〜50）
```

この閾値に達しても**自動で次Issueを起票しない**。人間がdatasetをレビューして
から次Issueを判断する（§33）。

## 9. Smoke test

- `backend/tests/smoke_targeted_capture.py`: target metadata付きセッション作成・
  frames.json記録・max_frames自動停止・review更新・candidate manifest出力・
  既存clientとの後方互換を検証（mock source、production camera/weight不要）。
- `backend/tests/smoke_audit_dataset_split.py`: near-duplicate判定（同一画像/
  微小shift/明確に異なる画像）とcandidate-vs-existing監査モードを検証。
- `backend/tests/smoke_targeted_capture_review.py`（Issue #42追加）: review
  summary一覧・duplicate audit・session跨ぎのtarget progress集計・
  accepted-onlyのcandidate manifest exportを検証。

## 10. Review UI（Issue #42）

Issue #41のbackend/API基盤を、人が実際に運用できるレビューUIへ仕上げた。
画面は新規ページを増やさず、既存のプロジェクト準備画面
（`frontend/src/pages/SetupPage.tsx` → `ImagesPanel.tsx`）内に
「レビュー（targeted capture）」タブを追加する形で統合した
（`frontend/src/components/TargetedCaptureReview.tsx`）。

```
Capture
  ↓
Review（session一覧 → frameごとにAccepted/Duplicate/Ambiguous/Wrong target）
  ↓
Duplicate audit（Train/Val/Test、Testは一切変更しない）
  ↓
Accepted independent primary（session跨ぎ集計）
  ↓
Threshold reached（最低20件、推奨30〜50件）
  ↓
Next training Issue（人間が判断して起票。自動では起票しない）
```

### UI機能

- **Session一覧**: session ID・purpose・target position/class・captured/
  unreviewed/accepted/rejected件数・created_atを表示。`All` /
  `Unreviewedあり` / `Completed review` でfilter。target未指定の既存session
  （purpose/target=null、frames.json無し）も壊れず0件表示される。
- **新規targeted session作成フォーム**: 既存のsource一覧ベースの撮影UI
  （`CaptureSourcesPanel`）とは別に、ad-hocなsession_name/target/max_frames
  指定で直接開始できる最小フォームを用意した（既存UIへの変更はゼロ）。
- **Frame review**: 1frameずつ、画像・frame index・timestamp・target
  position/class・現在の状態を表示。GT boxは一切描画しない（§12/§29）。
  ボタンまたはキーボードショートカット（`A`=Accepted, `D`=Duplicate,
  `X`=Ambiguous, `W`=Wrong target, `←`/`→`=前後）で判定し、判定後は
  自動で次のunreviewedへ移動する（§10/11）。既存ページ
  （AnnotatePage等、別ルート）とのショートカット衝突はない。
- **Duplicate audit連携**: manifest_path（+ 任意でgt_position）を指定して
  acceptedフレームを監査し、`No overlap` / `Near duplicate: <split>` を
  frameごとに表示する。Train/Val/Test側の変更は一切行わない（読み取り専用）。
- **Candidate manifest export**: 全件・accepted onlyの両方をCSVダウンロード
  可能。
- **Accepted independent primary進捗**: 同一 project + digit_position +
  target_class でsessionを跨いで集計し、`accepted_total −
  accepted_flagged_duplicate = independent_primary` を表示。最低条件(20)・
  推奨(30〜50)もあわせて表示するが、**閾値到達を検知してもUIが自動で次Issueを
  起票することはない**（人間が判断する、§20/§33）。

### 意図的に実装しなかったもの（§13/14、次Issue候補）

- production modelによる推論結果のプレビュー表示は、既存prediction APIが
  非同期job方式（job作成→polling→結果取得）であり「レビュー1枚ごとに軽量に
  呼べる」設計ではないため、本Issueでは見送った。実装する場合も、
  reviewerがbiasされないよう**折りたたみ・既定非表示**にすることを推奨する
  （§14）。
- 既存の`CaptureSourcesPanel`（source定義ベースの撮影）自体の変更。
  ad-hocなtargeted session開始は別の最小フォームとして追加し、既存UIの
  動作・レイアウトには一切手を入れていない。

## 11. 既知の制約・次候補

- production prediction連携（上記）は未実装。
- `scripts/audit_dataset_split.py`のGate 1 CIへの常時組み込みは、本Issueでは
  行っていない（軽量・GPU非依存なため将来組み込み可能、Issue #40 §39参照）。
- フロントエンドの対話的なブラウザ動作確認（実際にクリック操作して視認する
  テスト）は本Issueでは実施していない。`npm run build`（型チェック込み）と
  backend smoke testで機能を検証した。
