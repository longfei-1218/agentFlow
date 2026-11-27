/** Agent v2：与后端 app/models/agent.py 对齐（API 层 camelCase）。 */
export type VariableType = "string" | "number" | "boolean" | "json";
export type ResourceKind = "tool" | "mcp" | "knowledge";

export interface AgentVariable {
  key: string;
  label: string;
  type: VariableType;
  required: boolean;
  default: unknown;
  description: string;
}

export interface AgentPrompt {
  system: string;
  template: string;
}

export interface AgentResource {
  kind: ResourceKind;
  id: string;
  alias: string;
  tools: string[];
  queryVar: string;
  topK: number;
  rerank: boolean;
}

export interface AgentModelConfig {
  name: string;
  temperature: number;
  maxTokens: number;
  maxToolRounds: number;
}

export interface AgentOutput {
  description: string;
  schema: Record<string, unknown> | null;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  variables: AgentVariable[];
  prompt: AgentPrompt;
  resources: AgentResource[];
  model: AgentModelConfig;
  output: AgentOutput;
  createdAt: string;
  updatedAt: string;
}

export type AgentPayload = Omit<Agent, "id" | "createdAt" | "updatedAt">;

export interface AgentValidationIssue {
  nodeId?: string | null;
  field?: string | null;
  message: string;
}

export interface AgentValidationResult {
  valid: boolean;
  errors: AgentValidationIssue[];
  warnings: string[];
}

export const VARIABLE_TYPES: { value: VariableType; label: string }[] = [
  { value: "string", label: "文本" },
  { value: "number", label: "数字" },
  { value: "boolean", label: "布尔" },
  { value: "json", label: "JSON" },
];

export function emptyVariable(key = "query"): AgentVariable {
  return { key, label: "", type: "string", required: true, default: null, description: "" };
}

export function emptyAgentPayload(name = "新 Agent"): AgentPayload {
  return {
    name,
    description: "",
    variables: [{ ...emptyVariable("query"), label: "用户输入" }],
    prompt: { system: "你是一个简洁的中文助手。", template: "用户：{{query}}" },
    resources: [],
    model: { name: "", temperature: 0.2, maxTokens: 1024, maxToolRounds: 4 },
    output: { description: "", schema: null },
  };
}

/** prompt 里的资源引用：@kb[别名] / @tool[别名] / @mcp[别名.工具] */
export function resourceToken(resource: AgentResource): string {
  if (resource.kind === "knowledge") return `@kb[${resource.alias}]`;
  if (resource.kind === "tool") return `@tool[${resource.alias}]`;
  const tool = resource.tools[0] ?? "工具名";
  return `@mcp[${resource.alias}.${tool}]`;
}

/** 对话入口使用的变量：优先 query，否则第一个 string 变量 */
export function chatVariable(agent: Agent | null): AgentVariable | null {
  if (!agent) return null;
  return agent.variables.find((item) => item.key === "query")
    ?? agent.variables.find((item) => item.type === "string")
    ?? null;
}

/** 变量默认值转成表单字符串 */
export function variableToText(variable: AgentVariable): string {
  const value = variable.default;
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** 表单字符串按变量类型回填为真实值；空值保持 null，交给后端用默认值/必填校验 */
export function textToVariable(type: VariableType, text: string): unknown {
  if (text === "") return null;
  if (type === "number") {
    const value = Number(text);
    return Number.isNaN(value) ? text : value;
  }
  if (type === "boolean") return text === "true";
  if (type === "json") {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}
