import { create } from "zustand";
import type { RunEvent, RunStatus } from "@/types/run";

interface RunStore {
  runId: string | null;
  status: RunStatus;
  events: RunEvent[];
  activeNodeId: string | null;
  tokens: number;
  cost: number;
  lastSeq: number;
  error: string | null;

  reset: () => void;
  setRunId: (id: string | null) => void;
  setStatus: (status: RunStatus) => void;
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
};

export const useRunStore = create<RunStore>((set) => ({
  ...initial,

  reset: () => set({ ...initial, events: [] }),
  setRunId: (runId) => set({ runId }),
  setStatus: (status) => set({ status }),

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
        case "token":
          next.tokens = state.tokens + Number(event.payload.deltaTokens ?? 1);
          break;
        case "human_required":
          next.status = "waiting_human";
          break;
        case "run_completed":
          next.status = "succeeded";
          next.tokens = Number(event.payload.tokens ?? state.tokens);
          next.cost = Number(event.payload.cost ?? state.cost);
          next.activeNodeId = null;
          break;
        case "run_failed":
          next.status = "failed";
          next.error = String(event.payload.error ?? "运行失败");
          next.activeNodeId = null;
          break;
      }
      return next as RunStore;
    }),
}));
