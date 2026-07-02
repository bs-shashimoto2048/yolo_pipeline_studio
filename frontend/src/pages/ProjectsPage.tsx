// プロジェクト管理（トップ画面）。ブランドバナー（ヒーロー）＋一覧＋新規作成。
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectSummary, ProjectTask } from "../types";

const TASK_LABELS: Record<string, string> = {
  detect: "物体検出（bbox）",
  segment: "セグメンテーション（輪郭）",
};

// ヒーローの特徴アイコン（インラインSVG・currentColor）
function Icon({ kind }: { kind: string }) {
  const common = {
    width: 26,
    height: 26,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (kind) {
    case "data":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="8.5" cy="9" r="1.5" />
          <path d="M21 16l-5-5-7 7" />
        </svg>
      );
    case "annotate":
      return (
        <svg {...common}>
          <path d="M20.6 13.4 13 21l-9-9 7.6-7.6L20.6 13.4z" />
          <circle cx="8.5" cy="8.5" r="1.3" />
        </svg>
      );
    case "train":
      return (
        <svg {...common}>
          <rect x="7" y="7" width="10" height="10" rx="2" />
          <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5 5l2.5 2.5M19 5l-2.5 2.5M5 19l2.5-2.5M19 19l-2.5-2.5" />
        </svg>
      );
    case "evaluate":
      return (
        <svg {...common}>
          <path d="M4 20V4M4 20h16" />
          <path d="M8 16v-4M12 16V8M16 16v-6" />
          <path d="M7 9l3-3 3 2 4-4" />
        </svg>
      );
    case "export":
      return (
        <svg {...common}>
          <path d="M12 3v10M8 9l4 4 4-4" />
          <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
        </svg>
      );
    default:
      return null;
  }
}

const FEATURES = [
  { kind: "data", label: "データ管理" },
  { kind: "annotate", label: "アノテーション" },
  { kind: "train", label: "モデル学習" },
  { kind: "evaluate", label: "評価・可視化" },
  { kind: "export", label: "モデル出力" },
];

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [task, setTask] = useState<ProjectTask>("detect");
  const [error, setError] = useState("");
  const [health, setHealth] = useState("");
  const navigate = useNavigate();

  async function reload() {
    try {
      setProjects(await api.listProjects());
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth(h.message))
      .catch((e) => setHealth("APIに接続できません: " + e));
    reload();
  }, []);

  async function onDelete(projName: string) {
    if (
      !window.confirm(
        `プロジェクト「${projName}」を削除します。\n` +
          "画像、ラベル、学習結果、モデル、レポートもすべて削除されます。\n" +
          "この操作は元に戻せません。"
      )
    )
      return;
    setError("");
    try {
      await api.deleteProject(projName);
      await reload();
    } catch (e) {
      setError(String(e));
    }
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createProject(name.trim(), description.trim(), task);
      setName("");
      setDescription("");
      setTask("detect");
      await reload();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="landing">
      {/* ヒーローバナー */}
      <section className="hero">
        <div className="hero-left">
          <div className="hero-brand">
            <div className="scan-frame">
              <span className="hero-yolo">
                YOL
                <span className="hero-o">
                  O
                  <svg className="hero-cube" viewBox="0 0 24 24" aria-hidden>
                    <path
                      d="M12 3l7 4v10l-7 4-7-4V7l7-4z"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinejoin="round"
                    />
                    <path d="M12 3v8M12 11l7-4M12 11l-7-4" fill="none" stroke="currentColor" strokeWidth="1.6" />
                  </svg>
                </span>
              </span>
            </div>
            <div className="hero-studio">Tuning Studio</div>
          </div>

          <div className="hero-tagline">
            アノテーションから学習・評価・ONNXエクスポートまでをシームレスに統合したコンピュータビジョン開発環境。
          </div>

          <div className="hero-features">
            {FEATURES.map((f) => (
              <div key={f.kind} className="hero-feature">
                <span className="hero-feature-icon">
                  <Icon kind={f.kind} />
                </span>
                <span className="hero-feature-label">{f.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="hero-right">
          <div className="hero-badge">
            <div className="hero-badge-ring">
              <svg viewBox="0 0 24 24" width="30" height="30" aria-hidden>
                <path d="M12 3l7 4v10l-7 4-7-4V7l7-4z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                <path d="M12 3v8M12 11l7-4M12 11l-7-4" fill="none" stroke="currentColor" strokeWidth="1.6" />
              </svg>
            </div>
            <div className="hero-badge-title">BBOX</div>
            <div className="hero-badge-sub">物体検出</div>
          </div>
          <div className="hero-badge cyan">
            <div className="hero-badge-ring">
              <svg viewBox="0 0 24 24" width="30" height="30" aria-hidden>
                <rect x="3" y="3" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.9" />
                <rect x="14" y="3" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.55" />
                <rect x="3" y="14" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.55" />
                <rect x="14" y="14" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.9" />
              </svg>
            </div>
            <div className="hero-badge-title">Segmentation</div>
            <div className="hero-badge-sub">セマンティックセグメンテーション</div>
          </div>
        </div>

        <span className="hero-status">{health}</span>
      </section>

      <div className="landing-body">
        <section className="card">
          <h2>新規プロジェクト作成</h2>
          <form onSubmit={onCreate} className="row">
            <input
              placeholder="プロジェクト名（英数 _ - のみ）"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <input
              placeholder="説明（任意）"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <label className="field">
              タスク種別
              <select value={task} onChange={(e) => setTask(e.target.value as ProjectTask)} style={{ width: 220 }}>
                <option value="detect">{TASK_LABELS.detect}</option>
                <option value="segment">{TASK_LABELS.segment}</option>
              </select>
            </label>
            <button type="submit" disabled={!name.trim()}>
              作成
            </button>
          </form>
          {error && <div className="error">{error}</div>}
        </section>

        <section className="card">
          <h2>プロジェクト一覧</h2>
          {projects.length === 0 ? (
            <p className="muted">プロジェクトがありません。上から作成してください。</p>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>名前</th>
                    <th>タスク</th>
                    <th>説明</th>
                    <th>画像</th>
                    <th>ラベル</th>
                    <th>アノテ進捗</th>
                    <th>クラス</th>
                    <th>学習回数</th>
                    <th>作成日</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((p) => {
                    const prog =
                      p.image_count > 0
                        ? Math.min(100, Math.round((p.label_count / p.image_count) * 100))
                        : 0;
                    return (
                      <tr key={p.name}>
                        <td>{p.name}</td>
                        <td>
                          <span className={"task-badge " + (p.task === "segment" ? "seg" : "det")}>
                            {p.task === "segment" ? "Segmentation" : "BBOX"}
                          </span>
                        </td>
                        <td className="muted">{p.description}</td>
                        <td>{p.image_count}</td>
                        <td>{p.label_count}</td>
                        <td>
                          <div className="proj-prog" title={`${p.label_count}/${p.image_count} 枚`}>
                            <div className="proj-prog-bar">
                              <span
                                className={prog >= 100 ? "done" : ""}
                                style={{ width: `${prog}%` }}
                              />
                            </div>
                            <span className="proj-prog-label">{prog}%</span>
                          </div>
                        </td>
                        <td>{p.class_count}</td>
                        <td>{p.train_count}</td>
                        <td className="muted">{p.created_at ? p.created_at.slice(0, 10) : "-"}</td>
                        <td>
                          <button onClick={() => navigate(`/p/${p.name}/setup`)}>開く</button>{" "}
                          <button className="danger" onClick={() => onDelete(p.name)}>
                            削除
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
