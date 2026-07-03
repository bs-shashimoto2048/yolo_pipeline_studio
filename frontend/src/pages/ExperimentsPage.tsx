// 実験履歴画面。学習ジョブ=実験として一覧・横並び比較、フィルタ/並び替え、詳細、導線。
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ExperimentDetailResponse, ExperimentListItem } from "../types";

type Filter = "all" | "completed" | "failed" | "best" | "analysis";
type Sort =
  | "finished_desc"
  | "map50_desc"
  | "map5095_desc"
  | "recall_desc"
  | "precision_desc"
  | "f1_desc"
  | "fn_asc"
  | "fp_asc";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "すべて" },
  { key: "completed", label: "completedのみ" },
  { key: "failed", label: "failedのみ" },
  { key: "best", label: "best.ptあり" },
  { key: "analysis", label: "分析あり" },
];

const SORTS: { key: Sort; label: string }[] = [
  { key: "finished_desc", label: "finished_at 降順" },
  { key: "map50_desc", label: "mAP50 降順" },
  { key: "map5095_desc", label: "mAP50-95 降順" },
  { key: "recall_desc", label: "recall 降順" },
  { key: "precision_desc", label: "precision 降順" },
  { key: "f1_desc", label: "分析F1 降順" },
  { key: "fn_asc", label: "FN 昇順" },
  { key: "fp_asc", label: "FP 昇順" },
];

const num = (v: number | null | undefined, d = 4): string =>
  v === null || v === undefined ? "-" : v.toFixed(d);

