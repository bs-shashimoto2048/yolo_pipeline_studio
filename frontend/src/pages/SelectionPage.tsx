// 画像選別画面。低品質・重複を検出し included/excluded/review を管理（物理削除しない）。
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import HoverImagePreview from "../components/HoverImagePreview";
import type { SelectionItem, SelectionSummary } from "../types";

type Filter = "all" | "included" | "excluded" | "review" | "duplicate" | "small" | "dark" | "bright" | "blur";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "すべて" },
  { key: "included", label: "included" },
  { key: "excluded", label: "excluded" },
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

  const [items, setItems] = useState<SelectionItem[]>([]);
  const [summary, setSummary] = useState<SelectionSummary | null>(null);
  const [resolvedSource, setResolvedSource] = useState("raw");
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // 回転後にサムネ/画像のブラウザキャッシュを無効化して再取得させる
  const [bust, setBust] = useState(0);

  async function load() {
    try {
      const r = await api.getSelection(name);
      setItems(r.items);
      setSummary(r.summary);
      setResolvedSource(r.source);
    } catch {
      /* 未実行 */
    }
  }

  useEffect(() => {
    load();
  }, [name]);

  async function run() {
    setBusy(true);
    setError("");
    try {
      const r = await api.runSelection(name, {
        source, min_width: minW, min_height: minH,
        blur_threshold: blurT, dark_threshold: darkT, bright_threshold: brightT,
        detect_duplicates: detectDup, overwrite: true,
      });
      setSummary(r.summary);
      setResolvedSource(r.source);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
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
        case "excluded": return it.status === "excluded";
        case "review": return it.status === "review";
        case "all": return true;
        default: return it.warnings.includes(`${filter}_image`);
      }
    });
  }, [items, filter]);

  const statusClass = (s: string) =>
    s === "included" ? "success" : s === "excluded" ? "error" : "warn";

  return (
    <div className="page">
      <h1>画像選別: {name}</h1>
      <p className="muted">
        低品質・重複画像を検出して included / excluded / review を管理します。
        <strong>画像は物理削除しません</strong>（selection.json に保存）。除外は
        データセット作成時に反映できます。
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
          <button onClick={run} disabled={busy}>{busy ? "実行中…" : "チェック実行"}</button>
        </div>
        {error && <div className="error">{error}</div>}
      </details>

      {summary && (
        <>
          {/* サマリーを1行インラインでコンパクトに */}
          <div className="sel-summary">
            <span className="muted sel-source">ソース: {resolvedSource}</span>
            {[
              { label: "総数", value: summary.image_count },
              { label: "included", value: summary.included_count },
              { label: "excluded", value: summary.excluded_count, warn: true },
              { label: "review", value: summary.review_count, warn: true },
              { label: "duplicate", value: summary.duplicate_count, warn: true },
              { label: "small", value: summary.small_count, warn: true },
              { label: "dark", value: summary.dark_count, warn: true },
              { label: "bright", value: summary.bright_count, warn: true },
              { label: "blur", value: summary.blur_count, warn: true },
            ].map((c) => (
              <span key={c.label} className="summary-stat">
                <span className={"summary-value" + (c.warn && c.value > 0 ? " warn" : "")}>{c.value}</span>
                <span className="summary-label">{c.label}</span>
              </span>
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

          <div className="thumb-grid sel-grid">
            {view.map((it) => (
              <figure key={it.image_id} className="thumb">
                <HoverImagePreview
                  thumbSrc={`${api.thumbnailUrl(name, it.image_name, it.source)}&v=${bust}`}
                  fullSrc={`${api.imageUrl(name, it.image_name, it.source)}&v=${bust}`}
                  alt={it.image_name}
                />
                <figcaption>
                  <div className="thumb-name" title={it.image_name}>{it.image_name}</div>
                  <div className={statusClass(it.status)}>● {it.status}</div>
                  <div className="muted" style={{ fontSize: "0.7rem" }}>
                    {it.width}×{it.height} / 輝度 {it.brightness_mean} / ブレ {it.blur_score}
                  </div>
                  {it.warnings.length > 0 && (
                    <div className="warn" style={{ fontSize: "0.7rem" }}>{it.warnings.join(", ")}</div>
                  )}
                  <div className="row" style={{ gap: 4, margin: "4px 0" }}>
                    <button style={{ padding: "2px 6px" }} onClick={() => setStatus(it, "included")}>採用</button>
                    <button style={{ padding: "2px 6px" }} className="danger" onClick={() => setStatus(it, "excluded")}>除外</button>
                  </div>
                  <div className="row rotate-btns" style={{ gap: 4, margin: "4px 0" }}>
                    <button className="secondary" onClick={() => rotate(it, 90)}>↺90°</button>
                    <button className="secondary" onClick={() => rotate(it, -90)}>↻90°</button>
                    <button className="secondary" onClick={() => rotate(it, 180)}>180°</button>
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
