import clsx from "clsx";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import type { AgentNode } from "@/utils/flow";

function text(value: unknown): string {
  return value === undefined || value === null || value === "" ? "—" : String(value);
}

function summary(type: string, config: Record<string, unknown>): string {
  switch (type) {
    case "start": {
      const variables = Array.isArray(config.variables) ? config.variables : [];
      return `${variables.length} 个输入变量`;
    }
    case "agent": {
      const mappings = config.inputMap && typeof config.inputMap === "object"
        ? Object.keys(config.inputMap as Record<string, unknown>).length
        : 0;
      return `${text(config.agentId)} · 映射 ${mappings}`;
    }
    case "condition": return `表达式 ${text(config.expression)}`;
    case "loop": return `最大 ${text(config.maxRounds)} 轮${config.exitCondition ? " · 有退出条件" : ""}`;
    case "human": return text(config.message);
    case "end": {
      const outputs = config.outputs;
      if (Array.isArray(outputs)) return outputs.length ? `输出 ${outputs.length} 项` : "自动取最后 Agent 文本";
      if (outputs && typeof outputs === "object") return `输出 ${Object.keys(outputs).length} 个键`;
      return "自动取最后 Agent 文本";
    }
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
      {data.nodeType !== "start" && <Handle type="target" position={Position.Left} id="in" />}

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
      ) : data.nodeType === "loop" ? (
        <>
          <Handle type="source" id="body" position={Position.Right} style={{ top: "32%", background: "#3b82f6" }} />
          <Handle type="source" id="done" position={Position.Right} style={{ top: "68%", background: "#10b981" }} />
        </>
      ) : data.nodeType !== "end" ? (
        <Handle type="source" id="out" position={Position.Right} />
      ) : null}
    </div>
  );
}
