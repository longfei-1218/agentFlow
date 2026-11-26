import { useEffect, useMemo } from "react";
import { Copy, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { z } from "zod";
import { useFlowStore } from "@/store/flowStore";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import { useSettingsStore } from "@/store/settingsStore";
import { useToolStore } from "@/store/toolStore";
import { normalizeSchema, type NormalizedSchema, type SchemaProperty } from "@/utils/schema";
import type { FlowNode } from "@/types/flow";

/** tool 节点的工具选择：从注册表来，不给手填 id，避免写错一个字符到运行期才报错。 */
function ToolRefField({ node }: { node: FlowNode }) {
  const tools = useToolStore((s) => s.tools);
  const loadTools = useToolStore((s) => s.load);
  const updateConfig = useFlowStore((s) => s.updateConfig);

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  const value = String(node.config.tool_id ?? "");
  const missing = value !== "" && !tools.some((tool) => tool.id === value);

  return (
    <label className="block mb-3">
      <span className="block mb-1 text-[12px] text-ink-2">工具</span>
      <select className="field" value={value} onChange={(e) => updateConfig(node.id, { tool_id: e.target.value })}>
        <option value="">未选择（运行会失败）</option>
        {tools.map((tool) => (
          <option key={tool.id} value={tool.id}>
            {tool.name}{tool.enabled ? "" : "（已停用）"}{tool.kind === "builtin" ? " · 内置" : " · HTTP"}
          </option>
        ))}
        {missing && <option value={value}>{value}（注册表里不存在）</option>}
      </select>
      <div className="mt-1 text-[11px] text-ink-3">
        {tools.length === 0 ? (
          <>还没有工具，先到 <Link className="text-primary hover:underline" to="/tools">工具管理</Link> 注册一个。</>
        ) : (
          <>超时 / 重试 / 幂等跟随工具定义，可在 <Link className="text-primary hover:underline" to="/tools">工具管理</Link> 里改并试跑。</>
        )}
      </div>
    </label>
  );
}

/** llm 节点的工具绑定：勾选后模型会自己决定调不调，结果回填后继续生成。 */
function ToolBindField({ node }: { node: FlowNode }) {
  const tools = useToolStore((s) => s.tools);
  const loadTools = useToolStore((s) => s.load);
  const updateConfig = useFlowStore((s) => s.updateConfig);

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  const value = Array.isArray(node.config.tool_ids) ? (node.config.tool_ids as string[]) : [];
  const toggle = (id: string) => {
    const next = value.includes(id) ? value.filter((item) => item !== id) : [...value, id];
    updateConfig(node.id, { tool_ids: next });
  };

  return (
    <div className="mb-3">
      <div className="mb-1 text-[12px] text-ink-2">
        绑定工具
        <span className="ml-1 text-ink-3">· 勾选后模型自行决定调用，每多一轮算一步</span>
      </div>
      {tools.length === 0 ? (
        <div className="text-[11px] text-ink-3">
          还没有工具。去 <Link className="text-primary hover:underline" to="/tools">工具管理</Link> 注册后再勾选。
        </div>
      ) : (
        <div className="border border-line rounded-sm max-h-[132px] overflow-y-auto">
          {tools.map((tool) => (
            <label key={tool.id} className="flex items-center gap-2 px-2 py-1 text-[12px] hover:bg-slate-50 cursor-pointer">
              <input
                type="checkbox"
                className="w-3.5 h-3.5 accent-primary"
                checked={value.includes(tool.id)}
                disabled={!tool.enabled}
                onChange={() => toggle(tool.id)}
              />
              <span className="font-mono">{tool.name}</span>
              {!tool.enabled && <span className="text-[10px] text-ink-3">停用</span>}
              {tool.risk === "high" && <span className="badge badge-red !text-[10px] !py-0">high</span>}
            </label>
          ))}
        </div>
      )}
      {value.length > 0 && <div className="mt-1 text-[11px] text-ink-3">已绑定 {value.length} 个 · 工具失败不会中断运行，错误会回给模型</div>}
    </div>
  );
}

/** 分支/循环节点的出边归属。拉线时选的是锚点，这里可以复核和改归属。 */
const BRANCH_OPTIONS: Record<string, { value: string; label: string }[]> = {
  condition: [
    { value: "true", label: "真分支（表达式成立）" },
    { value: "false", label: "假分支（表达式不成立）" },
  ],
  loop: [
    { value: "body", label: "循环体（回到这里，再跑一轮）" },
    { value: "done", label: "退出（离开循环）" },
  ],
};

function BranchEdgesField({ node }: { node: FlowNode }) {
  const edges = useFlowStore((s) => s.flow.edges);
  const nodes = useFlowStore((s) => s.flow.nodes);
  const updateEdgeHandle = useFlowStore((s) => s.updateEdgeHandle);

  const options = BRANCH_OPTIONS[node.type];
  if (!options) return null;

  const outgoing = edges.filter((edge) => edge.source === node.id);
  const used = new Set(outgoing.map((edge) => edge.sourceHandle));
  const missing = options.filter((option) => !used.has(option.value));

  return (
    <div className="mb-3">
      <div className="mb-1 text-[12px] text-ink-2">
        分支连线
        <span className="ml-1 text-ink-3">· 出边归属决定走哪条，改下拉即可，不用删线重拉</span>
      </div>

      {outgoing.length === 0 ? (
        <div className="text-[11px] text-ink-3">
          还没有出边。从节点右侧对应颜色的锚点拉线到目标节点。
        </div>
      ) : (
        <div className="space-y-1.5">
          {outgoing.map((edge) => {
            const target = nodes.find((item) => item.id === edge.target);
            const known = options.some((option) => option.value === edge.sourceHandle);
            return (
              <div key={edge.id} className="flex items-center gap-2">
                <select
                  className="field !py-1 !text-[12px] flex-1"
                  value={edge.sourceHandle ?? ""}
                  onChange={(event) => updateEdgeHandle(edge.id, event.target.value)}
                >
                  {!known && <option value={edge.sourceHandle ?? ""}>未标注（选一个）</option>}
                  {options.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <span className="text-[11px] text-ink-3 font-mono shrink-0" title={target?.id}>
                  → {target?.type ?? "?"} {edge.target}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {missing.length > 0 && (
        <div className="mt-1 text-[11px] text-warn">
          缺少：{missing.map((option) => option.label).join("、")}
          {node.type === "loop" ? "（body 必填，done 缺失时直接结束）" : "（运行校验会拦下）"}
        </div>
      )}
    </div>
  );
}


function ModelField({ node }: { node: FlowNode }) {
  const models = useSettingsStore((s) => s.models);
  const view = useSettingsStore((s) => s.view);
  const updateConfig = useFlowStore((s) => s.updateConfig);
  const value = String(node.config.model ?? "");
  const supported = models.length === 0 || value === "" || models.includes(value);

  return (
    <label className="block mb-3">
      <span className="block mb-1 text-[12px] text-ink-2">
        模型
        <span className="ml-1 text-ink-3">· 留空则跟随「模型设置」里的默认（{view?.model ?? "未配置"}）</span>
      </span>

      {models.length > 0 ? (
        <select className="field" value={value} onChange={(e) => updateConfig(node.id, { model: e.target.value })}>
          <option value="">跟随系统默认（{view?.model ?? "未配置"}）</option>
          {!supported && <option value={value}>{value}（网关不支持）</option>}
          {models.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      ) : (
        <input
          className="field"
          value={value}
          placeholder={view?.model ? `留空 = 跟随系统默认（${view.model}）` : "留空 = 跟随系统默认"}
          onChange={(e) => updateConfig(node.id, { model: e.target.value })}
        />
      )}

      {!supported && (
        <button
          className="mt-1 text-[11px] text-danger hover:underline text-left"
          onClick={() => updateConfig(node.id, { model: "" })}
        >
          当前值 {value} 不在网关支持列表，点此改为跟随系统默认
        </button>
      )}
      <div className="mt-1 text-[11px] text-ink-3">节点级模型优先于系统默认。</div>
    </label>
  );
}

function buildZodSchema(schema: NormalizedSchema) {
  const shape: Record<string, z.ZodTypeAny> = {};
  const required = new Set(schema.required);

  for (const [key, prop] of Object.entries(schema.properties)) {
    const label = prop.title ?? key;
    let field: z.ZodTypeAny;

    if (prop.type === "number" || prop.type === "integer") {
      let number = z.number({ invalid_type_error: `${label} 必须是数字` });
      if (prop.type === "integer") number = number.int(`${label} 必须是整数`);
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

  const isLongText =
    ["template", "system", "expression", "message", "exit_condition"].includes(name) ||
    (prop.description?.length ?? 0) > 40 ||
    String(value ?? "").length > 60;

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
          placeholder="逗号分隔，如 text, score"
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

  const byType = useNodeTypeStore((s) => s.byType);
  const loaded = useNodeTypeStore((s) => s.loaded);
  const loadError = useNodeTypeStore((s) => s.error);
  const load = useNodeTypeStore((s) => s.load);
  const loadModels = useSettingsStore((s) => s.loadModels);

  const spec = node ? byType[node.type] : undefined;
  const schema = useMemo(() => normalizeSchema(spec?.configSchema), [spec]);

  // 选中模型节点时顺手拉一次网关模型列表（失败静默，退回手填）
  useEffect(() => {
    if (node?.type === "llm") void loadModels();
  }, [node?.type, loadModels]);

  const localErrors = useMemo(() => {
    if (!node || !spec) return [];
    const result = buildZodSchema(schema).safeParse(node.config);
    if (result.success) return [];
    return result.error.issues.map((issue) => issue.message);
  }, [node, spec, schema]);

  const nodeServerErrors = serverErrors.filter((issue) => issue.nodeId === selectedNodeId);

  if (!node) {
    return (
      <aside className="w-[272px] flex-shrink-0 bg-white border-l border-line p-4">
        <div className="text-[13px] font-semibold text-ink mb-2">配置面板</div>
        <div className="border border-dashed border-line rounded-sm p-4 text-[12px] text-ink-3 leading-relaxed">
          选中画布中的节点后，这里会按后端下发的 configSchema 自动生成表单。
        </div>
      </aside>
    );
  }

  if (!spec) {
    return (
      <aside className="w-[272px] flex-shrink-0 bg-white border-l border-line p-4">
        <div className="text-[13px] font-semibold text-ink mb-2">配置面板</div>
        <div className="border border-danger/30 bg-danger-50 rounded-sm p-3 text-[12px] text-danger">
          {loaded
            ? `节点类型 ${node.type} 不在后端注册表里，可能是旧流程或手改了 DSL。`
            : loadError || "节点定义加载中…"}
        </div>
        <button className="btn mt-3 w-full" onClick={() => void load(true)}>重新加载节点定义</button>
      </aside>
    );
  }

  return (
    <aside className="w-[272px] flex-shrink-0 bg-white border-l border-line flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <span className="w-6 h-6 rounded flex items-center justify-center text-white text-[12px]" style={{ background: spec.color }}>
            {spec.icon}
          </span>
          <span className="text-[13px] font-semibold">{spec.label}</span>
          {!spec.implemented && <span className="chip !text-warn" title="执行语义未实装，运行时会直通">占位</span>}
          <span className="badge badge-blue ml-auto">{spec.type}</span>
        </div>
        <div className="mt-1.5 text-[11px] text-ink-3 leading-relaxed">{spec.description}</div>
        <div className="mt-1 text-[11px] text-ink-3 font-mono">
          node: {node.id} · schema: {spec.type}.config.v1
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {Object.entries(schema.properties).map(([name, prop]) => {
          if (spec.type === "llm" && name === "model") return <ModelField key={name} node={node} />;
          if (spec.type === "llm" && name === "tool_ids") return <ToolBindField key={name} node={node} />;
          if (spec.type === "tool" && name === "tool_id") return <ToolRefField key={name} node={node} />;
          return <FieldControl key={name} node={node} prop={prop} name={name} />;
        })}

        {(spec.type === "condition" || spec.type === "loop") && <BranchEdgesField node={node} />}

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
