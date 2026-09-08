// 画像選別画面。低品質・重複を自動検出して included/review を管理する。
// 「削除」は実ファイル（raw/processed/サムネイル/ラベル）を消す破壊的操作（元に戻せない）。
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import HoverImagePreview from "../components/HoverImagePreview";
import type { SelectionItem, SelectionJobStatus, SelectionSummary } from "../types";

const THUMB_SIZE_STORAGE_KEY = "yts_selection_thumb_size";
const DEFAULT_THUMB_SIZE = 210; // 変更前の表示サイズ（既定値）

type Filter = "all" | "included" | "review" | "duplicate" | "small" | "dark" | "bright" | "blur";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "すべて" },
  { key: "included", label: "included" },
  { key: "review", label: "review" },
  { key: "duplicate", label: "duplicate" },
  { key: "small", label: "small" },
  { key: "dark", label: "dark" },
  { key: "bright", label: "bright" },
  { key: "blur", label: "blur" },
];

export default function SelectionPage() {
  const { name = "" } = useParams();
  const [source, setSource] = useState("auto");
  const [minW, setMinW] = useState(320);
  const [minH, setMinH] = useState(320);
  const [blurT, setBlurT] = useState(80);
  const [darkT, setDarkT] = useState(30);
  const [brightT, setBrightT] = useState(240);
  const [detectDup, setDetectDup] = useState(true);
  // 表示サイズ（スキャン結果には影響しない、見た目だけの設定。ブラウザに保存して次回も維持する）
  const [thumbSize, setThumbSize] = useState<number>(() => {
    const saved = Number(localStorage.getItem(THUMB_SIZE_STORAGE_KEY));
    return Number.isFinite(saved) && saved >= 120 ? saved : DEFAULT_THUMB_SIZE;
  });

  useEffect(() => {
    localStorage.setItem(THUMB_SIZE_STORAGE_KEY, String(thumbSize));
  }, [thumbSize]);

  const [items, setItems] = useState<SelectionItem[]>([]);
  const [summary, setSummary] = useState<SelectionSummary | null>(null);
  const [resolvedSource, setResolvedSource] = useState("raw");
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const [currentImageCount, setCurrentImageCount] = useState(0);
  const [newImageCount, setNewImageCount] = useState(0);
  const [missingImageCount, setMissingImageCount] = useState(0);
  const [isStale, setIsStale] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // 実行中(または直近)のジョブ進捗。差分更新/完全再生成の実行中はボタンを
  // 無効化し、二重実行をUI側でも防ぐ（バックエンドも409で拒否する）。
  const [job, setJob] = useState<SelectionJobStatus | null>(null);
  const pollingRef = useRef(false);
  // 回転後にサムネ/画像のブラウザキャッシュを無効化して再取得させる
  const [bust, setBust] = useState(0);

  async function load() {
    try {
      const r = await api.getSelection(name);
      setItems(r.items);
      setSummary(r.summary);
      setResolvedSource(r.source);
      setCreatedAt(r.created_at);
      setCurrentImageCount(r.current_image_count);
      setNewImageCount(r.new_image_count);
      setMissingImageCount(r.missing_image_count);
      setIsStale(r.is_stale);
      setJob(r.job);
    } catch {
      /* 未実行 */
    }
  }

  useEffect(() => {
    load();
    return () => {
      pollingRef.current = false;
    };
  }, [name]);

  async function pollUntilDone() {
    pollingRef.current = true;
    try {
      // 最大10分（数千枚規模でも十分な余裕を持たせる）。
      for (let i = 0; i < 3000; i++) {
        if (!pollingRef.current) return;
        await new Promise((r) => setTimeout(r, 500));
        const s = await api.getSelectionRunStatus(name);
        setJob(s);
        if (s.status === "completed" || s.status === "failed") {
          if (s.status === "failed") setError(s.message ?? "画像選別に失敗しました。");
          await load();
          return;
        }
      }
    } catch (e) {
      setError(String(e));
    } finally {
      pollingRef.current = false;
      setBusy(false);
    }
  }

  async function startRun(mode: "diff" | "full") {
    if (busy || job?.status === "running" || job?.status === "queued") return;
    setBusy(true);
    setError("");
    try {
      const r = await api.runSelection(name, {
        source, min_width: minW, min_height: minH,
        blur_threshold: blurT, dark_threshold: darkT, bright_threshold: brightT,
        detect_duplicates: detectDup, mode,
      });
      setJob(r.job);
      await pollUntilDone();
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }

  function runDiff() {
    startRun("diff");
  }

  function runFull() {
    if (
      !window.confirm(
        "完全再生成を行うと、既存の全画像の判定が現在の閾値で自動判定に置き換わり、\n" +
          "手動で変更した included/review の判定はすべて失われます（元に戻せません）。\n" +
          "続行しますか？"
      )
    )
      return;
    startRun("full");
  }

  async function resetToAuto(item: SelectionItem) {
    setError("");
    try {
      await api.resetSelectionToAuto(name, item.image_id);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function setStatus(item: SelectionItem, status: string) {
    try {
      await api.updateSelectionStatus(name, item.image_id, status);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function deleteImage(item: SelectionItem) {
    if (
      !window.confirm(
        `画像「${item.image_name}」を削除します。\n` +
          "raw/processed の画像本体・サムネイル・アノテーションラベルもすべて削除されます。\n" +
          "この操作は元に戻せません。"
      )
    )
      return;
    setError("");
    try {
      await api.deleteSelectionImage(name, item.image_id);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function rotate(item: SelectionItem, angle: number) {
    setError("");
    try {
      // 回転は即反映するため作業警告(alert)は表示しない
      await api.rotateSelectionImage(name, item.image_id, angle, "processed");
      await load();
      setBust((b) => b + 1); // キャッシュ回避で回転を即座に反映
    } catch (e) {
      // processed が無い等は分かりやすく表示
      setError(String(e));
    }
  }

  const view = useMemo(() => {
    return items.filter((it) => {
      switch (filter) {
        case "included": return it.status === "included";
        case "review": return it.status === "review";
        case "all": return true;
        default: return it.warnings.includes(`${filter}_image`);
      }
    });
  }, [items, filter]);

  // "excluded" は旧仕様（削除に置き換え前）の selection.json に残っている場合のみ表示され得る
  const statusClass = (s: string) =>
    s === "included" ? "success" : s === "excluded" ? "error" : "warn";
  const statusLabel = (s: string) =>
    s === "included" ? "✓ 採用" : s === "excluded" ? "✕ 除外（旧データ）" : "△ 要確認";

  const jobRunning = job?.status === "running" || job?.status === "queued";
  const sourceLabelOf = (s: string) =>
    s === "manual" ? "手動" : s === "unknown" ? "由来不明（旧データ）" : null;

  return (
    <div className="page">
      <h1>画像選別: {name}</h1>
      <p className="muted">
        低品質・重複画像を自動検出し、included（採用）/ review（要確認）を管理します。
        自動検出だけでは削除されず一覧に残るので、内容を確認してから
        画像ごとに<strong>「削除」</strong>を押してください。
        <strong>削除は raw/processed の画像本体・サムネイル・アノテーションラベルも含めて完全に消去され、元に戻せません。</strong>
      </p>

      <details className="card sel-settings" open>
        <summary className="sel-settings-summary">チェック設定</summary>
        <div className="row sel-settings-row">
          <label className="field">
            画像ソース
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="auto">auto</option>
              <option value="raw">raw</option>
              <option value="processed">processed</option>
            </select>
          </label>
          <label className="field">min_width<input type="number" value={minW} onChange={(e) => setMinW(Number(e.target.value))} /></label>
          <label className="field">min_height<input type="number" value={minH} onChange={(e) => setMinH(Number(e.target.value))} /></label>
          <label className="field">blur_threshold<input type="number" step="1" value={blurT} onChange={(e) => setBlurT(Number(e.target.value))} /></label>
          <label className="field">dark_threshold<input type="number" value={darkT} onChange={(e) => setDarkT(Number(e.target.value))} /></label>
          <label className="field">bright_threshold<input type="number" value={brightT} onChange={(e) => setBrightT(Number(e.target.value))} /></label>
          <label className="sel-dup"><input type="checkbox" checked={detectDup} onChange={(e) => setDetectDup(e.target.checked)} /> 重複検出</label>
          <button
            onClick={runDiff}
            disabled={busy || jobRunning}
            title="新規に追加された画像だけを自動判定します。既存の手動判定（included/review変更分）はそのまま保持されます。"
          >
            {jobRunning && job?.mode === "diff" ? "実行中…" : "差分更新"}
          </button>
          <button
            className="sel-act danger"
            onClick={runFull}
            disabled={busy || jobRunning}
            title="全画像を今の閾値で判定し直します。手動判定（included/review変更分）はすべて失われます。"
          >
            {jobRunning && job?.mode === "full" ? "実行中…" : "完全再生成"}
          </button>
          <span className="sel-settings-sep" />
          <label className="field sel-size-field" title="見た目のみの設定です。チェック結果には影響しません">
            表示サイズ
            <input
              type="range"
              min={120}
              max={400}
              step={10}
              value={thumbSize}
              onChange={(e) => setThumbSize(Number(e.target.value))}
            />
            <span className="sel-size-value">{thumbSize}px</span>
          </label>
        </div>
        {error && <div className="error">{error}</div>}
        {jobRunning && (
          <div className="muted">
            {job?.mode === "full" ? "完全再生成" : "差分更新"}実行中…
            {job && job.total_count > 0 && ` (${job.processed_count} / ${job.total_count})`}
          </div>
        )}
      </details>

      {summary && (
        <>
          {/* 鮮度: 最終実行日時と、実ファイルとの差分（未反映件数）を表示する。
              これが無いと、選別結果がいつ生成されたものか利用者から分からず、
              撮影等で画像が追加され続けても気づけない（Issue #11）。 */}
          <div className="sel-summary-head">
            <span className="muted">ソース: {resolvedSource}</span>
            {createdAt && <span className="muted"> ・ 最終実行: {createdAt}</span>}
            <span className="muted"> ・ 現在の画像数: {currentImageCount}</span>
            {isStale && (
              <span className="warn">
                {" "}
                ⚠ 未反映あり（新規 {newImageCount}件 / 削除 {missingImageCount}件）— 「差分更新」で反映できます
              </span>
            )}
          </div>
          <div className="analysis-counts sel-counts">
            {[
              { label: "総数", value: summary.image_count, kind: "" },
              { label: "included", value: summary.included_count, kind: "good" },
              { label: "excluded", value: summary.excluded_count, kind: "warn" },
              { label: "review", value: summary.review_count, kind: "warn" },
              { label: "duplicate", value: summary.duplicate_count, kind: "warn" },
              { label: "small", value: summary.small_count, kind: "warn" },
              { label: "dark", value: summary.dark_count, kind: "warn" },
              { label: "bright", value: summary.bright_count, kind: "warn" },
              { label: "blur", value: summary.blur_count, kind: "warn" },
            ].map((c) => (
              <div key={c.label} className={"analysis-count " + (c.kind === "warn" && c.value > 0 ? "warn" : c.kind)}>
                <span className="analysis-count-value">{c.value}</span>
                <span className="analysis-count-label">{c.label}</span>
              </div>
            ))}
          </div>

          <div className="row">
            {FILTERS.map((f) => (
              <button key={f.key} className={"chip" + (filter === f.key ? " active" : "")} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
            <span className="muted">{view.length} 件</span>
          </div>

          <div
            className="thumb-grid sel-grid"
            style={{ "--sel-thumb-w": `${thumbSize}px` } as React.CSSProperties}
          >
            {view.map((it) => (
              <figure key={it.image_id} className={"thumb sel-card status-" + it.status}>
                <span className={"sel-status-badge " + statusClass(it.status)}>{statusLabel(it.status)}</span>
                {sourceLabelOf(it.status_source) && (
                  <span
                    className="sel-status-badge muted"
                    title="この判定の由来（auto=自動判定 / manual=手動変更 / unknown=このIssue以前の旧データ）"
                  >
                    {sourceLabelOf(it.status_source)}
                  </span>
                )}
                <HoverImagePreview
                  thumbSrc={`${api.thumbnailUrl(name, it.image_name, it.source)}&v=${bust}`}
                  fullSrc={`${api.imageUrl(name, it.image_name, it.source)}&v=${bust}`}
                  alt={it.image_name}
                />
                <figcaption>
                  <div className="thumb-name" title={it.image_name}>{it.image_name}</div>
                  <div className="muted sel-metrics">
                    {it.width}×{it.height} ・ 輝度 {it.brightness_mean} ・ ブレ {it.blur_score}
                  </div>
                  {it.warnings.length > 0 && (
                    <div className="warn sel-warns">{it.warnings.join(", ")}</div>
                  )}
                  <div className="sel-actions">
                    <button
                      className={"sel-act" + (it.status === "included" ? " on" : "")}
                      onClick={() => setStatus(it, "included")}
                    >
                      採用
                    </button>
                    <button
                      className="sel-act danger"
                      title="raw/processed・サムネイル・ラベルを完全に削除します（元に戻せません）"
                      onClick={() => deleteImage(it)}
                    >
                      削除
                    </button>
                    {it.status_source !== "auto" && (
                      <button
                        className="sel-act secondary"
                        title="この画像だけ、現在の閾値で再解析して自動判定に戻します"
                        onClick={() => resetToAuto(it)}
                      >
                        自動判定に戻す
                      </button>
                    )}
                    <span className="sel-act-sep" />
                    <button className="sel-act secondary" title="反時計90°" onClick={() => rotate(it, 90)}>↺</button>
                    <button className="sel-act secondary" title="時計90°" onClick={() => rotate(it, -90)}>↻</button>
                    <button className="sel-act secondary" title="180°" onClick={() => rotate(it, 180)}>180</button>
                  </div>
                </figcaption>
              </figure>
            ))}
            {view.length === 0 && <p className="muted">該当する画像はありません。</p>}
          </div>
        </>
      )}
    </div>
  );
}
