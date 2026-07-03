// 学習結果評価画面。ジョブ選択 → サマリー・成果物画像・メトリクス表・推移グラフ。
// completed / running / failed それぞれで画面が壊れないように分岐する。
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import HoverImagePreview from "../components/HoverImagePreview";
import InfoTooltip from "../components/InfoTooltip";
import type {
  Artifact,
  EvaluationResponse,
  MetricsResponse,
  TrainJobInfo,
} from "../types";

// メトリクス列名の候補（バックエンドと同じ揺れを吸収）
const COLS = {
  precision: ["metrics/precision(B)", "metrics/precision", "precision"],
  recall: ["metrics/recall(B)", "metrics/recall", "recall"],
  map50: ["metrics/mAP50(B)", "metrics/mAP50", "mAP50"],
  map50_95: ["metrics/mAP50-95(B)", "metrics/mAP50-95", "mAP50-95"],
  train_box: ["train/box_loss"],
  val_box: ["val/box_loss"],
};

function pickCol(columns: string[], candidates: string[]): string | null {
  for (const c of candidates) if (columns.includes(c)) return c;
  return null;
}

function fmt(v: number | null): string {
  return v === null || v === undefined ? "-" : v.toFixed(4);
}

// results.csv の列を「意味のまとまり」に分類する。テーブルの背景色分けに使用。
type ColCat = "meta" | "train-loss" | "val-loss" | "metric" | "lr" | "other";
function colCategory(col: string): ColCat {
  const c = col.toLowerCase();
  if (c === "epoch" || c.startsWith("time")) return "meta";
  if (c.startsWith("train/")) return "train-loss";
  if (c.startsWith("val/")) return "val-loss";
  if (c.startsWith("metrics/")) return "metric";
  if (c.startsWith("lr")) return "lr";
  return "other";
}
const CAT_LABEL: Record<ColCat, string> = {
  meta: "エポック・時間（メタ情報）",
  "train-loss": "学習データの損失（train/*）",
  "val-loss": "検証データの損失（val/*）",
  metric: "検証精度メトリクス（precision / recall / mAP）",
  lr: "学習率（lr）",
  other: "その他",
};
// 凡例に出す順序
const CAT_ORDER: ColCat[] = ["meta", "metric", "train-loss", "val-loss", "lr", "other"];

