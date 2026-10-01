// targeted capture review workflow（Issue #42）。
// Issue #41で作ったrare-class capture infrastructure（purpose/target/max_frames、
// frames.json、review_status）を、人が効率よくレビューできるUIへ仕上げる。
//
// 最重要原則: このUIはGTを自動判定しない。target position/classはあくまで
// 収集意図であり、人が画像を見て初めてacceptedにする。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  CaptureFrameMetadata,
  CaptureReviewStatus,
  CaptureReviewSummary,
  CaptureSessionCreateRequest,
  CaptureTargetProgress,
} from "../types";

const STATUS_LABEL: Record<CaptureReviewStatus, string> = {
  unreviewed: "未レビュー",
  accepted: "採用",
  rejected_duplicate: "重複",
  rejected_ambiguous: "曖昧",
  rejected_wrong_target: "対象外",
};

type SessionFilter = "all" | "unreviewed" | "completed";

function isCompleted(s: CaptureReviewSummary): boolean {
  return s.captured_count > 0 && s.unreviewed_count === 0;
}

export default function TargetedCaptureReview({ name }: { name: string }) {
  const [sessions, setSessions] = useState<CaptureReviewSummary[]>([]);
  const [filter, setFilter] = useState<SessionFilter>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // 新規targeted session作成フォーム
  const [showNewForm, setShowNewForm] = useState(false);
  const [newSessionName, setNewSessionName] = useState("");
  const [newSourceType, setNewSourceType] = useState<"camera" | "url">("camera");
  const [newCameraIndex, setNewCameraIndex] = useState(0);
  const [newSourceUrl, setNewSourceUrl] = useState("");
  const [newDigitPosition, setNewDigitPosition] = useState<string>("");
  const [newTargetClass, setNewTargetClass] = useState("");
  const [newMaxFrames, setNewMaxFrames] = useState<string>("");
  const [newPurpose, setNewPurpose] = useState("rare_class_collection");

  // レビュー対象session
  const [selectedSid, setSelectedSid] = useState<string | null>(null);
  const [frames, setFrames] = useState<CaptureFrameMetadata[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);

  // duplicate audit
  const [manifestPath, setManifestPath] = useState("");
  const [gtPosition, setGtPosition] = useState<string>("");
  const [auditResults, setAuditResults] = useState<Record<string, { verdict: string; splits: string[] }>>({});
  const [auditError, setAuditError] = useState("");
  const [auditBusy, setAuditBusy] = useState(false);

  // target progress
  const [progress, setProgress] = useState<CaptureTargetProgress | null>(null);
  const [progressError, setProgressError] = useState("");

  async function loadSessions() {
    try {
      const r = await api.listCaptureReviewSummaries(name);
      setSessions(r.sessions);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  async function loadFrames(sid: string, preserveIndex = false) {
    try {
      const r = await api.listCaptureFrames(name, sid);
      setFrames(r.frames);
      if (!preserveIndex) {
        const firstUnreviewed = r.frames.findIndex((f) => f.review_status === "unreviewed");
        setCurrentIndex(firstUnreviewed >= 0 ? firstUnreviewed : 0);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  function selectSession(sid: string) {
    setSelectedSid(sid);
    setAuditResults({});
    setAuditError("");
    loadFrames(sid);
  }

  async function startNewSession(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const req: CaptureSessionCreateRequest = {
        session_name: newSessionName,
        source_type: newSourceType,
        camera_index: newCameraIndex,
        source_url: newSourceType === "url" ? newSourceUrl : null,
        video_fps: 10,
        interval_minutes: null,
        overwrite: false,
        purpose: newPurpose || null,
        target:
          newDigitPosition !== "" || newTargetClass !== ""
            ? { digit_position: newDigitPosition === "" ? null : Number(newDigitPosition), target_class: newTargetClass || null }
            : null,
        max_frames: newMaxFrames === "" ? null : Number(newMaxFrames),
      };
      await api.startCaptureSession(name, req);
      setShowNewForm(false);
      setNewSessionName("");
      await loadSessions();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const currentFrame = frames[currentIndex];

  const setReview = useCallback(
    async (status: CaptureReviewStatus) => {
      if (!selectedSid || !currentFrame) return;
      try {
        await api.updateCaptureFrameReview(name, selectedSid, currentFrame.stem, { review_status: status });
        // 次のunreviewedへ自動移動（§10: review速度優先）
        setFrames((prev) => {
          const next = prev.map((f) => (f.stem === currentFrame.stem ? { ...f, review_status: status } : f));
          const nextUnreviewedFromHere = next.findIndex(
            (f, i) => i > currentIndex && f.review_status === "unreviewed"
          );
          const anyUnreviewed = next.findIndex((f) => f.review_status === "unreviewed");
          setCurrentIndex(nextUnreviewedFromHere >= 0 ? nextUnreviewedFromHere : anyUnreviewed >= 0 ? anyUnreviewed : currentIndex);
          return next;
        });
        await loadSessions();
      } catch (e) {
        setError(String(e));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedSid, currentFrame, currentIndex, name]
  );

  function goPrev() {
    setCurrentIndex((i) => Math.max(0, i - 1));
  }
  function goNext() {
    setCurrentIndex((i) => Math.min(frames.length - 1, i + 1));
  }

  // --- keyboard shortcuts（§9: A=accepted D=duplicate X=ambiguous W=wrong target、
  //     ←/→=前後。既存ページ（AnnotatePage等）とは別ルートのためショートカット衝突なし） ---
  const setReviewRef = useRef(setReview);
  setReviewRef.current = setReview;
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!selectedSid || frames.length === 0) return;
      if (e.key === "a" || e.key === "A") setReviewRef.current("accepted");
      else if (e.key === "d" || e.key === "D") setReviewRef.current("rejected_duplicate");
      else if (e.key === "x" || e.key === "X") setReviewRef.current("rejected_ambiguous");
      else if (e.key === "w" || e.key === "W") setReviewRef.current("rejected_wrong_target");
      else if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "ArrowRight") goNext();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSid, frames.length]);

  async function runDuplicateAudit() {
    if (!selectedSid || !manifestPath) return;
    setAuditBusy(true);
    setAuditError("");
    try {
      const r = await api.getCaptureDuplicateAudit(
        name, selectedSid, manifestPath, gtPosition === "" ? null : Number(gtPosition)
      );
      const next: Record<string, { verdict: string; splits: string[] }> = {};
      for (const v of r.results) next[v.stem] = { verdict: v.verdict, splits: v.duplicate_splits };
      setAuditResults(next);
    } catch (e) {
      setAuditError(String(e));
    } finally {
      setAuditBusy(false);
    }
  }

  async function loadProgress() {
    if (!manifestPath) return;
    setProgressError("");
    try {
      const r = await api.getTargetedCaptureProgress(
        name, manifestPath,
        newDigitPosition === "" ? null : Number(newDigitPosition),
        newTargetClass || null,
        gtPosition === "" ? null : Number(gtPosition)
      );
      setProgress(r);
    } catch (e) {
      setProgressError(String(e));
    }
  }

  const view = useMemo(() => {
    return sessions.filter((s) => {
      if (filter === "unreviewed") return s.unreviewed_count > 0;
      if (filter === "completed") return isCompleted(s);
      return true;
    });
  }, [sessions, filter]);

  const reviewedCount = frames.filter((f) => f.review_status !== "unreviewed").length;
  const acceptedCount = frames.filter((f) => f.review_status === "accepted").length;
  const rejectedCount = frames.length - reviewedCount === 0
    ? reviewedCount - acceptedCount
    : frames.filter((f) => f.review_status.startsWith("rejected_")).length;
  const auditVerdict = currentFrame ? auditResults[currentFrame.stem] : undefined;

  return (
    <section className="card tcr-root">
      <h2>targeted capture レビュー</h2>
      <p className="muted" style={{ fontSize: "0.8rem" }}>
        target position/classは撮影時の<strong>収集意図</strong>であり、正解ラベルではありません。
        画像を見て内容を確認してから採否を判定してください。
      </p>
      {error && <div className="error">{error}</div>}

      <div className="row">
        <button type="button" onClick={() => setShowNewForm((v) => !v)}>
          {showNewForm ? "閉じる" : "新規 targeted session"}
        </button>
        {["all", "unreviewed", "completed"].map((f) => (
          <button
            key={f}
            type="button"
            className={"chip" + (filter === f ? " active" : "")}
            onClick={() => setFilter(f as SessionFilter)}
          >
            {f === "all" ? "All" : f === "unreviewed" ? "Unreviewedあり" : "Completed review"}
          </button>
        ))}
      </div>

      {showNewForm && (
        <form className="card tcr-new-form" onSubmit={startNewSession}>
          <div className="row">
            <label className="field">
              session_name
              <input value={newSessionName} onChange={(e) => setNewSessionName(e.target.value)} required />
            </label>
            <label className="field">
              source_type
              <select value={newSourceType} onChange={(e) => setNewSourceType(e.target.value as "camera" | "url")}>
                <option value="camera">camera</option>
                <option value="url">url</option>
              </select>
            </label>
            {newSourceType === "camera" ? (
              <label className="field">
                camera_index
                <input type="number" value={newCameraIndex} onChange={(e) => setNewCameraIndex(Number(e.target.value))} />
              </label>
            ) : (
              <label className="field">
                source_url
                <input value={newSourceUrl} onChange={(e) => setNewSourceUrl(e.target.value)} />
              </label>
            )}
          </div>
          <div className="row">
            <label className="field" title="収集意図。GTではない">
              digit_position
              <input type="number" min={0} value={newDigitPosition} onChange={(e) => setNewDigitPosition(e.target.value)} />
            </label>
            <label className="field" title="収集意図。GTではない">
              target_class
              <input value={newTargetClass} onChange={(e) => setNewTargetClass(e.target.value)} />
            </label>
            <label className="field" title="同一physical transitionの連写水増し防止">
              max_frames
              <input type="number" min={1} value={newMaxFrames} onChange={(e) => setNewMaxFrames(e.target.value)} />
            </label>
            <label className="field">
              purpose
              <input value={newPurpose} onChange={(e) => setNewPurpose(e.target.value)} />
            </label>
            <button type="submit" disabled={busy || !newSessionName}>
              {busy ? "作成中…" : "開始"}
            </button>
          </div>
        </form>
      )}

      <table className="tcr-session-table">
        <thead>
          <tr>
            <th>session</th><th>purpose</th><th>target</th><th>captured</th>
            <th>unreviewed</th><th>accepted</th><th>rejected</th><th>created_at</th>
          </tr>
        </thead>
        <tbody>
          {view.map((s) => (
            <tr
              key={s.session_id}
              className={"tcr-session-row" + (selectedSid === s.session_id ? " active" : "")}
              onClick={() => selectSession(s.session_id)}
            >
              <td>{s.session_id}</td>
              <td className="muted">{s.purpose ?? "—"}</td>
              <td className="muted">
                {s.target ? `pos=${s.target.digit_position ?? "?"} class=${s.target.target_class ?? "?"}` : "—"}
              </td>
              <td>{s.captured_count}</td>
              <td className={s.unreviewed_count > 0 ? "warn" : ""}>{s.unreviewed_count}</td>
              <td className="success">{s.accepted_count}</td>
              <td>
                {s.rejected_duplicate_count + s.rejected_ambiguous_count + s.rejected_wrong_target_count}
              </td>
              <td className="muted">{s.created_at ?? "—"}</td>
            </tr>
          ))}
          {view.length === 0 && (
            <tr>
              <td colSpan={8} className="muted">No targeted sessions</td>
            </tr>
          )}
        </tbody>
      </table>

      {selectedSid && (
        <div className="card tcr-review-panel">
          <h3>{selectedSid} のレビュー</h3>
          {frames.length === 0 ? (
            <p className="muted">No frames captured yet.</p>
          ) : (
            <>
              <div className="row tcr-progress">
                <span>Reviewed {reviewedCount} / {frames.length}</span>
                <span className="success">Accepted {acceptedCount}</span>
                <span className="warn">Rejected {rejectedCount}</span>
              </div>

              {currentFrame ? (
                <div className="tcr-frame-view">
                  <img
                    className="tcr-frame-image"
                    src={api.imageUrl(name, `${currentFrame.stem}.jpg`)}
                    alt={currentFrame.stem}
                  />
                  <div className="tcr-frame-meta">
                    <div><strong>{currentFrame.stem}</strong></div>
                    <div className="muted">frame #{currentFrame.frame_index} ・ {currentFrame.captured_at}</div>
                    <div>
                      target position: <strong>{currentFrame.target_digit_position ?? "—"}</strong>
                      {" / "}
                      target class: <strong>{currentFrame.target_class ?? "—"}</strong>
                      <span className="muted"> （収集意図、GTではありません）</span>
                    </div>
                    <div>
                      現在の状態:{" "}
                      <span className={currentFrame.review_status === "accepted" ? "success" : "muted"}>
                        {STATUS_LABEL[currentFrame.review_status]}
                      </span>
                    </div>
                    {auditVerdict && (
                      <div className={auditVerdict.verdict === "near_duplicate" ? "warn" : "success"}>
                        duplicate audit:{" "}
                        {auditVerdict.verdict === "near_duplicate"
                          ? `Near duplicate: ${auditVerdict.splits.join(", ")}`
                          : "No overlap"}
                      </div>
                    )}
                    <div className="row tcr-review-actions">
                      <button type="button" className="tcr-act accept" onClick={() => setReview("accepted")} title="A">
                        Accepted (A)
                      </button>
                      <button type="button" className="tcr-act" onClick={() => setReview("rejected_duplicate")} title="D">
                        Duplicate (D)
                      </button>
                      <button type="button" className="tcr-act" onClick={() => setReview("rejected_ambiguous")} title="X">
                        Ambiguous (X)
                      </button>
                      <button type="button" className="tcr-act" onClick={() => setReview("rejected_wrong_target")} title="W">
                        Wrong target (W)
                      </button>
                      <span className="tcr-act-sep" />
                      <button type="button" className="secondary" onClick={goPrev} disabled={currentIndex === 0}>← Prev</button>
                      <button type="button" className="secondary" onClick={goNext} disabled={currentIndex >= frames.length - 1}>Next →</button>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="muted">No unreviewed frames remaining.</p>
              )}

              <div className="tcr-thumb-strip">
                {frames.map((f, i) => (
                  <button
                    key={f.stem}
                    type="button"
                    className={"tcr-thumb-btn status-" + f.review_status + (i === currentIndex ? " active" : "")}
                    onClick={() => setCurrentIndex(i)}
                    title={`${f.stem} — ${STATUS_LABEL[f.review_status]}`}
                  >
                    <img src={api.thumbnailUrl(name, `${f.stem}.jpg`)} alt={f.stem} />
                  </button>
                ))}
              </div>

              <details className="card tcr-audit-form">
                <summary>Duplicate audit（Train/Val/Test、read-only）</summary>
                <div className="row">
                  <label className="field">
                    manifest_path
                    <input
                      placeholder="例: data_manifests/meter_src002_split_v3.csv"
                      value={manifestPath}
                      onChange={(e) => setManifestPath(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    gt_position
                    <input type="number" min={0} value={gtPosition} onChange={(e) => setGtPosition(e.target.value)} />
                  </label>
                  <button type="button" onClick={runDuplicateAudit} disabled={auditBusy || !manifestPath}>
                    {auditBusy ? "監査中…" : "acceptedフレームを監査"}
                  </button>
                </div>
                {auditError && <div className="error">{auditError}</div>}
                <p className="muted" style={{ fontSize: "0.78rem" }}>
                  near-duplicateと判明したらTest/Val/Train側は一切変更せず、
                  このsession側のframeを rejected_duplicate にしてください。
                </p>
              </details>

              <div className="row">
                <a href={api.captureCandidateManifestUrl(name, selectedSid, false)} target="_blank" rel="noreferrer">
                  candidate manifest（全件）をexport
                </a>
                <a href={api.captureCandidateManifestUrl(name, selectedSid, true)} target="_blank" rel="noreferrer">
                  candidate manifest（accepted onlyのみ）をexport
                </a>
              </div>

              <details className="card tcr-progress-form">
                <summary>Accepted independent primary 進捗（同一 project+position+class 集計）</summary>
                <div className="row">
                  <button type="button" onClick={loadProgress} disabled={!manifestPath}>進捗を取得</button>
                  <span className="muted">
                    フォーム上部の digit_position / target_class と manifest_path を使用します。
                  </span>
                </div>
                {progressError && <div className="error">{progressError}</div>}
                {progress && (
                  <div className="tcr-progress-result">
                    <div>
                      Accepted independent primary:{" "}
                      <strong>{progress.independent_primary}</strong> / {progress.threshold_minimum}
                      {progress.independent_primary >= progress.threshold_minimum ? (
                        <span className="success"> ✓ 次training issue起票の最低条件に到達</span>
                      ) : (
                        <span className="muted"> （最低条件未到達）</span>
                      )}
                    </div>
                    <div className="muted">
                      Minimum: {progress.threshold_minimum} ・ Recommended: {progress.threshold_recommended_low}–{progress.threshold_recommended_high}
                    </div>
                    <div className="muted">
                      accepted_total={progress.accepted_total} − accepted_flagged_duplicate={progress.accepted_flagged_duplicate}{" "}
                      = independent_primary={progress.independent_primary}
                    </div>
                    <div className="muted" style={{ fontSize: "0.78rem" }}>
                      閾値に到達しても自動でtraining issueは起票されません（人がdatasetをレビューしてから判断します）。
                    </div>
                  </div>
                )}
              </details>
            </>
          )}
        </div>
      )}
    </section>
  );
}
