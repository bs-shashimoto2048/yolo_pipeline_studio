// 複数の撮影ソース（カメラ/URL）を管理するパネル（画像取り込み「カメラ・URLで撮影」タブの中身）。
// - 各ソースは個別に開始/停止・今すぐ撮影ができる
// - 自動撮影間隔はプロジェクト共通（壁時計基準で同期するため）。「全て開始」で一括起動できる
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import HoverImagePreview from "./HoverImagePreview";
import type {
  CameraInfo,
  CaptureSessionInfo,
  CaptureSourceInfo,
  VideoSourceInfo,
} from "../types";

const DEFAULT_PREVIEW_FPS = 6;
const INTERVAL_STORAGE_PREFIX = "yts_capture_interval_";

function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, totalSeconds);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

interface SourceFormValue {
  label: string;
  sourceType: "camera" | "url";
  cameraIndex: number;
  sourceUrl: string;
}

const EMPTY_FORM: SourceFormValue = { label: "", sourceType: "camera", cameraIndex: 0, sourceUrl: "" };

// URL/カメラ選択から名前を自動提案する（ユーザーが手で編集したら以降は上書きしない）
function suggestLabel(form: SourceFormValue, camerasList: CameraInfo[]): string {
  if (form.sourceType === "camera") {
    return camerasList.find((c) => c.index === form.cameraIndex)?.label ?? `カメラ ${form.cameraIndex}`;
  }
  const raw = form.sourceUrl.trim();
  if (!raw) return "";
  try {
    const u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`);
    return u.hostname;
  } catch {
    return "";
  }
}

export default function CaptureSourcesPanel({ name, onCaptured }: { name: string; onCaptured: () => void }) {
  const [sources, setSources] = useState<CaptureSourceInfo[]>([]);
  const [sessions, setSessions] = useState<Record<string, CaptureSessionInfo | undefined>>({});
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [camerasLoading, setCamerasLoading] = useState(false);
  const [knownSources, setKnownSources] = useState<VideoSourceInfo[]>([]);
  const [intervalMinutes, setIntervalMinutes] = useState<number>(() => {
    const saved = Number(localStorage.getItem(INTERVAL_STORAGE_PREFIX + name) ?? "5");
    return Number.isFinite(saved) && saved >= 0 ? saved : 5;
  });
  const [error, setError] = useState("");
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [groupBusy, setGroupBusy] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<SourceFormValue>(EMPTY_FORM);
  const addLabelTouched = useRef(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<SourceFormValue>(EMPTY_FORM);
  const [notice, setNotice] = useState("");
  const lastCapturedTotal = useRef(0);
  const pollTimer = useRef<number | null>(null);
  const streamBust = useRef<Record<string, number>>({});
  const [nowTick, setNowTick] = useState(() => Date.now());

  useEffect(() => {
    localStorage.setItem(INTERVAL_STORAGE_PREFIX + name, String(intervalMinutes));
  }, [intervalMinutes, name]);

  // カウントダウン表示用（1秒ごと、サーバー問い合わせなし）
  useEffect(() => {
    const t = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  function setBusy(id: string, v: boolean) {
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (v) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function loadSources() {
    try {
      setSources((await api.listCaptureSources(name)).sources);
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadCameras() {
    setCamerasLoading(true);
    try {
      setCameras((await api.listCameras(name)).cameras);
    } catch (e) {
      setError(String(e));
    } finally {
      setCamerasLoading(false);
    }
  }

  async function loadKnownSources() {
    try {
      setKnownSources((await api.listVideoSources(name)).sources);
    } catch {
      /* 一覧表示のみのため失敗しても致命的ではない */
    }
  }

  useEffect(() => {
    loadSources();
    loadCameras();
    loadKnownSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  // 全ソースの状態を2秒間隔でポーリングし、撮影枚数が増えたら登録画像一覧も更新する
  useEffect(() => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    async function refresh() {
      const results = await Promise.all(
        sources.map(async (s) => {
          try {
            return [s.source_id, await api.getCaptureSession(name, s.source_id)] as const;
          } catch {
            return [s.source_id, undefined] as const;
          }
        })
      );
      const next: Record<string, CaptureSessionInfo | undefined> = {};
      let total = 0;
      for (const [id, info] of results) {
        next[id] = info;
        total += info?.captured_count ?? 0;
        const active = info?.status === "running" || info?.status === "queued";
        if (active) streamBust.current[id] = (streamBust.current[id] ?? 0) + 1;
      }
      setSessions(next);
      if (total > lastCapturedTotal.current) {
        lastCapturedTotal.current = total;
        onCaptured();
      } else {
        lastCapturedTotal.current = total;
      }
      for (const [, info] of results) {
        if (info?.status === "running" && info.source_type === "url") {
          loadKnownSources();
          break;
        }
      }
    }
    if (sources.length > 0) {
      refresh();
      pollTimer.current = window.setInterval(refresh, 2000);
    }
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources, name]);

  function isActive(id: string): boolean {
    const st = sessions[id]?.status;
    return st === "running" || st === "queued";
  }

  // 複数ソースを同時にプレビューするため、MJPEG(持続接続)ではなく都度取得の
  // frame エンドポイントを使う（2秒ごとのポーリングに合わせて再取得する）。
  // 持続接続を何本も張るとブラウザの同時接続数上限（HTTP/1.1で通常オリジンあたり6）に
  // 達し、他のAPI呼び出しが失敗する（Failed to fetch）ことがあるため。
  function frameSrcFor(id: string): string {
    const bust = streamBust.current[id] ?? 0;
    return `${api.captureFrameUrl(name, id)}?t=${bust}`;
  }

  async function startOne(id: string) {
    if (busyIds.has(id) || isActive(id)) return; // 連打・重複起動を防ぐ
    const src = sources.find((s) => s.source_id === id);
    if (!src) return;
    setBusy(id, true);
    setError("");
    try {
      const res = await api.startCaptureSession(name, {
        session_name: id,
        source_type: src.source_type as "camera" | "url",
        camera_index: src.camera_index ?? 0,
        source_url: src.source_type === "url" ? src.source_url ?? undefined : undefined,
        video_fps: DEFAULT_PREVIEW_FPS,
        interval_minutes: intervalMinutes > 0 ? intervalMinutes : null,
        overwrite: true,
      });
      streamBust.current[id] = (streamBust.current[id] ?? 0) + 1;
      setSessions((prev) => ({ ...prev, [id]: res }));
    } catch (e) {
      setError(`${src.label}: ${String(e)}`);
    } finally {
      setBusy(id, false);
    }
  }

  async function stopOne(id: string) {
    setBusy(id, true);
    try {
      const res = await api.stopCaptureSession(name, id);
      setSessions((prev) => ({ ...prev, [id]: res }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(id, false);
    }
  }

  async function captureNowOne(id: string) {
    const src = sources.find((s) => s.source_id === id);
    setBusy(id, true);
    setNotice("");
    try {
      const res = await api.captureNow(name, id);
      if (res.status === "captured") {
        setNotice(`${src?.label ?? id}: 撮影しました（${res.filename ?? ""}）`);
        onCaptured();
      } else if (res.status === "pending") {
        setNotice(`${src?.label ?? id}: 撮影を受け付けました。`);
      } else {
        setError(`${src?.label ?? id}: ${res.message ?? "撮影に失敗しました。"}`);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(id, false);
    }
  }

  async function startAll() {
    setGroupBusy(true);
    setError("");
    try {
      await Promise.all(sources.map((s) => startOne(s.source_id)));
    } finally {
      setGroupBusy(false);
    }
  }

  async function stopAll() {
    setGroupBusy(true);
    try {
      await Promise.all(sources.map((s) => stopOne(s.source_id)));
    } finally {
      setGroupBusy(false);
    }
  }

  function updateAddForm(patch: Partial<SourceFormValue>) {
    setAddForm((prev) => {
      const next = { ...prev, ...patch };
      if (!addLabelTouched.current) next.label = suggestLabel(next, cameras) || next.label;
      return next;
    });
  }

  function closeAdd() {
    setAddOpen(false);
    setAddForm(EMPTY_FORM);
    addLabelTouched.current = false;
  }

  async function submitAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!addForm.label.trim()) return;
    if (addForm.sourceType === "url" && !addForm.sourceUrl.trim()) return;
    setError("");
    try {
      await api.addCaptureSource(name, {
        label: addForm.label.trim(),
        source_type: addForm.sourceType,
        camera_index: addForm.cameraIndex,
        source_url: addForm.sourceType === "url" ? addForm.sourceUrl.trim() : undefined,
      });
      closeAdd();
      await loadSources();
    } catch (e2) {
      setError(String(e2));
    }
  }

  function startEdit(s: CaptureSourceInfo) {
    setEditingId(s.source_id);
    setEditForm({
      label: s.label,
      sourceType: (s.source_type as "camera" | "url") ?? "camera",
      cameraIndex: s.camera_index ?? 0,
      sourceUrl: s.source_url ?? "",
    });
  }

  async function submitEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingId) return;
    if (!editForm.label.trim()) return;
    if (editForm.sourceType === "url" && !editForm.sourceUrl.trim()) return;
    try {
      await api.updateCaptureSource(name, editingId, {
        label: editForm.label.trim(),
        source_type: editForm.sourceType,
        camera_index: editForm.cameraIndex,
        source_url: editForm.sourceType === "url" ? editForm.sourceUrl.trim() : undefined,
      });
      setEditingId(null);
      await loadSources();
    } catch (e2) {
      setError(String(e2));
    }
  }

  async function removeSource(id: string) {
    try {
      await api.deleteCaptureSource(name, id);
      await loadSources();
    } catch (e) {
      setError(String(e));
    }
  }

  const anyActive = useMemo(() => sources.some((s) => isActive(s.source_id)), [sources, sessions]);

  return (
    <div>
      <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 8px" }}>
        接続中のカメラ、またはネットワークカメラの映像URL（RTSP/HTTP・MJPEG）を複数登録し、
        個別に「今すぐ撮影」、または一括で自動撮影できます。自動撮影間隔は全ソース共通（壁時計基準で
        同期するため、開始タイミングがずれても同じ瞬間に一斉に撮影されます）。
      </p>

      <div className="capture-toolbar">
        <label className="field">
          自動撮影間隔（分・全ソース共通）
          <input
            type="number"
            min={0}
            step={1}
            value={intervalMinutes}
            onChange={(e) => setIntervalMinutes(Math.max(0, Math.round(Number(e.target.value))))}
            placeholder="0 = 手動のみ"
          />
        </label>
        <div className="capture-toolbar-actions">
          <button type="button" onClick={startAll} disabled={groupBusy || sources.length === 0}>
            ▶ 全て開始
          </button>
          <button type="button" className="secondary" onClick={stopAll} disabled={groupBusy || !anyActive}>
            ■ 全て停止
          </button>
        </div>
        <div className="capture-toolbar-spacer" />
        <button type="button" className="secondary" onClick={() => (addOpen ? closeAdd() : setAddOpen(true))}>
          {addOpen ? "閉じる" : "+ ソースを追加"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && <div className="success">{notice}</div>}

      <div className="capture-sources-grid">
        {addOpen && (
          <form onSubmit={submitAdd} className="capture-source-card capture-source-add">
            <div className="capture-source-head">
              <span className="capture-source-label">新しいソース</span>
            </div>
            <label className="capture-add-field">
              種別
              <select
                value={addForm.sourceType}
                onChange={(e) => updateAddForm({ sourceType: e.target.value as "camera" | "url" })}
              >
                <option value="camera">ローカルカメラ</option>
                <option value="url">URL（RTSP/HTTP・MJPEG）</option>
              </select>
            </label>
            {addForm.sourceType === "camera" ? (
              <label className="capture-add-field">
                カメラ
                <div className="video-camera-row">
                  <select value={addForm.cameraIndex} onChange={(e) => updateAddForm({ cameraIndex: Number(e.target.value) })}>
                    {cameras.length === 0 && <option value={0}>（カメラ未検出）</option>}
                    {cameras.map((c) => (
                      <option key={c.index} value={c.index}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="secondary" onClick={loadCameras} disabled={camerasLoading}>
                    {camerasLoading ? "…" : "⟳"}
                  </button>
                </div>
              </label>
            ) : (
              <label className="capture-add-field">
                URL
                {knownSources.length > 0 && (
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) updateAddForm({ sourceUrl: e.target.value });
                    }}
                  >
                    <option value="">保存済みURLから選択…（{knownSources.length}件）</option>
                    {knownSources.map((s) => (
                      // value は再接続用にraw URL（password含む場合あり）を保持するが、
                      // 表示テキストはmasked_url（passwordマスク済み）を使い画面に平文表示しない。
                      <option key={s.url} value={s.url}>
                        {s.masked_url}
                      </option>
                    ))}
                  </select>
                )}
                <input
                  type="text"
                  value={addForm.sourceUrl}
                  onChange={(e) => updateAddForm({ sourceUrl: e.target.value })}
                  placeholder="http://192.0.2.10/mjpg/..."
                  required
                />
              </label>
            )}
            <label className="capture-add-field">
              名前
              <input
                value={addForm.label}
                onChange={(e) => {
                  addLabelTouched.current = true;
                  setAddForm({ ...addForm, label: e.target.value });
                }}
                required
              />
            </label>
            <div className="row" style={{ gap: 6 }}>
              <button type="submit" className="secondary">
                追加
              </button>
              <button type="button" className="secondary" onClick={closeAdd}>
                キャンセル
              </button>
            </div>
          </form>
        )}

        {sources.map((s) => {
          const session = sessions[s.source_id];
          const active = isActive(s.source_id);
          const busy = busyIds.has(s.source_id);
          const countdown =
            active && session?.next_auto_capture_at
              ? Math.max(0, Math.round((new Date(session.next_auto_capture_at).getTime() - nowTick) / 1000))
              : null;
          const editing = editingId === s.source_id;

          return (
            <div key={s.source_id} className="capture-source-card">
              {editing ? (
                <form onSubmit={submitEdit} className="capture-source-edit">
                  <input value={editForm.label} onChange={(e) => setEditForm({ ...editForm, label: e.target.value })} required />
                  <select
                    value={editForm.sourceType}
                    onChange={(e) => setEditForm({ ...editForm, sourceType: e.target.value as "camera" | "url" })}
                  >
                    <option value="camera">ローカルカメラ</option>
                    <option value="url">URL</option>
                  </select>
                  {editForm.sourceType === "camera" ? (
                    <select value={editForm.cameraIndex} onChange={(e) => setEditForm({ ...editForm, cameraIndex: Number(e.target.value) })}>
                      {cameras.length === 0 && <option value={0}>（カメラ未検出）</option>}
                      {cameras.map((c) => (
                        <option key={c.index} value={c.index}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={editForm.sourceUrl}
                      onChange={(e) => setEditForm({ ...editForm, sourceUrl: e.target.value })}
                      placeholder="URL"
                      required
                    />
                  )}
                  <div className="row" style={{ gap: 6 }}>
                    <button type="submit" className="secondary">
                      保存
                    </button>
                    <button type="button" className="secondary" onClick={() => setEditingId(null)}>
                      キャンセル
                    </button>
                  </div>
                </form>
              ) : (
                <>
                  <div className="capture-source-head">
                    <span className="capture-source-label" title={s.label}>
                      {s.label}
                    </span>
                    <span className="im-badge">{s.source_type === "camera" ? "カメラ" : "URL"}</span>
                  </div>
                  <div className="video-live-frame capture-source-preview">
                    {countdown !== null && <span className="capture-countdown-badge">{formatCountdown(countdown)}</span>}
                    {active ? (
                      <HoverImagePreview
                        thumbSrc={frameSrcFor(s.source_id)}
                        fullSrc={frameSrcFor(s.source_id)}
                        alt={s.label}
                        large
                      />
                    ) : (
                      <p className="muted video-live-placeholder">未開始</p>
                    )}
                  </div>
                  <p className="muted capture-source-meta">
                    {session ? (
                      <>
                        <span className={active ? "success" : "muted"}>● {session.status}</span>
                        {" ／ 撮影 "}
                        {session.captured_count}枚
                      </>
                    ) : (
                      "未開始"
                    )}
                  </p>
                  <div className="capture-source-actions">
                    {!active ? (
                      <button type="button" onClick={() => startOne(s.source_id)} disabled={busy}>
                        開始
                      </button>
                    ) : (
                      <button type="button" className="danger" onClick={() => stopOne(s.source_id)} disabled={busy}>
                        停止
                      </button>
                    )}
                    <button type="button" className="secondary" onClick={() => captureNowOne(s.source_id)} disabled={busy || !active}>
                      📷 今すぐ
                    </button>
                  </div>
                  <div className="capture-source-manage">
                    <button type="button" onClick={() => startEdit(s)} disabled={active}>
                      編集
                    </button>
                    <button type="button" onClick={() => removeSource(s.source_id)} disabled={active}>
                      削除
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
        {sources.length === 0 && !addOpen && (
          <p className="muted">撮影ソースがありません。「+ ソースを追加」から登録してください。</p>
        )}
      </div>
    </div>
  );
}
