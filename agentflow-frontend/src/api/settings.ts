/** 系统设置：LLM 配置（key 永远只在后端存，前端只拿到脱敏预览）。 */
import { api } from "./client";

export interface LlmSettings {
  baseUrl: string;
  model: string;
  temperature: number;
  maxTokens: number;
  hasApiKey: boolean;
  apiKeyPreview: string | null;
  configured: boolean;
  source: "db" | "env" | "none";
  updatedAt: string | null;
}

export interface LlmSettingsPatch {
  baseUrl?: string;
  apiKey?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
}

export interface LlmTestResult {
  ok: boolean;
  message: string;
  code?: string;
  latencyMs: number;
  models: string[];
}

export interface LlmModelsResult {
  ok: boolean;
  models: string[];
  message: string;
  current: string;
  supported: boolean;
}

export const settingsApi = {
  getLlm: () => api.get<LlmSettings>("/settings/llm").then((r) => r.data),
  saveLlm: (patch: LlmSettingsPatch) => api.put<LlmSettings>("/settings/llm", patch).then((r) => r.data),
  testLlm: (patch?: LlmSettingsPatch) =>
    api.post<LlmTestResult>("/settings/llm/test", patch ?? {}).then((r) => r.data),
  /** 网关支持的模型列表，用于节点里的模型下拉 */
  getModels: () => api.get<LlmModelsResult>("/settings/llm/models").then((r) => r.data),
};
