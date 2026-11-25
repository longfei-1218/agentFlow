import { useMemo } from "react";
import { Copy, Trash2 } from "lucide-react";
import { z } from "zod";
import { definitionsByType, type SchemaProperty } from "@/registry/nodes";
import { useFlowStore } from "@/store/flowStore";
import type { FlowNode } from "@/types/flow";

function buildZodSchema(schema: { properties: Record<string, SchemaProperty>; required?: string[] }) {
  const shape: Record<string, z.ZodTypeAny> = {};
  const required = new Set(schema.required ?? []);

  for (const [key, prop] of Object.entries(schema.properties)) {
    const label = prop.title ?? key;
    let field: z.ZodTypeAny;

    if (prop.type === "number" || prop.type === "integer") {
      let number = z.number({ invalid_type_error: `${label} 必须是数字` });
      if (prop.type === "integer") number = number.int().positive(`${label} 必须为正整数`);
      if (prop.minimum !== undefined) number = number.min(prop.minimum, `${label} 不能小于 ${prop.minimum}`);
      if (prop.maximum !== undefined) number = number.max(prop.maximum, `${label} 不能大于 ${prop.maximum}`);
      field = number;
    } else if (prop.type === "boolean") {
      field = z.boolean();
    } else if (prop.type === "array") {
      field = z.array(z.union([z.string(), z.number()]));
    } else {
      let string: z.ZodTypeAny = z.string({ invalid_type_error: `${label} 必须是文本` });
      if (prop.minLength) string = (string as z.ZodString).min(prop.minLength, `${label} 不能为空`);
      if (prop.enum?.length) string = string.refine((v) => prop.enum!.includes(v as string), `${label} 取值非法`);
      field = string;
    }

    shape[key] = required.has(key) ? field : field.optional();
  }
  return z.object(shape).passthrough();
}

function FieldControl({
  node,
  prop,
  name,
}: {
  node: FlowNode;
  prop: SchemaProperty;
  name: string;
}) {
  const updateConfig = useFlowStore((s) => s.updateConfig);
  const value = node.config[name];
  const label = prop.title ?? name;
  const set = (next: unknown) => updateConfig(node.id, { [name]: next });

  const isLongText = ["template", "system", "expression", "message"].includes(name) || (prop.minLength ?? 0) > 40;

  return (
    <label className="block mb-3">
      <span className="block mb-1 text-[12px] text-ink-2">
        {label}
        {prop.description && <span className="ml-1 text-ink-3">· {prop.description}</span>}
      </span>

      {prop.enum ? (
        <select className="field" value={String(value ?? prop.default ?? "")} onChange={(e) => set(e.target.value)}>
          {prop.enum.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      ) : prop.type === "boolean" ? (
        <input
          type="checkbox"
          className="w-4 h-4 accent-primary"
          checked={Boolean(value ?? prop.default ?? false)}
          onChange={(e) => set(e.target.checked)}
        />
      ) : prop.type === "array" ? (
        <input
          className="field"
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(e) => set(e.target.value.split(",").map((v) => v.trim()).filter(Boolean))}
        />
      ) : prop.type === "number" || prop.type === "integer" ? (
        <input
          type="number"
          className="field"
          min={prop.minimum}
          max={prop.maximum}
          step={prop.type === "integer" ? 1 : 0.1}
          value={Number(value ?? prop.default ?? 0)}
          onChange={(e) => set(Number(e.target.value))}
        />
      ) : isLongText ? (
        <textarea
          className="field min-h-[92px] resize-y"
          value={String(value ?? prop.default ?? "")}
          onChange={(e) => set(e.target.value)}
        />
      ) : (
        <input
          className="field"
          value={String(value ?? prop.default ?? "")}
          onChange={(e) => set(e.target.value)}
        />
      )}
    </label>
  );
}

export function ConfigPanel() {
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const node = useFlowStore((s) => s.flow.nodes.find((n) => n.id === s.selectedNodeId));
  const serverErrors = useFlowStore((s) => s.validationErrors);
  const removeNode = useFlowStore((s) => s.removeNode);
  const duplicateNode = useFlowStore((s) => s.duplicateNode);

  const definition = node ? definitionsByType[node.type] : undefined;
  const localErrors = useMemo(() => {
    if (!node || !definition) return [];
    const result = buildZodSchema(definition.configSchema).safeParse(node.config);
    if (result.success) return [];
    return result.error.issues.map((issue) => issue.message);
  }, [node, definition]);

  const nodeServerErrors = serverErrors.filter((issue) => issue.nodeId === selectedNodeId);

  if (!node || !definition) {
    return (
      <aside className="w-[272px] flex-shrink-0 bg-white border-l border-line p-4">
        <div className="text-[13px] font-semibold text-ink mb-2">配置面板</div>
        <div className="border border-dashed border-line rounded-sm p-4 text-[12px] text-ink-3 leading-relaxed">
          选中画布中的节点后，这里会按节点的 configSchema 自动生成表单。
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-[272px] flex-shrink-0 bg-white border-l border-line flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <span className="w-6 h-6 rounded flex items-center justify-center text-white text-[12px]" style={{ background: definition.color }}>
            {definition.icon}
          </span>
          <span className="text-[13px] font-semibold">{definition.label}</span>
          <span className="badge badge-blue ml-auto">{definition.type}</span>
        </div>
        <div className="mt-1.5 text-[11px] text-ink-3 font-mono">
          node: {node.id} · schema: {definition.type}.config.v1
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {Object.entries(definition.configSchema.properties).map(([name, prop]) => (
          <FieldControl key={name} node={node} prop={prop} name={name} />
        ))}

        {(localErrors.length > 0 || nodeServerErrors.length > 0) && (
          <div className="border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">
            <div className="font-semibold mb-1">配置校验失败</div>
            <ul className="list-disc pl-4 space-y-0.5">
              {localErrors.map((message, index) => <li key={`local-${index}`}>{message}</li>)}
              {nodeServerErrors.map((issue, index) => <li key={`server-${index}`}>{issue.message}</li>)}
            </ul>
          </div>
        )}
      </div>

      <div className="px-4 py-3 border-t border-line flex items-center gap-2">
        <button className="btn flex-1" onClick={() => duplicateNode(node.id)}>
          <Copy size={13} className="inline mr-1 -mt-0.5" />复制
        </button>
        <button className="btn flex-1 !text-danger !border-danger-200" onClick={() => removeNode(node.id)}>
          <Trash2 size={13} className="inline mr-1 -mt-0.5" />删除
        </button>
      </div>
    </aside>
  );
}
