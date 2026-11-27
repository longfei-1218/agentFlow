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
  // 演示 / 导入的流程可能所有节点都塞在 (0,0)。全部重合时按数组顺序横向铺开，
  // 只在展示层兜底；用户拖动后写回真实坐标，不再自动排列。
  const allOverlapped = flow.nodes.length > 1
    && flow.nodes.every((node) => !node.position || (node.position.x === 0 && node.position.y === 0));

  return flow.nodes.map((node, index) => ({
    id: node.id,
    type: "agent",
    position: allOverlapped
      ? { x: 80 + index * 280, y: 160 }
      : node.position,
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

/** 新流程只有 start / end：Agent、条件、循环、审批由用户按需拖入。 */
export const createDefaultFlow = (name = "未命名流程"): FlowCreate => ({
  name,
  dslVersion: 2,
  nodes: [
    {
      id: "start_1",
      type: "start",
      position: { x: 80, y: 180 },
      config: {
        variables: [
          { key: "query", label: "用户输入", type: "string", required: true, default: null, description: "" },
        ],
      },
    },
    {
      id: "end_1",
      type: "end",
      position: { x: 640, y: 180 },
      config: { outputs: [] },
    },
  ],
  edges: [],
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
