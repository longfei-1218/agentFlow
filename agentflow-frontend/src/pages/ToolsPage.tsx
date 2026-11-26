import { useEffect, useState } from "react";
import { FlaskConical, Pencil, Plus, RefreshCw, Server, Trash2, Wrench } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toolsApi, type ToolDef, type ToolInvocation } from "@/api/tools";
import { ToolEditorModal } from "@/components/tools/ToolEditorModal";
import { ToolTestModal } from "@/components/tools/ToolTestModal";
import { useToolStore } from "@/store/toolStore";

const RISK_BADGE: Record<string, string> = {
  low: "badge-green",
  medium: "badge-orange",
  high: "badge-red",
};

const STATUS_BADGE: Record<string, string> = {
  ok: "badge-green",
  error: "badge-red",
  timeout: "badge-orange",
};

function target(tool: ToolDef) {
  if (tool.kind === "builtin") return `builtin:${tool.builtin}`;
  return `${tool.method} ${tool.url}`;
}

export function ToolsPage() {
  const navigate = useNavigate();
  const tools = useToolStore((s) => s.tools);
  const builtins = useToolStore((s) => s.builtins);
  const loading = useToolStore((s) => s.loading);
  const error = useToolStore((s) => s.error);
  const load = useToolStore((s) => s.load);
  const remove = useToolStore((s) => s.remove);

  const [editing, setEditing] = useState<ToolDef | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [testing, setTesting] = useState<ToolDef | null>(null);
  const [invocations, setInvocations] = useState<ToolInvocation[]>([]);
  const [invLoading, setInvLoading] = useState(false);
  const [filterTool, setFilterTool] = useState<string>("");

  const loadInvocations = async (toolId?: string) => {
    setInvLoading(true);
    try {
      setInvocations(await toolsApi.invocations(toolId || undefined, 25));
    } finally {
      setInvLoading(false);
    }
  };

  useEffect(() => {
    void load(true);
    void loadInvocations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDelete = async (tool: ToolDef) => {
    if (!window.confirm(`删除工具 ${tool.name}？已引用它的节点会在运行时失败。`)) return;
    await remove(tool.id);
    void loadInvocations(filterTool);
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-start gap-3">
        <div>
          <h1 className="text-[20px] font-semibold">工具管理</h1>
          <p className="text-[12px] text-ink-3 mt-1">
            注册 Function Calling 工具。工具定义同时用于：给模型看的 tools 数组、调用的入参强校验、试跑表单。
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="btn" onClick={() => void load(true)}>
            <RefreshCw size={13} className="inline mr-1 -mt-0.5" />刷新
          </button>
          <button
            className="btn-primary"
            onClick={() => {
              setEditing(null);
              setEditorOpen(true);
            }}
          >
            <Plus size={13} className="inline mr-1 -mt-0.5" />新建工具
          </button>
        </div>
      </div>

      {error && <div className="mt-3 border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">{error}</div>}

      <section className="card mt-4 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
          <Wrench size={15} className="text-ok" />
          <span className="font-semibold text-[13px]">Function Calling 工具</span>
          <span className="badge badge-gray">{tools.length}</span>
          {loading && <span className="text-[11px] text-ink-3">加载中…</span>}
        </div>

        {tools.length === 0 ? (
          <div className="py-12 text-center text-[12px] text-ink-3">
            还没有工具。点右上「新建工具」→ 选「内置」→ 保存，就能先跑通整条链路。
          </div>
        ) : (
          <table className="w-full text-[12px]">
            <thead className="bg-slate-50 text-ink-3">
              <tr>
                {["名称", "类型", "目标", "超时 / 重试", "幂等", "风险", "状态", "操作"].map((head) => (
                  <th key={head} className="text-left px-3 py-1.5 font-medium whitespace-nowrap">{head}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tools.map((tool) => (
                <tr key={tool.id} className="border-t border-line">
                  <td className="px-3 py-2">
                    <div className="font-mono text-ink">{tool.name}</div>
                    <div className="text-[11px] text-ink-3 truncate max-w-[220px]">{tool.description || "—"}</div>
                  </td>
                  <td className="px-3 py-2"><span className="badge badge-gray">{tool.kind}</span></td>
                  <td className="px-3 py-2 font-mono text-[11px] text-ink-2 break-all max-w-[240px]">{target(tool)}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-ink-2">{tool.timeoutMs} ms / {tool.retries}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-ink-2">
                    {tool.idempotency === "key" ? `key·${tool.idempotencyTtlS}s` : "none"}
                  </td>
                  <td className="px-3 py-2"><span className={`badge ${RISK_BADGE[tool.risk]}`}>{tool.risk}</span></td>
                  <td className="px-3 py-2">
                    {tool.enabled ? <span className="badge badge-green">启用</span> : <span className="badge badge-gray">停用</span>}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <button className="text-primary hover:underline mr-2" onClick={() => setTesting(tool)}>
                      <FlaskConical size={12} className="inline -mt-0.5 mr-0.5" />试跑
                    </button>
                    <button
                      className="text-ink-2 hover:text-primary mr-2"
                      onClick={() => {
                        setEditing(tool);
                        setEditorOpen(true);
                      }}
                    >
                      <Pencil size={12} className="inline -mt-0.5 mr-0.5" />编辑
                    </button>
                    <button className="text-danger hover:underline" onClick={() => void handleDelete(tool)}>
                      <Trash2 size={12} className="inline -mt-0.5 mr-0.5" />删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card mt-4 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
          <span className="font-semibold text-[13px]">最近调用记录</span>
          <select
            className="field !w-auto !py-1 text-[12px] ml-2"
            value={filterTool}
            onChange={(event) => {
              setFilterTool(event.target.value);
              void loadInvocations(event.target.value);
            }}
          >
            <option value="">全部工具</option>
            {tools.map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}
          </select>
          {invLoading && <span className="text-[11px] text-ink-3">加载中…</span>}
          <button className="ml-auto text-[11px] text-ink-3 hover:text-primary" onClick={() => void loadInvocations(filterTool)}>
            <RefreshCw size={11} className="inline mr-1" />刷新
          </button>
        </div>

        {invocations.length === 0 ? (
          <div className="py-10 text-center text-[12px] text-ink-3">
            还没有调用。试跑一个工具，或在流程里运行 tool 节点 / 绑定工具的 llm 节点。
          </div>
        ) : (
          <div className="max-h-[280px] overflow-auto">
            <table className="w-full text-[12px]">
              <thead className="bg-slate-50 text-ink-3 sticky top-0">
                <tr>
                  {["时间", "工具", "来源", "状态", "尝试", "耗时", "幂等", "run"].map((head) => (
                    <th key={head} className="text-left px-3 py-1.5 font-medium whitespace-nowrap">{head}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {invocations.map((item) => (
                  <tr key={item.id} className="border-t border-line">
                    <td className="px-3 py-1.5 text-ink-3 whitespace-nowrap">
                      {item.createdAt ? new Date(item.createdAt).toLocaleTimeString("zh-CN", { hour12: false }) : "—"}
                    </td>
                    <td className="px-3 py-1.5 font-mono">{item.toolName}</td>
                    <td className="px-3 py-1.5 text-ink-3">{item.nodeId ?? "试跑"}</td>
                    <td className="px-3 py-1.5"><span className={`badge ${STATUS_BADGE[item.status] ?? "badge-gray"}`}>{item.status}</span></td>
                    <td className="px-3 py-1.5">{item.attempts}</td>
                    <td className="px-3 py-1.5">{item.latencyMs} ms</td>
                    <td className="px-3 py-1.5">{item.idemHit ? <span className="badge badge-purple">命中</span> : <span className="text-ink-3">—</span>}</td>
                    <td className="px-3 py-1.5 font-mono text-[11px]">
                      {item.runId ? (
                        <button className="text-info hover:underline" onClick={() => navigate(`/runs/${item.runId}`)}>
                          {item.runId}
                        </button>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {invocations.some((item) => item.error) && (
          <div className="px-4 py-2 border-t border-line text-[11px] text-danger">
            最近一次失败原因：{invocations.find((item) => item.error)?.error}
          </div>
        )}
      </section>

      <section className="card mt-4 p-4">
        <div className="flex items-center gap-2 mb-2">
          <Server size={15} className="text-info" />
          <span className="font-semibold text-[13px]">MCP Server</span>
          <span className="badge badge-green ml-auto">R5 已实装</span>
        </div>
        <div className="text-[12px] text-ink-2 leading-relaxed">
          stdio JSON-RPC Server 在
          <button className="text-primary hover:underline mx-1" onClick={() => navigate("/mcp")}>「MCP 服务」页</button>
          注册与探测工具；画布 mcp 节点调用时重新握手，不做常驻连接。
        </div>
      </section>

      <div className="card p-4 mt-4 text-[12px] text-ink-2 leading-relaxed">
        安全约定：工具描述视为不可信数据（模型可能被它影响）；high 风险工具建议在流程里用 human 节点审批后再调。
        tool 节点调用失败会让整个 run 失败；llm 节点里的 Function Calling 失败则把错误作为工具结果回给模型，让它自己改参数重试。
      </div>

      {editorOpen && (
        <ToolEditorModal
          tool={editing}
          builtins={builtins}
          onClose={() => {
            setEditorOpen(false);
            setEditing(null);
            void loadInvocations(filterTool);
          }}
        />
      )}
      {testing && (
        <ToolTestModal
          tool={testing}
          onClose={() => {
            setTesting(null);
            void loadInvocations(filterTool);
          }}
        />
      )}
    </div>
  );
}
