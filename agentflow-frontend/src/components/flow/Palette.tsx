import { categories, nodeDefinitions } from "@/registry/nodes";
import type { NodeType } from "@/types/flow";

export const NODE_DRAG_MIME = "application/agentflow-node";

export function Palette() {
  return (
    <aside className="w-[200px] flex-shrink-0 bg-white border-r border-line overflow-y-auto px-3 py-3">
      <div className="text-[12px] font-semibold text-ink mb-2">节点库</div>
      {categories.map((category) => (
        <section key={category} className="mb-4">
          <div className="text-[11px] text-ink-3 mb-1.5">{category}</div>
          <div className="flex flex-col gap-1.5">
            {nodeDefinitions
              .filter((definition) => definition.category === category)
              .map((definition) => (
                <div
                  key={definition.type}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData(NODE_DRAG_MIME, definition.type as NodeType);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  className="flex items-center gap-2 px-2 py-1.5 border border-line rounded-sm text-[12px] cursor-grab hover:border-primary hover:bg-primary-soft transition-colors"
                >
                  <span
                    className="w-5 h-5 rounded flex items-center justify-center text-white text-[11px]"
                    style={{ background: definition.color }}
                  >
                    {definition.icon}
                  </span>
                  <span>{definition.label}</span>
                  <span className="ml-auto font-mono text-[10px] text-ink-3">{definition.type}</span>
                </div>
              ))}
          </div>
        </section>
      ))}
      <div className="text-[11px] text-ink-3 leading-relaxed pt-2 border-t border-line">
        拖拽节点到画布，拖动端口连线。condition 节点需分别连接 true / false。
      </div>
    </aside>
  );
}
