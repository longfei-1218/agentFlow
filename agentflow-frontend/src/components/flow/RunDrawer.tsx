import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, CircleStop, Play } from "lucide-react";
import { useRunStore } from "@/store/runStore";
import type { EventType, RunStatus } from "@/types/run";

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

const statusText: Record<RunStatus, string> = {
  pending: "未开始",
  running: "运行中",
  waiting_human: "等待审批",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
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
  const { status, events, tokens, cost, error, runId } = useRunStore();

  useEffect(() => {
    if (tab === "logs" && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events, tab]);

  const completed = events.find((event) => event.type === "run_completed");
  const outputs = completed?.payload.outputs;
  const elapsed = events.length > 1
    ? new Date(events[events.length - 1].createdAt).getTime() - new Date(events[0].createdAt).getTime()
    : 0;

  return (
    <section className={`bg-white border-t border-line flex flex-col flex-shrink-0 ${collapsed ? "h-[44px]" : "h-[248px]"}`}>
      <div className="h-[44px] flex-shrink-0 flex items-center gap-3 px-4 border-b border-line">
        <span className="text-[13px] font-semibold">运行面板</span>
        <span className={`badge ${status === "succeeded" ? "badge-green" : status === "failed" ? "badge-red" : status === "waiting_human" ? "badge-purple" : "badge-blue"}`}>
          {statusText[status]}
        </span>
        <span className="text-[11px] text-ink-3 font-mono">{runId ?? "未开始运行"}</span>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-ink-2">Token <b className="text-ink">{tokens}</b></span>
          <span className="text-[11px] text-ink-2">成本 <b className="text-ink">¥{cost.toFixed(4)}</b></span>
          <span className="text-[11px] text-ink-2">耗时 <b className="text-ink">{(elapsed / 1000).toFixed(1)}s</b></span>
          {status === "running" || status === "waiting_human" ? (
            <button className="btn !text-danger" onClick={onCancel}>
              <CircleStop size={13} className="inline mr-1 -mt-0.5" />停止
            </button>
          ) : (
            <button className="btn-primary" disabled={!canRun} onClick={onRun}>
              <Play size={13} className="inline mr-1 -mt-0.5" />运行
            </button>
          )}
          <button className="btn !px-2" onClick={() => setCollapsed((v) => !v)}>
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
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {status === "waiting_human" && (
              <div className="mx-4 mt-3 border border-violet/30 bg-violet-50 rounded-sm px-3 py-2 flex items-center gap-3">
                <span className="badge badge-purple">human_required</span>
                <span className="text-[12px] text-ink-2 flex-1">需要人工批准才能继续执行当前高危操作</span>
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
              <div className="h-full overflow-auto px-4 py-3">
                {outputs ? (
                  <pre className="font-mono text-[12px] text-ink whitespace-pre-wrap">{JSON.stringify(outputs, null, 2)}</pre>
                ) : (
                  <div className="text-[12px] text-ink-3">运行完成后显示最终输出。</div>
                )}
              </div>
            )}

            {tab === "metrics" && (
              <div className="h-full overflow-auto px-4 py-3 flex flex-wrap gap-3 content-start">
                {[
                  ["Token 用量", String(tokens)],
                  ["预估成本", `¥${cost.toFixed(4)}`],
                  ["执行耗时", `${(elapsed / 1000).toFixed(1)} s`],
                  ["事件数", String(events.length)],
                ].map(([label, value]) => (
                  <div key={label} className="card px-4 py-3 min-w-[150px]">
                    <div className="text-[11px] text-ink-3">{label}</div>
                    <div className="text-[18px] font-semibold mt-1">{value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
