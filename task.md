# Issue 029: Web UI レイアウト安定化・レスポンシブ改善

## 目的

YOLO Tuning Studio は、detect / segment、SAM支援、学習、評価、推論、モデル配布、ONNXエクスポート、ONNX同梱パッケージまで実装済みである。

ここで機能追加を一旦止め、Web UIの実用性を改善する。

Issue 026ではブランドデザインを反映したが、今回は実務上の表示崩れを修正する。
特に、セレクトボックスや入力欄の文字見切れ、ブラウザサイズ変更時のコンテンツはみ出し、テーブルやカードの横幅問題を重点的に直す。

---

## 重要方針

このIssueでは、機能ロジックを変更しない。

変更しないもの：

```text
・API仕様
・保存形式
・学習処理
・推論処理
・ONNXエクスポート処理
・モデル配布処理
・アノテーション保存処理
・Konva描画ロジック
・ルーティング構成
```

主に CSS / レイアウト / className / コンポーネント構造の軽微な整理で対応する。

---

## 対象

主な対象：

```text
frontend/src/styles.css
frontend/src/App.tsx
frontend/src/pages/*.tsx
frontend/src/components/*.tsx
```

特に確認するページ：

```text
・ProjectsPage
・ProjectLayout / Sidebar
・ImageImportPage
・SelectionPage
・PreprocessPage
・AnnotatePage
・DatasetPage
・TrainPage
・EvaluatePage
・PredictPage
・AnalysisPage
・ExperimentsPage
・ModelsPage
・ReportsPage
・AugmentationPage
```

---

## 改善対象

### 1. セレクトボックスの見切れ修正

以下のようなselectが、文字切れ・幅不足・親要素からはみ出しを起こさないようにする。

```text
・project selector
・task selector
・model selector
・dataset selector
・weight selector
・ONNX export job selector
・augmentation preset selector
・image source selector
・preprocess resize mode selector
・SAM mode / merge setting
```

要件：

```text
・選択中の値ができるだけ見える
・親幅が狭い場合は自然に縮む
・必要なら横幅100%
・長い値はtitle属性で全文確認できるようにする
・selectがカード外にはみ出さない
```

CSS方針：

```css
select,
input,
textarea {
  max-width: 100%;
  min-width: 0;
}
```

必要に応じて共通クラスを追加する。

```css
.form-field {
  min-width: 180px;
  flex: 1 1 220px;
}

.form-field--wide {
  flex: 2 1 320px;
}

.form-field select,
.form-field input {
  width: 100%;
}
```

---

### 2. フォーム行の伸縮・折り返し

フォームやツールバーの横並び要素が、画面幅に応じて折り返されるようにする。

対象例：

```text
・学習設定
・ONNXエクスポート設定
・モデル配布設定
・前処理設定
・データセット作成設定
・推論設定
・SAM設定
・フィルタ行
```

要件：

```text
・広い画面では横並び
・狭い画面では自然に折り返し
・入力欄が極端に細くならない
・ボタンが画面外へ逃げない
```

CSS方針：

```css
.form-row,
.toolbar,
.action-row,
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: end;
  min-width: 0;
}
```

---

### 3. ボタン群の折り返し

複数ボタンが横に並ぶ箇所で、画面幅が狭い場合に崩れないようにする。

対象：

```text
・ModelsPage の download / package / ONNX export ボタン
・TrainPage の start / refresh / log copy
・PredictPage の run / refresh / download
・ReportsPage の generate / download
・AnnotatePage の save / mode / SAM操作
```

要件：

```text
・ボタン群はflex-wrapする
・ボタン文字は基本nowrap
・狭い画面では必要に応じて幅100%
```

CSS例：

```css
.button-row,
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.button-row button,
.action-row button {
  white-space: nowrap;
}
```

---

### 4. テーブルの横スクロール制御

テーブルが画面全体を押し広げないようにする。

対象：

```text
・LabelCheckPage
・DatasetPage
・TrainPage job一覧
・EvaluatePage artifact一覧
・PredictPage results
・AnalysisPage
・ExperimentsPage
・ModelsPage
・ReportsPage
```

要件：

```text
・テーブル外側の .table-scroll だけ横スクロール
・ページ全体には横スクロールを出さない
・ヘッダー sticky は維持
・長い文字列は折り返しまたは省略
```

CSS方針：

```css
.table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: auto;
  min-width: 0;
}

.table-scroll table {
  width: 100%;
  min-width: 820px;
}
```

長いIDやパスは以下を使う。

```css
.text-break,
.path-text,
.job-id,
.file-name {
  overflow-wrap: anywhere;
  word-break: break-word;
}
```

