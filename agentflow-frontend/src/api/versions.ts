import { api } from "./client";
import { kindPath, type PublishState, type ResourceVersionState, type VersionDetail, type VersionKind } from "@/types/version";

export const versionsApi = {
  /** 版本管理页左侧：所有 Agent / 流程的发布状态与版本数 */
  list: () => api.get<ResourceVersionState[]>("/versions").then((r) => r.data),

  versions: (kind: VersionKind, id: string) =>
    api.get<VersionDetail[]>(`/${kindPath(kind)}/${id}/versions`).then((r) => r.data),

  detail: (kind: VersionKind, id: string, version: number) =>
    api.get<VersionDetail>(`/${kindPath(kind)}/${id}/versions/${version}`).then((r) => r.data),

  publishState: (kind: VersionKind, id: string) =>
    api.get<PublishState>(`/${kindPath(kind)}/${id}/publish-state`).then((r) => r.data),

  /** 回滚：发布指针指回历史版本 + 快照写回草稿，不产生新版本、不改任何资源版本号 */
  rollback: (kind: VersionKind, id: string, version: number) =>
    api
      .post(`/${kindPath(kind)}/${id}/rollback`, { version })
      .then((r) => r.data),
};
