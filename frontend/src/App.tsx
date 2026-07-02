import { Navigate, Route, Routes } from "react-router-dom";
import ProjectLayout from "./components/ProjectLayout";
import ProjectsPage from "./pages/ProjectsPage";
import SetupPage from "./pages/SetupPage";
import AnnotatePage from "./pages/AnnotatePage";
import DatasetPage from "./pages/DatasetPage";
import TrainPage from "./pages/TrainPage";
import EvaluatePage from "./pages/EvaluatePage";
import PredictPage from "./pages/PredictPage";
import AnalysisPage from "./pages/AnalysisPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import ModelsPage from "./pages/ModelsPage";
import PreprocessPage from "./pages/PreprocessPage";
import SelectionPage from "./pages/SelectionPage";
import ReportsPage from "./pages/ReportsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      <Route path="/p/:name" element={<ProjectLayout />}>
        <Route index element={<Navigate to="setup" replace />} />
        <Route path="setup" element={<SetupPage />} />
        {/* 旧「概要/クラス設計/画像取り込み」工程は「プロジェクト準備」へ統合（後方互換リダイレクト） */}
        <Route path="overview" element={<Navigate to="../setup" replace />} />
        <Route path="classes" element={<Navigate to="../setup" replace />} />
        <Route path="images" element={<Navigate to="../setup" replace />} />
        <Route path="annotate" element={<AnnotatePage />} />
        <Route path="selection" element={<SelectionPage />} />
        {/* 旧「ラベル品質チェック」工程はデータセット作成へ統合（後方互換リダイレクト） */}
        <Route path="quality" element={<Navigate to="../dataset" replace />} />
        <Route path="dataset" element={<DatasetPage />} />
        <Route path="preprocess" element={<PreprocessPage />} />
        {/* 旧「データ拡張」工程は「学習」画面の右カラムへ統合（後方互換リダイレクト） */}
        <Route path="augment" element={<Navigate to="../train" replace />} />
        <Route path="train" element={<TrainPage />} />
        <Route path="eval" element={<EvaluatePage />} />
        <Route path="infer" element={<PredictPage />} />
        <Route path="analysis" element={<AnalysisPage />} />
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="reports" element={<ReportsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
