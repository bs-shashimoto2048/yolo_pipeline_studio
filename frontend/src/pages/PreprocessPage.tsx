// 前処理画面（アノテーション前工程）。raw/images → processed/images。
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import HoverImagePreview from "../components/HoverImagePreview";
import type {
  ImageInfo,
  PreprocessInfoResponse,
  PreprocessPreviewResponse,
  PreprocessRunResponse,
  PreprocessSettings,
} from "../types";

const DEFAULTS: PreprocessSettings = {
  job_name: "preprocess_001",
  overwrite: false,
  output_format: "jpg",
  resize_enabled: false,
  resize_mode: "width",
  resize_size: 640,
  resize_width: 640,
  resize_height: 640,
  keep_aspect_ratio: true,
  padding: true,
  padding_color: "black",
  brightness_enabled: false,
  brightness: 0,
  contrast_enabled: false,
  contrast: 1.0,
  grayscale_enabled: false,
  binary_enabled: false,
  binary_threshold: 128,
  binary_invert: false,
  sharpen_enabled: false,
  sharpen_strength: 1.0,
  clahe_enabled: false,
  clahe_clip_limit: 2.0,
  clahe_tile_grid_size: 8,
};

export default function PreprocessPage() {
  const { name = "" } = useParams();
  const [s, setS] = useState<PreprocessSettings>({ ...DEFAULTS });
  const [info, setInfo] = useState<PreprocessInfoResponse | null>(null);
  const [result, setResult] = useState<PreprocessRunResponse | null>(null);
  const [preview, setPreview] = useState<ImageInfo[]>([]);
  const [rawImages, setRawImages] = useState<ImageInfo[]>([]);
  const [previewTarget, setPreviewTarget] = useState("");
  const [ba, setBa] = useState<PreprocessPreviewResponse | null>(null);
  const [previewSeq, setPreviewSeq] = useState(0); // afterプレビューのキャッシュ回避用
  const [previewBusy, setPreviewBusy] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function set<K extends keyof PreprocessSettings>(key: K, value: PreprocessSettings[K]) {
    setS((prev) => ({ ...prev, [key]: value }));
  }

  async function reload() {
    try {
      setInfo(await api.getPreprocessInfo(name));
      const r = await api.listImages(name, "processed");
      setPreview(r.images.slice(0, 12));
    } catch {
      /* processed未生成時は無視 */
    }
  }

  useEffect(() => {
    reload();
    api.listImages(name, "raw").then((r) => {
      setRawImages(r.images);
      if (r.images.length > 0) setPreviewTarget((t) => t || r.images[0].filename);
    }).catch(() => {});
  }, [name]);

  async function runPreview() {
    if (!previewTarget) return;
    setError("");
    setPreviewBusy(true);
    try {
      const stem = previewTarget.replace(/\.[^./\\]+$/, "");
      setBa(await api.previewPreprocess(name, s, stem));
      setPreviewSeq((n) => n + 1);
    } catch (e) {
      setError(String(e));
    } finally {
      setPreviewBusy(false);
    }
  }

  // 設定変更・対象変更を検知して自動でプレビュー更新（デバウンス）。
  // 更新ボタンを押さなくても即時に処理結果を確認できる。
  const previewTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!previewTarget) return;
    if (previewTimer.current) window.clearTimeout(previewTimer.current);
    previewTimer.current = window.setTimeout(() => {
      runPreview();
    }, 250);
    return () => {
      if (previewTimer.current) window.clearTimeout(previewTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s, previewTarget]);

  async function run() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.runPreprocess(name, s));
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const numField = (
    key: keyof PreprocessSettings,
    label: string,
    min: number,
    max: number,
    step: number
  ) => (
    <label className="field">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={s[key] as number}
        onChange={(e) => set(key, Number(e.target.value) as never)}
      />
    </label>
  );

  // 処理オプション行（チェックで有効化、有効時のみパラメータを表示）。
  const opt = (
    enabledKey: keyof PreprocessSettings,
    label: string,
    body?: React.ReactNode
  ) => {
    const on = Boolean(s[enabledKey]);
    return (
      <div className={"pp-opt" + (on ? " on" : "")}>
        <label className="pp-opt-head">
          <input
            type="checkbox"
            checked={on}
            onChange={(e) => set(enabledKey, e.target.checked as never)}
          />
          <span>{label}</span>
        </label>
        {on && body && <div className="pp-opt-body">{body}</div>}
      </div>
    );
  };

  const latestJob =
    info?.has_processed_images && info.metadata && typeof info.metadata.job_name === "string"
      ? String(info.metadata.job_name)
      : null;

  return (
    <div className="page">
      <h1>前処理: {name}</h1>
      <p className="muted">
        アノテーション前工程です。<code>raw/images</code> は破壊せず{" "}
        <code>processed/images</code> に別画像として出力し、出力後の画像がアノテーション・
        データセット作成の基準になります。
      </p>

      {/* 上部サマリー */}
      <section className="card setup-summary">
        <span className="summary-stat">
          <span className="summary-value">{rawImages.length}</span>
          <span className="summary-label">raw 画像</span>
        </span>
        <span className="summary-stat">
          <span className="summary-value">{info?.processed_count ?? 0}</span>
          <span className="summary-label">processed 画像</span>
        </span>
        <span className="summary-meta muted">
          {latestJob ? <>直近ジョブ: {latestJob}</> : "未処理（processed 画像なし）"}
        </span>
      </section>

      {/* 設定 / プレビュー 2カラム */}
      <div className="pp-cols">
        {/* 左: 前処理設定 */}
        <section className="card pp-settings">
          <h2>前処理設定</h2>

          <div className="pp-basic">
            <label className="field">
              job_name
              <input value={s.job_name} onChange={(e) => set("job_name", e.target.value)} />
            </label>
            <label className="field">
              出力形式
              <select value={s.output_format} onChange={(e) => set("output_format", e.target.value)}>
                <option value="jpg">jpg</option>
                <option value="png">png</option>
              </select>
            </label>
            <label className="pp-inline-check">
              <input type="checkbox" checked={s.overwrite} onChange={(e) => set("overwrite", e.target.checked)} />
              上書き
            </label>
          </div>

          <h3 className="pp-opts-title">処理オプション</h3>
          <div className="pp-opts">
            {opt(
              "resize_enabled",
              "リサイズ",
              <div className="row">
                <label className="field">
                  基準
                  <select value={s.resize_mode ?? "width"} onChange={(e) => set("resize_mode", e.target.value)}>
                    <option value="width">横幅（width）</option>
                    <option value="height">高さ（height）</option>
                  </select>
                </label>
                {numField("resize_size", "サイズ(px)", 32, 4096, 1)}
                <span className="muted pp-hint">
                  {s.resize_mode === "height" ? "高さ" : "横幅"}を {s.resize_size}px にし、もう一方はアスペクト比維持で自動計算。
                </span>
              </div>
            )}

            {opt(
              "brightness_enabled",
              "明るさ補正",
              <div className="row">{numField("brightness", "brightness", -100, 100, 1)}</div>
            )}

            {opt(
              "contrast_enabled",
              "コントラスト補正",
              <div className="row">{numField("contrast", "contrast", 0.5, 3.0, 0.1)}</div>
            )}

            {opt("grayscale_enabled", "グレースケール化")}

            {opt(
              "binary_enabled",
              "2値化",
              <>
                <div className="row">
                  {numField("binary_threshold", "threshold", 0, 255, 1)}
                  <label className="pp-inline-check">
                    <input type="checkbox" checked={s.binary_invert} onChange={(e) => set("binary_invert", e.target.checked)} />
                    反転（invert）
                  </label>
                </div>
                <p className="muted pp-hint">有効にすると内部でグレースケール化してから白黒変換します。</p>
              </>
            )}

            {opt(
              "sharpen_enabled",
              "シャープ化",
              <div className="row">{numField("sharpen_strength", "strength", 0.0, 3.0, 0.1)}</div>
            )}

            {opt(
              "clahe_enabled",
              "CLAHE",
              <div className="row">
                {numField("clahe_clip_limit", "clip_limit", 1.0, 10.0, 0.5)}
                {numField("clahe_tile_grid_size", "tile_grid_size", 4, 16, 1)}
              </div>
            )}
          </div>

          <div className="row pp-run">
            <button onClick={run} disabled={busy || !s.job_name.trim()}>
              {busy ? "実行中…" : "前処理を実行"}
            </button>
          </div>
          {error && <div className="error">{error}</div>}
          {result && (
            <div className="card">
              <strong>
                完了: 入力 {result.input_count} / 生成 {result.processed_count} / スキップ {result.skipped_count}
              </strong>
              {result.warning && <div className="warn">{result.warning}</div>}
            </div>
          )}
        </section>

        {/* 右: Before / After プレビュー */}
        <section className="card pp-preview">
          <h2>プレビュー（Before / After）</h2>
          <div className="row">
            <label className="field">
              プレビュー対象
              <select value={previewTarget} onChange={(e) => setPreviewTarget(e.target.value)}>
                {rawImages.length === 0 && <option value="">画像なし</option>}
                {rawImages.map((im) => (
                  <option key={im.filename} value={im.filename}>{im.filename}</option>
                ))}
              </select>
            </label>
            <button className="secondary" onClick={runPreview} disabled={!previewTarget || previewBusy}>
              {previewBusy ? "更新中…" : "プレビュー更新"}
            </button>
          </div>
          <p className="muted pp-hint">
            設定を変更すると自動で反映されます。画像にカーソルを合わせると拡大表示します。
          </p>

          {ba ? (
            <div className="ba-grid">
              <figure className="ba-cell">
                <figcaption className="muted">Before（元画像 {ba.before_width}×{ba.before_height}）</figcaption>
                <HoverImagePreview large thumbSrc={ba.before_url} fullSrc={ba.before_url} alt="before" />
              </figure>
              <figure className="ba-cell">
                <figcaption className="muted">After（前処理後 {ba.after_width}×{ba.after_height}）</figcaption>
                <HoverImagePreview
                  large
                  thumbSrc={`${ba.preview_url}?t=${previewSeq}`}
                  fullSrc={`${ba.preview_url}?t=${previewSeq}`}
                  alt="after"
                />
              </figure>
            </div>
          ) : (
            <p className="muted">対象画像を選ぶとプレビューを表示します。</p>
          )}
        </section>
      </div>

      {/* 最下部: 処理後プレビュー */}
      {preview.length > 0 && (
        <section className="card">
          <h2>処理後プレビュー（処理結果の代表画像）</h2>
          <div className="thumb-grid">
            {preview.map((img) => (
              <figure key={img.filename} className="thumb">
                <HoverImagePreview
                  thumbSrc={api.thumbnailUrl(name, img.filename, "processed")}
                  fullSrc={api.imageUrl(name, img.filename, "processed")}
                  alt={img.filename}
                />
                <figcaption>
                  <div className="thumb-name" title={img.filename}>{img.filename}</div>
                  <div className="muted">{img.width}×{img.height}</div>
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
