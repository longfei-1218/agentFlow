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
