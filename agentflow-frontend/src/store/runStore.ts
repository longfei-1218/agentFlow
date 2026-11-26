import { create } from "zustand";
import type { Run, RunEvent, RunStats, RunStatus } from "@/types/run";

interface RunStore {
  runId: string | null;
  status: RunStatus;
  events: RunEvent[];
  activeNodeId: string | null;
  tokens: number;
  cost: number;
  lastSeq: number;
  error: string | null;
  /** token 事件累积的可见文本：运行中实时追加，用于输出区流式预览 */
  streamText: string;
  outputs: Record<string, unknown> | null;
  stats: RunStats | null;
  /** 模型调用次数（后端 state.steps）：与 MAX_STEPS 同一口径 */
  llmSteps: number;
  maxSteps: number | null;

  reset: () => void;
  setRunId: (id: string | null) => void;
  setStatus: (status: RunStatus) => void;
  /** 用 GET /runs/{id} 的权威数据覆盖本地推断状态（回放页/刷新后） */
  applyRunDetail: (run: Run) => void;
  setStats: (stats: RunStats | null) => void;
  appendEvent: (event: RunEvent) => void;
}

const initial = {
  runId: null as string | null,
  status: "pending" as RunStatus,
  events: [] as RunEvent[],
  activeNodeId: null as string | null,
  tokens: 0,
  cost: 0,
  lastSeq: 0,
  error: null as string | null,
  streamText: "",
  outputs: null as Record<string, unknown> | null,
  stats: null as RunStats | null,
  llmSteps: 0,
  maxSteps: null as number | null,
};

export const useRunStore = create<RunStore>((set) => ({
  ...initial,

  reset: () => set({ ...initial, events: [] }),
  setRunId: (runId) => set({ runId }),
  setStatus: (status) => set({ status }),
  setStats: (stats) => set({ stats }),

  applyRunDetail: (run) =>
    set((state) => {
      const steps = Number((run.state as Record<string, unknown> | undefined)?.steps ?? state.llmSteps);
      return {
        runId: run.id,
        status: run.status,
        tokens: run.tokenUsage,
        cost: run.costEstimate,
        outputs: run.outputs ?? null,
        error: run.error ?? null,
        llmSteps: Number.isFinite(steps) ? steps : state.llmSteps,
      };
    }),

  appendEvent: (event) =>
    set((state) => {
      if (event.seq <= state.lastSeq) return state;
      const events = [...state.events, event].sort((a, b) => a.seq - b.seq);
      const next: Partial<RunStore> = { events, lastSeq: Math.max(state.lastSeq, event.seq) };

      switch (event.type) {
        case "run_started":
          next.status = "running";
          break;
        case "node_started":
          next.activeNodeId = event.nodeId ?? null;
          break;
        case "node_completed":
          next.activeNodeId = null;
          break;
        case "token": {
          // 关键：token 事件必须逐块拼到可见文本，而不是只做计数
          next.streamText = state.streamText + String(event.payload.text ?? "");
          next.tokens = state.tokens + Number(event.payload.deltaTokens ?? 0);
          next.cost = state.cost + Number(event.payload.cost ?? 0);
          break;
        }
        case "human_required":
          next.status = "waiting_human";
          break;
        case "run_completed":
          next.status = "succeeded";
          next.tokens = Number(event.payload.tokens ?? state.tokens);
          next.cost = Number(event.payload.cost ?? state.cost);
          next.llmSteps = Number(event.payload.steps ?? state.llmSteps);
          next.maxSteps = event.payload.maxSteps ? Number(event.payload.maxSteps) : state.maxSteps;
          next.outputs = (event.payload.outputs as Record<string, unknown>) ?? null;
          next.activeNodeId = null;
          break;
        case "run_failed":
          next.status = "cancelled";
          next.error = String(event.payload.error ?? "运行失败");
          next.activeNodeId = null;
          if (event.payload.cancelled) {
            next.status = "cancelled";
          } else {
            next.status = "failed";
          }
          break;
      }
      return next as RunStore;
    }),
}));

/** 运行中由事件推断的「节点执行数」：一个节点启动即一步（注意不等于模型调用次数）。 */
export function countSteps(events: RunEvent[]): number {
  return events.filter((event) => event.type === "node_started").length;
}
