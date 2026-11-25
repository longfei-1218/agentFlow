import { api } from "./client";
import type { Run } from "@/types/run";

export const runsApi = {
  list: (status?: string) =>
    api.get<Run[]>("/runs", { params: status ? { status } : {} }).then((r) => r.data),
  get: (id: string) => api.get<Run>(`/runs/${id}`).then((r) => r.data),
  cancel: (id: string) => api.post<Run>(`/runs/${id}/cancel`).then((r) => r.data),
  resume: (id: string, approved = true) =>
    api.post<Run>(`/runs/${id}/resume`, { approved }).then((r) => r.data),
  toCase: (id: string) => api.post(`/runs/${id}/to-case`).then((r) => r.data),
};
