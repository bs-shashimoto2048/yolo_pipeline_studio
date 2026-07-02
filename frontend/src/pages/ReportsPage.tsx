// レポート画面。プロジェクト全体のサマリーを Markdown/JSON で生成・一覧・プレビュー・DL。
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ReportDetailResponse, ReportListItem } from "../types";

export default function ReportsPage() {
  const { name = "" } = useParams();
  const [reportName, setReportName] = useState("");
  const [format, setFormat] = useState("both");
  const [includePredictions, setIncludePredictions] = useState(true);
  const [includeAnalysis, setIncludeAnalysis] = useState(true);
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [detail, setDetail] = useState<ReportDetailResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    try {
      setReports((await api.listReports(name)).reports);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    reload();
  }, [name]);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.generateReport(name, {
        report_name: reportName.trim() || null,
        format,
        include_predictions: includePredictions,
        include_analysis: includeAnalysis,
      });
      await reload();
      await openReport(res.report_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function openReport(reportId: string) {
    try {
      setDetail(await api.getReport(name, reportId));
    } catch (e) {
      setError(String(e));
    }
  }

  const ov = detail?.content?.project_overview as Record<string, unknown> | undefined;
  const tips = (detail?.content?.improvement_suggestions as string[] | undefined) ?? [];

  return (
    <div className="page">
      <h1>レポート: {name}</h1>
      <p className="muted">
        プロジェクトの概要・クラス・選別・前処理・データセット・学習評価・推論分析・
        採用モデル・改善候補をまとめて Markdown / JSON に出力します。
      </p>

      <section className="card">
        <h2>レポート生成</h2>
        <form onSubmit={generate}>
          <div className="row">
            <label className="field">
              report_name（省略時は日時）
              <input value={reportName} onChange={(e) => setReportName(e.target.value)} placeholder="report_001" />
            </label>
            <label className="field">
              形式
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="both">both</option>
                <option value="markdown">markdown</option>
                <option value="json">json</option>
              </select>
            </label>
            <label><input type="checkbox" checked={includePredictions} onChange={(e) => setIncludePredictions(e.target.checked)} /> 推論を含める</label>
            <label><input type="checkbox" checked={includeAnalysis} onChange={(e) => setIncludeAnalysis(e.target.checked)} /> 分析を含める</label>
            <button type="submit" disabled={busy}>{busy ? "生成中…" : "レポート生成"}</button>
          </div>
        </form>
        {error && <div className="error">{error}</div>}
      </section>

      <section className="card">
        <h2>レポート一覧（{reports.length}）</h2>
        <div className="table-scroll">
        <table className="table">
          <thead>
            <tr><th>report_id</th><th>作成日時</th><th>ダウンロード</th><th></th></tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.report_id}>
                <td>{r.report_id}</td>
                <td className="muted">{r.created_at ?? "-"}</td>
                <td>
                  {r.markdown_path && (
                    <a href={api.reportDownloadUrl(name, r.report_id, "markdown")} download>Markdown</a>
                  )}
                  {r.markdown_path && " / "}
                  <a href={api.reportDownloadUrl(name, r.report_id, "json")} download>JSON</a>
                </td>
                <td><button onClick={() => openReport(r.report_id)}>プレビュー</button></td>
              </tr>
            ))}
            {reports.length === 0 && (
              <tr><td colSpan={4} className="muted">まだレポートがありません。</td></tr>
            )}
          </tbody>
        </table>
        </div>
      </section>

      {detail && (
        <section className="card">
          <h2>プレビュー: {detail.report_id}</h2>
          {ov && (
            <ul className="compact">
              <li>画像数: {String(ov.image_count)} / クラス数: {String(ov.class_count)} / processed: {String(ov.processed_image_count)}</li>
              <li>データセット: {String(ov.dataset_count)} / 学習: {String(ov.train_job_count)} / 推論: {String(ov.predict_job_count)}</li>
              <li>採用モデル: {String(ov.selected_model_id ?? "未設定")}</li>
            </ul>
          )}
          {tips.length > 0 && (
            <>
              <h3>改善候補</h3>
              <ul className="compact">
                {tips.map((t, i) => (<li key={i}>{t}</li>))}
              </ul>
            </>
          )}
          <h3>JSON</h3>
          <textarea readOnly className="train-log" value={JSON.stringify(detail.content, null, 2)} />
        </section>
      )}
    </div>
  );
}
