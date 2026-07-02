// 概要パネル（プロジェクト準備画面のセクション）。画像枚数・ラベル数・クラス数・学習回数。
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectSummary } from "../types";

const TASK_LABELS: Record<string, string> = {
  detect: "物体検出（bbox）",
  segment: "セグメンテーション（輪郭）",
};

export default function OverviewPanel() {
  const { name = "" } = useParams();
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getProject(name).then(setSummary).catch((e) => setError(String(e)));
  }, [name]);

  const items = summary
    ? [
        { label: "画像", value: summary.image_count },
        { label: "ラベル", value: summary.label_count },
        { label: "クラス", value: summary.class_count },
        { label: "学習", value: summary.train_count },
      ]
    : [];

  return (
    <section className="card setup-summary">
      {error && <div className="error">{error}</div>}
      {!summary && !error && <span className="muted">読み込み中…</span>}
      {summary && (
        <>
          <span className={"task-badge " + (summary.task === "segment" ? "seg" : "det")}>
            {TASK_LABELS[summary.task] ?? summary.task}
          </span>
          {items.map((it) => (
            <span key={it.label} className="summary-stat">
              <span className="summary-value">{it.value}</span>
              <span className="summary-label">{it.label}</span>
            </span>
          ))}
          {summary.created_at && (
            <span className="summary-meta muted">作成: {summary.created_at}</span>
          )}
          {summary.description && (
            <span className="summary-meta muted text-break">{summary.description}</span>
          )}
        </>
      )}
    </section>
  );
}
