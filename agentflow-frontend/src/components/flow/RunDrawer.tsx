import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, CircleStop, Play, RefreshCw } from "lucide-react";
import { runsApi } from "@/api/runs";
import { countSteps, useRunStore } from "@/store/runStore";
import { isTerminal, STATUS_BADGE, STATUS_TEXT, type EventType } from "@/types/run";

const badgeClass: Record<EventType, string> = {
  run_started: "badge-blue",
  node_started: "badge-blue",
  node_completed: "badge-cyan",
  token: "badge-gray",
  tool_call: "badge-orange",
  tool_result: "badge-green",
  human_required: "badge-purple",
  run_completed: "badge-green",
  run_failed: "badge-red",
};

interface Props {
  onRun: () => void;
  onCancel: () => void;
  onApprove: (approved: boolean) => void;
  canRun: boolean;
}

export function RunDrawer({ onRun, onCancel, onApprove, canRun }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [tab, setTab] = useState<"logs" | "output" | "metrics">("logs");
  const logRef = useRef<HTMLDivElement>(null);
  const outputRef = useRef<HTMLPreElement>(null);
  const { status, events, tokens, cost, error, runId, streamText, outputs, stats, setStats } =
      useRunStore();

  const steps = useMemo(() => countSteps(events), [events]);
  const terminal = isTerminal(status);
  const approval = events.find((event) => event.type === "human_required");

  const elapsed = events.length > 1
    ? new Date(events[events.length - 1].createdAt).getTime() - new Date(events[0].createdAt).getTime()
    : 0;

  useEffect(() => {
    if (tab === "logs" && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events, tab]);

  useEffect(() => {
    if (tab === "output" && outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [streamText, tab]);

  // 指标页与终态时按需拉节点维度统计（Token/耗时/成本由后端聚合，前端不重复算）
  useEffect(() => {
    if (!runId) return;
    if (tab !== "metrics" && !terminal) return;
    let cancelled = false;
    runsApi
      .stats(runId)
      .then((result) => {
        if (!cancelled) setStats(result);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, terminal, tab, setStats]);

  return (
    <section className={`bg-white border-t border-line flex flex-col flex-shrink-0 ${collapsed ? "h-[44px]" : "h-[264px]"}`}>
      <div className="h-[44px] flex-shrink-0 flex items-center gap-3 px-4 border-b border-line">
        <span className="text-[13px] font-semibold">运行面板</span>
        <span className={`badge ${STATUS_BADGE[status]}`}>{STATUS_TEXT[status]}</span>
        <span className="text-[11px] text-ink-3 font-mono">{runId ?? "未开始运行"}</span>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-[11px] text-ink-2">步骤 <b className="text-ink">{steps}</b></span>
          <span className="text-[11px] text-ink-2">Token <b className="text-ink">{tokens}</b></span>
          <span className="text-[11px] text-ink-2">成本 <b className="text-ink">¥{cost.toFixed(4)}</b></span>
          <span className="text-[11px] text-ink-2">耗时 <b className="text-ink">{(elapsed / 1000).toFixed(1)}s</b></span>
          {!terminal && status !== "pending" ? (
            <button className="btn !text-danger" onClick={onCancel}>
              <CircleStop size={13} className="inline mr-1 -mt-0.5" />停止
            </button>
          ) : (
            <button className="btn-primary" disabled={!canRun} onClick={onRun}>
              <Play size={13} className="inline mr-1 -mt-0.5" />运行
            </button>
          )}
          <button className="btn !px-2" onClick={() => setCollapsed((value) => !value)}>
            {collapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          <div className="h-[34px] flex-shrink-0 flex items-center gap-1 px-3 border-b border-line bg-slate-50">
            {([
              ["logs", "实时日志"],
              ["output", "输出结果"],
              ["metrics", "指标成本"],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                className={`px-3 py-1 rounded-sm text-[12px] ${tab === key ? "bg-white border border-line text-primary" : "text-ink-2"}`}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
            <button
              className="ml-auto text-[11px] text-ink-3 hover:text-primary flex items-center gap-1"
              onClick={() => runId && void runsApi.stats(runId).then(setStats).catch(() => setStats(null))}
            >
              <RefreshCw size={11} />刷新指标
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {status === "waiting_human" && (
              <div className="mx-4 mt-3 border border-violet/30 bg-violet-50 rounded-sm px-3 py-2 flex items-center gap-3">
                <span className="badge badge-purple">human_required</span>
                <span className="text-[12px] text-ink-2 flex-1 truncate">
                  {String(approval?.payload.message ?? "需要人工批准才能继续执行当前高危操作")}
                </span>
                <button className="btn-primary !py-1" onClick={() => onApprove(true)}>批准并续跑</button>
                <button className="btn !py-1" onClick={() => onApprove(false)}>拒绝</button>
              </div>
            )}

            {tab === "logs" && (
              <div ref={logRef} className="h-full overflow-y-auto px-4 py-2 font-mono text-[12px] leading-6">
                {events.length === 0 && <div className="text-ink-3">点击「运行」后，事件将实时出现在这里。</div>}
                {events.map((event) => (
                  <div key={event.seq} className="flex gap-2 items-start border-b border-line/60 py-0.5">
                    <span className="text-ink-3 shrink-0">
                      {new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour12: false })}
                    </span>
                    <span className={`badge ${badgeClass[event.type]} shrink-0`}>{event.type}</span>
                    {event.nodeId && <span className="text-info shrink-0">{event.nodeId}</span>}
                    <span className="text-ink-2 break-all">
                      {event.type === "token" ? String(event.payload.text ?? "") : JSON.stringify(event.payload)}
                    </span>
                  </div>
                ))}
                {error && <div className="text-danger mt-2">错误：{error}</div>}
              </div>
            )}

            {tab === "output" && (
              <div className="h-full overflow-auto px-4 py-3 space-y-3">
                {(streamText || status === "running") && (
                  <div>
                    <div className="text-[11px] text-ink-3 mb-1">流式输出（token 事件逐块追加）</div>
                    <pre ref={outputRef} className="font-mono text-[12px] text-ink whitespace-pre-wrap max-h-[92px] overflow-auto">
                      {streamText || "等待首个 token…"}
                      {status === "running" && <span className="animate-pulse text-primary">▌</span>}
                    </pre>
                  </div>
                )}
                {outputs ? (
                  <div>
                    <div className="text-[11px] text-ink-3 mb-1">最终输出（run_completed.outputs）</div>
                    <pre className="font-mono text-[12px] text-ink whitespace-pre-wrap">{JSON.stringify(outputs, null, 2)}</pre>
                  </div>
                ) : (
                  <div className="text-[12px] text-ink-3">运行完成后显示最终输出。</div>
                )}
              </div>
            )}

            {tab === "metrics" && (
              <div className="h-full overflow-auto px-4 py-3">
                <div className="flex flex-wrap gap-3">
                  {[
                    ["Token 用量", String(tokens)],
                    ["预估成本", `¥${cost.toFixed(4)}`],
                    ["执行步数", String(steps)],
                    ["耗时", `${(elapsed / 1000).toFixed(1)} s`],
                  ].map(([label, value]) => (
                    <div key={label} className="card px-4 py-2.5 min-w-[140px]">
                      <div className="text-[11px] text-ink-3">{label}</div>
                      <div className="text-[18px] font-semibold mt-0.5">{value}</div>
                    </div>
                  ))}
                </div>

                <div className="mt-3">
                  <div className="text-[11px] text-ink-3 mb-1">节点维度（GET /api/runs/:id/stats）</div>
                  {stats && stats.nodes.length > 0 ? (
                    <table className="w-full text-[12px] border border-line rounded-sm">
                      <thead className="bg-slate-50 text-ink-3">
                        <tr>
                          {["节点", "状态", "Token", "耗时", "成本"].map((head) => (
                            <th key={head} className="text-left px-3 py-1.5 font-medium">{head}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {stats.nodes.map((node) => (
                          <tr key={node.nodeId} className="border-t border-line">
                            <td className="px-3 py-1.5 font-mono text-info">{node.nodeId}</td>
                            <td className="px-3 py-1.5">{node.status}</td>
                            <td className="px-3 py-1.5">{node.tokens}</td>
                            <td className="px-3 py-1.5">{node.durationMs} ms</td>
                            <td className="px-3 py-1.5">¥{node.cost.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="text-[12px] text-ink-3">运行后展示按节点聚合的 token、耗时与成本。</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
