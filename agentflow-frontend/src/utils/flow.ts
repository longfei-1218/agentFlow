import type { Edge, Node } from "@xyflow/react";
import type { Flow, FlowCreate } from "@/types/flow";

export type RuntimeState = "idle" | "running" | "done" | "error";

export interface AgentNodeData extends Record<string, unknown> {
  nodeType: Flow["nodes"][number]["type"];
  config: Record<string, unknown>;
  runtime: RuntimeState;
}

export type AgentNode = Node<AgentNodeData, "agent">;

export function flowToNodes(flow: Flow, runtime: Record<string, RuntimeState>): AgentNode[] {
  return flow.nodes.map((node) => ({
    id: node.id,
    type: "agent",
    position: node.position,
    data: {
      nodeType: node.type,
      config: node.config,
      runtime: runtime[node.id] ?? "idle",
    },
  }));
}

/** 分支连线的锚点名 → 画布上显示的文字。condition 用真假，loop 用循环体/退出。 */
export function handleLabel(handle?: string | null): string | undefined {
  switch (handle) {
    case "true": return "真";
    case "false": return "假";
    case "body": return "循环体";
    case "done": return "退出";
    default: return undefined;
  }
}

export function flowToEdges(flow: Flow): Edge[] {
  return flow.edges.map((edge) => {
    const label = handleLabel(edge.sourceHandle);
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? undefined,
      label,
      labelStyle: label ? { fontSize: 10, fill: "#475569" } : undefined,
      labelBgStyle: label ? { fill: "#f8fafc", fillOpacity: 0.85 } : undefined,
    };
  });
}

export const createDefaultFlow = (name = "未命名流程"): FlowCreate => ({
  name,
  nodes: [
    {
      id: "input_1",
      type: "input",
      position: { x: 80, y: 160 },
      config: { name: "query", type: "string", default: "" },
    },
    {
      id: "llm_1",
      type: "llm",
      position: { x: 360, y: 160 },
      config: {
        // 留空 = 跟随「模型设置」里的默认模型；写死厂商模型名换网关就 400
        model: "",
        temperature: 0.7,
        max_tokens: 1024,
        system: "你是一个有帮助的助手。",
      },
    },
    {
      id: "output_1",
      type: "output",
      position: { x: 640, y: 160 },
      config: { fields: ["text"] },
    },
  ],
  edges: [
    { id: "e_1", source: "input_1", target: "llm_1" },
    { id: "e_2", source: "llm_1", target: "output_1" },
  ],
});

export function downloadFlow(flow: Flow): void {
  const blob = new Blob([JSON.stringify(flow, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${flow.name || "flow"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
