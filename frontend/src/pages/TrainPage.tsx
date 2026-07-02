// 学習画面。データセット選択・学習設定フォーム・ジョブ一覧・状態/ログ表示。
// 実行中のジョブはポーリングで状態とログを更新する。
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import AugmentationPanel from "../components/AugmentationPanel";
import type {
  DatasetListItem,
  ProjectTask,
  TrainJobInfo,
  TrainLogLine,
} from "../types";

const DEVICES = ["auto", "cpu", "mps", "cuda"];

// タスク種別ごとのモデル候補（先頭が初期値）
const MODEL_CANDIDATES: Record<ProjectTask, string[]> = {
  detect: ["yolov8n.pt", "yolov8s.pt"],
  segment: ["yolov8n-seg.pt", "yolov8s-seg.pt"],
};

function statusClass(status: string): string {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "running" || status === "queued") return "warn";
  return "muted";
}

export default function TrainPage() {
  const { name = "" } = useParams();
  const [datasets, setDatasets] = useState<DatasetListItem[]>([]);
  const [jobs, setJobs] = useState<TrainJobInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TrainJobInfo | null>(null);
  const [log, setLog] = useState("");
  const [logLines, setLogLines] = useState<TrainLogLine[]>([]);
  const [errorSummary, setErrorSummary] = useState<string | null>(null);
  const [errorOnly, setErrorOnly] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const logBoxRef = useRef<HTMLDivElement>(null);

  // フォーム（初期値は task.md 準拠）
  const [datasetName, setDatasetName] = useState("");
  const [jobName, setJobName] = useState("train_001");
  const [projectTask, setProjectTask] = useState<ProjectTask>("detect");
  const [model, setModel] = useState("yolov8n.pt");
  const [epochs, setEpochs] = useState(50);
  const [imgsz, setImgsz] = useState(640);
  const [batch, setBatch] = useState(8);
  const [device, setDevice] = useState("auto");
  const [workers, setWorkers] = useState(2);
  const [patience, setPatience] = useState(20);
  const [seed, setSeed] = useState(42);
  const [overwrite, setOverwrite] = useState(false);
  const [augPreset, setAugPreset] = useState("none");

  async function reloadDatasets() {
    try {
      const r = await api.listDatasets(name);
      setDatasets(r.datasets);
      if (!datasetName && r.datasets.length > 0) {
        setDatasetName(r.datasets[0].dataset_name);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function reloadJobs() {
    try {
      const r = await api.listTrainJobs(name);
      setJobs(r.jobs);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    reloadDatasets();
    reloadJobs();
    // プロジェクトの task に応じてモデル候補・初期モデルを切り替える
    api
      .getProject(name)
      .then((p) => {
        const t = (p.task ?? "detect") as ProjectTask;
        setProjectTask(t);
        setModel(MODEL_CANDIDATES[t][0]);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  // 選択ジョブの状態・ログをポーリング（実行中のみ継続）
  const timerRef = useRef<number | null>(null);
  useEffect(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (!selected) return;

    async function refresh() {
      try {
        const [d, l] = await Promise.all([
          api.getTrainJob(name, selected!),
          api.getTrainLogs(name, selected!),
        ]);
        setDetail(d);
        setLog(l.log);
        setLogLines(l.lines ?? []);
        setErrorSummary(l.error_summary ?? null);
        if (d.status === "completed" || d.status === "failed") {
          if (timerRef.current) window.clearInterval(timerRef.current);
          reloadJobs();
        }
      } catch (e) {
        setError(String(e));
      }
    }
    refresh();
    timerRef.current = window.setInterval(refresh, 2000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, name]);

  // 最新ログへ自動スクロール
  useEffect(() => {
    const box = logBoxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [logLines]);

  function copyLog() {
    navigator.clipboard?.writeText(log).catch(() => {});
  }

  async function onStart(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res = await api.startTrainJob(name, {
        dataset_name: datasetName,
        job_name: jobName.trim(),
        task: projectTask,
        model,
        epochs,
        imgsz,
        batch,
        device,
        workers,
        patience,
        seed,
        overwrite,
        augmentation_preset: augPreset,
      });
      await reloadJobs();
      setSelected(res.job_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>学習: {name}</h1>
      <p className="muted">
        作成済みデータセットの data.yaml を使って Ultralytics YOLO 学習を実行します。
        学習は別プロセスで動くため、実行中も画面操作・API応答は継続します。
        （学習用ライブラリは <code>requirements-train.txt</code> で導入）
      </p>

      {/* 左: 学習ジョブ / 右: データ拡張（4:6） */}
      <div className="train-cols">
        <section className="card train-job-col">
          <h2>学習ジョブ開始</h2>
          <form onSubmit={onStart}>
            <h3 className="train-group-title">データ・モデル</h3>
            <div className="train-fields">
              <label className="field field-wide">
                データセット
                <select
                  value={datasetName}
                  onChange={(e) => setDatasetName(e.target.value)}
                  required
                >
                  <option value="" disabled>
                    選択してください
                  </option>
                  {datasets.map((d) => (
                    <option key={d.dataset_name} value={d.dataset_name}>
                      {d.dataset_name}（train {d.train_image_count}/val {d.val_image_count}）
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                job_name
                <input value={jobName} onChange={(e) => setJobName(e.target.value)} required />
              </label>
              <label className="field field-wide">
                model（{projectTask === "segment" ? "セグメンテーション" : "物体検出"}）
                <select value={model} onChange={(e) => setModel(e.target.value)}>
                  {MODEL_CANDIDATES[projectTask].map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                  {!MODEL_CANDIDATES[projectTask].includes(model) && (
                    <option value={model}>{model}</option>
                  )}
                </select>
              </label>
            </div>

            <h3 className="train-group-title">ハイパーパラメータ</h3>
            <div className="train-fields">
              <label className="field">
                epochs
                <input type="number" value={epochs} onChange={(e) => setEpochs(Number(e.target.value))} />
              </label>
              <label className="field">
                imgsz
                <input type="number" value={imgsz} onChange={(e) => setImgsz(Number(e.target.value))} />
              </label>
              <label className="field">
                batch
                <input type="number" value={batch} onChange={(e) => setBatch(Number(e.target.value))} />
              </label>
              <label className="field">
                device
                <select value={device} onChange={(e) => setDevice(e.target.value)}>
                  {DEVICES.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                workers
                <input type="number" value={workers} onChange={(e) => setWorkers(Number(e.target.value))} />
              </label>
              <label className="field">
                patience
                <input type="number" value={patience} onChange={(e) => setPatience(Number(e.target.value))} />
              </label>
              <label className="field">
                seed
                <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
              </label>
            </div>

            <h3 className="train-group-title">実行</h3>
            <div className="row train-run-row">
              <span className="train-aug-note">
                データ拡張: <strong>{augPreset}</strong>
                <span className="muted">（右で選択・調整）</span>
              </span>
              <label className="train-overwrite">
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> 上書き
              </label>
              <button type="submit" disabled={busy || !datasetName || !jobName.trim()}>
                {busy ? "開始中…" : "学習開始"}
              </button>
            </div>
          </form>
          {error && <div className="error">{error}</div>}
          {datasets.length === 0 && (
            <div className="warn">
              データセットがありません。「データセット作成」で先に作成してください。
            </div>
          )}
        </section>

        <section className="card train-aug-col">
          <h2>データ拡張（オーギュメンテーション）</h2>
          <AugmentationPanel selected={augPreset} onSelect={setAugPreset} />
        </section>
      </div>

      <section className="card">
        <h2>ジョブ一覧（{jobs.length}）</h2>
        <div className="row">
          <button onClick={reloadJobs}>一覧を更新</button>
        </div>
        <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>job_id</th>
              <th>dataset</th>
              <th>status</th>
              <th>model</th>
              <th>epochs</th>
              <th>作成</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.job_id} className={j.job_id === selected ? "selected-row" : ""}>
                <td>{j.job_id}</td>
                <td>{j.dataset_name}</td>
                <td className={statusClass(j.status)}>● {j.status}</td>
                <td>{j.model}</td>
                <td>{j.epochs}</td>
                <td className="muted">{j.created_at ?? "-"}</td>
                <td>
                  <button onClick={() => setSelected(j.job_id)}>詳細</button>
                </td>
              </tr>
            ))}
            {jobs.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  まだジョブがありません。
                </td>
              </tr>
            )}
          </tbody>
        </table>
        </div>
      </section>

      {detail && (
        <section className="card">
          <h2>
            ジョブ詳細: {detail.job_id}{" "}
            <span className={statusClass(detail.status)}>● {detail.status}</span>
          </h2>
          <ul className="compact">
            <li>message: {detail.message ?? "-"}</li>
            <li>started_at: {detail.started_at ?? "-"} / finished_at: {detail.finished_at ?? "-"}</li>
            <li>return_code: {detail.return_code ?? "-"}</li>
            <li>run_path: <code>{detail.run_path ?? "-"}</code></li>
            <li>best.pt: <code>{detail.best_model_path ?? "-"}</code></li>
            <li>last.pt: <code>{detail.last_model_path ?? "-"}</code></li>
            <li>results.csv: <code>{detail.results_csv_path ?? "-"}</code></li>
          </ul>
          {errorSummary && (
            <div className="error-summary">⚠ {errorSummary}</div>
          )}

          <div className="row">
            <h3 style={{ margin: 0 }}>ログ（train.log）</h3>
            <span style={{ flex: 1 }} />
            <label className="muted">
              <input type="checkbox" checked={errorOnly} onChange={(e) => setErrorOnly(e.target.checked)} /> エラー行のみ
            </label>
            <button onClick={copyLog}>コピー</button>
          </div>
          <div className="train-log-box" ref={logBoxRef}>
            {(errorOnly ? logLines.filter((l) => l.level === "error") : logLines).map((l, i) => (
              <div key={i} className={`log-line log-${l.level}`}>{l.text}</div>
            ))}
            {logLines.length === 0 && <div className="muted">ログはまだありません。</div>}
          </div>
        </section>
      )}
    </div>
  );
}
