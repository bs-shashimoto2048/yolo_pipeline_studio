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

## 10. 既知の制約・次候補

- フロントエンドUIへのtargeted capture専用コントロールは本Issueでは追加して
  いない（backend/APIのみ。既存UIから通常の撮影セッション作成経由で`purpose`/
  `target`/`max_frames`を含むPOSTは可能だが、専用フォームはまだ無い）。
  次Issue候補（Priority 2: targeted capture session review UX）。
- `scripts/audit_dataset_split.py`のGate 1 CIへの常時組み込みは、本Issueでは
  行っていない（軽量・GPU非依存なため将来組み込み可能、Issue #40 §39参照）。
