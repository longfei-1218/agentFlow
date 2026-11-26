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
  /** 显式发布：version + 1，同时后端会先校验 DSL 再接受。 */
  publish: (id: string) => api.post<Flow>(`/flows/${id}/publish`).then((r) => r.data),
  validate: (id: string) =>
    api.post<ValidationResult>(`/flows/${id}/validate`).then((r) => r.data),
  run: (id: string, inputs: Record<string, unknown> = {}) =>
    api.post<Run>(`/flows/${id}/run`, { inputs }).then((r) => r.data),
};
