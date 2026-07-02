// 推論テスト画面。学習ジョブ/weight選択・画像複数選択・推論実行・結果画像と検出一覧表示。
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  CameraInfo,
  ImageInfo,
  PredictJobInfo,
  PredictResultsResponse,
  PreprocessInfoResponse,
  TrainJobInfo,
  VideoJobInfo,
} from "../types";

const DEVICES = ["auto", "cpu", "mps", "cuda"];

function preInfoSummary(meta: Record<string, unknown> | null | undefined): string {
  if (!meta) return "";
  const s = (meta.settings ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (s.resize_enabled) parts.push(`resize ${s.resize_mode ?? "width"} ${s.resize_size ?? ""}`);
  parts.push(`grayscale ${s.grayscale_enabled ? "on" : "off"}`);
  parts.push(`binary ${s.binary_enabled ? "on" : "off"}`);
  if (s.brightness_enabled) parts.push(`brightness ${s.brightness}`);
  if (s.contrast_enabled) parts.push(`contrast ${s.contrast}`);
  return parts.join(" / ");
}

function statusClass(status: string): string {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "running" || status === "queued") return "warn";
  return "muted";
}

function stemOf(filename: string): string {
  return filename.replace(/\.[^./\\]+$/, "");
}

export default function PredictPage() {
  const { name = "" } = useParams();
  const [searchParams] = useSearchParams();
  const [trainJobs, setTrainJobs] = useState<TrainJobInfo[]>([]);
  const [images, setImages] = useState<ImageInfo[]>([]);
  const [jobs, setJobs] = useState<PredictJobInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<PredictJobInfo | null>(null);
  const [log, setLog] = useState("");
  const [results, setResults] = useState<PredictResultsResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // フォーム（初期値は task.md 準拠）
  const [trainJobId, setTrainJobId] = useState("");
  const [weightType, setWeightType] = useState("best");
  const [predictName, setPredictName] = useState("predict_001");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [conf, setConf] = useState(0.25);
  const [iou, setIou] = useState(0.7);
  const [imgsz, setImgsz] = useState(640);
  const [device, setDevice] = useState("auto");
  const [saveTxt, setSaveTxt] = useState(true);
  const [saveConf, setSaveConf] = useState(true);
  const [overwrite, setOverwrite] = useState(false);
  const [preprocessMode, setPreprocessMode] = useState("none");
  const [preInfo, setPreInfo] = useState<PreprocessInfoResponse | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // 推論モード（画像 / 映像）
  const [mode, setMode] = useState<"image" | "video">("image");
  // 映像（カメラ）推論フォーム
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [camerasLoading, setCamerasLoading] = useState(false);
  const [cameraIndex, setCameraIndex] = useState(0);
  const [videoName, setVideoName] = useState("video_001");
  const [videoFps, setVideoFps] = useState(15);
  const [inferFps, setInferFps] = useState(5);
  const [videoJob, setVideoJob] = useState<VideoJobInfo | null>(null);
  const [videoBusy, setVideoBusy] = useState(false);
  const [videoError, setVideoError] = useState("");
  const [streamSrc, setStreamSrc] = useState("");

  async function loadCameras() {
    setCamerasLoading(true);
    try {
      const r = await api.listCameras(name);
      setCameras(r.cameras);
      if (r.cameras.length > 0) setCameraIndex(r.cameras[0].index);
    } catch (e) {
      setVideoError(String(e));
    } finally {
      setCamerasLoading(false);
    }
  }

  async function reloadJobs() {
    try {
      setJobs((await api.listPredictJobs(name)).jobs);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    api
      .listTrainJobs(name)
      .then((r) => {
        setTrainJobs(r.jobs);
        if (!trainJobId && r.jobs.length > 0) setTrainJobId(r.jobs[0].job_id);
      })
      .catch((e) => setError(String(e)));
    api.listImages(name).then((r) => setImages(r.images)).catch(() => {});
    api.getPreprocessInfo(name).then(setPreInfo).catch(() => setPreInfo(null));
    reloadJobs();
    // 誤検出分析画面からの導線（?job=<predict_job_id>）で該当ジョブを開く
    const j = searchParams.get("job");
    if (j) setSelected(j);
    // 実験履歴/モデル管理からの導線（?train_job=...&weight=...）で初期選択
    const tj = searchParams.get("train_job");
    if (tj) setTrainJobId(tj);
    const wt = searchParams.get("weight");
    if (wt === "best" || wt === "last") setWeightType(wt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  // 選択ジョブの状態/ログ/結果をポーリング
  const timerRef = useRef<number | null>(null);
  useEffect(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (!selected) return;

    async function refresh() {
      try {
        const [d, l] = await Promise.all([
          api.getPredictJob(name, selected!),
          api.getPredictLogs(name, selected!),
        ]);
        setDetail(d);
        setLog(l.log);
        if (d.status === "completed" || d.status === "failed") {
          if (timerRef.current) window.clearInterval(timerRef.current);
          if (d.status === "completed") {
            setResults(await api.getPredictResults(name, selected!));
          }
          reloadJobs();
        }
      } catch (e) {
        setError(String(e));
      }
    }
    setResults(null);
    setDetail(null);
    setLog("");
    refresh();
    timerRef.current = window.setInterval(refresh, 2000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, name, reloadKey]);

  function toggleImage(stem: string) {
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(stem)) next.delete(stem);
      else next.add(stem);
      return next;
    });
  }

  async function onStart(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (chosen.size === 0) {
      setError("推論対象の画像を1枚以上選択してください。");
      return;
    }
    setBusy(true);
    try {
      const res = await api.startPredictJob(name, {
        predict_job_name: predictName.trim(),
        train_job_id: trainJobId,
        weight_type: weightType,
        source_type: "project_images",
        image_ids: Array.from(chosen),
        conf,
        iou,
        imgsz,
        device,
        save_txt: saveTxt,
        save_conf: saveConf,
        overwrite,
        preprocess_mode: preprocessMode,
      });
      await reloadJobs();
      setSelected(res.predict_job_id);
      setReloadKey((k) => k + 1); // 同名ジョブ(overwrite)でも結果表示を必ず更新
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  // 映像ジョブの状態ポーリング
  const videoTimer = useRef<number | null>(null);
  useEffect(() => {
    if (videoTimer.current) window.clearInterval(videoTimer.current);
    if (!videoJob) return;
    const vid = videoJob.video_job_id;
    async function refresh() {
      try {
        const d = await api.getVideoJob(name, vid);
        setVideoJob(d);
        if (d.status === "stopped" || d.status === "failed" || d.status === "completed") {
          if (videoTimer.current) window.clearInterval(videoTimer.current);
        }
      } catch {
        /* ignore */
      }
    }
    videoTimer.current = window.setInterval(refresh, 2000);
    return () => {
      if (videoTimer.current) window.clearInterval(videoTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoJob?.video_job_id, name]);

  async function onStartVideo(e: React.FormEvent) {
    e.preventDefault();
    setVideoError("");
    setVideoBusy(true);
    try {
      const res = await api.startVideoJob(name, {
        video_job_name: videoName.trim(),
        train_job_id: trainJobId,
        weight_type: weightType,
        camera_index: cameraIndex,
        video_fps: videoFps,
        infer_fps: inferFps,
        conf,
        iou,
        imgsz,
        device,
        preprocess_mode: preprocessMode,
        overwrite: true, // 同名は常に上書きで再開
      });
      setVideoJob(res);
      // キャッシュ回避のためクエリを付けてMJPEGを開始
      setStreamSrc(`${api.videoStreamUrl(name, res.video_job_id)}?t=${reloadKey + 1}`);
      setReloadKey((k) => k + 1);
    } catch (e) {
      setVideoError(String(e));
    } finally {
      setVideoBusy(false);
    }
  }

  async function onStopVideo() {
    if (!videoJob) return;
    try {
      const d = await api.stopVideoJob(name, videoJob.video_job_id);
      setVideoJob(d);
      setStreamSrc(""); // ストリーム停止
    } catch (e) {
      setVideoError(String(e));
    }
  }

  const videoActive = videoJob && (videoJob.status === "running" || videoJob.status === "queued");

  return (
    <div className="page">
      <h1>推論テスト: {name}</h1>

      <div className="row" style={{ gap: 8, marginBottom: 4 }}>
        <button
          type="button"
          className={mode === "image" ? "" : "secondary"}
          onClick={() => setMode("image")}
        >
          画像
        </button>
        <button
          type="button"
          className={mode === "video" ? "" : "secondary"}
          onClick={() => {
            setMode("video");
            if (cameras.length === 0) loadCameras();
          }}
        >
          映像（カメラ）
        </button>
      </div>

      {mode === "image" && (
        <>
      <p className="muted">
        学習済みモデル（best.pt / last.pt）を選び、登録済み画像に対して推論を実行します。
        推論は別プロセスで動くため、実行中もFastAPIは応答します。
      </p>

      <section className="card">
        <h2>推論ジョブ開始</h2>
        <form onSubmit={onStart}>
          <div className="predict-setup-cols">
            {/* 左(2): 実行ジョブ設定 */}
            <div className="predict-setup-form">
              <div className="predict-fields">
                <label className="field field-wide">
                  学習ジョブ
                  <select value={trainJobId} onChange={(e) => setTrainJobId(e.target.value)} required>
                    <option value="" disabled>
                      選択してください
                    </option>
                    {trainJobs.map((j) => (
                      <option key={j.job_id} value={j.job_id}>
                        {j.job_id}（{j.status}）
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  weight
                  <select value={weightType} onChange={(e) => setWeightType(e.target.value)}>
                    <option value="best">best</option>
                    <option value="last">last</option>
                  </select>
                </label>
                <label className="field field-wide">
                  predict_job_name
                  <input value={predictName} onChange={(e) => setPredictName(e.target.value)} required />
                </label>
                <label className="field">
                  conf
                  <input type="number" step="0.05" value={conf} onChange={(e) => setConf(Number(e.target.value))} />
                </label>
                <label className="field">
                  iou
                  <input type="number" step="0.05" value={iou} onChange={(e) => setIou(Number(e.target.value))} />
                </label>
                <label className="field">
                  imgsz
                  <input type="number" value={imgsz} onChange={(e) => setImgsz(Number(e.target.value))} />
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
                <label className="field field-wide">
                  推論前処理
                  <select value={preprocessMode} onChange={(e) => setPreprocessMode(e.target.value)}>
                    <option value="none">なし（raw画像のまま）</option>
                    <option value="latest" disabled={!preInfo?.has_processed_images}>
                      最新前処理設定を適用{preInfo?.has_processed_images ? "" : "（前処理未実行）"}
                    </option>
                  </select>
                </label>
              </div>

              {preprocessMode === "latest" && preInfo?.has_processed_images && (
                <p className="muted" style={{ fontSize: "0.76rem", margin: "4px 0" }}>
                  使用設定: {preInfoSummary(preInfo.metadata)}
                </p>
              )}

              <div className="predict-checks">
                <label>
                  <input type="checkbox" checked={saveTxt} onChange={(e) => setSaveTxt(e.target.checked)} /> save_txt
                </label>
                <label>
                  <input type="checkbox" checked={saveConf} onChange={(e) => setSaveConf(e.target.checked)} /> save_conf
                </label>
                <label>
                  <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> overwrite
                </label>
              </div>

              <button type="submit" className="predict-start" disabled={busy || !trainJobId || !predictName.trim()}>
                {busy ? "開始中…" : "推論開始"}
              </button>
            </div>

            {/* 右(8): 推論対象画像 */}
            <div className="predict-setup-images">
              <h3 className="predict-images-head">
                推論対象画像（{chosen.size} 枚選択中 / 全 {images.length} 枚）
              </h3>
              <div className="thumb-grid predict-thumb-grid">
                {images.map((img) => {
                  const stem = stemOf(img.filename);
                  const on = chosen.has(stem);
                  return (
                    <figure
                      key={img.filename}
                      className={"thumb selectable" + (on ? " on" : "")}
                      onClick={() => toggleImage(stem)}
                    >
                      <img src={api.thumbnailUrl(name, img.filename)} alt={img.filename} loading="lazy" />
                      <figcaption>
                        <input type="checkbox" checked={on} readOnly /> {img.filename}
                      </figcaption>
                    </figure>
                  );
                })}
                {images.length === 0 && <p className="muted">画像がありません。</p>}
              </div>
            </div>
          </div>
        </form>
        {error && <div className="error">{error}</div>}
        {trainJobs.length === 0 && (
          <div className="warn">学習ジョブがありません。「学習」で先に実行してください。</div>
        )}
      </section>

      {/* ジョブ一覧(左4) / ジョブ詳細(右6) */}
      <div className={"predict-lower-cols" + (detail ? "" : " single")}>
      <section className="card">
        <h2>推論ジョブ一覧（{jobs.length}）</h2>
        <div className="row">
          <button onClick={reloadJobs}>一覧を更新</button>
        </div>
        <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>predict_job_id</th>
              <th>train_job_id</th>
              <th>weight</th>
              <th>status</th>
              <th>画像数</th>
              <th>検出数</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.predict_job_id} className={j.predict_job_id === selected ? "selected-row" : ""}>
                <td>{j.predict_job_id}</td>
                <td>{j.train_job_id}</td>
                <td>{j.weight_type}</td>
                <td className={statusClass(j.status)}>● {j.status}</td>
                <td>{j.image_count ?? "-"}</td>
                <td>{j.detection_count ?? "-"}</td>
                <td>
                  <button onClick={() => setSelected(j.predict_job_id)}>詳細</button>
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
            ジョブ詳細: {detail.predict_job_id}{" "}
            <span className={statusClass(detail.status)}>● {detail.status}</span>
          </h2>
          <p className="muted predict-detail-meta">
            {detail.message ?? "-"} ／ started {detail.started_at ?? "-"} → finished{" "}
            {detail.finished_at ?? "-"} ／ <code>{detail.prediction_path ?? "-"}</code>
          </p>

          {results && (
            <>
              <p>
                <strong>
                  推論対象 {results.image_count} 枚 / 総検出 {results.detection_count} 件
                </strong>
              </p>
              <div className="predict-results">
                {results.results.map((r) => (
                  <div key={r.image_id} className="predict-result">
                    <div className="predict-result-body">
                      {/* 左: 結果画像 */}
                      <div className="predict-result-img">
                        {r.result_image_url ? (
                          <img className="predict-image" src={r.result_image_url} alt={r.image_name} loading="lazy" />
                        ) : (
                          <div className="muted">画像なし</div>
                        )}
                      </div>
                      {/* 右: 検出パラメータ */}
                      <div className="predict-result-info">
                        <h4>
                          {r.image_name}（検出 {r.detections.length} 件）
                        </h4>
                        {r.detections.length > 0 ? (
                          <div className="table-scroll predict-det-table">
                            <table className="table">
                              <thead>
                                <tr>
                                  <th>class</th>
                                  <th>conf</th>
                                  <th>x</th>
                                  <th>y</th>
                                  <th>w</th>
                                  <th>h</th>
                                </tr>
                              </thead>
                              <tbody>
                                {r.detections.map((d, i) => (
                                  <tr key={i}>
                                    <td>
                                      {d.class_name ?? d.class_id} ({d.class_id})
                                    </td>
                                    <td>{d.confidence.toFixed(4)}</td>
                                    <td>{d.x_center.toFixed(4)}</td>
                                    <td>{d.y_center.toFixed(4)}</td>
                                    <td>{d.width.toFixed(4)}</td>
                                    <td>{d.height.toFixed(4)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="muted">検出なし</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          <details>
            <summary className="muted">ログ（predict.log）</summary>
            <textarea readOnly className="train-log" value={log} />
          </details>
        </section>
      )}
      </div>
        </>
      )}

      {mode === "video" && (
        <>
          <p className="muted">
            接続中のカメラ映像にリアルタイム推論します（サーバー側 OpenCV）。映像FPSと推論FPSは
            別々に設定でき、推論は間引き実行されます。前処理「最新設定」を選ぶと、各フレームに
            学習時と同じ前処理を適用します。
          </p>

          {/* 左: 設定 / 右: ライブ映像（映像を広め・最初から確保） */}
          <div className="video-cols">
          <section className="card">
            <h2>映像推論{videoActive && <span className="video-live-badge">● 実行中</span>}</h2>
            <form onSubmit={onStartVideo}>
              <h3 className="train-group-title">カメラ・モデル</h3>
              <div className="predict-fields">
                <label className="field field-wide">
                  カメラ
                  <div className="video-camera-row">
                    <select
                      value={cameraIndex}
                      onChange={(e) => setCameraIndex(Number(e.target.value))}
                      disabled={videoActive || cameras.length === 0}
                    >
                      {cameras.length === 0 && <option value={0}>（カメラ未検出）</option>}
                      {cameras.map((c) => (
                        <option key={c.index} value={c.index}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                    <button type="button" className="secondary" onClick={loadCameras} disabled={camerasLoading || !!videoActive}>
                      {camerasLoading ? "検出中…" : "再検出"}
                    </button>
                  </div>
                </label>
                <label className="field field-wide">
                  video_job_name
                  <input value={videoName} onChange={(e) => setVideoName(e.target.value)} disabled={!!videoActive} required />
                </label>
                <label className="field field-wide">
                  学習ジョブ
                  <select value={trainJobId} onChange={(e) => setTrainJobId(e.target.value)} disabled={!!videoActive} required>
                    <option value="" disabled>
                      選択してください
                    </option>
                    {trainJobs.map((j) => (
                      <option key={j.job_id} value={j.job_id}>
                        {j.job_id}（{j.status}）
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  weight
                  <select value={weightType} onChange={(e) => setWeightType(e.target.value)} disabled={!!videoActive}>
                    <option value="best">best</option>
                    <option value="last">last</option>
                  </select>
                </label>
              </div>

              <h3 className="train-group-title">FPS・推論設定</h3>
              <div className="predict-fields">
                <label className="field">
                  映像FPS
                  <input
                    type="number"
                    min={1}
                    max={60}
                    value={videoFps}
                    onChange={(e) => setVideoFps(Number(e.target.value))}
                    disabled={!!videoActive}
                  />
                </label>
                <label className="field">
                  推論FPS
                  <input
                    type="number"
                    min={1}
                    max={videoFps}
                    value={inferFps}
                    onChange={(e) => setInferFps(Number(e.target.value))}
                    disabled={!!videoActive}
                  />
                </label>
                <label className="field">
                  conf
                  <input type="number" step="0.05" value={conf} onChange={(e) => setConf(Number(e.target.value))} disabled={!!videoActive} />
                </label>
                <label className="field">
                  iou
                  <input type="number" step="0.05" value={iou} onChange={(e) => setIou(Number(e.target.value))} disabled={!!videoActive} />
                </label>
                <label className="field">
                  imgsz
                  <input type="number" value={imgsz} onChange={(e) => setImgsz(Number(e.target.value))} disabled={!!videoActive} />
                </label>
                <label className="field">
                  device
                  <select value={device} onChange={(e) => setDevice(e.target.value)} disabled={!!videoActive}>
                    {DEVICES.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="muted" style={{ fontSize: "0.76rem", margin: "4px 0" }}>
                映像FPSは表示、推論FPSは検出の頻度です（推論FPS ≤ 映像FPS）。推論FPSを下げると負荷が減ります。
              </p>

              <h3 className="train-group-title">前処理</h3>
              <div className="predict-fields">
                <label className="field field-wide">
                  推論前処理
                  <select
                    value={preprocessMode}
                    onChange={(e) => setPreprocessMode(e.target.value)}
                    disabled={!!videoActive}
                  >
                    <option value="none">なし（raw映像のまま）</option>
                    <option value="latest" disabled={!preInfo?.has_processed_images}>
                      最新前処理設定を適用{preInfo?.has_processed_images ? "" : "（前処理未実行）"}
                    </option>
                  </select>
                </label>
              </div>
              {preprocessMode === "latest" && preInfo?.has_processed_images && (
                <p className="muted" style={{ fontSize: "0.76rem", margin: "4px 0" }}>
                  使用設定: {preInfoSummary(preInfo.metadata)}
                </p>
              )}

              {!videoActive ? (
                <button
                  type="submit"
                  className="predict-start"
                  disabled={videoBusy || !trainJobId || !videoName.trim() || cameras.length === 0}
                >
                  {videoBusy ? "開始中…" : "映像推論を開始"}
                </button>
              ) : (
                <button type="button" className="danger predict-start" onClick={onStopVideo}>
                  ■ 停止
                </button>
              )}
            </form>
            {videoError && <div className="error">{videoError}</div>}
            {trainJobs.length === 0 && (
              <div className="warn">学習ジョブがありません。「学習」で先に実行してください。</div>
            )}
            {cameras.length === 0 && !camerasLoading && (
              <div className="warn">
                利用可能なカメラが見つかりません。カメラ接続と他アプリでの占有を確認し、「カメラ再検出」を押してください。
              </div>
            )}
          </section>

          {/* 映像コンテナは最初から確保（開始でレイアウトが崩れないように） */}
          <section className="card video-live-col">
            <h2>
              ライブ映像{videoJob ? `: ${videoJob.video_job_id}` : ""}
              {videoJob && (
                <>
                  {" "}
                  <span className={statusClass(videoJob.status)}>● {videoJob.status}</span>
                </>
              )}
            </h2>
            {videoJob && (
              <p className="muted video-live-meta">
                {videoJob.message ?? "-"} ／ camera #{videoJob.camera_index} / 映像FPS {videoJob.video_fps} /
                推論FPS {videoJob.infer_fps} / 前処理 {videoJob.preprocess_mode}
              </p>
            )}
            <div className="video-live-frame">
              {streamSrc && videoActive ? (
                <img className="video-live-img" src={streamSrc} alt="live stream" />
              ) : (
                <p className="muted video-live-placeholder">
                  {videoJob
                    ? "ストリームは停止中です。再開するには「映像推論を開始」を押してください。"
                    : "左の設定を入力して「映像推論を開始」を押すと、ここにライブ映像が表示されます。"}
                </p>
              )}
            </div>
          </section>
          </div>
        </>
      )}
    </div>
  );
}
