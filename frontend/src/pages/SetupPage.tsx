// プロジェクト準備（概要・クラス設計・画像取り込みを1画面に統合）。
import { useParams } from "react-router-dom";
import OverviewPanel from "../components/OverviewPanel";
import ClassesPanel from "../components/ClassesPanel";
import ImagesPanel from "../components/ImagesPanel";

export default function SetupPage() {
  const { name = "" } = useParams();
  return (
    <div className="page">
      <h1>プロジェクト準備: {name}</h1>
      <p className="muted">
        プロジェクトの概要確認、クラス設計、画像取り込みをこの画面でまとめて行います。
      </p>
      <OverviewPanel />
      <div className="setup-cols">
        <div className="setup-col-classes">
          <ClassesPanel />
        </div>
        <div className="setup-col-images">
          <ImagesPanel />
        </div>
      </div>
    </div>
  );
}
