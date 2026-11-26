/** 工具注册表的全局缓存：工具管理页与配置面板共用，避免两处各自拉一份。 */
import { create } from "zustand";
import { toolsApi, type BuiltinInfo, type ToolDef, type ToolPayload } from "@/api/tools";

interface ToolStore {
  tools: ToolDef[];
  builtins: BuiltinInfo[];
  loading: boolean;
  loaded: boolean;
  error: string | null;

  load: (force?: boolean) => Promise<void>;
  save: (payload: ToolPayload, id?: string) => Promise<ToolDef>;
  remove: (id: string) => Promise<void>;
}

export const useToolStore = create<ToolStore>((set, get) => ({
  tools: [],
  builtins: [],
  loading: false,
  loaded: false,
  error: null,

  load: async (force = false) => {
    if (get().loading) return;
    if (get().loaded && !force) return;
    set({ loading: true, error: null });
    try {
      const [tools, builtins] = await Promise.all([toolsApi.list(), toolsApi.builtins()]);
      set({ tools, builtins, loading: false, loaded: true });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : "工具列表加载失败",
      });
    }
  },

  save: async (payload, id) => {
    const tool = id ? await toolsApi.update(id, payload) : await toolsApi.create(payload);
    // 新建/改名会影响 llm 节点的工具绑定与 tool 节点下拉，统一重拉一次最省心
    set({ loaded: false });
    void get().load(true);
    return tool;
  },

  remove: async (id) => {
    await toolsApi.remove(id);
    set({ tools: get().tools.filter((tool) => tool.id !== id) });
  },
}));
