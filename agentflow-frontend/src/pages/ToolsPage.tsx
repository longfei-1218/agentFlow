import { Database, Server, Wrench } from "lucide-react";

export function ToolsPage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="text-[20px] font-semibold">工具管理</h1>
      <p className="text-[12px] text-ink-3 mt-1 mb-5">注册 Function Calling 工具与 MCP Server，供 tool / mcp 节点引用。</p>

      <div className="grid grid-cols-2 gap-4">
        <section className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Wrench size={16} className="text-ok" />
            <span className="font-semibold text-[14px]">Function Calling 工具</span>
            <span className="badge badge-green ml-auto">P3</span>
          </div>
          <div className="border border-dashed border-line rounded-sm py-10 text-center text-[12px] text-ink-3">
            暂无已注册工具<br />
            <span className="text-[11px]">参数以 JSON Schema 定义，执行前强校验</span>
          </div>
        </section>

        <section className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Server size={16} className="text-info" />
            <span className="font-semibold text-[14px]">MCP Server</span>
            <span className="badge badge-blue ml-auto">P3</span>
          </div>
          <div className="border border-dashed border-line rounded-sm py-10 text-center text-[12px] text-ink-3">
            暂无已注册 MCP Server<br />
            <span className="text-[11px]">支持 stdio / sse，运行时动态发现工具</span>
          </div>
        </section>
      </div>

      <div className="card p-4 mt-4 flex items-center gap-3 text-[12px] text-ink-2">
        <Database size={15} className="text-ink-3" />
        安全约定：工具描述视为不可信数据；高危工具调用前需经 human 节点审批。
      </div>
    </div>
  );
}
