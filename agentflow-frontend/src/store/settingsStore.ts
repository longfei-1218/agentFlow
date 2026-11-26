/** 系统设置：LLM 配置视图 + 设置弹层开关。 */
import { create } from "zustand";
import { settingsApi, type LlmSettings, type LlmSettingsPatch, type LlmTestResult } from "@/api/settings";

interface SettingsStore {
  open: boolean;
  view: LlmSettings | null;
  loading: boolean;
  error: string | null;
  /** 网关支持的模型清单（节点配置里的模型下拉用），失败时为空 */
  models: string[];
  openModal: () => void;
  closeModal: () => void;
  refresh: () => Promise<void>;
  loadModels: () => Promise<void>;
  save: (patch: LlmSettingsPatch) => Promise<LlmSettings>;
  test: (patch?: LlmSettingsPatch) => Promise<LlmTestResult>;
}

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  open: false,
  view: null,
  loading: false,
  error: null,
  models: [],

  openModal: () => set({ open: true }),
  closeModal: () => set({ open: false }),

  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const view = await settingsApi.getLlm();
      set({ view, loading: false });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : "设置读取失败" });
    }
  },

  loadModels: async () => {
    if (get().models.length > 0) return;
    try {
      const result = await settingsApi.getModels();
      set({ models: result.models });
    } catch {
      // 网关没实现 /models 或没配置时静默：模型字段退回手填
    }
  },

  save: async (patch) => {
    const view = await settingsApi.saveLlm(patch);
    set({ view, models: [] });  // 换网关后模型列表要重新拉
    return view;
  },

  test: async (patch) => {
    const result = await settingsApi.testLlm(patch);
    if (result.ok && result.models.length > 0) set({ models: result.models });
    return result;
  },
}));

/** 是否已配置模型：未配置时运行会被后端 409 拦下，界面提前给出入口。 */
export function useLlmConfigured(): boolean {
  return useSettingsStore((s) => s.view?.configured ?? false);
}
