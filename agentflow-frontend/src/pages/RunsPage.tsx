import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Play, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { flowsApi } from "@/api/flows";
import { runsApi } from "@/api/runs";
import type { Agent } from "@/types/agent";
import type { Flow } from "@/types/flow";
import { STATUS_BADGE, STATUS_TEXT, type Run, type RunStatus, type RunTargetType } from "@/types/run";

const statusFilters: { label: string; value: RunStatus | "" }[] = [
  { label: "全部", value: "" },
  { label: "运行中", value: "running" },
  { label: "等待审批", value: "waiting_human" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
  { label: "已取消", value: "cancelled" },
];

function duration(run: Run): string {
  if (!run.startedAt) return "—";
  const end = run.finishedAt ? new Date(run.finishedAt).getTime() : Date.now();
  const ms = end - new Date(run.startedAt).getTime();
  return ms > 0 ? `${(ms / 1000).toFixed(1)}s` : "—";
}

function inputSummary(run: Run): string {
  const values = Object.values(run.inputs ?? {});
  if (values.length === 0) return "—";
  return values.map((value) => String(value)).join(" / ").slice(0, 40);
}

export function RunsPage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<Run[]>([]);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [targetType, setTargetType] = useState<RunTargetType | "">("");
  const [targetId, setTargetId] = useState("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await runsApi.list({
        targetType: targetType || undefined,
        targetId: targetId || undefined,
        status: status || undefined,
        limit: 200,
      });
      setRuns(list);
    } finally {
      setLoading(false);
    }
  }, [targetType, targetId, status]);

  useEffect(() => {
    void Promise.all([
      flowsApi.list().then(setFlows).catch(() => []),
      agentsApi.list().then(setAgents).catch(() => []),
    ]);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const targetName = useMemo(() => {
    const map = new Map<string, { name: string; type: RunTargetType; version?: number }>();
    flows.forEach((flow) => map.set(flow.id, { name: flow.name, type: "flow", version: flow.version }));
    agents.forEach((agent) => map.set(agent.id, { name: agent.name, type: "agent" }));
    return (run: Run) => map.get(run.targetId) ?? { name: run.targetId, type: run.targetType };
  }, [flows, agents]);

  const toCase = async (id: string) => {
    await runsApi.toCase(id);
    window.alert("已转换为评测 Case，可在评测回归页管理评测集。");
  };

  const changeTargetType = (value: RunTargetType | "") => {
    setTargetType(value);
    setTargetId("");
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[20px] font-semibold">运行历史</h1>
          <p className="text-[12px] text-ink-3 mt-1">Flow 运行与 Agent 对话 / 调试共用一张运行表；按目标类型与状态筛选，点回放查看事件时序。</p>
        </div>
        <button className="btn" onClick={() => void load()}>
          <RefreshCw size={13} className="inline mr-1 -mt-0.5" />刷新
        </button>
      </div>

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <select className="field w-[120px]" value={targetType} onChange={(event) => changeTargetType(event.target.value as RunTargetType | "")}>
          <option value="">全部类型</option>
          <option value="flow">Flow</option>
          <option value="agent">Agent</option>
        </select>

        {targetType === "flow" ? (
          <select className="field w-[220px]" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
            <option value="">全部流程</option>
            {flows.map((flow) => <option key={flow.id} value={flow.id}>{flow.name}（v{flow.version}）</option>)}
          </select>
        ) : targetType === "agent" ? (
          <select className="field w-[220px]" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
            <option value="">全部 Agent</option>
            {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
        ) : null}

        <div className="flex gap-1">
          {statusFilters.map((item) => (
            <button
              key={item.value}
              className={`px-3 py-1.5 rounded-sm text-[12px] ${status === item.value ? "bg-primary text-white" : "bg-white border border-line text-ink-2"}`}
              onClick={() => setStatus(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <span className="ml-auto chip">共 {runs.length} 条{loading ? "（加载中）" : ""}</span>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead className="bg-slate-50 text-ink-3">
            <tr>
              {["Run ID", "目标", "类型", "状态", "输入摘要", "Token", "成本", "耗时", "开始时间", "操作"].map((head) => (
                <th key={head} className="text-left px-3 py-2.5 font-medium">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 && (
              <tr>
                <td colSpan={10} className="px-3 py-10 text-center text-ink-3">
                  暂无运行记录。在流程编辑器或 Agent 对话页发起一次运行。
                </td>
              </tr>
            )}
            {runs.map((run) => {
              const target = targetName(run);
              return (
                <tr key={run.id} className="border-t border-line hover:bg-slate-50">
                  <td className="px-3 py-2.5 font-mono text-info">{run.id}</td>
                  <td className="px-3 py-2.5 max-w-[180px] truncate">
                    <div className="truncate">{target.name}</div>
                    <div className="text-[10px] text-ink-3 font-mono truncate">{run.targetId}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`badge ${run.targetType === "flow" ? "badge-blue" : "badge-cyan"}`}>
                      {run.targetType === "flow" ? `Flow v${run.flowVersion}` : "Agent"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`badge ${STATUS_BADGE[run.status]}`}>{STATUS_TEXT[run.status]}</span>
                  </td>
                  <td className="px-3 py-2.5 text-ink-2 max-w-[180px] truncate">{inputSummary(run)}</td>
                  <td className="px-3 py-2.5">{run.tokenUsage}</td>
                  <td className="px-3 py-2.5">¥{run.costEstimate.toFixed(4)}</td>
                  <td className="px-3 py-2.5 text-ink-2">{duration(run)}</td>
                  <td className="px-3 py-2.5 text-ink-3">
                    {run.startedAt ? new Date(run.startedAt).toLocaleString("zh-CN", { hour12: false }) : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex gap-2 whitespace-nowrap">
                      <button className="text-primary hover:underline" onClick={() => navigate(`/runs/${run.id}`)}>
                        回放
                      </button>
                      {run.status === "waiting_human" && (
                        <button className="text-violet hover:underline" onClick={() => navigate(`/runs/${run.id}`)}>
                          审批/续跑
                        </button>
                      )}
                      {run.status === "failed" && run.targetType === "flow" && (
                        <button className="text-warn hover:underline" onClick={() => void toCase(run.id)}>
                          转 Case
                        </button>
                      )}
                      {run.status === "running" && (
                        <button className="text-danger hover:underline" onClick={() => void runsApi.cancel(run.id).then(load)}>
                          停止
                        </button>
                      )}
                      <button
                        className="text-ink-3 hover:text-primary"
                        title={run.targetType === "flow" ? "打开流程" : "打开 Agent"}
                        onClick={() => navigate(run.targetType === "flow" ? `/flows/${run.targetId}` : `/agents/${run.targetId}`)}
                      >
                        <ArrowRight size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] text-ink-3 mt-3 flex items-center gap-1">
        <Play size={11} />
        Flow 运行的节点维度统计按 flow 事件聚合；Agent 运行只有一层模型调用，回放页展示 token / 工具 / 知识库事件。
      </div>
    </div>
  );
}
