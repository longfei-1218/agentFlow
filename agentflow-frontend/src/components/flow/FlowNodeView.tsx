import clsx from "clsx";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import type { AgentNode } from "@/utils/flow";

function text(value: unknown): string {
  return value === undefined || value === null ? "—" : String(value);
}

function summary(type: string, config: Record<string, unknown>): string {
  switch (type) {
    case "input": return `变量 ${text(config.name)}: ${text(config.type)}`;
    case "prompt": return `模板 ${text(config.template)}`;
    case "knowledge": return `top_k ${text(config.top_k)} · rerank ${config.rerank ? "开" : "关"}`;
    case "llm": return `${text(config.model)} · ${text(config.max_tokens)} tokens`;
    case "condition": return `表达式 ${text(config.expression)}`;
    case "tool": return `工具 ${text(config.tool_id)} · 重试 ${text(config.retry)}`;
    case "mcp": return `${text(config.server_id)} / ${text(config.tool_name)}`;
    case "skill": return `子流程 ${text(config.flow_id)}`;
    case "loop": return `最大 ${text(config.max_rounds)} 轮`;
    case "human": return text(config.message);
    case "output": return `映射 ${Array.isArray(config.fields) ? config.fields.join(", ") : text(config.fields)}`;
    default: return "";
  }
}

export function FlowNodeView({ data, selected }: NodeProps<AgentNode>) {
  const spec = useNodeTypeStore((s) => s.byType[data.nodeType]);
  // Schema 还没加载到时给一个降级外观，别让整张画布出现空白节点
  const definition = spec ?? {
    label: data.nodeType,
    icon: "?",
    color: "#94a3b8",
    type: data.nodeType,
  };

  return (
    <div
      className={clsx(
        "node-card",
        data.runtime === "running" && "is-running",
        data.runtime === "done" && "is-done",
        data.runtime === "error" && "is-error",
        selected && "!border-primary ring-2 ring-indigo-100",
      )}
    >
      {data.nodeType !== "input" && <Handle type="target" position={Position.Left} id="in" />}

      <div className="node-head">
        <span className="node-ico" style={{ background: definition.color }}>{definition.icon}</span>
        <span className="node-name">{definition.label}</span>
        <span className="node-type">{definition.type}</span>
      </div>
      <div className="node-body">{summary(definition.type, data.config)}</div>

      {data.nodeType === "condition" ? (
        <>
          <Handle type="source" id="true" position={Position.Right} style={{ top: "32%", background: "#10b981" }} />
          <Handle type="source" id="false" position={Position.Right} style={{ top: "68%", background: "#ef4444" }} />
        </>
      ) : data.nodeType !== "output" ? (
        <Handle type="source" id="out" position={Position.Right} />
      ) : null}

      {data.nodeType === "knowledge" && (
        <Handle type="source" id="context" position={Position.Top} style={{ background: "#10b981" }} />
      )}
    </div>
  );
}
