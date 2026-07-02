// モデル管理画面。best.pt/last.pt を一覧化し、評価/分析と紐付けて比較、採用モデル設定。
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  ModelItem,
  ModelListResponse,
  ModelPackageResponse,
  OnnxExportInfo,
} from "../types";

const ONNX_DEFAULTS = {
  weight_type: "best",
  imgsz: 640,
  opset: 12,
  simplify: true,
  dynamic: false,
  half: false,
  device: "cpu",
  overwrite: false,
};

function onnxStatusClass(status: string): string {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "running" || status === "queued") return "warn";
  return "muted";
}

function triggerDownload(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

type Filter = "all" | "best" | "last" | "selected" | "exists" | "analysis";
type Sort =
  | "map50_desc" | "map5095_desc" | "recall_desc" | "precision_desc"
  | "f1_desc" | "fn_asc" | "fp_asc" | "created_desc";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "すべて" },
  { key: "best", label: "bestのみ" },
  { key: "last", label: "lastのみ" },
  { key: "selected", label: "採用モデルのみ" },
  { key: "exists", label: "存在するモデルのみ" },
  { key: "analysis", label: "分析あり" },
];

const SORTS: { key: Sort; label: string }[] = [
  { key: "map50_desc", label: "mAP50 降順" },
  { key: "map5095_desc", label: "mAP50-95 降順" },
  { key: "recall_desc", label: "recall 降順" },
  { key: "precision_desc", label: "precision 降順" },
  { key: "f1_desc", label: "分析F1 降順" },
  { key: "fn_asc", label: "FN 昇順" },
  { key: "fp_asc", label: "FP 昇順" },
  { key: "created_desc", label: "created_at 降順" },
];

const num = (v: number | null | undefined, d = 4): string =>
  v === null || v === undefined ? "-" : v.toFixed(d);

function sizeMB(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "-";
  return (bytes / 1024 / 1024).toFixed(2) + " MB";
}

