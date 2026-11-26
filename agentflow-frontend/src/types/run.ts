export type RunStatus =
  | "pending" | "running" | "waiting_human" | "succeeded" | "failed" | "cancelled";

export type EventType =
  | "run_started" | "node_started" | "node_completed"
  | "token" | "tool_call" | "tool_result"
  | "human_required" | "run_completed" | "run_failed";

export interface RunEvent {
  id: string;
  runId: string;
  seq: number;
  type: EventType;
  nodeId?: string | null;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface Run {
  id: string;
  flowId: string;
  flowVersion: number;
  status: RunStatus;
  inputs: Record<string, unknown>;
  outputs?: Record<string, unknown> | null;
  state?: Record<string, unknown>;
  error?: string | null;
  tokenUsage: number;
  costEstimate: number;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface NodeStats {
  nodeId: string;
  tokens: number;
  cost: number;
  durationMs: number;
  status: string;
}

export interface RunStats {
  runId: string;
  totalTokens: number;
  nodes: NodeStats[];
}

export const TERMINAL_STATUSES: RunStatus[] = ["succeeded", "failed", "cancelled"];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export const STATUS_TEXT: Record<RunStatus, string> = {
  pending: "未开始",
  running: "运行中",
  waiting_human: "等待审批",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
};

export const STATUS_BADGE: Record<RunStatus, string> = {
  pending: "badge-gray",
  running: "badge-blue",
  waiting_human: "badge-purple",
  succeeded: "badge-green",
  failed: "badge-red",
  cancelled: "badge-gray",
};
