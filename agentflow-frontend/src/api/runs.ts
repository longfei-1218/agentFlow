import { api } from "./client";
import type { Run, RunStats } from "@/types/run";

export interface RunListParams {
  flowId?: string;
  status?: string;
  startedAfter?: string;
  limit?: number;
}

export const runsApi = {
  list: (params: RunListParams = {}) =>
    api
      .get<Run[]>("/runs", {
        params: {
          flow_id: params.flowId || undefined,
          status: params.status || undefined,
          started_after: params.startedAfter || undefined,
          limit: params.limit,
        },
      })
      .then((r) => r.data),
  get: (id: string) => api.get<Run>(`/runs/${id}`).then((r) => r.data),
  stats: (id: string) => api.get<RunStats>(`/runs/${id}/stats`).then((r) => r.data),
  cancel: (id: string) => api.post<Run>(`/runs/${id}/cancel`).then((r) => r.data),
  resume: (id: string, approved = true) =>
    api.post<Run>(`/runs/${id}/resume`, { approved }).then((r) => r.data),
  toCase: (id: string) => api.post(`/runs/${id}/to-case`).then((r) => r.data),
};
