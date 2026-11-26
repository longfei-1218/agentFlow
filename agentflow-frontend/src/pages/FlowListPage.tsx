import { useCallback, useEffect, useState } from "react";
import { Copy, GitBranch, Plus, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { flowsApi } from "@/api/flows";
import { runsApi } from "@/api/runs";
import { definitionsByType } from "@/registry/nodes";
import type { Flow } from "@/types/flow";
import { createDefaultFlow } from "@/utils/flow";

export function FlowListPage() {
  const navigate = useNavigate();
  const [flows, setFlows] = useState<Flow[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, runs] = await Promise.all([flowsApi.list(), runsApi.list()]);
      setFlows(list);
      setRunCount(runs.length);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleDelete = async (flow: Flow) => {
    if (!window.confirm(`确认删除流程「${flow.name}」？该操作不可撤销。`)) return;
    await flowsApi.remove(flow.id);
    await load();
  };

  const handleDuplicate = async (flow: Flow) => {
    await flowsApi.create({ name: `${flow.name} 副本`, nodes: flow.nodes, edges: flow.edges });
    await load();
  };

  const handleCreate = async () => {
    const created = await flowsApi.create(createDefaultFlow());
    navigate(`/flows/${created.id}`);
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-[20px] font-semibold">流程编排</h1>
          <p className="text-[12px] text-ink-3 mt-1">在画布上定义节点拓扑，配置参数后运行并观测全流程事件。</p>
        </div>
        <div className="flex gap-2 items-center">
          <span className="chip">共 {flows.length} 个流程</span>
          <span className="chip">运行记录 {runCount}</span>
          <span className="chip">节点类型 {Object.keys(definitionsByType).length}</span>
          <button className="btn-primary" onClick={() => void handleCreate()}>
            <Plus size={14} className="inline mr-1.5 -mt-0.5" />新建流程
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-[13px] text-ink-3 py-10 text-center">加载中…</div>
      ) : flows.length === 0 ? (
        <div className="card border-dashed py-16 text-center text-[13px] text-ink-3">
          还没有流程。点击右上角「新建流程」开始编排。
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-4">
          {flows.map((flow) => {
            const types = Array.from(new Set(flow.nodes.map((node) => node.type))).slice(0, 4);
            return (
              <div
                key={flow.id}
                className="card p-4 cursor-pointer hover:border-primary transition-colors group"
                onClick={() => navigate(`/flows/${flow.id}`)}
              >
                <div className="flex items-center gap-2">
                  <span className="w-8 h-8 rounded-sm bg-primary-soft text-primary flex items-center justify-center">
                    <GitBranch size={16} />
                  </span>
                  <div className="min-w-0">
                    <div className="font-semibold text-[14px] truncate">{flow.name}</div>
                    <div className="text-[11px] text-ink-3 font-mono">v{flow.version} · {flow.id}</div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1.5 mt-3">
                  {types.map((type) => (
                    <span key={type} className="badge badge-blue">{type}</span>
                  ))}
                </div>

                <div className="mt-4 pt-3 border-t border-line flex items-center justify-between text-[11px] text-ink-3">
                  <span>{flow.nodes.length} 个节点 · {flow.edges.length} 条连线</span>
                  <span className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      className="p-1 hover:text-primary"
                      title="复制"
                      onClick={(e) => { e.stopPropagation(); void handleDuplicate(flow); }}
                    >
                      <Copy size={14} />
                    </button>
                    <button
                      className="p-1 hover:text-danger"
                      title="删除"
                      onClick={(e) => { e.stopPropagation(); void handleDelete(flow); }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