---

### 5. メインレイアウトのはみ出し防止

Flex子要素が親幅を超えてしまう問題を防ぐ。

要件：

```text
・サイドバー + メイン領域で横スクロールが出にくい
・メイン領域内のカードが親幅を超えない
・カード内のテーブル/フォームもはみ出さない
```

CSS方針：

```css
.app-shell,
.project-layout,
.main-content,
.page-content,
.card,
.panel,
.section-card {
  min-width: 0;
}
```

メイン領域：

```css
.main-content {
  width: 100%;
  max-width: 100%;
  overflow-x: hidden;
}
```

ただし、必要な横スクロールは `.table-scroll` や `.canvas-scroll` の中だけで行う。

---

### 6. カード内コンテンツの伸縮

カード内のフォーム、説明文、プレビュー、ログがはみ出さないようにする。

対象：

```text
・ModelsPage 詳細パネル
・ONNXエクスポートセクション
・モデル配布セクション
・TrainPage ログ
・PredictPage 結果
・EvaluatePage artifact画像
・ReportsPage JSON/Markdownプレビュー
```

要件：

```text
・長いログはpre内でスクロール
・長いJSONはpre内でスクロール
・画像はmax-width: 100%
・カード内の横スクロールは必要箇所だけ
```

CSS例：

```css
pre,
.log-panel,
.json-preview {
  max-width: 100%;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

img,
.preview-image {
  max-width: 100%;
  height: auto;
}
```

---

### 7. アノテーション画面のレスポンシブ改善

アノテーション画面は作業性を優先する。

要件：

```text
・キャンバス領域が極端に小さくならない
・右側/下側パネルが画面幅に応じて折り返す
・SAM操作UI、クラス一覧、Polygon編集UIが見切れない
・Konva描画ロジックは変更しない
```

必要なら、アノテーション画面専用のレイアウトクラスを整理する。

```css
.annotation-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
  gap: 16px;
}

@media (max-width: 1100px) {
  .annotation-layout {
    grid-template-columns: 1fr;
  }
}
```

---

### 8. ModelsPage重点対応

Issue 025〜028でModelsPageに多くの機能が追加されたため、特に見直す。

対象：

```text
・モデル一覧
・モデル詳細
・best/last download
・配布パッケージ作成
・ONNXエクスポート
・ONNX job一覧
・ログ表示
・ONNX同梱設定
```

要件：

```text
・selectが見切れない
・ONNX job idが長くても崩れない
・ボタン群が折り返す
・ログ表示がカード外へ出ない
・狭い画面ではセクションが縦積みになる
```

---

## 共通ユーティリティクラス

必要に応じて以下を追加する。

```css
.w-full {
  width: 100%;
}

.min-w-0 {
  min-width: 0;
}

.flex-wrap {
  flex-wrap: wrap;
}

.text-break {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.scroll-x {
  overflow-x: auto;
}

.stack-sm {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stack-md {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.grid-responsive {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}
```

---

## ブラウザサイズ確認

最低限、以下の幅で確認する。

```text
・1440px
・1280px
・1024px
・768px
```

スマホ最適化は必須ではないが、768px程度で操作不能にならないようにする。

---

## テスト

### フロント

```text
npm run typecheck
npm run build
```

または既存の手順に合わせて、

```text
tsc -b
vite build
```

を通す。

### 目視確認

以下を確認する。

```text
・selectの文字が見切れすぎない
・カード外にはみ出しがない
・ページ全体に不要な横スクロールが出ない
・テーブルはテーブル領域内で横スクロールする
・ModelsPageのONNX/配布設定が崩れない
・TrainPageのログが崩れない
・AnnotatePageの操作パネルが見切れない
・EvaluatePageのメトリクス/画像が崩れない
```

---

## README更新

READMEに以下を追記する。

```text
・UIレイアウト安定化
・フォーム/セレクト/テーブル/カードのレスポンシブ改善
・機能ロジックは変更していないこと
```

---

## 完了条件

* select/input/textareaが親幅からはみ出さない
* セレクトボックスの表示見切れが改善している
* フォーム行がブラウザ幅に応じて折り返す
* ボタン群がブラウザ幅に応じて折り返す
* テーブルがページ全体を押し広げず、テーブル領域内で横スクロールする
* 長いID/パス/ログがカード外へはみ出さない
* ModelsPageのモデル配布/ONNX関連UIが崩れない
* AnnotatePageの作業性が悪化していない
* 1024px/768px程度でも最低限操作できる
* 機能ロジックに変更がない
* フロントエンドの tsc / vite build が通る
* READMEが更新されている
