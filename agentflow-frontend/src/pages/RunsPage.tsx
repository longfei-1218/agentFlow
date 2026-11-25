import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { runsApi } from "@/api/runs";
import type { Run, RunStatus } from "@/types/run";

const filters: { label: string; value: RunStatus | "" }[] = [
  { label: "全部", value: "" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
  { label: "等待审批", value: "waiting_human" },
];

const statusClass: Record<RunStatus, string> = {
  pending: "badge-gray",
  running: "badge-blue",
  waiting_human: "badge-purple",
  succeeded: "badge-green",
  failed: "badge-red",
  cancelled: "badge-gray",
};

export function RunsPage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<Run[]>([]);
  const [filter, setFilter] = useState<RunStatus | "">("");

  const load = useCallback(async () => {
    setRuns(await runsApi.list(filter || undefined));
  }, [filter]);

  useEffect(() => { void load(); }, [load]);

  const toCase = async (id: string) => {
    await runsApi.toCase(id);
    window.alert("已转换为评测 Case，可在评测回归页管理评测集。");
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-[20px] font-semibold">运行历史</h1>
          <p className="text-[12px] text-ink-3 mt-1">按状态筛选运行记录，点击回放查看完整事件时序。</p>
        </div>
      </div>

      <div className="flex gap-1 mb-4">
        {filters.map((item) => (
          <button
            key={item.value}
            className={`px-3 py-1.5 rounded-sm text-[12px] ${filter === item.value ? "bg-primary text-white" : "bg-white border border-line text-ink-2"}`}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead className="bg-slate-50 text-ink-3">
            <tr>
              {["Run ID", "流程", "版本", "状态", "Token", "成本", "开始时间", "操作"].map((h) => (
                <th key={h} className="text-left px-4 py-2.5 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-ink-3">暂无运行记录</td></tr>
            )}
            {runs.map((run) => (
              <tr key={run.id} className="border-t border-line hover:bg-slate-50">
                <td className="px-4 py-2.5 font-mono text-info">{run.id}</td>
                <td className="px-4 py-2.5 font-mono">{run.flowId}</td>
                <td className="px-4 py-2.5">v{run.flowVersion}</td>
                <td className="px-4 py-2.5"><span className={`badge ${statusClass[run.status]}`}>{run.status}</span></td>
                <td className="px-4 py-2.5">{run.tokenUsage}</td>
                <td className="px-4 py-2.5">¥{run.costEstimate.toFixed(4)}</td>
                <td className="px-4 py-2.5 text-ink-3">
                  {run.startedAt ? new Date(run.startedAt).toLocaleString("zh-CN", { hour12: false }) : "—"}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex gap-2">
                    <button className="text-primary hover:underline" onClick={() => navigate(`/runs/${run.id}`)}>回放</button>
                    {run.status === "failed" && (
                      <button className="text-warn hover:underline" onClick={() => void toCase(run.id)}>＋ 转 Case</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
