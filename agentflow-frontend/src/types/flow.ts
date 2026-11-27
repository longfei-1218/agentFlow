/** Flow DSL v2：与后端 app/models/flow.py / app/nodes/registry.py 对齐（API 层 camelCase）。 */
export type NodeType = "start" | "agent" | "condition" | "loop" | "human" | "end";

export const NODE_TYPES: NodeType[] = ["start", "agent", "condition", "loop", "human", "end"];

export interface FlowNode {
  id: string;
  type: NodeType;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
}

export interface Flow {
  id: string;
  name: string;
  dslVersion: number;
  version: number;
  nodes: FlowNode[];
  edges: FlowEdge[];
  createdAt?: string;
  updatedAt?: string;
}

export interface FlowCreate {
  name: string;
  dslVersion?: number;
  nodes: FlowNode[];
  edges: FlowEdge[];
  /** 乐观锁：加载时看到的 updatedAt；服务端发现已被改过会回 409 FLOW_STALE */
  baseUpdatedAt?: string | null;
}

export interface ValidationIssue {
  nodeId?: string | null;
  field?: string | null;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
}

/** 开始节点的变量定义（与 AgentVariable 同构，只取 v2 用到的字段） */
export interface StartVariable {
  key: string;
  label: string;
  type: "string" | "number" | "boolean" | "json";
  required: boolean;
  default: unknown;
  description: string;
}

export function startVariables(config: Record<string, unknown>): StartVariable[] {
  const value = config.variables;
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => ({
      key: String(item.key ?? ""),
      label: String(item.label ?? ""),
      type: (item.type as StartVariable["type"]) ?? "string",
      required: item.required !== false,
      default: item.default ?? null,
      description: String(item.description ?? ""),
    }))
    .filter((item) => item.key !== "");
}
