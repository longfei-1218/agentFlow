/** 节点类型 Schema：直接来自后端 Pydantic 模型，前端不再维护一份硬编码定义。 */
import { api } from "./client";

export interface RawSchemaProperty {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  items?: { type?: string };
}

export interface RawNodeSchema {
  properties?: Record<string, RawSchemaProperty>;
  required?: string[];
}

export interface NodeTypeSpec {
  type: string;
  label: string;
  icon: string;
  category: string;
  color: string;
  description: string;
  configSchema: RawNodeSchema;
  defaultConfig: Record<string, unknown>;
  inputs: string[];
  outputs: string[];
  /** 该节点在当前轮次是否真的能执行（false = 占位，运行时会直通） */
  implemented: boolean;
}

export interface NodeTypesPayload {
  types: NodeTypeSpec[];
  categories: string[];
  llmConfigured: boolean;
}

export const nodeTypesApi = {
  list: () => api.get<NodeTypesPayload>("/node-types").then((r) => r.data),
};
