import type { Connection } from "@xyflow/react";
import { create } from "zustand";
import { ApiError } from "@/api/client";
import { flowsApi } from "@/api/flows";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import type { Flow, FlowCreate, NodeType, ValidationIssue } from "@/types/flow";
import type { RuntimeState } from "@/utils/flow";

const emptyFlow: Flow = {
  id: "", name: "", dslVersion: 2, version: 1, nodes: [], edges: [],
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
  /** 改一条连线的分支归属（画错了不用删线重拉，直接在配置面板下拉里改） */
  updateEdgeHandle: (edgeId: string, handle: string) => void;
  removeNode: (id: string) => void;
  duplicateNode: (id: string) => void;
  removeEdge: (id: string) => void;
  setSelected: (id: string | null) => void;
  setRuntime: (id: string, state: RuntimeState) => void;
  validate: () => Promise<boolean>;
  save: () => Promise<void>;
  publish: (name: string, note?: string) => Promise<void>;
  toCreatePayload: () => FlowCreate;
}

/** 保存队列：保证同一时刻只有一个 PUT 在飞（见 save() 注释） */
let saveQueue: Promise<void> = Promise.resolve();

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
    // 默认配置也来自后端 Schema：新增节点开箱即合法，不用在前端再抄一份默认值
    const definition = useNodeTypeStore.getState().byType[type];
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
    if (sourceNode.type === "end" || targetNode.type === "start") return;
    if (sourceNode.type === "condition" && sourceHandle !== "true" && sourceHandle !== "false") return;
    if (sourceNode.type === "loop" && sourceHandle !== "body" && sourceHandle !== "done") return;
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

  updateEdgeHandle: (edgeId, handle) => {
    const { flow } = get();
    set({
      flow: {
        ...flow,
        edges: flow.edges.map((e) => (e.id === edgeId ? { ...e, sourceHandle: handle } : e)),
      },
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
    const flow = get().flow;
    if (!flow.id) return;

    // 串行化保存：并发的两个 PUT 会拿着同一个 baseUpdatedAt，
    // 后到的那个必然被判 FLOW_STALE，白白丢掉刚敲的字
    const task = async () => {
      const current = get().flow;
      if (!current.id) return;
      try {
        // 带上 baseUpdatedAt：如果这期间别处改过这条流程，服务端会 409 而不是默默被覆盖
        const updated = await flowsApi.update(current.id, {
          ...get().toCreatePayload(),
          baseUpdatedAt: current.updatedAt,
        });
        set({
          flow: updated,
          dirty: false,
          lastSavedAt: new Date().toISOString(),
        });
      } catch (error) {
        if (error instanceof ApiError && error.code === "FLOW_STALE") {
          await get().loadFlow(current.id);  // 拉回最新，别让本地留着一份覆盖不了的状态
          throw new ApiError(
            409,
            "FLOW_STALE",
            "该流程在别的窗口或标签页被修改过，已重新加载最新内容，本次修改没有覆盖上去",
          );
        }
        throw error;
      }
    };

    const queued = saveQueue.then(task, task);
    saveQueue = queued.catch(() => undefined);
    return queued;
  },

  publish: async (name, note = "") => {
    const { flow } = get();
    if (!flow.id) return;
    // 保存冲突时直接抛给页面，不要把过期的 DSL 发布成新版本
    await get().save();
    const published = await flowsApi.publish(flow.id, { name, note });
    set({
      flow: published,
      dirty: false,
      validationErrors: [],
      lastSavedAt: new Date().toISOString(),
    });
  },

  toCreatePayload: () => {
    const { flow } = get();
    return { name: flow.name, dslVersion: 2, nodes: flow.nodes, edges: flow.edges };
  },
}));
