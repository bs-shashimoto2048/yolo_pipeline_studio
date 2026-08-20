# ドキュメント一覧

YOLO Tuning Studio のドキュメントは、読み手の目的に応じて以下から選んでください。

## はじめてアプリを操作する方（作業者）

- **[operator-manual.md](operator-manual.md)** — 実際のアプリ画面のスクリーンショット付きで、
  プロジェクト作成から学習・推論・レポート出力までの一連の操作を順番に説明します。
  まずここから読んでください。

## 開発・拡張する方（開発者）

- **[architecture.md](architecture.md)** — 内部構成・データレイアウト・ワーカー方式・設計方針。
- **[api-reference.md](api-reference.md)** — REST API エンドポイント一覧（`backend/app/routers/`と対応）。
- **[development.md](development.md)** — 開発環境セットアップ、テスト、コーディング規約、
  作業者マニュアル用スクリーンショットの再撮影手順。

## その他

- ルートの [`README.md`](../README.md) — プロジェクト概要・QuickStart（最短でアプリを動かす手順）。

## ドキュメントの構成方針

- **作業者向け**（operator-manual.md）と**開発者向け**（architecture / api-reference / development）を分離しています。
  作業者は実装の詳細を読む必要がなく、開発者はスクリーンショット付きの操作説明を毎回読む必要がないためです。
- スクリーンショットは `docs/images/operator/` に保存し、実際に動作しているアプリから撮影したものだけを使用します
  （架空UI・モック画像は使用しません）。
