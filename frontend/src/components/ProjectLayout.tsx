// プロジェクト配下の共通レイアウト（左に工程サイドバー、右にOutlet）
import { useEffect, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectTask } from "../types";
import { WORKFLOW_STEPS } from "../workflow";

export default function ProjectLayout() {
  const { name = "" } = useParams();
  const [task, setTask] = useState<ProjectTask | null>(null);

  useEffect(() => {
    setTask(null);
    api.getProject(name).then((p) => setTask((p.task ?? "detect") as ProjectTask)).catch(() => {});
  }, [name]);

  return (
    <div className="project-layout">
      <aside className="steps">
        <div className="steps-head">
          <NavLink to="/" className="back-link">
            ← プロジェクト一覧
          </NavLink>
          <div className="project-name">{name}</div>
          {task && (
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
            >
              <span className="step-no">{s.no}</span>
              <span className="step-label">{s.label}</span>
              {!s.implemented && <span className="badge">骨組み</span>}
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
