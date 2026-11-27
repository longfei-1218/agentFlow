import { api } from "./client";
import type { Run, RunStats, RunTargetType } from "@/types/run";

export interface RunListParams {
  targetType?: RunTargetType;
  targetId?: string;
  flowId?: string;
  agentId?: string;
  status?: string;
  startedAfter?: string;
  limit?: number;
}

export const runsApi = {
  list: (params: RunListParams = {}) =>
    api
      .get<Run[]>("/runs", {
        params: {
          target_type: params.targetType || undefined,
          target_id: params.targetId || undefined,
          flow_id: params.flowId || undefined,
          agent_id: params.agentId || undefined,
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
