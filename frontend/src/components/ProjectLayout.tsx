// プロジェクト配下の共通レイアウト（左に工程サイドバー、右にOutlet）
import { useEffect, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectTask } from "../types";
import { WORKFLOW_STEPS } from "../workflow";

export default function ProjectLayout() {
  const { name = "" } = useParams();
  const [task, setTask] = useState<ProjectTask | null>(null);

  // 左の工程メニューの折り畳み状態。ブラウザに保存して次回も維持する。
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("yts_steps_collapsed") === "1"
  );
  useEffect(() => {
    localStorage.setItem("yts_steps_collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  useEffect(() => {
    setTask(null);
    api.getProject(name).then((p) => setTask((p.task ?? "detect") as ProjectTask)).catch(() => {});
  }, [name]);

  return (
    <div className="project-layout">
      <aside className={"steps" + (collapsed ? " collapsed" : "")}>
        <div className="steps-head">
          <div className="steps-head-row">
            <NavLink to="/" className="back-link" title="プロジェクト一覧へ">
              {collapsed ? "←" : "← プロジェクト一覧"}
            </NavLink>
            <button
              type="button"
              className="steps-toggle"
              onClick={() => setCollapsed((c) => !c)}
              title={collapsed ? "メニューを開く" : "メニューを折り畳む"}
              aria-label={collapsed ? "メニューを開く" : "メニューを折り畳む"}
              aria-expanded={!collapsed}
            >
              {collapsed ? "▶" : "◀"}
            </button>
          </div>
          {!collapsed && <div className="project-name">{name}</div>}
          {!collapsed && task && (
            <span className={"side-task-badge " + (task === "segment" ? "seg" : "det")}>
              {task === "segment" ? "◨ Segmentation" : "▭ BBOX"}
            </span>
          )}
        </div>
        <nav>
          {WORKFLOW_STEPS.map((s) => (
            <NavLink
              key={s.path}
              to={`/p/${name}/${s.path}`}
              className={({ isActive }) =>
                "step" + (isActive ? " active" : "")
              }
              title={collapsed ? s.label : undefined}
            >
              <span className="step-no">{s.no}</span>
              {!collapsed && <span className="step-label">{s.label}</span>}
              {!collapsed && !s.implemented && <span className="badge">骨組み</span>}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
