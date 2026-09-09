# Domain A Fixed Test Set v1（`meter_domain_a_fixed_test_v1.csv`）

Issue #1 Checkpoint 1A〜1Eで設計・検証・固定した、`meter`プロジェクトDomain A（7セグLCD）の公式Fixed Test Setです。

## 固定内容（v1、fixed_at=2026-09-09）

- `purpose=test` の行が **21 images**
- **19 unique Full Readings**（`0215218`・`0215257`のみ各2枚重複、他は全て異なる値）
- **2 confirmed physical meters**（個体Y: 20枚 / 個体Z: 1枚）
- 全21枚 **Domain A** のみ（Domain Bは混在しない）

## 重要な制約

- Issue #1本文が目標とする「physical meter 5台以上」は**現時点では未達**です。v1は現データで再現可能な比較基準として固定しましたが、実質2個体中心である制約を踏まえた上で結果を解釈してください。
- **この21枚は今後の学習・augmentation選定・hyperparameter tuningに使用禁止**です（Test専用）。
- `source_url`/カメラIPだけでは physical meter の同一性を保証できないことが実データで判明しています（`src_001_20260818_140200`と`meter_004.png`は、job.json上は別IPのセッションでしたが目視確認で実際にはTrain側個体と同一物理個体でした）。今後physical meter IDを機械的に決め打ちしないでください。
- 追加のphysical meterを評価したい場合は、この v1 を上書きせず **v2等の別ファイル/別versionとして追加**してください。

## manifest列の除外/不採用ステータス

- `purpose=excluded_leakage`: Train側支配個体と同一物理個体と判明したため除外（`src_001_20260818_140200`, `meter_004.png`）
- `purpose=excluded_domain_b`: 機械式ドラム型メーター（Domain B）のため除外（`meter_003.png`, `src_004*`全件）
- `purpose=dropped_redundant_reading`: 同一Reading重複（`0215257`）のうち条件差のない冗長画像として不採用（4枚）。annotationファイル自体は削除していません。
