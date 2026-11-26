/** 节点定义（后端 Schema）的全局缓存：Palette / 画布 / 配置面板共用一份。 */
import { create } from "zustand";
import { nodeTypesApi, type NodeTypeSpec } from "@/api/nodeTypes";

interface NodeTypeStore {
  loaded: boolean;
  loading: boolean;
  error: string | null;
  types: NodeTypeSpec[];
  byType: Record<string, NodeTypeSpec>;
  categories: string[];
  /** 后端当前用的执行引擎（graph / loop / demo），顶栏与运行面板据此显示 */
  engine: string | null;
  engines: string[];
  load: (force?: boolean) => Promise<void>;
}

export const useNodeTypeStore = create<NodeTypeStore>((set, get) => ({
  loaded: false,
  loading: false,
  error: null,
  types: [],
  byType: {},
  categories: [],
  engine: null,
  engines: [],

  load: async (force = false) => {
    if (get().loading) return;
    if (get().loaded && !force) return;
    set({ loading: true, error: null });
    try {
      const payload = await nodeTypesApi.list();
      set({
        types: payload.types,
        byType: Object.fromEntries(payload.types.map((spec) => [spec.type, spec])),
        categories: payload.categories,
        engine: payload.engine ?? null,
        engines: payload.engines ?? [],
        loaded: true,
        loading: false,
      });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : "节点定义加载失败",
      });
    }
  },
}));
