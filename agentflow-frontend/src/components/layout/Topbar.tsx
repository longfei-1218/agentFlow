import { useRef } from "react";
import { Download, FileUp, Plus, Settings } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { flowsApi } from "@/api/flows";
import { useFlowStore } from "@/store/flowStore";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import { useLlmConfigured, useSettingsStore } from "@/store/settingsStore";
import type { FlowCreate } from "@/types/flow";
import { createDefaultFlow, downloadFlow } from "@/utils/flow";

const titles: Record<string, string> = {
  "/flows": "流程编排",
  "/agents": "Agent 库",
  "/runs": "运行历史",
  "/versions": "版本管理",
  "/tools": "工具管理",
  "/knowledge": "知识库",
  "/eval": "评测回归",
};

const ENGINE_LABEL: Record<string, string> = {
  graph: "LangGraph",
  loop: "手写 Loop",
  demo: "演示桩",
};

export function Topbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const flow = useFlowStore((s) => s.flow);
  const engine = useNodeTypeStore((s) => s.engine);
  const openSettings = useSettingsStore((s) => s.openModal);
  const configured = useLlmConfigured();
  const isFlowRoute = location.pathname.startsWith("/flows");
  const isEditor = /^\/flows\/[^/]+/.test(location.pathname);

  const title = isEditor ? flow.name || "编辑器" : titles[location.pathname] ?? "AgentFlow";

  const handleCreate = async () => {
    const created = await flowsApi.create(createDefaultFlow());
    navigate(`/flows/${created.id}`);
  };

  const handleImport = async (file: File) => {
    const parsed = JSON.parse(await file.text());
    if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
      throw new Error("DSL 格式错误：缺少 nodes 或 edges 数组");
    }
    const payload: FlowCreate = {
      name: parsed.name ?? file.name.replace(/\.json$/i, ""),
      nodes: parsed.nodes,
      edges: parsed.edges,
    };
    const created = await flowsApi.create(payload);
    navigate(`/flows/${created.id}`);
  };

  return (
    <header className="h-[52px] flex-shrink-0 flex items-center justify-between px-5 bg-white border-b border-line">
      <div className="flex items-center gap-2 text-[13px] text-ink-3">
        <span>AgentFlow</span>
        <span>/</span>
        <span className="text-ink font-medium">{title}</span>
      </div>

      <div className="flex items-center gap-2">
        {engine && (
          <span
            className="chip !text-ink-2"
            title="执行引擎：graph = LangGraph（条件边 / 有界循环 / checkpointer 续跑），loop = R2 手写 Agent Loop"
          >
            引擎 {ENGINE_LABEL[engine] ?? engine}
          </span>
        )}
        {!configured && (
          <button
            className="chip !text-warn !border-warn/40"
            title="尚未配置 LLM API Key，运行含模型节点的流程会被拦下"
            onClick={openSettings}
          >
            未配置模型
          </button>
        )}
        <button className="btn" onClick={openSettings} title="配置 LLM Base URL / Key / 默认模型">
          <Settings size={14} className="inline mr-1.5 -mt-0.5" />模型设置
        </button>

        {isFlowRoute && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleImport(file);
                event.target.value = "";
              }}
            />
            <button className="btn" onClick={() => fileRef.current?.click()}>
              <FileUp size={14} className="inline mr-1.5 -mt-0.5" />导入 JSON
            </button>
            <button className="btn" disabled={!isEditor || !flow.id} onClick={() => downloadFlow(flow)}>
              <Download size={14} className="inline mr-1.5 -mt-0.5" />导出 JSON
            </button>
            <button className="btn-primary" onClick={() => void handleCreate()}>
              <Plus size={14} className="inline mr-1.5 -mt-0.5" />新建流程
            </button>
          </>
        )}
      </div>
    </header>
  );
}
