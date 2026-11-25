import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "@/components/layout/Shell";
import { EditorPage } from "@/pages/EditorPage";
import { EvalPage } from "@/pages/EvalPage";
import { FlowListPage } from "@/pages/FlowListPage";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { RunReplayPage } from "@/pages/RunReplayPage";
import { RunsPage } from "@/pages/RunsPage";
import { ToolsPage } from "@/pages/ToolsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Navigate to="/flows" replace />} />
          <Route path="/flows" element={<FlowListPage />} />
          <Route path="/flows/:id" element={<EditorPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunReplayPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/eval" element={<EvalPage />} />
          <Route path="*" element={<Navigate to="/flows" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
