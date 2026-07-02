// プロジェクト配下の共通レイアウト（左に工程サイドバー、右にOutlet）
import { NavLink, Outlet, useParams } from "react-router-dom";
import { WORKFLOW_STEPS } from "../workflow";

export default function ProjectLayout() {
  const { name = "" } = useParams();

  return (
    <div className="project-layout">
      <aside className="steps">
        <div className="steps-head">
          <NavLink to="/" className="back-link">
            ← プロジェクト一覧
          </NavLink>
          <div className="project-name">{name}</div>
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
