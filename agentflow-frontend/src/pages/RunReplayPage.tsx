import { useEffect } from "react";
import { ArrowLeft } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { useFlowEvents } from "@/hooks/useFlowEvents";
import { useRunStore } from "@/store/runStore";

export function RunReplayPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const events = useRunStore((s) => s.events);
  const status = useRunStore((s) => s.status);
  const reset = useRunStore((s) => s.reset);
  const setRunId = useRunStore((s) => s.setRunId);
  const runId = useRunStore((s) => s.runId);

  useEffect(() => {
    reset();
    if (id) setRunId(id);
  }, [id, reset, setRunId]);

  useFlowEvents(runId);

  return (
    <div className="h-full overflow-y-auto p-6">
      <button className="btn mb-4" onClick={() => navigate("/runs")}>
        <ArrowLeft size={14} className="inline mr-1 -mt-0.5" />返回运行历史
      </button>
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-[20px] font-semibold">运行回放</h1>
        <span className="chip">{id}</span>
        <span className="badge badge-blue">{status}</span>
        <span className="text-[12px] text-ink-3">共 {events.length} 个事件</span>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead className="bg-slate-50 text-ink-3">
            <tr>
              {["Seq", "时间", "类型", "节点", "Payload"].map((h) => (
                <th key={h} className="text-left px-4 py-2.5 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.seq} className="border-t border-line font-mono">
                <td className="px-4 py-2 text-ink-3">{event.seq}</td>
                <td className="px-4 py-2 text-ink-3">
                  {new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour12: false })}
                </td>
                <td className="px-4 py-2 text-info">{event.type}</td>
                <td className="px-4 py-2">{event.nodeId ?? "—"}</td>
                <td className="px-4 py-2 text-ink-2 break-all">{JSON.stringify(event.payload)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
