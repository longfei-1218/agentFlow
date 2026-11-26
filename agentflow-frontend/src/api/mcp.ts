/** MCP Server API（R5）：注册表 CRUD、探测工具、试跑调用。 */
import { api } from "./client";

export interface MCPServer {
  id: string;
  name: string;
  transport: "stdio";
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd?: string | null;
  timeoutS: number;
  enabled: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export type MCPServerPayload = Omit<MCPServer, "id" | "createdAt" | "updatedAt">;

export interface MCPToolInfo {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface MCPProbeResult {
  ok: boolean;
  tools: MCPToolInfo[];
  latencyMs: number;
  error?: string | null;
  code?: string | null;
}

export interface MCPCallResult {
  ok: boolean;
  result?: unknown;
  raw?: unknown;
  latencyMs: number;
  error?: string | null;
  code?: string | null;
}

export const mcpApi = {
  list: () => api.get<MCPServer[]>("/mcp-servers").then((r) => r.data),
  create: (payload: MCPServerPayload) =>
    api.post<MCPServer>("/mcp-servers", payload).then((r) => r.data),
  update: (id: string, payload: MCPServerPayload) =>
    api.put<MCPServer>(`/mcp-servers/${id}`, payload).then((r) => r.data),
  remove: (id: string) => api.delete(`/mcp-servers/${id}`),
  probe: (id: string) =>
    api.get<MCPProbeResult>(`/mcp-servers/${id}/tools`).then((r) => r.data),
  call: (id: string, toolName: string, args: Record<string, unknown>) =>
    api
      .post<MCPCallResult>(`/mcp-servers/${id}/call`, { toolName, args })
      .then((r) => r.data),
};
