import { api } from "./client";
import type { Flow, FlowCreate, ValidationResult } from "@/types/flow";
import type { Run } from "@/types/run";

export const flowsApi = {
  list: () => api.get<Flow[]>("/flows").then((r) => r.data),
  get: (id: string) => api.get<Flow>(`/flows/${id}`).then((r) => r.data),
  create: (payload: FlowCreate) => api.post<Flow>("/flows", payload).then((r) => r.data),
  update: (id: string, payload: FlowCreate) =>
    api.put<Flow>(`/flows/${id}`, payload).then((r) => r.data),
  remove: (id: string) => api.delete(`/flows/${id}`),
  /** 发布：快照 + 绑定各节点 Agent 发布版本；版本名必填，自动保存不会递增版本 */
  publish: (id: string, payload: { name: string; note?: string }) =>
    api.post<Flow>(`/flows/${id}/publish`, payload).then((r) => r.data),
  validate: (id: string) =>
    api.post<ValidationResult>(`/flows/${id}/validate`).then((r) => r.data),
  run: (id: string, inputs: Record<string, unknown> = {}) =>
    api.post<Run>(`/flows/${id}/run`, { inputs }).then((r) => r.data),
};
