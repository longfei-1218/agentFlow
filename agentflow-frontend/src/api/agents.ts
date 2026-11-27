import { api } from "./client";
import type { Agent, AgentPayload, AgentValidationResult } from "@/types/agent";
import type { Run } from "@/types/run";

export const agentsApi = {
  list: () => api.get<Agent[]>("/agents").then((r) => r.data),
  get: (id: string) => api.get<Agent>(`/agents/${id}`).then((r) => r.data),
  create: (payload: AgentPayload) => api.post<Agent>("/agents", payload).then((r) => r.data),
  update: (id: string, payload: AgentPayload) =>
    api.put<Agent>(`/agents/${id}`, payload).then((r) => r.data),
  remove: (id: string) => api.delete(`/agents/${id}`),
  validateDefinition: (payload: AgentPayload) =>
    api.post<AgentValidationResult>("/agents/validate", payload).then((r) => r.data),
  validateSaved: (id: string) =>
    api.post<AgentValidationResult>(`/agents/${id}/validate`).then((r) => r.data),
  /** 发布 = 生成不可变快照 + 记录配置指纹 / 工具指纹 / 代码 commit；版本名必填 */
  publish: (id: string, payload: { name: string; note?: string }) =>
    api.post<Agent>(`/agents/${id}/publish`, payload).then((r) => r.data),
  /** 异步调试运行：落 runs，前端订阅 /api/runs/{id}/events */
  startRun: (id: string, variables: Record<string, unknown>) =>
    api.post<Run>(`/agents/${id}/runs`, { variables }).then((r) => r.data),
};
