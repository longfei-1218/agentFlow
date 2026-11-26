import type { Connection } from "@xyflow/react";
import { create } from "zustand";
import { flowsApi } from "@/api/flows";
import { definitionsByType } from "@/registry/nodes";
import type { Flow, FlowCreate, NodeType, ValidationIssue } from "@/types/flow";
import type { RuntimeState } from "@/utils/flow";

const emptyFlow: Flow = {
  id: "", name: "", version: 1, nodes: [], edges: [],
};

function nextNodeId(type: NodeType, existing: string[]): string {
  let id = `${type}_${Date.now().toString(36).slice(-4)}`;
  while (existing.includes(id)) id = `${type}_${Math.random().toString(36).slice(2, 6)}`;
  return id;
}

interface FlowStore {
  flow: Flow;
  selectedNodeId: string | null;
  runtime: Record<string, RuntimeState>;
  validationErrors: ValidationIssue[];
  dirty: boolean;
  loading: boolean;
  loadError: string | null;
  lastSavedAt: string | null;

  loadFlow: (id: string) => Promise<void>;
  setFlow: (flow: Flow) => void;
  rename: (name: string) => void;
  addNode: (type: NodeType, position: { x: number; y: number }) => void;
  updatePosition: (id: string, position: { x: number; y: number }) => void;
  updateConfig: (id: string, patch: Record<string, unknown>) => void;
  onConnect: (connection: Connection) => void;
  removeNode: (id: string) => void;
  duplicateNode: (id: string) => void;
  removeEdge: (id: string) => void;
  setSelected: (id: string | null) => void;
  setRuntime: (id: string, state: RuntimeState) => void;
  validate: () => Promise<boolean>;
  save: () => Promise<void>;
  publish: () => Promise<void>;
  toCreatePayload: () => FlowCreate;
}

export const useFlowStore = create<FlowStore>((set, get) => ({
  flow: emptyFlow,
  selectedNodeId: null,
  runtime: {},
  validationErrors: [],
  dirty: false,
  loading: false,
  loadError: null,
  lastSavedAt: null,

  loadFlow: async (id) => {
    set({ loading: true, loadError: null });
    try {
      const flow = await flowsApi.get(id);
      set({
        flow,
        runtime: {},
        selectedNodeId: null,
        validationErrors: [],
        dirty: false,
        loading: false,
        lastSavedAt: null,
      });
    } catch (error) {
      set({
        loading: false,
        loadError: error instanceof Error ? error.message : "流程加载失败",
      });
    }
  },

  setFlow: (flow) => set({ flow, runtime: {}, selectedNodeId: null, dirty: true }),

  rename: (name) => {
    const { flow } = get();
    set({ flow: { ...flow, name }, dirty: true });
  },

  addNode: (type, position) => {
    const definition = definitionsByType[type];
    if (!definition) return;
    const { flow } = get();
    const id = nextNodeId(type, flow.nodes.map((n) => n.id));
    set({
      flow: {
        ...flow,
        nodes: [...flow.nodes, { id, type, position, config: { ...definition.defaultConfig } }],
      },
      selectedNodeId: id,
      dirty: true,
    });
  },

  updatePosition: (id, position) => {
    const { flow } = get();
    set({
      flow: {
        ...flow,
        nodes: flow.nodes.map((n) => (n.id === id ? { ...n, position } : n)),
      },
      dirty: true,
    });
  },

  updateConfig: (id, patch) => {
    const { flow } = get();
    set({
      flow: {
        ...flow,
        nodes: flow.nodes.map((n) => (n.id === id ? { ...n, config: { ...n.config, ...patch } } : n)),
      },
      dirty: true,
    });
  },

  onConnect: (connection) => {
    const { source, target, sourceHandle } = connection;
    if (!source || !target || source === target) return;
    const { flow } = get();
    const sourceNode = flow.nodes.find((n) => n.id === source);
    const targetNode = flow.nodes.find((n) => n.id === target);
    if (!sourceNode || !targetNode) return;
    if (sourceNode.type === "output" || targetNode.type === "input") return;
    if (sourceNode.type === "condition" && sourceHandle !== "true" && sourceHandle !== "false") return;
    if (flow.edges.some((e) => e.source === source && e.target === target && e.sourceHandle === sourceHandle)) return;

    set({
      flow: {
        ...flow,
        edges: [
          ...flow.edges,
          {
            id: `e_${Date.now().toString(36).slice(-6)}`,
            source,
            target,
            sourceHandle: sourceHandle ?? null,
          },
        ],
      },
      dirty: true,
    });
  },

  removeNode: (id) => {
    const { flow, selectedNodeId } = get();
    set({
      flow: {
        ...flow,
        nodes: flow.nodes.filter((n) => n.id !== id),
        edges: flow.edges.filter((e) => e.source !== id && e.target !== id),
      },
      selectedNodeId: selectedNodeId === id ? null : selectedNodeId,
      dirty: true,
    });
  },

  duplicateNode: (id) => {
    const { flow } = get();
    const node = flow.nodes.find((n) => n.id === id);
    if (!node) return;
    const newId = nextNodeId(node.type, flow.nodes.map((n) => n.id));
    set({
      flow: {
        ...flow,
        nodes: [
          ...flow.nodes,
          {
            ...node,
            id: newId,
            position: { x: node.position.x + 40, y: node.position.y + 40 },
            config: { ...node.config },
          },
        ],
      },
      selectedNodeId: newId,
      dirty: true,
    });
  },

  removeEdge: (id) => {
    const { flow } = get();
    set({
      flow: { ...flow, edges: flow.edges.filter((e) => e.id !== id) },
      dirty: true,
    });
  },

  setSelected: (id) => set({ selectedNodeId: id }),

  setRuntime: (id, state) =>
    set((s) => ({ runtime: { ...s.runtime, [id]: state } })),

  validate: async () => {
    const { flow } = get();
    if (!flow.id) return false;
    const result = await flowsApi.validate(flow.id);
    set({ validationErrors: result.errors });
    return result.valid;
  },

  save: async () => {
    const { flow } = get();
    if (!flow.id) return;
    const updated = await flowsApi.update(flow.id, get().toCreatePayload());
    set({
      flow: updated,
      dirty: false,
      lastSavedAt: new Date().toISOString(),
    });
  },

  publish: async () => {
    const { flow } = get();
    if (!flow.id) return;
    await get().save();
    const published = await flowsApi.publish(flow.id);
    set({
      flow: published,
      dirty: false,
      validationErrors: [],
      lastSavedAt: new Date().toISOString(),
    });
  },

  toCreatePayload: () => {
    const { flow } = get();
    return { name: flow.name, nodes: flow.nodes, edges: flow.edges };
  },
}));
