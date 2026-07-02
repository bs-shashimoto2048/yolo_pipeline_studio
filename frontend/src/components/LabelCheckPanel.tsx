// ラベル品質チェック（データセット作成の事前チェック）。
// データセット作成画面に埋め込んで使う。チェック実行・サマリー・クラス別統計・
// 問題一覧を表示し、問題行から該当画像のアノテーション画面へ移動できる。
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { LabelIssue, LabelValidationResponse } from "../types";

export default function LabelCheckPanel() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const [result, setResult] = useState<LabelValidationResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [onlyErrors, setOnlyErrors] = useState(false);

  async function runCheck() {
    setBusy(true);
    setError("");
    try {
      setResult(await api.validateLabels(name));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function openInAnnotate(issue: LabelIssue) {
    if (!issue.image_id) return;
    navigate(`/p/${name}/annotate?image=${encodeURIComponent(issue.image_id)}`);
  }

  const summaryCards = result
    ? [
        { label: "画像総数", value: result.summary.image_count },
        { label: "ラベル数", value: result.summary.label_file_count },
        { label: "アノテ済", value: result.summary.annotated_image_count },
        { label: "未ラベル", value: result.summary.missing_label_count },
        { label: "空ラベル", value: result.summary.empty_label_image_count },
        { label: "件数", value: result.summary.total_bbox_count },
        { label: "error", value: result.summary.error_count, kind: "error" },
        { label: "warning", value: result.summary.warning_count, kind: "warn" },
      ]
    : [];

  const issues = result
    ? onlyErrors
      ? result.issues.filter((i) => i.severity === "error")
      : result.issues
    : [];

  const hasError = (result?.summary.error_count ?? 0) > 0;

  return (
    <section className="card">
      <h2>ラベル品質チェック（作成前チェック）</h2>
      <p className="muted" style={{ fontSize: "0.82rem" }}>
        データセット作成前にラベルの整合性を確認します。<strong>error</strong> があると
        作成は中止されます（下のフォームで作成しても同じ検証が実行されます）。
      </p>
      <div className="row">
        <button onClick={runCheck} disabled={busy}>
          {busy ? "チェック中…" : "チェック実行"}
        </button>
        {result && (
          <>
            <span className={hasError ? "error" : "success"}>
              {hasError
                ? `● error ${result.summary.error_count} 件（要修正）`
                : "● error なし（作成可能）"}
            </span>
            <label className="muted">
              <input
                type="checkbox"
                checked={onlyErrors}
                onChange={(e) => setOnlyErrors(e.target.checked)}
              />{" "}
              errorのみ表示
            </label>
          </>
        )}
      </div>
      {error && <div className="error">{error}</div>}

      {result && (
        <>
          {/* サマリーはインラインで縦方向をコンパクトに */}
          <div className="lc-summary">
            {summaryCards.map((c) => (
              <span key={c.label} className="summary-stat">
                <span
                  className={
                    "summary-value" +
                    (c.kind === "error" && c.value > 0
                      ? " error"
                      : c.kind === "warn" && c.value > 0
                      ? " warn"
                      : "")
                  }
                >
                  {c.value}
                </span>
                <span className="summary-label">{c.label}</span>
              </span>
            ))}
          </div>

          {/* 各結果は折りたたみ可能・高さ上限付きスクロールでコンパクトに */}
          <details className="lc-details" open>
            <summary>クラス別統計（{result.class_stats.length}）</summary>
            <div className="table-scroll lc-table">
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>クラス名</th>
                    <th>件数</th>
                    <th>画像数</th>
                  </tr>
                </thead>
                <tbody>
                  {result.class_stats.map((c) => (
                    <tr key={c.class_id}>
                      <td>{c.class_id}</td>
                      <td>{c.class_name}</td>
                      <td className={c.bbox_count === 0 ? "warn" : ""}>{c.bbox_count}</td>
                      <td>{c.image_count}</td>
                    </tr>
                  ))}
                  {result.class_stats.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted">
                        クラスが未定義です。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </details>

          <details className="lc-details" open>
            <summary>
              問題一覧（{issues.length}）
              {hasError && <span className="error"> ・error {result.summary.error_count}</span>}
            </summary>
            <div className="table-scroll lc-table">
              <table className="table">
                <thead>
                  <tr>
                    <th>severity</th>
                    <th>type</th>
                    <th>image_name</th>
                    <th>line</th>
                    <th>message</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {issues.map((i, idx) => (
                    <tr key={idx}>
                      <td>
                        <span className={i.severity === "error" ? "error" : "warn"}>
                          {i.severity}
                        </span>
                      </td>
                      <td>
                        <code>{i.type}</code>
                      </td>
                      <td className="text-break">{i.image_name ?? i.image_id ?? "-"}</td>
                      <td>{i.line_number ?? "-"}</td>
                      <td className="text-break">{i.message}</td>
                      <td>
                        {i.image_id && i.type !== "orphan_label" && (
                          <button onClick={() => openInAnnotate(i)}>アノテーションへ</button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {issues.length === 0 && (
                    <tr>
                      <td colSpan={6} className="muted">
                        問題は見つかりませんでした。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
