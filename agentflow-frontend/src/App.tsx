import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "@/components/layout/Shell";
import { AgentChatPage } from "@/pages/AgentChatPage";
import { AgentEditorPage } from "@/pages/AgentEditorPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { EditorPage } from "@/pages/EditorPage";
import { EvalPage } from "@/pages/EvalPage";
import { FlowListPage } from "@/pages/FlowListPage";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { McpPage } from "@/pages/McpPage";
import { RunReplayPage } from "@/pages/RunReplayPage";
import { RunsPage } from "@/pages/RunsPage";
import { ToolsPage } from "@/pages/ToolsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Agent 工作台：对话 + 编辑同屏，独立占满窗口，避免再被全局侧栏压缩 */}
        <Route path="/agents/:id" element={<AgentEditorPage />} />
        <Route element={<Shell />}>
          <Route path="/" element={<Navigate to="/flows" replace />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/:id/chat" element={<AgentChatPage />} />
          <Route path="/flows" element={<FlowListPage />} />
          <Route path="/flows/:id" element={<EditorPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunReplayPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/mcp" element={<McpPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/eval" element={<EvalPage />} />
          <Route path="*" element={<Navigate to="/flows" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