export default function ExperimentsPage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const [experiments, setExperiments] = useState<ExperimentListItem[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("finished_desc");
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ExperimentDetailResponse | null>(null);

  useEffect(() => {
    api
      .listExperiments(name)
      .then((r) => setExperiments(r.experiments))
      .catch((e) => setError(String(e)));
  }, [name]);

  useEffect(() => {
    if (!openId) {
      setDetail(null);
      return;
    }
    api.getExperiment(name, openId).then(setDetail).catch((e) => setError(String(e)));
  }, [name, openId]);

  const view = useMemo(() => {
    const f = experiments.filter((e) => {
      switch (filter) {
        case "completed":
          return e.status === "completed";
        case "failed":
          return e.status === "failed";
        case "best":
          return !!e.best_model_path;
        case "analysis":
          return e.latest_analysis !== null;
        default:
          return true;
      }
    });
    const desc = (a: number | null | undefined, b: number | null | undefined) =>
      (b ?? -Infinity) - (a ?? -Infinity);
    const asc = (a: number | null | undefined, b: number | null | undefined) =>
      (a ?? Infinity) - (b ?? Infinity);
    const sorted = [...f];
    sorted.sort((a, b) => {
      switch (sort) {
        case "map50_desc":
          return desc(a.map50, b.map50);
        case "map5095_desc":
          return desc(a.map50_95, b.map50_95);
        case "recall_desc":
          return desc(a.recall, b.recall);
        case "precision_desc":
          return desc(a.precision, b.precision);
        case "f1_desc":
          return desc(a.latest_analysis?.f1, b.latest_analysis?.f1);
        case "fn_asc":
          return asc(a.latest_analysis?.fn_count, b.latest_analysis?.fn_count);
        case "fp_asc":
          return asc(a.latest_analysis?.fp_count, b.latest_analysis?.fp_count);
        default:
          return (b.finished_at ?? "").localeCompare(a.finished_at ?? "");
      }
    });
    return sorted;
  }, [experiments, filter, sort]);

  return (
    <div className="page">
      <h1>実験履歴: {name}</h1>
      {error && <div className="error">{error}</div>}

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
        <span style={{ flex: 1 }} />
        <label className="field">
          並び替え
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {experiments.length === 0 ? (
        <p className="muted">実験（学習ジョブ）がありません。</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>experiment</th><th>status</th><th>dataset</th><th>model</th>
                <th>epochs</th><th>imgsz</th><th>batch</th><th>device</th><th>aug</th>
                <th>train</th><th>val</th>
                <th>precision</th><th>recall</th><th>mAP50</th><th>mAP50-95</th>
                <th>分析F1</th><th>FP</th><th>FN</th><th>mismatch</th>
                <th>finished_at</th><th></th>
              </tr>
            </thead>
            <tbody>
              {view.map((e) => {
                const a = e.latest_analysis;
                return (
                  <tr key={e.experiment_id} className={e.experiment_id === openId ? "selected-row" : ""}>
                    <td>{e.experiment_id}</td>
                    <td className={e.status === "completed" ? "success" : e.status === "failed" ? "error" : "warn"}>
                      {e.status}
                    </td>
                    <td>{e.dataset_name ?? "-"}</td>
                    <td>{e.model ?? "-"}</td>
                    <td>{e.epochs ?? "-"}</td>
                    <td>{e.imgsz ?? "-"}</td>
                    <td>{e.batch ?? "-"}</td>
                    <td>{e.device ?? "-"}</td>
                    <td>{e.augmentation_preset ?? "-"}</td>
                    <td>{e.train_image_count ?? "-"}</td>
                    <td>{e.val_image_count ?? "-"}</td>
                    <td>{num(e.precision)}</td>
                    <td>{num(e.recall)}</td>
                    <td>{num(e.map50)}</td>
                    <td>{num(e.map50_95)}</td>
                    <td>{a ? num(a.f1) : "-"}</td>
                    <td className={a && a.fp_count > 0 ? "warn" : ""}>{a ? a.fp_count : "-"}</td>
                    <td className={a && a.fn_count > 0 ? "warn" : ""}>{a ? a.fn_count : "-"}</td>
                    <td className={a && a.class_mismatch_count > 0 ? "warn" : ""}>{a ? a.class_mismatch_count : "-"}</td>
                    <td className="muted">{e.finished_at ?? "-"}</td>
                    <td>
                      <button onClick={() => setOpenId(e.experiment_id)}>詳細</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <section className="card">
          <div className="exp-detail-head">
            <h2>実験詳細: {detail.experiment_id}</h2>
            <div className="row">
              <button className="secondary" onClick={() => navigate(`/p/${name}/eval?job=${detail.experiment_id}`)}>
                評価画面へ
              </button>
              <button className="secondary" onClick={() => navigate(`/p/${name}/infer?train_job=${detail.experiment_id}`)}>
                推論画面へ
              </button>
            </div>
          </div>

          {/* 学習条件 / データセット / 評価 を全幅タイルで敷き詰める */}
          <div className="exp-specs">
            <section>
              <div className="spec-section-title">学習条件</div>
              <div className="kv-grid">
                <div className="kv"><span className="k">status</span><span className={"v " + (detail.train_job?.status === "completed" ? "success" : detail.train_job?.status === "failed" ? "error" : "")}>{detail.train_job?.status ?? "-"}</span></div>
                <div className="kv"><span className="k">model</span><span className="v">{detail.train_job?.model ?? "-"}</span></div>
                <div className="kv"><span className="k">epochs</span><span className="v">{detail.train_job?.epochs ?? "-"}</span></div>
                <div className="kv"><span className="k">imgsz</span><span className="v">{detail.train_job?.imgsz ?? "-"}</span></div>
                <div className="kv"><span className="k">batch</span><span className="v">{detail.train_job?.batch ?? "-"}</span></div>
                <div className="kv"><span className="k">device</span><span className="v">{detail.train_job?.device ?? "-"}</span></div>
                <div className="kv"><span className="k">seed</span><span className="v">{detail.train_job?.seed ?? "-"}</span></div>
                <div className="kv"><span className="k">patience</span><span className="v">{detail.train_job?.patience ?? "-"}</span></div>
              </div>
            </section>

            <section>
              <div className="spec-section-title">データセット</div>
              {detail.dataset ? (
                <div className="kv-grid">
                  <div className="kv"><span className="k">name</span><span className="v">{detail.dataset.dataset_name ?? "-"}</span></div>
                  <div className="kv"><span className="k">train</span><span className="v">{detail.dataset.train_image_count ?? "-"} 枚</span></div>
                  <div className="kv"><span className="k">val</span><span className="v">{detail.dataset.val_image_count ?? "-"} 枚</span></div>
                  <div className="kv"><span className="k">test</span><span className="v">{detail.dataset.test_image_count ?? "-"} 枚</span></div>
                  <div className="kv"><span className="k">class</span><span className="v">{detail.dataset.class_count ?? "-"}</span></div>
                  <div className="kv"><span className="k">ratios (t/v/te)</span><span className="v">{num(detail.dataset.train_ratio, 2)} / {num(detail.dataset.val_ratio, 2)} / {num(detail.dataset.test_ratio, 2)}</span></div>
                </div>
              ) : (
                <p className="muted">データセット情報なし</p>
              )}
            </section>

            <section>
              <div className="spec-section-title">評価</div>
              {detail.evaluation ? (
                <div className="kv-grid">
                  <div className="kv"><span className="k">precision</span><span className="v">{num(detail.evaluation.precision)}</span></div>
                  <div className="kv"><span className="k">recall</span><span className="v">{num(detail.evaluation.recall)}</span></div>
                  <div className="kv"><span className="k">mAP50</span><span className="v">{num(detail.evaluation.map50)}</span></div>
                  <div className="kv"><span className="k">mAP50-95</span><span className="v">{num(detail.evaluation.map50_95)}</span></div>
                  <div className="kv kv-wide"><span className="k">weights</span><span className="v">best {detail.evaluation.has_best_model ? "○" : "×"} / last {detail.evaluation.has_last_model ? "○" : "×"} / csv {detail.evaluation.has_results_csv ? "○" : "×"}</span></div>
                </div>
              ) : (
                <p className="muted">評価情報なし</p>
              )}
            </section>
          </div>

          <div className="spec-section-title">推論・誤検出分析（{detail.predictions.length}）</div>
          {detail.predictions.length === 0 ? (
            <p className="muted">この実験を使った推論ジョブはありません。</p>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>predict_job</th><th>status</th><th>画像</th><th>検出</th>
                    <th>TP</th><th>FP</th><th>FN</th><th>mismatch</th><th>F1</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {detail.predictions.map((p) => (
                    <tr key={p.predict_job_id}>
                      <td>{p.predict_job_id}</td>
                      <td className={p.status === "completed" ? "success" : p.status === "failed" ? "error" : "warn"}>{p.status ?? "-"}</td>
                      <td>{p.image_count ?? "-"}</td>
                      <td>{p.detection_count ?? "-"}</td>
                      <td>{p.analysis?.tp_count ?? "-"}</td>
                      <td className={p.analysis && p.analysis.fp_count > 0 ? "warn" : ""}>{p.analysis?.fp_count ?? "-"}</td>
                      <td className={p.analysis && p.analysis.fn_count > 0 ? "warn" : ""}>{p.analysis?.fn_count ?? "-"}</td>
                      <td className={p.analysis && p.analysis.class_mismatch_count > 0 ? "warn" : ""}>{p.analysis?.class_mismatch_count ?? "-"}</td>
                      <td>{p.analysis ? num(p.analysis.f1) : "-"}</td>
                      <td>
                        <button onClick={() => navigate(`/p/${name}/analysis?job=${p.predict_job_id}`)}>
                          分析へ
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