export default function EvaluatePage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<TrainJobInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [evalData, setEvalData] = useState<EvaluationResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listTrainJobs(name)
      .then((r) => {
        setJobs(r.jobs);
        const jobParam = searchParams.get("job"); // 実験履歴からの導線
        if (jobParam) setSelected(jobParam);
        else if (!selected && r.jobs.length > 0) setSelected(r.jobs[0].job_id);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  useEffect(() => {
    if (!selected) return;
    setError("");
    setEvalData(null);
    setMetrics(null);
    api.getEvaluation(name, selected).then(setEvalData).catch((e) => setError(String(e)));
    api.getMetrics(name, selected).then(setMetrics).catch(() => setMetrics(null));
  }, [name, selected]);

  // メトリクス行 → グラフ用データ
  const chartData = useMemo(() => {
    if (!metrics || metrics.rows.length === 0) return [];
    const cols = metrics.columns;
    const c = {
      precision: pickCol(cols, COLS.precision),
      recall: pickCol(cols, COLS.recall),
      map50: pickCol(cols, COLS.map50),
      map50_95: pickCol(cols, COLS.map50_95),
      train_box: pickCol(cols, COLS.train_box),
      val_box: pickCol(cols, COLS.val_box),
    };
    const num = (row: Record<string, unknown>, key: string | null) =>
      key && typeof row[key] === "number" ? (row[key] as number) : null;
    return metrics.rows.map((row, i) => ({
      epoch: typeof row["epoch"] === "number" ? (row["epoch"] as number) : i + 1,
      precision: num(row, c.precision),
      recall: num(row, c.recall),
      map50: num(row, c.map50),
      map50_95: num(row, c.map50_95),
      train_box: num(row, c.train_box),
      val_box: num(row, c.val_box),
    }));
  }, [metrics]);

  // グラフのコメント生成用に、系列の最終値・初期値（非null）を取り出すヘルパー。
  type SeriesKey = "precision" | "recall" | "map50" | "map50_95" | "train_box" | "val_box";
  const lastVal = (key: SeriesKey): number | null => {
    for (let i = chartData.length - 1; i >= 0; i--) {
      const v = chartData[i][key];
      if (typeof v === "number") return v;
    }
    return null;
  };
  const firstVal = (key: SeriesKey): number | null => {
    for (let i = 0; i < chartData.length; i++) {
      const v = chartData[i][key];
      if (typeof v === "number") return v;
    }
    return null;
  };

  // グラフごとの「概要（黒）」と「考察コメント（良かった点=青 / 改善点=赤）」を、
  // 現在の学習結果の最終値から一般的な傾向にもとづいて生成する。
  type ChartNote = { desc: string; verdict: "good" | "improve"; comment: string };
  function buildChartNote(kind: "map" | "pr" | "loss"): ChartNote {
    if (kind === "map") {
      const m50 = lastVal("map50");
      const m5095 = lastVal("map50_95");
      const desc =
        "mAP50 は IoU0.5 の緩い基準、mAP50-95 は 0.5〜0.95 の厳しい基準での平均精度です。エポックが進むほど右肩上がりになり、終盤で頭打ちになるのが理想です。";
      if (m50 == null)
        return { desc, verdict: "improve", comment: "mAP が記録されていません。学習途中、またはログ未出力の可能性があります。" };
      if (m50 >= 0.8 && m5095 != null && m5095 >= 0.5)
        return {
          desc,
          verdict: "good",
          comment: `最終 mAP50=${m50.toFixed(3)} / mAP50-95=${m5095.toFixed(3)} と高精度で、対象を安定して検出できています。この設定を基準にして問題ありません。`,
        };
      if (m5095 != null && m50 - m5095 > 0.3)
        return {
          desc,
          verdict: "improve",
          comment: `mAP50=${m50.toFixed(3)} に対し mAP50-95=${m5095.toFixed(3)} と差が大きく、検出はできても枠の位置精度が粗い傾向です。アノテーションのbbox精度の見直しや、エポック追加による収束が有効です。`,
        };
      return {
        desc,
        verdict: "improve",
        comment: `最終 mAP50=${m50.toFixed(3)} と伸び悩んでいます。学習エポックの追加、データ拡張の強化、画像枚数の増加を検討してください。`,
      };
    }
    if (kind === "pr") {
      const p = lastVal("precision");
      const r = lastVal("recall");
      const desc =
        "precision は誤検出の少なさ、recall は見逃しの少なさを表します。両方が高く、バランスが取れているのが理想です。";
      if (p == null || r == null)
        return { desc, verdict: "improve", comment: "precision / recall が記録されていません。" };
      if (p >= 0.8 && r >= 0.8)
        return {
          desc,
          verdict: "good",
          comment: `precision=${p.toFixed(3)} / recall=${r.toFixed(3)} と高い水準で両立できています。誤検出・見逃しともに少ない良好な状態です。`,
        };
      if (r < p - 0.1)
        return {
          desc,
          verdict: "improve",
          comment: `recall=${r.toFixed(3)} が precision=${p.toFixed(3)} より低く、見逃しが多い傾向です。画像枚数の追加、対象の角度・距離・明るさのバリエーション強化、confidence閾値の引き下げが有効です。`,
        };
      if (p < r - 0.1)
        return {
          desc,
          verdict: "improve",
          comment: `precision=${p.toFixed(3)} が recall=${r.toFixed(3)} より低く、誤検出が多い傾向です。ネガティブ画像の追加、クラス定義の見直し、ラベルの誤り確認が有効です。`,
        };
      return {
        desc,
        verdict: "improve",
        comment: `precision=${p.toFixed(3)} / recall=${r.toFixed(3)} ともに改善余地があります。データ量とアノテーション品質の見直しを推奨します。`,
      };
    }
    // kind === "loss"
    const tb0 = firstVal("train_box");
    const tb = lastVal("train_box");
    const vb = lastVal("val_box");
    const desc =
      "train / val の box loss は枠の位置・大きさの誤差です。両方が下がり続け、両者の差が小さいのが理想で、val が train より大きく開くと過学習のサインです。";
    if (tb == null) return { desc, verdict: "improve", comment: "box loss が記録されていません。" };
    if (vb != null && vb > tb * 1.5 && vb - tb > 0.1)
      return {
        desc,
        verdict: "improve",
        comment: `val box loss (${vb.toFixed(3)}) が train (${tb.toFixed(3)}) より大きく乖離しており、過学習の傾向です。データ拡張の強化、学習データの追加、早期終了（epoch短縮）の検討が有効です。`,
      };
    if (tb0 != null && tb0 - tb < 0.05)
      return {
        desc,
        verdict: "improve",
        comment: `train box loss が ${tb0.toFixed(3)} → ${tb.toFixed(3)} とほとんど下がっておらず、学習不足の可能性があります。学習率・エポック数・モデルサイズの見直しを検討してください。`,
      };
    return {
      desc,
      verdict: "good",
      comment: `train box loss が着実に低下し${
        vb != null ? `、val (${vb.toFixed(3)}) との乖離も小さく` : ""
      }良好に学習できています。`,
    };
  }

  // Ultralyticsのバージョンで曲線画像名に "Box" 接頭辞が付く場合があるため、
  // 正規名 or "box"+正規名（大文字小文字無視）で一致を取る。
  const artifactByName = (n: string): Artifact | undefined => {
    const t = n.toLowerCase();
    return evalData?.artifacts.find((a) => {
      const an = a.name.toLowerCase();
      return an === t || an === "box" + t;
    });
  };

  const showImages = ["results.png", "confusion_matrix.png", "PR_curve.png", "F1_curve.png", "P_curve.png", "R_curve.png", "labels.jpg"];

  function renderChart(
    title: string,
    series: { key: string; label: string; color: string }[],
    kind: "map" | "pr" | "loss"
  ) {
    const note = buildChartNote(kind);
    return (
      <div className="chart-box">
        <h3>{title}</h3>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="epoch" />
            <YAxis />
            <Tooltip />
            <Legend />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <p className="chart-desc">{note.desc}</p>
        <p className={"chart-comment " + note.verdict}>
          <strong>{note.verdict === "good" ? "良かった点: " : "反省・改善点: "}</strong>
          {note.comment}
        </p>
      </div>
    );
  }

  // 検出・マスクのサマリーカード定義
  const detectionCards = evalData?.summary
    ? [
        { label: "precision", value: evalData.summary.precision, tip: "検出したもののうち、正解だった割合です。\n高いほど「誤検出が少ない」状態です。\n低い場合は、背景や別物を対象物として検出している可能性があります。\nネガティブ画像の追加、クラス定義の見直し、ラベルの誤り確認が有効です。" },
        { label: "recall", value: evalData.summary.recall, tip: "本来検出すべき対象のうち、実際に検出できた割合です。\n高いほど「見逃しが少ない」状態です。\n低い場合は、対象物を検出できていない画像が多い可能性があります。\n画像枚数の追加、対象物の角度・距離・明るさのバリエーション追加、confidence閾値の見直しが有効です。" },
        { label: "mAP50", value: evalData.summary.map50, tip: "IoU 0.50 を基準にした平均適合率です。\n検出枠が正解枠と50%以上重なれば正解として評価されます。\n物体検出でよく使われる代表的な精度指標です。\nただし、mAP50だけが高くても、枠の位置精度が粗い場合があります。" },
        { label: "mAP50-95", value: evalData.summary.map50_95, tip: "IoU 0.50〜0.95 を複数段階で評価した平均適合率です。\nmAP50より厳しい指標で、bboxの位置精度も強く反映されます。\nこの値が低い場合は、検出はできていても枠の位置がズレている可能性があります。\nアノテーションのbbox精度を見直す際の参考になります。" },
        { label: "box_loss", value: evalData.summary.train_box_loss, tip: "bboxの位置や大きさのズレに関する損失です。\n低いほど、予測枠が正解枠に近づいています。\n高い場合は、bboxの付け方が不安定、対象物サイズのばらつきが大きい、または学習不足の可能性があります。" },
        { label: "cls_loss", value: evalData.summary.train_cls_loss, tip: "クラス分類に関する損失です。\n低いほど、対象物を正しいクラスとして分類できています。\n高い場合は、クラス間の見た目が似ている、ラベルの付け間違いがある、またはクラスごとの画像数が不足している可能性があります。" },
        { label: "dfl_loss", value: evalData.summary.train_dfl_loss, tip: "bbox境界位置の分布推定に関する損失です。\n低いほど、bboxの境界位置が安定しています。\nbox_lossとあわせて確認することで、枠の位置精度の改善状況を判断できます。" },
      ]
    : [];
  const maskCards =
    evalData?.summary && evalData.summary.mask_map50 != null
      ? [
          { label: "mask_precision", value: evalData.summary.mask_precision, tip: "マスク（輪郭領域）に対する適合率です。\n検出した領域のうち正解だった割合で、高いほど誤検出が少ない状態です。" },
          { label: "mask_recall", value: evalData.summary.mask_recall, tip: "マスクに対する再現率です。\n本来検出すべき領域のうち検出できた割合で、高いほど見逃しが少ない状態です。" },
          { label: "mask_mAP50", value: evalData.summary.mask_map50, tip: "IoU 0.50 基準のマスク平均適合率です。\nマスク領域が50%以上重なれば正解として評価されます。" },
          { label: "mask_mAP50-95", value: evalData.summary.mask_map50_95, tip: "IoU 0.50〜0.95 のマスク平均適合率です。\nより厳しい指標で、輪郭の一致精度も強く反映されます。" },
        ]
      : [];

  const renderCards = (cards: { label: string; value: number | null; tip: string }[]) => (
    <div className="metrics-compact-grid">
      {cards.map((c) => (
        <div key={c.label} className="metric-card-compact">
          <div className="metric-value">{fmt(c.value)}</div>
          <div className="metric-label">{c.label}<InfoTooltip text={c.tip} /></div>
        </div>
      ))}
    </div>
  );

  // テーブルに実在するカテゴリのみ凡例に出す
  const presentCats = metrics
    ? CAT_ORDER.filter((cat) => metrics.columns.some((c) => colCategory(c) === cat))
    : [];

  return (
    <div className="page">
      {/* 最上段：タイトル（左）と学習ジョブ選択（右端） */}
      <div className="eval-head">
        <h1>評価: {name}</h1>
        <label className="field eval-job">
          学習ジョブ
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="" disabled>
              選択してください
            </option>
            {jobs.map((j) => (
              <option key={j.job_id} value={j.job_id}>
                {j.job_id}（{j.status}）
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="error">{error}</div>}
      {jobs.length === 0 && <p className="muted">学習ジョブがありません。</p>}

      {evalData && (
        <>
          {/* 状態別の案内 */}
          {(evalData.status === "running" || evalData.status === "queued") && (
            <div className="warn">学習中のため評価未確定です。</div>
          )}
          {evalData.status === "failed" && (
            <div className="error">
              学習失敗しました。{" "}
              <button onClick={() => navigate(`/p/${name}/train`)}>
                ログ画面へ
              </button>
            </div>
          )}

          {/* 有無 */}
          <p className="muted">
            best.pt: {evalData.has_best_model ? "あり" : "なし"} / last.pt:{" "}
            {evalData.has_last_model ? "あり" : "なし"} / results.csv:{" "}
            {evalData.has_results_csv ? "あり" : "なし"}
          </p>

          {/* サマリーカード：検出とマスクを別コンテナに分け、横1行に並べる */}
          {evalData.summary ? (
            <div className={"metric-groups-row" + (maskCards.length > 0 ? "" : " single")}>
              <div className="metric-group">
                <div className="metric-group-title">検出（Detection）メトリクス</div>
                {renderCards(detectionCards)}
              </div>
              {maskCards.length > 0 && (
                <div className="metric-group mask">
                  <div className="metric-group-title">セグメンテーション（Mask）メトリクス</div>
                  {renderCards(maskCards)}
                </div>
              )}
            </div>
          ) : (
            <p className="muted">results.csv が未生成のため、サマリーはありません。</p>
          )}

          {/* グラフ（各グラフ下に概要＋考察コメント） */}
          {chartData.length > 0 && (
            <div className="chart-grid">
              {renderChart(
                "mAP50 / mAP50-95 推移",
                [
                  { key: "map50", label: "mAP50", color: "#2563eb" },
                  { key: "map50_95", label: "mAP50-95", color: "#16a34a" },
                ],
                "map"
              )}
              {renderChart(
                "precision / recall 推移",
                [
                  { key: "precision", label: "precision", color: "#9333ea" },
                  { key: "recall", label: "recall", color: "#ea580c" },
                ],
                "pr"
              )}
              {renderChart(
                "train / val box loss 推移",
                [
                  { key: "train_box", label: "train box loss", color: "#dc2626" },
                  { key: "val_box", label: "val box loss", color: "#0891b2" },
                ],
                "loss"
              )}
            </div>
          )}

          {/* 成果物画像 */}
          <h2>学習成果物</h2>
          <div className="artifact-grid">
            {showImages.map((n) => {
              const a = artifactByName(n);
              return (
                <figure key={n} className="artifact">
                  <figcaption className="muted">{n}</figcaption>
                  {a ? (
                    // results.png は多パネルで小さく見えるため、他より大きい倍率で表示する
                    <HoverImagePreview
                      thumbSrc={a.url}
                      fullSrc={a.url}
                      alt={n}
                      center
                      maxW={n === "results.png" ? 1500 : 1040}
                      maxH={n === "results.png" ? 1150 : 780}
                    />
                  ) : (
                    <div className="artifact-missing">未生成</div>
                  )}
                </figure>
              );
            })}
          </div>

          {/* メトリクステーブル */}
          {metrics && metrics.rows.length > 0 && (
            <>
              <h2>メトリクス（results.csv）</h2>
              <div className="table-scroll">
                <table className="table metrics-table">
                  <thead>
                    <tr>
                      {metrics.columns.map((c) => (
                        <th key={c} className={"col-" + colCategory(c)}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.rows.map((row, i) => (
                      <tr key={i}>
                        {metrics.columns.map((c) => (
                          <td key={c} className={"col-" + colCategory(c)}>{String(row[c] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* 色分けの凡例 */}
              {presentCats.length > 0 && (
                <div className="table-legend">
                  <span className="muted">列の背景色は項目のまとまりを表します：</span>
                  {presentCats.map((cat) => (
                    <span key={cat} className="legend-item">
                      <span className={"legend-chip col-" + cat} />
                      {CAT_LABEL[cat]}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
