import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
} from "@xyflow/react";
import { useFlowStore } from "@/store/flowStore";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import type { NodeType } from "@/types/flow";
import { flowToEdges, flowToNodes, type AgentNode } from "@/utils/flow";
import { FlowNodeView } from "./FlowNodeView";
import { NODE_DRAG_MIME } from "./Palette";

const nodeTypes = { agent: FlowNodeView };

export function FlowCanvas() {
  const flow = useFlowStore((s) => s.flow);
  const runtime = useFlowStore((s) => s.runtime);
  const validationErrors = useFlowStore((s) => s.validationErrors);
  const addNode = useFlowStore((s) => s.addNode);
  const updatePosition = useFlowStore((s) => s.updatePosition);
  const onConnect = useFlowStore((s) => s.onConnect);
  const removeNode = useFlowStore((s) => s.removeNode);
  const removeEdge = useFlowStore((s) => s.removeEdge);
  const setSelected = useFlowStore((s) => s.setSelected);
  const byType = useNodeTypeStore((s) => s.byType);
  const { screenToFlowPosition, fitView } = useReactFlow();

  const [nodes, setNodes, onNodesChange] = useNodesState<AgentNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    setNodes(flowToNodes(flow, runtime));
  }, [flow.nodes, runtime, setNodes]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setEdges(flowToEdges(flow));
  }, [flow.edges, setEdges]); // eslint-disable-line react-hooks/exhaustive-deps

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData(NODE_DRAG_MIME) as NodeType;
      if (!type || !byType[type]) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      addNode(type, position);
    },
    [addNode, byType, screenToFlowPosition],
  );

  const errorNodes = useMemo(
    () => new Set(validationErrors.map((issue) => issue.nodeId).filter(Boolean)),
    [validationErrors],
  );

  return (
    <div className="relative flex-1 min-w-0 h-full" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => setSelected(node.id)}
        onPaneClick={() => setSelected(null)}
        onNodeDragStop={(_, node) => updatePosition(node.id, node.position)}
        onNodesDelete={(deleted) => deleted.forEach((node) => removeNode(node.id))}
        onEdgesDelete={(deleted) => deleted.forEach((edge) => removeEdge(edge.id))}
        fitView
        proOptions={{ hideAttribution: true }}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#d1d5db" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(node) => byType[(node.data as AgentNode["data"]).nodeType]?.color ?? "#94a3b8"}
          maskColor="rgba(246,247,249,.75)"
        />
      </ReactFlow>

      <div className="absolute bottom-3 right-3 flex items-center gap-3 px-3 py-1.5 bg-white/95 border border-line rounded-sm shadow-card text-[11px] text-ink-2">
        <span>节点 <b className="text-ink">{flow.nodes.length}</b></span>
        <span>连线 <b className="text-ink">{flow.edges.length}</b></span>
        <span className="flex items-center gap-1">
          校验
          {validationErrors.length === 0 ? (
            <b className="text-ok">通过</b>
          ) : (
            <b className="text-danger">{validationErrors.length} 个问题</b>
          )}
        </span>
        {errorNodes.size > 0 && <span className="text-danger">高亮 {errorNodes.size} 个节点</span>}
        <button
          className="text-primary hover:underline"
          onClick={() => void fitView({ padding: 0.2 })}
        >
          适应画布
        </button>
      </div>
    </div>
  );
}
