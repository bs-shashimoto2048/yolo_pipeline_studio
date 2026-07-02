// 誤検出分析画面。推論ジョブ選択 → IoU/conf しきい値で分析実行 → サマリー・
// クラス別・画像別結果・フィルタ・アノテーション/推論結果への導線。
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";
import type {
  AnalysisImageResult,
  AnalysisResponse,
  PredictJobInfo,
} from "../types";

type Filter = "all" | "fp" | "fn" | "cm" | "no_tp";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "すべて" },
  { key: "fp", label: "FPあり" },
  { key: "fn", label: "FNあり" },
  { key: "cm", label: "class_mismatchあり" },
  { key: "no_tp", label: "TPなし" },
];

function fmt(v: number): string {
  return v.toFixed(4);
}

export default function AnalysisPage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<PredictJobInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [iou, setIou] = useState(0.5);
  const [conf, setConf] = useState(0.25);
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [openImage, setOpenImage] = useState<string | null>(null);

  useEffect(() => {
    api
      .listPredictJobs(name)
      .then((r) => {
        setJobs(r.jobs);
        const jobParam = searchParams.get("job"); // 実験履歴からの導線
        if (jobParam) setSelected(jobParam);
        else if (!selected && r.jobs.length > 0) setSelected(r.jobs[0].predict_job_id);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  // ジョブ切替時に保存済み分析を読込（無ければ未表示）
  useEffect(() => {
    if (!selected) return;
    setData(null);
    setError("");
    setOpenImage(null);
    api
      .getAnalysis(name, selected)
      .then((d) => {
        setData(d);
        setIou(d.iou_threshold);
        setConf(d.conf_threshold);
      })
      .catch(() => {});
  }, [name, selected]);

  async function run() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      setData(await api.runAnalysis(name, selected, iou, conf));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reload() {
    if (!selected) return;
    setError("");
    try {
      setData(await api.getAnalysis(name, selected));
    } catch (e) {
      setError(String(e));
    }
  }

  const filtered = useMemo<AnalysisImageResult[]>(() => {
    if (!data) return [];
    return data.image_results.filter((im) => {
      switch (filter) {
        case "fp":
          return im.fp_count > 0;
        case "fn":
          return im.fn_count > 0;
        case "cm":
          return im.class_mismatch_count > 0;
        case "no_tp":
          return im.tp_count === 0;
        default:
          return true;
      }
    });
  }, [data, filter]);

  const openResult = data?.image_results.find((im) => im.image_id === openImage) ?? null;

  return (
    <div className="page">
      {/* 最上段: タイトル左・推論ジョブ右上端 */}
      <div className="analysis-head">
        <h1>誤検出分析: {name}</h1>
        <label className="field analysis-job">
          推論ジョブ
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="" disabled>
              選択してください
            </option>
            {jobs.map((j) => (
              <option key={j.predict_job_id} value={j.predict_job_id}>
                {j.predict_job_id}（{j.status}）
              </option>
            ))}
          </select>
        </label>
      </div>

      <section className="card">
        <div className="row">
          <label className="field">
            iou_threshold
            <input type="number" step="0.05" min="0" max="1" value={iou} onChange={(e) => setIou(Number(e.target.value))} />
          </label>
          <label className="field">
            conf_threshold
            <input type="number" step="0.05" min="0" max="1" value={conf} onChange={(e) => setConf(Number(e.target.value))} />
          </label>
          <button onClick={run} disabled={busy || !selected}>
            {busy ? "分析中…" : "分析実行"}
          </button>
          <button onClick={reload} disabled={!selected}>
            再読込
          </button>
          {selected && (
            <button onClick={() => navigate(`/p/${name}/infer?job=${selected}`)}>
              推論結果へ
            </button>
          )}
        </div>
        {error && <div className="error">{error}</div>}
        {jobs.length === 0 && <p className="muted">推論ジョブがありません。</p>}
      </section>

      {data && (
        <>
          {/* サマリー(左) / クラス別統計(右) */}
          <div className="analysis-summary-cols">
            <section className="card">
              <h2 className="analysis-h2">サマリー</h2>
              <div className="analysis-stats">
                {[
                  { label: "画像数", value: data.summary.image_count },
                  { label: "GT数", value: data.summary.ground_truth_count },
                  { label: "pred数", value: data.summary.prediction_count },
                  { label: "TP", value: data.summary.tp_count },
                  { label: "FP", value: data.summary.fp_count, warn: true },
                  { label: "FN", value: data.summary.fn_count, warn: true },
                  { label: "mismatch", value: data.summary.class_mismatch_count, warn: true },
                  { label: "precision", value: fmt(data.summary.precision) },
                  { label: "recall", value: fmt(data.summary.recall) },
                  { label: "F1", value: fmt(data.summary.f1) },
                ].map((c) => (
                  <span key={c.label} className="summary-stat">
                    <span className={"summary-value" + (c.warn && Number(c.value) > 0 ? " warn" : "")}>
                      {c.value}
                    </span>
                    <span className="summary-label">{c.label}</span>
                  </span>
                ))}
              </div>
            </section>

            <section className="card">
              <h2 className="analysis-h2">クラス別統計</h2>
              <div className="table-scroll analysis-table">
                <table className="table">
                  <thead>
                    <tr>
                      <th>ID</th><th>クラス</th>
                      <th>GT<InfoTooltip placement="down" text="ground truth（正解ラベル）の数。このクラスの正解bbox件数です。" /></th>
                      <th>pred<InfoTooltip placement="down" text="このクラスとして予測（検出）した件数（conf閾値以上）。" /></th>
                      <th>TP<InfoTooltip placement="down" text="True Positive。正解クラスかつ IoU≥閾値 で正しく検出できた件数。" /></th>
                      <th>FP<InfoTooltip placement="down" text="False Positive。正解と対応しない/重複した誤検出の件数。多いと誤検出が多い。" /></th>
                      <th>FN<InfoTooltip placement="down" text="False Negative。検出できなかった正解（見逃し）の件数。多いと見逃しが多い。" /></th>
                      <th>mis<InfoTooltip placement="down" text="class_mismatch。位置(IoU≥閾値)は合うがクラスを取り違えた件数。クラス定義の見直しが有効。" /></th>
                      <th>prec<InfoTooltip placement="down" text="このクラスの適合率 = TP/(TP+FP)。検出のうち正解だった割合。" /></th>
                      <th>rec<InfoTooltip placement="down" text="このクラスの再現率 = TP/(TP+FN)。正解のうち検出できた割合。" /></th>
                      <th>F1<InfoTooltip placement="down" text="precision と recall の調和平均。総合的な検出性能の指標。" /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.class_stats.map((c) => (
                      <tr key={c.class_id}>
                        <td>{c.class_id}</td>
                        <td>{c.class_name}</td>
                        <td>{c.ground_truth_count}</td>
                        <td>{c.prediction_count}</td>
                        <td>{c.tp_count}</td>
                        <td className={c.fp_count > 0 ? "warn" : ""}>{c.fp_count}</td>
                        <td className={c.fn_count > 0 ? "warn" : ""}>{c.fn_count}</td>
                        <td className={c.class_mismatch_count > 0 ? "warn" : ""}>{c.class_mismatch_count}</td>
                        <td>{fmt(c.precision)}</td>
                        <td>{fmt(c.recall)}</td>
                        <td>{fmt(c.f1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          {/* 画像の詳細(左) / 画像別結果(右) */}
          <div className="analysis-result-cols">
            <section className="card analysis-detail-col">
              {openResult ? (
                <>
                  <h2 className="analysis-h2">
                    {openResult.image_name} の詳細{" "}
                    <button onClick={() => navigate(`/p/${name}/annotate?image=${encodeURIComponent(openResult.image_id)}`)}>
                      アノテーション画面へ
                    </button>
                  </h2>
                  {openResult.result_image_url && (
                    <img className="predict-image" src={openResult.result_image_url} alt={openResult.image_name} loading="lazy" />
                  )}
                  <div className="table-scroll analysis-table">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>type</th><th>class</th><th>GTクラス</th><th>conf</th><th>IoU</th>
                          <th>pred bbox</th><th>GT bbox</th>
                        </tr>
                      </thead>
                      <tbody>
                        {openResult.items.map((it, i) => (
                          <tr key={i}>
                            <td className={
                              it.type === "tp" ? "success" :
                              it.type === "class_mismatch" ? "warn" : "error"
                            }>{it.type}</td>
                            <td>{it.class_name ?? it.class_id ?? "-"}</td>
                            <td>{it.gt_class_name ?? it.gt_class_id ?? "-"}</td>
                            <td>{it.confidence !== null ? it.confidence.toFixed(3) : "-"}</td>
                            <td>{it.iou !== null ? it.iou.toFixed(3) : "-"}</td>
                            <td>
                              {it.prediction_bbox
                                ? `${it.prediction_bbox.x_center.toFixed(3)}, ${it.prediction_bbox.y_center.toFixed(3)}, ${it.prediction_bbox.width.toFixed(3)}, ${it.prediction_bbox.height.toFixed(3)}`
                                : "-"}
                            </td>
                            <td>
                              {it.ground_truth_bbox
                                ? `${it.ground_truth_bbox.x_center.toFixed(3)}, ${it.ground_truth_bbox.y_center.toFixed(3)}, ${it.ground_truth_bbox.width.toFixed(3)}, ${it.ground_truth_bbox.height.toFixed(3)}`
                                : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <>
                  <h2 className="analysis-h2">画像の詳細</h2>
                  <p className="muted">
                    右の「画像別結果」で画像の「詳細」を押すと、ここに結果画像と判定内訳（TP/FP/FN/mismatch）を表示します。
                  </p>
                </>
              )}
            </section>

            <section className="card analysis-list-col">
              <h2 className="analysis-h2">画像別結果</h2>
              <div className="row">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    className={"chip" + (filter === f.key ? " active" : "")}
                    onClick={() => setFilter(f.key)}
                  >
                    {f.label}
                  </button>
                ))}
                <span className="muted">{filtered.length} 件</span>
              </div>
              <div className="table-scroll analysis-table analysis-list-table">
                <table className="table">
                  <thead>
                    <tr>
                      <th>image</th><th>GT</th><th>pred</th><th>TP</th><th>FP</th>
                      <th>FN</th><th>mis</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((im) => (
                      <tr key={im.image_id} className={im.image_id === openImage ? "selected-row" : ""}>
                        <td>{im.image_name}</td>
                        <td>{im.ground_truth_count}</td>
                        <td>{im.prediction_count}</td>
                        <td>{im.tp_count}</td>
                        <td className={im.fp_count > 0 ? "warn" : ""}>{im.fp_count}</td>
                        <td className={im.fn_count > 0 ? "warn" : ""}>{im.fn_count}</td>
                        <td className={im.class_mismatch_count > 0 ? "warn" : ""}>{im.class_mismatch_count}</td>
                        <td>
                          <button onClick={() => setOpenImage(im.image_id)}>詳細</button>{" "}
                          <button onClick={() => navigate(`/p/${name}/annotate?image=${encodeURIComponent(im.image_id)}`)}>
                            修正
                          </button>
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={8} className="muted">該当する画像はありません。</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
