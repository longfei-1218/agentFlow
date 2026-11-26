/** 工具注册表 API（R3）：CRUD、试跑、调用记录、内置工具目录。 */
import { api } from "./client";

export type ToolKind = "http" | "builtin";
export type ToolRisk = "low" | "medium" | "high";
export type IdemMode = "none" | "key";
export type BuiltinName = "echo" | "now" | "calc";

export interface ToolDef {
  id: string;
  name: string;
  description: string;
  kind: ToolKind;
  builtin?: BuiltinName | null;
  method: string;
  url: string;
  headers: Record<string, string>;
  bodyTemplate?: string | null;
  paramsSchema: Record<string, unknown>;
  timeoutMs: number;
  retries: number;
  backoffMs: number;
  idempotency: IdemMode;
  idempotencyTtlS: number;
  risk: ToolRisk;
  enabled: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export type ToolPayload = Omit<ToolDef, "id" | "createdAt" | "updatedAt">;

export interface BuiltinInfo {
  name: BuiltinName;
  description: string;
  paramsSchema: Record<string, unknown>;
}

export interface ToolInvocation {
  id: string;
  toolId: string;
  toolName: string;
  runId?: string | null;
  nodeId?: string | null;
  args: Record<string, unknown>;
  status: "ok" | "error" | "timeout";
  attempts: number;
  latencyMs: number;
  httpStatus?: number | null;
  result?: unknown;
  error?: string | null;
  idemKey?: string | null;
  idemHit: boolean;
  createdAt?: string | null;
}

export interface ToolTestResult {
  ok: boolean;
  status: string;
  attempts: number;
  latencyMs: number;
  httpStatus?: number | null;
  result?: unknown;
  idemHit: boolean;
  error?: string | null;
  code?: string;
  startedAt?: string;
}

export const toolsApi = {
  list: () => api.get<ToolDef[]>("/tools").then((r) => r.data),
  builtins: () => api.get<BuiltinInfo[]>("/tools/builtins").then((r) => r.data),
  create: (payload: ToolPayload) => api.post<ToolDef>("/tools", payload).then((r) => r.data),
  update: (id: string, payload: ToolPayload) =>
    api.put<ToolDef>(`/tools/${id}`, payload).then((r) => r.data),
  remove: (id: string) => api.delete(`/tools/${id}`),
  test: (id: string, args: Record<string, unknown>, useIdempotency = false) =>
    api
      .post<ToolTestResult>(`/tools/${id}/test`, { args, useIdempotency })
      .then((r) => r.data),
  invocations: (toolId?: string, limit = 20) =>
    api
      .get<ToolInvocation[]>("/tools/invocations", {
        params: { ...(toolId ? { toolId } : {}), limit },
      })
      .then((r) => r.data),
};
