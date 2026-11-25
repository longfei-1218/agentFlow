import type { NodeType } from "@/types/flow";

export interface SchemaProperty {
  type: "string" | "number" | "integer" | "boolean" | "array";
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
}

export interface NodeSchema {
  properties: Record<string, SchemaProperty>;
  required?: string[];
}

export interface NodeDefinition {
  type: NodeType;
  label: string;
  icon: string;
  category: "基础" | "模型" | "工具" | "控制";
  color: string;
  configSchema: NodeSchema;
  defaultConfig: Record<string, unknown>;
  inputs: string[];
  outputs: string[];
}

const C = { base: "#6b7280", model: "#3b82f6", tool: "#10b981", ctrl: "#f59e0b" };

export const nodeDefinitions: NodeDefinition[] = [
  {
    type: "input", label: "入口", icon: "⇥", category: "基础", color: C.base,
    configSchema: {
      properties: {
        name: { type: "string", title: "变量名", default: "query" },
        type: { type: "string", title: "类型", enum: ["string", "number", "boolean"], default: "string" },
        default: { type: "string", title: "默认值" },
      },
      required: ["name"],
    },
    defaultConfig: { name: "query", type: "string", default: "" },
    inputs: [], outputs: ["variables"],
  },
  {
    type: "output", label: "出口", icon: "⇤", category: "基础", color: C.base,
    configSchema: {
      properties: { fields: { type: "array", title: "输出字段", description: "逗号分隔，如 text, score" } },
      required: ["fields"],
    },
    defaultConfig: { fields: ["text"] },
    inputs: ["variables"], outputs: [],
  },
  {
    type: "llm", label: "模型", icon: "✦", category: "模型", color: C.model,
    configSchema: {
      properties: {
        model: {
          type: "string", title: "模型",
          enum: ["gpt-4o-mini", "deepseek-chat", "qwen-plus", "custom"], default: "gpt-4o-mini",
        },
        temperature: { type: "number", title: "Temperature", minimum: 0, maximum: 2, default: 0.7 },
        max_tokens: { type: "integer", title: "Max tokens", minimum: 1, default: 1024 },
        system: { type: "string", title: "System Prompt", minLength: 1, default: "你是一个有帮助的助手。" },
      },
      required: ["model", "system"],
    },
    defaultConfig: {
      model: "gpt-4o-mini", temperature: 0.7, max_tokens: 1024, system: "你是一个有帮助的助手。",
    },
    inputs: ["variables", "messages"], outputs: ["text", "tool_calls"],
  },
  {
    type: "prompt", label: "模板", icon: "T", category: "模型", color: C.model,
    configSchema: {
      properties: { template: { type: "string", title: "模板字符串", description: "使用 {{var}} 插值" } },
      required: ["template"],
    },
    defaultConfig: { template: "请回答：{{query}}" },
    inputs: ["variables"], outputs: ["text"],
  },
  {
    type: "tool", label: "工具", icon: "⚙", category: "工具", color: C.tool,
    configSchema: {
      properties: {
        tool_id: { type: "string", title: "工具 ID" },
        timeout: { type: "number", title: "超时（秒）", minimum: 1, default: 10 },
        retry: { type: "integer", title: "重试次数", minimum: 0, maximum: 5, default: 2 },
      },
      required: ["tool_id"],
    },
    defaultConfig: { tool_id: "", timeout: 10, retry: 2 },
    inputs: ["variables"], outputs: ["result"],
  },
  {
    type: "mcp", label: "MCP", icon: "⊕", category: "工具", color: C.tool,
    configSchema: {
      properties: {
        server_id: { type: "string", title: "MCP Server" },
        tool_name: { type: "string", title: "工具名称" },
      },
      required: ["server_id", "tool_name"],
    },
    defaultConfig: { server_id: "", tool_name: "" },
    inputs: ["variables"], outputs: ["result"],
  },
  {
    type: "skill", label: "子流程", icon: "⤴", category: "工具", color: C.tool,
    configSchema: {
      properties: { flow_id: { type: "string", title: "子流程 ID" } },
      required: ["flow_id"],
    },
    defaultConfig: { flow_id: "" },
    inputs: ["variables"], outputs: ["variables"],
  },
  {
    type: "knowledge", label: "知识", icon: "▤", category: "工具", color: C.tool,
    configSchema: {
      properties: {
        kb_id: { type: "string", title: "知识库 ID" },
        top_k: { type: "integer", title: "Top K", minimum: 1, maximum: 20, default: 4 },
        rerank: { type: "boolean", title: "启用重排", default: false },
      },
      required: ["kb_id"],
    },
    defaultConfig: { kb_id: "", top_k: 4, rerank: false },
    inputs: ["query"], outputs: ["context"],
  },
  {
    type: "condition", label: "分支", icon: "⑂", category: "控制", color: C.ctrl,
    configSchema: {
      properties: { expression: { type: "string", title: "条件表达式", description: "如 {{score}} > 0.8" } },
      required: ["expression"],
    },
    defaultConfig: { expression: "{{score}} > 0.8" },
    inputs: ["variables"], outputs: ["true", "false"],
  },
  {
    type: "loop", label: "循环", icon: "↻", category: "控制", color: C.ctrl,
    configSchema: {
      properties: {
        max_rounds: { type: "integer", title: "最大轮次", minimum: 1, maximum: 32, default: 3 },
        exit_condition: { type: "string", title: "退出条件" },
      },
      required: ["max_rounds"],
    },
    defaultConfig: { max_rounds: 3, exit_condition: "{{done}} == true" },
    inputs: ["variables"], outputs: ["variables"],
  },
  {
    type: "human", label: "人工", icon: "☝", category: "控制", color: C.ctrl,
    configSchema: {
      properties: {
        message: { type: "string", title: "审批提示" },
        timeout: { type: "number", title: "超时（秒）", minimum: 1, default: 300 },
      },
      required: ["message"],
    },
    defaultConfig: { message: "是否允许执行该高危操作？", timeout: 300 },
    inputs: ["variables"], outputs: ["approved"],
  },
];

export const definitionsByType = Object.fromEntries(
  nodeDefinitions.map((definition) => [definition.type, definition]),
) as Record<NodeType, NodeDefinition>;

export const categories = ["基础", "模型", "工具", "控制"] as const;
