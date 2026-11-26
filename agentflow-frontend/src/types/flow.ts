/** Flow DSL：与后端 app/models/flow.py 逐字段对齐（API 层 camelCase）。 */
export type NodeType =
  | "input" | "llm" | "prompt" | "tool" | "mcp"
  | "skill" | "knowledge" | "condition" | "loop" | "human" | "output";

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
  version: number;
  nodes: FlowNode[];
  edges: FlowEdge[];
  createdAt?: string;
  updatedAt?: string;
}

export interface FlowCreate {
  name: string;
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
