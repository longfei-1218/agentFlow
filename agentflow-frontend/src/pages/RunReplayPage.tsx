import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { runsApi } from "@/api/runs";
import { useFlowEvents } from "@/hooks/useFlowEvents";
import { useRunStore } from "@/store/runStore";
import { isTerminal, STATUS_BADGE, STATUS_TEXT, type Run, type RunStats } from "@/types/run";

const eventColor: Record<string, string> = {
  run_started: "text-info",
  node_started: "text-info",
  node_completed: "text-ok",
  token: "text-ink-3",
  tool_call: "text-warn",
  tool_result: "text-ok",
  human_required: "text-violet",
  run_completed: "text-ok",
  run_failed: "text-danger",
};

export function RunReplayPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<Run | null>(null);
  const [stats, setStats] = useState<RunStats | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const events = useRunStore((s) => s.events);
  const status = useRunStore((s) => s.status);
  const runId = useRunStore((s) => s.runId);
  const tokens = useRunStore((s) => s.tokens);
  const cost = useRunStore((s) => s.cost);
  const reset = useRunStore((s) => s.reset);
  const setRunId = useRunStore((s) => s.setRunId);
  const applyRunDetail = useRunStore((s) => s.applyRunDetail);

  useEffect(() => {
    reset();
    if (!id) return;
    let cancelled = false;
    runsApi
      .get(id)
      .then((detail) => {
        if (cancelled) return;
        setRun(detail);
        applyRunDetail(detail);
        setRunId(detail.id);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "运行详情加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [id, reset, applyRunDetail, setRunId]);

  // 终态 run 的 SSE 会补完历史后自行关闭，所以这里不需要额外兜底定时器
  useFlowEvents(runId);

  useEffect(() => {
    if (!id) return;
    runsApi.stats(id).then(setStats).catch(() => setStats(null));
  }, [id, status]);

  const approve = async (approved: boolean) => {
    if (!id) return;
    const updated = await runsApi.resume(id, approved);
    setRun(updated);
    applyRunDetail(updated);
  };

  const elapsed = run?.startedAt
    ? ((run.finishedAt ? new Date(run.finishedAt).getTime() : Date.now()) -
        new Date(run.startedAt).getTime()) / 1000
    : 0;

  if (loadError) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="card p-6 text-center max-w-[380px]">
          <AlertTriangle className="mx-auto text-warn" size={22} />
          <div className="text-[14px] font-semibold mt-2">运行记录加载失败</div>
          <div className="text-[12px] text-ink-3 mt-1">{loadError}</div>
          <button className="btn mt-4" onClick={() => navigate("/runs")}>
            <ArrowLeft size={13} className="inline mr-1 -mt-0.5" />返回运行历史
          </button>
        </div>
      </div>
    );
  }

  if (!run) {
    return <div className="h-full flex items-center justify-center text-[13px] text-ink-3">加载运行详情…</div>;
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <button className="btn mb-4" onClick={() => navigate("/runs")}>
        <ArrowLeft size={14} className="inline mr-1 -mt-0.5" />返回运行历史
      </button>

      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <h1 className="text-[20px] font-semibold">运行回放</h1>
        <span className="chip font-mono">{run.id}</span>
        <span className={`badge ${STATUS_BADGE[status]}`}>{STATUS_TEXT[status]}</span>
        <span className={`badge ${run.targetType === "flow" ? "badge-blue" : "badge-cyan"}`}>
          {run.targetType === "flow" ? "Flow" : "Agent"}
        </span>
        <button
          className="text-[12px] text-info hover:underline"
          onClick={() => navigate(run.targetType === "flow" ? `/flows/${run.targetId}` : `/agents/${run.targetId}`)}
        >
          {run.targetId}{run.targetType === "flow" ? ` · v${run.flowVersion}` : ""}
        </button>
        <span className="text-[12px] text-ink-3">共 {events.length} 个事件</span>
      </div>

      <div className="card px-4 py-3 mb-4 flex flex-wrap gap-5 text-[12px] text-ink-2">
        <span>Token <b className="text-ink">{tokens}</b></span>
        <span>成本 <b className="text-ink">¥{cost.toFixed(4)}</b></span>
        <span>耗时 <b className="text-ink">{elapsed.toFixed(1)}s</b></span>
        <span>开始 <b className="text-ink">{run.startedAt ? new Date(run.startedAt).toLocaleString("zh-CN", { hour12: false }) : "—"}</b></span>
        <span>输入 <b className="text-ink font-mono">{JSON.stringify(run.inputs)}</b></span>
      </div>

      {run.error && (
        <div className="border border-danger/30 bg-danger-50 text-danger rounded-sm px-3 py-2 text-[12px] mb-4">
          失败原因：{run.error}
        </div>
      )}

      {status === "waiting_human" && (
        <div className="card border-violet/40 px-4 py-3 mb-4 flex items-center gap-3">
          <span className="badge badge-purple">waiting_human</span>
          <span className="text-[12px] text-ink-2 flex-1">
            {String(events.find((event) => event.type === "human_required")?.payload.message ?? "该运行正在等待人工审批")}
          </span>
          <button className="btn-primary !py-1" onClick={() => void approve(true)}>
            <CheckCircle2 size={13} className="inline mr-1 -mt-0.5" />批准并续跑
          </button>
          <button className="btn !py-1 !text-danger" onClick={() => void approve(false)}>
            <XCircle size={13} className="inline mr-1 -mt-0.5" />拒绝
          </button>
        </div>
      )}

      {stats && stats.nodes.length > 0 && (
        <div className="card p-4 mb-4">
          <div className="text-[13px] font-semibold mb-2">节点维度</div>
          <div className="flex flex-wrap gap-2">
            {stats.nodes.map((node) => (
              <div key={node.nodeId} className="border border-line rounded-sm px-3 py-2 min-w-[150px]">
                <div className="font-mono text-[12px] text-info">{node.nodeId}</div>
                <div className="text-[11px] text-ink-3 mt-1">
                  {node.durationMs} ms · {node.tokens} tokens · ¥{node.cost.toFixed(4)}
                </div>
                <div className="text-[11px] mt-0.5">{node.status}</div>
              </div>
            ))}
          </div>
          {!isTerminal(status) && (
            <div className="text-[11px] text-ink-3 mt-2">运行尚未结束，节点耗时会在完成后补齐。</div>
          )}
        </div>
      )}

      <div className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead className="bg-slate-50 text-ink-3">
            <tr>
              {["Seq", "时间", "类型", "节点", "Payload"].map((head) => (
                <th key={head} className="text-left px-4 py-2.5 font-medium">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-ink-3">
                  {isTerminal(status) ? "该运行没有可回放的事件" : "事件流连接中…"}
                </td>
              </tr>
            )}
            {events.map((event) => (
              <tr key={event.seq} className="border-t border-line font-mono hover:bg-slate-50">
                <td className="px-4 py-2 text-ink-3">{event.seq}</td>
                <td className="px-4 py-2 text-ink-3 whitespace-nowrap">
                  {new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour12: false })}
                </td>
                <td className={`px-4 py-2 ${eventColor[event.type] ?? "text-info"}`}>{event.type}</td>
                <td className="px-4 py-2">{event.nodeId ?? "—"}</td>
                <td className="px-4 py-2 text-ink-2 break-all">
                  {event.type === "token"
                    ? JSON.stringify(String(event.payload.text ?? ""))
                    : JSON.stringify(event.payload)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