export default function ModelsPage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<ModelListResponse | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("map50_desc");
  const [openId, setOpenId] = useState<string | null>(null);
  const [memo, setMemo] = useState("");
  const [pkg, setPkg] = useState<ModelPackageResponse | null>(null);
  const [pkgBusy, setPkgBusy] = useState(false);
  // ONNX
  const [projectTask, setProjectTask] = useState<string>("detect");
  const [onnxExports, setOnnxExports] = useState<OnnxExportInfo[]>([]);
  const [onnx, setOnnx] = useState({ ...ONNX_DEFAULTS });
  const [onnxBusy, setOnnxBusy] = useState(false);
  const [onnxError, setOnnxError] = useState("");
  const [onnxLog, setOnnxLog] = useState<{ id: string; text: string } | null>(null);
  const [includeOnnx, setIncludeOnnx] = useState(false);
  const [onnxJobForPkg, setOnnxJobForPkg] = useState("");

  async function createPackage(m: ModelItem) {
    setPkgBusy(true);
    setError("");
    try {
      setPkg(
        await api.createModelPackage(name, m.train_job_id, m.weight_type, {
          include_onnx: includeOnnx,
          onnx_export_job_id: includeOnnx ? onnxJobForPkg : null,
        })
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setPkgBusy(false);
    }
  }

  async function reloadOnnx() {
    try {
      setOnnxExports((await api.listOnnxExports(name)).exports);
    } catch {
      /* ignore */
    }
  }

  async function startOnnx(m: ModelItem) {
    setOnnxBusy(true);
    setOnnxError("");
    try {
      await api.startOnnxExport(name, {
        train_job_id: m.train_job_id,
        weight_type: onnx.weight_type,
        imgsz: onnx.imgsz,
        opset: onnx.opset,
        simplify: onnx.simplify,
        dynamic: onnx.dynamic,
        half: onnx.half,
        device: onnx.device,
        overwrite: onnx.overwrite,
      });
      await reloadOnnx();
    } catch (e) {
      setOnnxError(String(e));
    } finally {
      setOnnxBusy(false);
    }
  }

  async function showOnnxLog(id: string) {
    try {
      const r = await api.getOnnxExportLogs(name, id);
      setOnnxLog({ id, text: r.log || "（ログはまだありません）" });
    } catch (e) {
      setOnnxError(String(e));
    }
  }

  async function reload() {
    try {
      setData(await api.listModels(name));
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    reload();
    reloadOnnx();
    api.getProject(name).then((p) => setProjectTask(p.task ?? "detect")).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  // 実行中のONNXエクスポートがあればポーリング
  useEffect(() => {
    const active = onnxExports.some((e) => e.status === "queued" || e.status === "running");
    if (!active) return;
    const t = window.setTimeout(reloadOnnx, 2000);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onnxExports]);

  async function select(m: ModelItem) {
    setError("");
    try {
      await api.setSelectedModel(name, m.train_job_id, m.weight_type, memo);
      setMemo("");
      await reload();
    } catch (e) {
      setError(String(e));
    }
  }

  const view = useMemo<ModelItem[]>(() => {
    if (!data) return [];
    const f = data.models.filter((m) => {
      switch (filter) {
        case "best": return m.weight_type === "best";
        case "last": return m.weight_type === "last";
        case "selected": return m.is_selected;
        case "exists": return m.exists;
        case "analysis": return m.latest_analysis !== null;
        default: return true;
      }
    });
    const desc = (a: number | null | undefined, b: number | null | undefined) =>
      (b ?? -Infinity) - (a ?? -Infinity);
    const asc = (a: number | null | undefined, b: number | null | undefined) =>
      (a ?? Infinity) - (b ?? Infinity);
    return [...f].sort((a, b) => {
      switch (sort) {
        case "map5095_desc": return desc(a.map50_95, b.map50_95);
        case "recall_desc": return desc(a.recall, b.recall);
        case "precision_desc": return desc(a.precision, b.precision);
        case "f1_desc": return desc(a.latest_analysis?.f1, b.latest_analysis?.f1);
        case "fn_asc": return asc(a.latest_analysis?.fn_count, b.latest_analysis?.fn_count);
        case "fp_asc": return asc(a.latest_analysis?.fp_count, b.latest_analysis?.fp_count);
        case "created_desc": return (b.created_at ?? "").localeCompare(a.created_at ?? "");
        default: return desc(a.map50, b.map50);
      }
    });
  }, [data, filter, sort]);

  const openModel = data?.models.find((m) => m.model_id === openId) ?? null;
  const selectedModel = data?.models.find((m) => m.is_selected) ?? null;

  return (
    <div className="page">
      <h1>モデル管理: {name}</h1>
      {error && <div className="error">{error}</div>}

      <section className="card selected-model-bar">
        <span className="selected-model-label">採用モデル</span>
        {selectedModel ? (
          <>
            <span className="selected-model-info">
              <strong>{selectedModel.model_id}</strong>
              <span className="muted">
                {selectedModel.dataset_name} / mAP50 {num(selectedModel.map50)}
              </span>
            </span>
            <button
              className="secondary"
              onClick={() => navigate(`/p/${name}/infer?train_job=${selectedModel.train_job_id}&weight=${selectedModel.weight_type}`)}
            >
              このモデルで推論
            </button>
          </>
        ) : (
          <span className="muted">未設定です。一覧から設定してください。</span>
        )}
      </section>

      <div className="row">
        {FILTERS.map((f) => (
          <button key={f.key} className={"chip" + (filter === f.key ? " active" : "")} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <label className="field">
          並び替え
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>model_id</th><th>採用</th><th>weight</th><th>存在</th><th>サイズ</th>
              <th>dataset</th><th>base</th><th>epochs</th><th>imgsz</th><th>batch</th><th>device</th><th>aug</th>
              <th>precision</th><th>recall</th><th>mAP50</th><th>mAP50-95</th>
              <th>分析F1</th><th>FP</th><th>FN</th><th>mismatch</th><th>created</th><th></th>
            </tr>
          </thead>
          <tbody>
            {view.map((m) => {
              const a = m.latest_analysis;
              return (
                <tr key={m.model_id} className={m.model_id === openId ? "selected-row" : ""}>
                  <td>{m.model_id}</td>
                  <td>{m.is_selected ? "★" : ""}</td>
                  <td>{m.weight_type}</td>
                  <td className={m.exists ? "success" : "error"}>{m.exists ? "あり" : "なし"}</td>
                  <td>{sizeMB(m.file_size_bytes)}</td>
                  <td>{m.dataset_name ?? "-"}</td>
                  <td>{m.base_model ?? "-"}</td>
                  <td>{m.epochs ?? "-"}</td>
                  <td>{m.imgsz ?? "-"}</td>
                  <td>{m.batch ?? "-"}</td>
                  <td>{m.device ?? "-"}</td>
                  <td>{m.augmentation_preset ?? "-"}</td>
                  <td>{num(m.precision)}</td>
                  <td>{num(m.recall)}</td>
                  <td>{num(m.map50)}</td>
                  <td>{num(m.map50_95)}</td>
                  <td>{a ? num(a.f1) : "-"}</td>
                  <td className={a && a.fp_count > 0 ? "warn" : ""}>{a ? a.fp_count : "-"}</td>
                  <td className={a && a.fn_count > 0 ? "warn" : ""}>{a ? a.fn_count : "-"}</td>
                  <td className={a && a.class_mismatch_count > 0 ? "warn" : ""}>{a ? a.class_mismatch_count : "-"}</td>
                  <td className="muted">{m.created_at ?? "-"}</td>
                  <td>
                    <button
                      onClick={() => {
                        setOpenId(m.model_id);
                        setPkg(null);
                        setOnnx({ ...ONNX_DEFAULTS, weight_type: m.weight_type, imgsz: m.imgsz ?? 640 });
                        setOnnxLog(null);
                        setOnnxError("");
                        setIncludeOnnx(false);
                        setOnnxJobForPkg("");
                      }}
                    >
                      詳細
                    </button>
                  </td>
                </tr>
              );
            })}
            {view.length === 0 && (
              <tr><td colSpan={22} className="muted">モデルがありません。</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {openModel && (
        <section className="card">
          <h2>モデル詳細: {openModel.model_id}</h2>

          {/* 左: モデル詳細(3) / 右: モデル配布・ONNXエクスポート(7) */}
          <div className="model-detail-cols">
            {/* 左: モデル詳細 */}
            <div className="model-detail-left">
              <dl className="spec-list">
                <div className="spec-row"><dt>weight</dt><dd>{openModel.weight_type}{openModel.is_selected ? " ★採用中" : ""}</dd></div>
                <div className="spec-row"><dt>存在</dt><dd className={openModel.exists ? "success" : "error"}>{openModel.exists ? "あり" : "なし"} / {sizeMB(openModel.file_size_bytes)}</dd></div>
                <div className="spec-row"><dt>dataset</dt><dd>{openModel.dataset_name ?? "-"}</dd></div>
                <div className="spec-row"><dt>base</dt><dd>{openModel.base_model ?? "-"}</dd></div>
                <div className="spec-row"><dt>epochs</dt><dd>{openModel.epochs ?? "-"}</dd></div>
                <div className="spec-row"><dt>imgsz</dt><dd>{openModel.imgsz ?? "-"}</dd></div>
                <div className="spec-row"><dt>batch</dt><dd>{openModel.batch ?? "-"}</dd></div>
                <div className="spec-row"><dt>device</dt><dd>{openModel.device ?? "-"}</dd></div>
                <div className="spec-row"><dt>aug</dt><dd>{openModel.augmentation_preset ?? "-"}</dd></div>
                <div className="spec-row"><dt>created</dt><dd className="muted">{openModel.created_at ?? "-"}</dd></div>
                <div className="spec-row"><dt>path</dt><dd><code>{openModel.model_path}</code></dd></div>
              </dl>

              <div className="spec-section-title">評価</div>
              <div className="model-metrics">
                {[
                  { label: "precision", value: num(openModel.precision) },
                  { label: "recall", value: num(openModel.recall) },
                  { label: "mAP50", value: num(openModel.map50) },
                  { label: "mAP50-95", value: num(openModel.map50_95) },
                ].map((c) => (
                  <span key={c.label} className="summary-stat">
                    <span className="summary-value">{c.value}</span>
                    <span className="summary-label">{c.label}</span>
                  </span>
                ))}
              </div>

              {openModel.latest_analysis && (
                <>
                  <div className="spec-section-title">最新分析</div>
                  <div className="model-metrics">
                    {[
                      { label: "F1", value: num(openModel.latest_analysis.f1), warn: false },
                      { label: "TP", value: String(openModel.latest_analysis.tp_count), warn: false },
                      { label: "FP", value: String(openModel.latest_analysis.fp_count), warn: openModel.latest_analysis.fp_count > 0 },
                      { label: "FN", value: String(openModel.latest_analysis.fn_count), warn: openModel.latest_analysis.fn_count > 0 },
                    ].map((c) => (
                      <span key={c.label} className="summary-stat">
                        <span className={"summary-value" + (c.warn ? " warn" : "")}>{c.value}</span>
                        <span className="summary-label">{c.label}</span>
                      </span>
                    ))}
                  </div>
                </>
              )}

              <div className="model-detail-actions">
                <input
                  className="model-memo"
                  placeholder="採用メモ（任意）"
                  value={memo}
                  onChange={(e) => setMemo(e.target.value)}
                />
                <button onClick={() => select(openModel)} disabled={!openModel.exists}>
                  採用モデルに設定
                </button>
                {!openModel.exists && <span className="error">ファイルが存在しないため採用できません</span>}
              </div>
              <div className="row">
                <button className="secondary" onClick={() => navigate(`/p/${name}/infer?train_job=${openModel.train_job_id}&weight=${openModel.weight_type}`)}>推論画面へ</button>
                <button className="secondary" onClick={() => navigate(`/p/${name}/eval?job=${openModel.train_job_id}`)}>評価画面へ</button>
                <button className="secondary" onClick={() => navigate(`/p/${name}/experiments`)}>実験履歴へ</button>
              </div>
            </div>

            {/* 右: モデル配布 + ONNXエクスポート */}
            <div className="model-detail-right">
              <h3>モデル配布</h3>
              <p className="muted" style={{ fontSize: "0.8rem" }}>
                重み(.pt)単体、または再利用に必要な情報（クラス定義・前処理・推論条件・学習条件・
                評価・データセット情報＋README＋sample_infer.py）をまとめたZIPを出力できます。
              </p>
              {(() => {
                const bestExists = data?.models.find(
                  (x) => x.train_job_id === openModel.train_job_id && x.weight_type === "best"
                )?.exists;
                const lastExists = data?.models.find(
                  (x) => x.train_job_id === openModel.train_job_id && x.weight_type === "last"
                )?.exists;
                return (
                  <div className="row">
                    <button
                      className="secondary"
                      onClick={() => triggerDownload(api.weightDownloadUrl(name, openModel.train_job_id, "best"))}
                      disabled={!bestExists}
                    >
                      best.pt をダウンロード
                    </button>
                    <button
                      className="secondary"
                      onClick={() => triggerDownload(api.weightDownloadUrl(name, openModel.train_job_id, "last"))}
                      disabled={!lastExists}
                    >
                      last.pt をダウンロード
                    </button>
                  </div>
                );
              })()}
              {(() => {
                const onnxOptions = onnxExports.filter(
                  (e) =>
                    e.train_job_id === openModel.train_job_id &&
                    e.weight_type === openModel.weight_type &&
                    e.status === "completed"
                );
                if (onnxOptions.length === 0) {
                  return (
                    <p className="muted" style={{ fontSize: "0.8rem" }}>
                      ONNXを同梱するには、先にこのモデル（{openModel.weight_type}）のONNXエクスポートを実行してください。
                    </p>
                  );
                }
                return (
                  <div className="row onnx-bundle-row">
                    <label>
                      <input
                        type="checkbox"
                        checked={includeOnnx}
                        onChange={(e) => {
                          setIncludeOnnx(e.target.checked);
                          if (e.target.checked && !onnxJobForPkg) setOnnxJobForPkg(onnxOptions[0].export_job_id);
                        }}
                      />{" "}
                      ONNXを同梱する
                    </label>
                    {/* 選択欄は常に領域を確保し、未チェック時は非表示にして画面の揺れを防ぐ */}
                    <label className="field" style={{ visibility: includeOnnx ? "visible" : "hidden" }}>
                      ONNX export job
                      <select
                        value={onnxJobForPkg}
                        onChange={(e) => setOnnxJobForPkg(e.target.value)}
                        disabled={!includeOnnx}
                      >
                        {onnxOptions.map((e) => (
                          <option key={e.export_job_id} value={e.export_job_id}>
                            {e.export_job_id}（imgsz {e.imgsz} / opset {e.opset}）
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                );
              })()}
              <div className="row">
                <button onClick={() => createPackage(openModel)} disabled={pkgBusy || !openModel.exists}>
                  {pkgBusy
                    ? "作成中…"
                    : `配布パッケージを作成（${openModel.weight_type}${includeOnnx ? " + ONNX" : ""}）`}
                </button>
                {pkg && pkg.model_id === openModel.model_id && (
                  <>
                    <button className="secondary" onClick={() => triggerDownload(api.packageDownloadUrl(name, pkg.package_id))}>
                      配布パッケージをダウンロード
                    </button>
                    <span className="muted" style={{ fontSize: "0.8rem" }}>
                      {pkg.files.length} ファイル / <code>{pkg.zip_path}</code>
                    </span>
                  </>
                )}
              </div>

              <h3>ONNXエクスポート</h3>
              <p className="muted" style={{ fontSize: "0.8rem" }}>
                学習済みモデルを ONNX 形式へ変換します（ONNX Runtime / C# / C++ など他環境での推論向け）。
                別プロセスで実行され、`requirements-train.txt`（ultralytics）が必要です。
              </p>
              {projectTask === "segment" && (
                <div className="warn" style={{ fontSize: "0.8rem" }}>
                  セグメンテーションONNXは、利用先でmask出力の後処理が必要になる場合があります。
                </div>
              )}
              <div className="row">
                <label className="field">
                  weight
                  <select
                    value={onnx.weight_type}
                    onChange={(e) => setOnnx({ ...onnx, weight_type: e.target.value })}
                  >
                    <option value="best">best</option>
                    <option value="last">last</option>
                  </select>
                </label>
                <label className="field">
                  imgsz
                  <input type="number" value={onnx.imgsz} onChange={(e) => setOnnx({ ...onnx, imgsz: Number(e.target.value) })} />
                </label>
                <label className="field">
                  opset
                  <input type="number" value={onnx.opset} onChange={(e) => setOnnx({ ...onnx, opset: Number(e.target.value) })} />
                </label>
                <label className="field">
                  device
                  <select value={onnx.device} onChange={(e) => setOnnx({ ...onnx, device: e.target.value })}>
                    <option value="cpu">cpu</option>
                    <option value="auto">auto</option>
                    <option value="cuda">cuda</option>
                  </select>
                </label>
              </div>
              <div className="row">
                <label><input type="checkbox" checked={onnx.simplify} onChange={(e) => setOnnx({ ...onnx, simplify: e.target.checked })} /> simplify</label>
                <label><input type="checkbox" checked={onnx.dynamic} onChange={(e) => setOnnx({ ...onnx, dynamic: e.target.checked })} /> dynamic</label>
                <label><input type="checkbox" checked={onnx.half} onChange={(e) => setOnnx({ ...onnx, half: e.target.checked })} /> half</label>
                <label><input type="checkbox" checked={onnx.overwrite} onChange={(e) => setOnnx({ ...onnx, overwrite: e.target.checked })} /> overwrite</label>
                <button onClick={() => startOnnx(openModel)} disabled={onnxBusy}>
                  {onnxBusy ? "開始中…" : "ONNXエクスポート開始"}
                </button>
              </div>
              {onnxError && <div className="error">{onnxError}</div>}
            </div>
          </div>

          {/* テーブル: ONNXエクスポート一覧（全幅） */}
          {(() => {
            const rows = onnxExports.filter((e) => e.train_job_id === openModel.train_job_id);
            if (rows.length === 0) return <p className="muted">このモデルのONNXエクスポートはまだありません。</p>;
            return (
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>export_job_id</th><th>weight</th><th>status</th><th>imgsz</th><th>opset</th><th>作成</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((e) => (
                      <tr key={e.export_job_id}>
                        <td>{e.export_job_id}</td>
                        <td>{e.weight_type}</td>
                        <td className={onnxStatusClass(e.status)}>● {e.status}</td>
                        <td>{e.imgsz ?? "-"}</td>
                        <td>{e.opset ?? "-"}</td>
                        <td className="muted">{e.created_at ?? "-"}</td>
                        <td>
                          <button
                            className="secondary"
                            disabled={e.status !== "completed"}
                            onClick={() => triggerDownload(api.onnxDownloadUrl(name, e.export_job_id))}
                          >
                            ONNX DL
                          </button>{" "}
                          <button className="secondary" onClick={() => showOnnxLog(e.export_job_id)}>
                            ログ
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()}
          {onnxLog && (
            <>
              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 8 }}>ログ: {onnxLog.id}</div>
              <textarea readOnly className="train-log" value={onnxLog.text} />
            </>
          )}
        </section>
      )}
    </div>
  );
}
