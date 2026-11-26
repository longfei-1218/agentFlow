/** MCP Server 列表缓存：配置面板下拉与 MCP 页共用，避免各拉各的。 */
import { create } from "zustand";
import { mcpApi, type MCPToolInfo } from "@/api/mcp";

interface MCPState {
  servers: Awaited<ReturnType<typeof mcpApi.list>>;
  tools: Record<string, MCPToolInfo[]>;
  loading: boolean;
  error: string | null;
  load: (force?: boolean) => Promise<void>;
  probe: (serverId: string) => Promise<MCPToolInfo[]>;
  clearProbe: (serverId: string) => void;
}

export const useMcpStore = create<MCPState>((set, get) => ({
  servers: [],
  tools: {},
  loading: false,
  error: null,
  load: async (force = false) => {
    if (get().loading) return;
    if (!force && get().servers.length > 0) return;
    set({ loading: true, error: null });
    try {
      set({ servers: await mcpApi.list(), loading: false });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : "加载 MCP Server 失败" });
    }
  },
  probe: async (serverId) => {
    const cached = get().tools[serverId];
    if (cached) return cached;
    const result = await mcpApi.probe(serverId);
    if (!result.ok) throw new Error(result.error || "探测失败");
    set((state) => ({ tools: { ...state.tools, [serverId]: result.tools } }));
    return result.tools;
  },
  clearProbe: (serverId) =>
    set((state) => {
      const next = { ...state.tools };
      delete next[serverId];
      return { tools: next };
    }),
}));
