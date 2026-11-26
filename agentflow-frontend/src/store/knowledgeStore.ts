/** 知识库列表缓存：配置面板的 kb_id 下拉与知识库页共用。 */
import { create } from "zustand";
import { knowledgeApi, type KnowledgeBase } from "@/api/knowledge";

interface KnowledgeState {
  kbs: KnowledgeBase[];
  loading: boolean;
  error: string | null;
  load: (force?: boolean) => Promise<void>;
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  kbs: [],
  loading: false,
  error: null,
  load: async (force = false) => {
    if (get().loading) return;
    if (!force && get().kbs.length > 0) return;
    set({ loading: true, error: null });
    try {
      set({ kbs: await knowledgeApi.list(), loading: false });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : "加载知识库失败" });
    }
  },
}));
