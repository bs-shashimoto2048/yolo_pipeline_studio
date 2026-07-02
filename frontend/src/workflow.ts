// task.md のワークフロー工程に対応する画面定義。
// path はプロジェクト配下の相対パス（/p/:name/<path>）。

export interface WorkflowStep {
  path: string;
  label: string;
  no: number;
  implemented: boolean; // 実働 or 骨組み
}

// 工程順（Issue 011）: 取り込み→選別→前処理→アノテーション の順とし、
// 前処理を画像加工としてアノテーション前に置く。オーギュメンテーションは
// データセット作成後・学習前（学習時拡張）に置く。
// Issue 029補足: 「ラベル品質チェック」は単独工程をやめ、データセット作成画面の
// 作成前チェックとして統合した（工程数を削減）。
// Issue 029補足2: 「概要」「クラス設計」「画像取り込み」は作業が少ないため、
// 「プロジェクト準備」1工程に統合した（工程数を削減）。
// 補足3: 「データ拡張」は単独工程をやめ、「学習」画面の右カラムに統合した
// （学習ジョブと拡張パラメータを1画面で確認・設定できるようにするため）。
export const WORKFLOW_STEPS: WorkflowStep[] = [
  { no: 1, path: "setup", label: "プロジェクト準備", implemented: true },
  { no: 2, path: "selection", label: "画像選別", implemented: true },
  { no: 3, path: "preprocess", label: "前処理", implemented: true },
  { no: 4, path: "annotate", label: "アノテーション", implemented: true },
  { no: 5, path: "dataset", label: "データセット作成", implemented: true },
  { no: 6, path: "train", label: "学習", implemented: true },
  { no: 7, path: "eval", label: "評価", implemented: true },
  { no: 8, path: "infer", label: "推論テスト", implemented: true },
  { no: 9, path: "analysis", label: "誤検出分析", implemented: true },
  { no: 10, path: "experiments", label: "実験履歴", implemented: true },
  { no: 11, path: "models", label: "モデル管理", implemented: true },
  { no: 12, path: "reports", label: "レポート", implemented: true },
];
