/** 资源包导入 API。 */
import { api } from "./client";

export type ResourceImportKind = "mcp_local" | "mcp_remote" | "http_tool";

export interface ResourceImportResult {
  ok: boolean;
  kind: ResourceImportKind;
  status: "installed" | "verified" | "rejected";
  name: string;
  targetId?: string | null;
  packagePath?: string | null;
  tools: Array<Record<string, unknown>>;
  message?: string | null;
  code?: string | null;
  verifiedAt?: string | null;
}

export interface ResourceOverview {
  ownerId: string;
  builtinTools: Array<Record<string, unknown>>;
  tools: Array<Record<string, unknown>>;
  mcpServers: Array<Record<string, unknown>>;
  knowledgeBases: Array<Record<string, unknown>>;
}

export const resourcesApi = {
  overview: () => api.get<ResourceOverview>("/resources").then((r) => r.data),
  importPackage: (kind: ResourceImportKind, file: File) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    return api
      .post<ResourceImportResult>("/resources/import", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      })
      .then((r) => r.data);
  },
  importManifest: (kind: ResourceImportKind, manifest: string) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("manifest", manifest);
    return api
      .post<ResourceImportResult>("/resources/import", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      })
      .then((r) => r.data);
  },
};
