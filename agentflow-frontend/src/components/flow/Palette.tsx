import { useNodeTypeStore } from "@/store/nodeTypeStore";
import type { NodeType } from "@/types/flow";

export const NODE_DRAG_MIME = "application/agentflow-node";

export function Palette() {
  const types = useNodeTypeStore((s) => s.types);
  const categories = useNodeTypeStore((s) => s.categories);
  const loading = useNodeTypeStore((s) => s.loading);
  const error = useNodeTypeStore((s) => s.error);
  const load = useNodeTypeStore((s) => s.load);

  return (
    <aside className="w-[200px] flex-shrink-0 bg-white border-r border-line overflow-y-auto px-3 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[12px] font-semibold text-ink">节点库</span>
        {loading && <span className="text-[10px] text-ink-3">加载…</span>}
      </div>

      {error && (
        <div className="mb-3 border border-danger/30 bg-danger-50 rounded-sm px-2 py-1.5 text-[11px] text-danger">
          节点定义加载失败
          <button className="ml-1 underline" onClick={() => void load(true)}>重试</button>
        </div>
      )}

      {categories.map((category) => (
        <section key={category} className="mb-4">
          <div className="text-[11px] text-ink-3 mb-1.5">{category}</div>
          <div className="flex flex-col gap-1.5">
            {types
              .filter((spec) => spec.category === category)
              .map((spec) => (
                <div
                  key={spec.type}
                  draggable
                  title={spec.description}
                  onDragStart={(event) => {
                    event.dataTransfer.setData(NODE_DRAG_MIME, spec.type as NodeType);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  className="flex items-center gap-2 px-2 py-1.5 border border-line rounded-sm text-[12px] cursor-grab hover:border-primary hover:bg-primary-soft transition-colors"
                >
                  <span
                    className="w-5 h-5 rounded flex items-center justify-center text-white text-[11px]"
                    style={{ background: spec.color }}
                  >
                    {spec.icon}
                  </span>
                  <span>{spec.label}</span>
                  {!spec.implemented && (
                    <span className="chip !py-0 !px-1 !text-[9px] !text-ink-3" title="执行语义尚未实装，运行时会直通">
                      占位
                    </span>
                  )}
                  <span className="ml-auto font-mono text-[10px] text-ink-3">{spec.type}</span>
                </div>
              ))}
          </div>
        </section>
      ))}

      <div className="text-[11px] text-ink-3 leading-relaxed pt-2 border-t border-line">
        只有 6 类编排节点。提示词、模型、工具、MCP、知识库都收进 Agent 库；Agent 节点引用一个全局 Agent，条件节点需分别连接 true / false。
      </div>
    </aside>
  );
}
