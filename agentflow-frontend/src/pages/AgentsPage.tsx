import { useCallback, useEffect, useState } from "react";
import { Bot, MessageSquare, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { ApiError } from "@/api/client";
import { emptyAgentPayload, type Agent } from "@/types/agent";

const KIND_LABEL: Record<string, string> = { tool: "工具", mcp: "MCP", knowledge: "知识库" };

export function AgentsPage() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setAgents(await agentsApi.list());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent 列表加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    setCreating(true);
    setError(null);
    try {
      const created = await agentsApi.create(emptyAgentPayload());
      navigate(`/agents/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError) setError(`${err.message}${err.code ? `（${err.code}）` : ""}`);
      else setError(err instanceof Error ? err.message : "新建 Agent 失败");
    } finally {
      setCreating(false);
    }
  };

  const remove = async (agent: Agent) => {
    if (!window.confirm(`删除 Agent「${agent.name}」？引用它的流程节点会变成未选择状态。`)) return;
    try {
      await agentsApi.remove(agent.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[20px] font-semibold">Agent 库</h1>
          <p className="text-[12px] text-ink-3 mt-1">
            Agent 是全局可复用资源：变量、提示词、工具 / MCP / 知识库、模型、输出契约都在这里定义，流程节点只引用 agentId。
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <span className="chip">共 {agents.length} 个 Agent</span>
          <button className="btn" onClick={() => void load()}><RefreshCw size={13} className="inline mr-1 -mt-0.5" />刷新</button>
          <button className="btn-primary" disabled={creating} onClick={() => void create()}>
            <Plus size={14} className="inline mr-1.5 -mt-0.5" />{creating ? "创建中…" : "新建 Agent"}
          </button>
        </div>
      </div>

      {error && (
        <div className="border border-danger/30 bg-danger-50 text-[12px] text-danger rounded-sm px-3 py-2 mb-4">{error}</div>
      )}

      {loading ? (
        <div className="text-[13px] text-ink-3 py-10 text-center">加载中…</div>
      ) : agents.length === 0 ? (
        <div className="card border-dashed py-16 text-center">
          <Bot size={28} className="mx-auto text-ink-3" />
          <div className="text-[14px] font-semibold mt-2">还没有 Agent</div>
          <div className="text-[12px] text-ink-3 mt-1">先建一个带 query 变量的通用对话 Agent，再回流程画布引用它。</div>
          <button className="btn-primary mt-4" onClick={() => void create()}>
            <Plus size={13} className="inline mr-1 -mt-0.5" />新建 Agent
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="card p-4 cursor-pointer hover:border-primary transition-colors group"
              onClick={() => navigate(`/agents/${agent.id}`)}
            >
              <div className="flex items-center gap-2">
                <span className="w-8 h-8 rounded-sm bg-primary-soft text-primary flex items-center justify-center">
                  <Bot size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-[14px] truncate">{agent.name}</div>
                  <div className="text-[10px] text-ink-3 font-mono truncate">{agent.id}</div>
                </div>
                <button
                  className="text-ink-3 hover:text-danger opacity-0 group-hover:opacity-100"
                  title="删除 Agent"
                  onClick={(event) => { event.stopPropagation(); void remove(agent); }}
                >
                  <Trash2 size={13} />
                </button>
              </div>

              <div className="text-[12px] text-ink-2 mt-3 min-h-[34px] line-clamp-2">
                {agent.description || <span className="text-ink-3">未填写描述</span>}
              </div>

              <div className="flex flex-wrap gap-1.5 mt-2">
                <span className="badge badge-blue">{agent.variables.length} 个变量</span>
                {agent.model.name
                  ? <span className="badge badge-gray">{agent.model.name}</span>
                  : <span className="badge badge-gray">默认模型</span>}
                {agent.resources.map((resource) => (
                  <span key={`${resource.kind}:${resource.id}`} className="badge badge-cyan">
                    {KIND_LABEL[resource.kind] ?? resource.kind} · {resource.alias}
                  </span>
                ))}
                {agent.output.schema && <span className="badge badge-purple">Schema</span>}
              </div>

              <div className="mt-4 pt-3 border-t border-line flex items-center justify-between">
                <span className="text-[11px] text-ink-3">更新 {new Date(agent.updatedAt).toLocaleDateString("zh-CN")}</span>
                <span className="flex gap-2 text-[12px]">
                  <button
                    className="text-primary hover:underline flex items-center gap-1"
                    onClick={(event) => { event.stopPropagation(); navigate(`/agents/${agent.id}`); }}
                  >
                    <Pencil size={12} />编辑
                  </button>
                  <button
                    className="text-primary hover:underline flex items-center gap-1"
                    onClick={(event) => { event.stopPropagation(); navigate(`/agents/${agent.id}/chat`); }}
                  >
                    <MessageSquare size={12} />对话
                  </button>
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
