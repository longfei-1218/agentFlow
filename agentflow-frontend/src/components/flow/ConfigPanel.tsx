import { useEffect, useMemo, useState } from "react";
import { Copy, MessageSquare, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { useFlowStore } from "@/store/flowStore";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import { startVariables, type FlowNode, type StartVariable } from "@/types/flow";
import type { Agent } from "@/types/agent";
import { VARIABLE_TYPES, emptyVariable } from "@/types/agent";

function nodeLabel(node: FlowNode | undefined): string {
  if (!node) return "—";
  return `${node.type} · ${node.id}`;
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <span className="block mb-1 text-[12px] text-ink-2">{children}</span>;
}

/** 分支节点的出边归属：true/false 或 body/done；画错线不用删，直接在下拉里改。 */
function BranchEdgesField({ node, handles }: { node: FlowNode; handles: string[] }) {
  const flow = useFlowStore((s) => s.flow);
  const updateEdgeHandle = useFlowStore((s) => s.updateEdgeHandle);
  const removeEdge = useFlowStore((s) => s.removeEdge);
  const edges = flow.edges.filter((edge) => edge.source === node.id);

  return (
    <div className="mt-3 border-t border-line pt-3">
      <div className="text-[11px] text-ink-3 mb-1.5">出边（连错可在这里改分支归属）</div>
      {edges.length === 0 && <div className="text-[11px] text-ink-3">还没有出边，从节点右侧锚点拖线。</div>}
      <div className="space-y-1.5">
        {edges.map((edge) => {
          const target = flow.nodes.find((item) => item.id === edge.target);
          return (
            <div key={edge.id} className="flex items-center gap-2 text-[11px]">
              <select
                className="field !py-1"
                value={edge.sourceHandle ?? ""}
                onChange={(event) => updateEdgeHandle(edge.id, event.target.value)}
              >
                {handles.map((handle) => (
                  <option key={handle} value={handle}>{handle}</option>
                ))}
              </select>
              <span className="text-ink-3 shrink-0">→</span>
              <span className="truncate flex-1">{nodeLabel(target)}</span>
              <button className="text-ink-3 hover:text-danger" title="删掉这条线" onClick={() => removeEdge(edge.id)}>
                <Trash2 size={12} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StartConfig({ node }: { node: FlowNode }) {
  const updateConfig = useFlowStore((s) => s.updateConfig);
  const variables = startVariables(node.config);

  const write = (next: StartVariable[]) => updateConfig(node.id, { variables: next });

  const patch = (index: number, values: Partial<StartVariable>) => {
    write(variables.map((item, i) => (i === index ? { ...item, ...values } : item)));
  };

  return (
    <div>
      <div className="text-[11px] text-ink-3 leading-relaxed mb-3">
        流程入口。运行时从「运行」弹窗取值，下游节点用 {"{{start.<key>}}"} 引用。
      </div>
      {variables.map((variable, index) => (
        <div key={index} className="border border-line rounded-sm p-2 mb-2 bg-slate-50/60">
          <div className="flex items-center gap-2">
            <input
              className="field !py-1 font-mono"
              value={variable.key}
              placeholder="变量名，如 query"
              onChange={(event) => patch(index, { key: event.target.value })}
            />
            <select
              className="field !py-1 w-[88px]"
              value={variable.type}
              onChange={(event) => patch(index, { type: event.target.value as StartVariable["type"] })}
            >
              {VARIABLE_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <button className="text-ink-3 hover:text-danger" onClick={() => write(variables.filter((_, i) => i !== index))}>
              <Trash2 size={13} />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2">
            <input
              className="field !py-1"
              value={variable.label}
              placeholder="展示名（可选）"
              onChange={(event) => patch(index, { label: event.target.value })}
            />
            <input
              className="field !py-1"
              value={variable.default === null || variable.default === undefined ? "" : String(variable.default)}
              placeholder="默认值（可选）"
              onChange={(event) => patch(index, { default: event.target.value === "" ? null : event.target.value })}
            />
          </div>
          <label className="flex items-center gap-1.5 mt-2 text-[11px] text-ink-2">
            <input
              type="checkbox"
              className="w-3.5 h-3.5 accent-primary"
              checked={variable.required}
              onChange={(event) => patch(index, { required: event.target.checked })}
            />
            必填
            <input
              className="field !py-1 ml-auto"
              value={variable.description}
              placeholder="说明（可选）"
              onChange={(event) => patch(index, { description: event.target.value })}
            />
          </label>
        </div>
      ))}
      <button
        className="btn w-full !py-1.5"
        onClick={() => write([...variables, { ...emptyVariable(`var_${variables.length + 1}`), required: false }])}
      >
        <Plus size={12} className="inline mr-1 -mt-0.5" />添加变量
      </button>
    </div>
  );
}

function AgentConfigField({ node }: { node: FlowNode }) {
  const flow = useFlowStore((s) => s.flow);
  const updateConfig = useFlowStore((s) => s.updateConfig);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    agentsApi.list()
      .then(setAgents)
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, []);

  const agentId = String(node.config.agentId ?? "");
  const agent = agents.find((item) => item.id === agentId);
  const inputMap = (node.config.inputMap && typeof node.config.inputMap === "object")
    ? node.config.inputMap as Record<string, string>
    : {};
  const missing = agentId !== "" && !agent;

  const setMapping = (key: string, value: string) => {
    const next = { ...inputMap };
    if (value === "") delete next[key];
    else next[key] = value;
    updateConfig(node.id, { inputMap: next });
  };

  const autoMap = () => {
    const vars = agent?.variables ?? [];
    const starts = startVariables(flow.nodes.find((item) => item.type === "start")?.config ?? {});
    const next: Record<string, string> = { ...inputMap };
    vars.forEach((variable) => {
      if (next[variable.key]) return;
      const exact = starts.find((item) => item.key === variable.key);
      if (exact) next[variable.key] = `{{start.${exact.key}}}`;
    });
    updateConfig(node.id, { inputMap: next });
  };

  return (
    <div>
      <FieldLabel>Agent</FieldLabel>
      <select
        className="field"
        value={agentId}
        onChange={(event) => updateConfig(node.id, { agentId: event.target.value })}
      >
        <option value="">{loading ? "加载 Agent 库…" : "未选择（运行会失败）"}</option>
        {agents.map((item) => (
          <option key={item.id} value={item.id}>{item.name}（{item.id}）</option>
        ))}
        {missing && <option value={agentId}>{agentId}（Agent 库里不存在）</option>}
      </select>
      <div className="mt-1 text-[11px] text-ink-3">
        {agents.length === 0 && !loading ? (
          <>还没有 Agent，先到 <Link className="text-primary hover:underline" to="/agents">Agent 库</Link> 新建。</>
        ) : (
          <>Agent 是全局可复用资源，流程只保存引用，不复制定义。</>
        )}
      </div>

      {agentId && (
        <div className="flex gap-2 mt-2">
          <Link className="btn !py-1" to={`/agents/${agentId}`}>
            <Pencil size={12} className="inline mr-1 -mt-0.5" />编辑 Agent
          </Link>
          <Link
            className="btn !py-1"
            to={`/agents/${agentId}/chat?flowId=${flow.id}&nodeId=${node.id}`}
          >
            <MessageSquare size={12} className="inline mr-1 -mt-0.5" />对话
          </Link>
        </div>
      )}

      {agent ? (
        <div className="mt-4 border-t border-line pt-3">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[12px] font-semibold">变量映射</span>
            <button className="ml-auto text-[11px] text-primary hover:underline flex items-center gap-1" onClick={autoMap}>
              <RefreshCw size={10} />同名自动映射
            </button>
          </div>
          <div className="text-[11px] text-ink-3 mb-2">
            左列是 Agent 的变量，右列写流程表达式；产物可用 {"{{<nodeId>.output.<field>}}"} 取。
          </div>
          {agent.variables.length === 0 && (
            <div className="text-[11px] text-warn">该 Agent 没有声明变量，调用时不会注入任何输入。</div>
          )}
          <div className="space-y-1.5">
            {agent.variables.map((variable) => (
              <div key={variable.key} className="grid grid-cols-[112px_1fr] gap-2 items-center">
                <div className="min-w-0">
                  <div className="font-mono text-[11px] truncate">{variable.key}</div>
                  <div className="text-[10px] text-ink-3 truncate">
                    {variable.type}{variable.required ? " · 必填" : ""}
                  </div>
                </div>
                <input
                  className="field !py-1 font-mono"
                  value={inputMap[variable.key] ?? ""}
                  placeholder={variable.key === "query" ? "{{start.query}}" : `{{start.${variable.key}}}`}
                  onChange={(event) => setMapping(variable.key, event.target.value)}
                />
              </div>
            ))}
          </div>
          <div className="mt-2 text-[10px] text-ink-3 leading-relaxed">
            变量模板示例：{"{{start.query}}"}、{"{{chat_1.output.text}}"}、{"{{nodes.chat_1.output.text}}"}。
            留空的必填变量会按后端默认值补，仍缺失时运行返回 AGENT_INPUT_MISSING。
          </div>
        </div>
      ) : missing ? (
        <div className="mt-3 text-[11px] text-danger">引用的 Agent 不存在，重新选一个再运行。</div>
      ) : null}
    </div>
  );
}

function ConditionConfig({ node }: { node: FlowNode }) {
  const updateConfig = useFlowStore((s) => s.updateConfig);
  return (
    <div>
      <FieldLabel>条件表达式</FieldLabel>
      <textarea
        className="field font-mono min-h-[76px]"
        value={String(node.config.expression ?? "")}
        placeholder="{{chat_1.output.text}} != ''"
        onChange={(event) => updateConfig(node.id, { expression: event.target.value })}
      />
      <div className="mt-1 text-[11px] text-ink-3 leading-relaxed">
        结果转成布尔，true 走真分支，false 走假分支；两个出边都要连，运行时只走其中一条。
      </div>
      <BranchEdgesField node={node} handles={["true", "false"]} />
    </div>
  );
}

function LoopConfig({ node }: { node: FlowNode }) {
  const updateConfig = useFlowStore((s) => s.updateConfig);
  return (
    <div>
      <FieldLabel>最大轮次</FieldLabel>
      <input
        type="number"
        min={1}
        max={32}
        className="field"
        value={Number(node.config.maxRounds ?? 3)}
        onChange={(event) => updateConfig(node.id, { maxRounds: Number(event.target.value) })}
      />
      <div className="mt-3">
        <FieldLabel>退出条件（可选）</FieldLabel>
        <input
          className="field font-mono"
          value={String(node.config.exitCondition ?? "")}
          placeholder="{{chat_1.output.done}} == true"
          onChange={(event) => updateConfig(node.id, { exitCondition: event.target.value })}
        />
      </div>
      <div className="mt-1 text-[11px] text-ink-3 leading-relaxed">
        每轮先判断退出条件；为空或为假时走 body，达到上限走 done。
      </div>
      <BranchEdgesField node={node} handles={["body", "done"]} />
    </div>
  );
}

function HumanConfig({ node }: { node: FlowNode }) {
  const updateConfig = useFlowStore((s) => s.updateConfig);
  return (
    <div>
      <FieldLabel>审批提示</FieldLabel>
      <textarea
        className="field min-h-[64px]"
        value={String(node.config.message ?? "")}
        onChange={(event) => updateConfig(node.id, { message: event.target.value })}
      />
      <div className="mt-3">
        <FieldLabel>超时（秒）</FieldLabel>
        <input
          type="number"
          min={1}
          className="field"
          value={Number(node.config.timeout ?? 300)}
          onChange={(event) => updateConfig(node.id, { timeout: Number(event.target.value) })}
        />
      </div>
      <div className="mt-1 text-[11px] text-ink-3">运行时进入 waiting_human，运行面板或回放页批准后继续。</div>
    </div>
  );
}

function EndConfigField({ node }: { node: FlowNode }) {
  const updateConfig = useFlowStore((s) => s.updateConfig);
  const raw = node.config.outputs;
  const objectMode = !!raw && !Array.isArray(raw) && typeof raw === "object";
  const outputs = objectMode ? raw as Record<string, string> : [];

  const setObjectMode = (next: boolean) => {
    if (next) {
      updateConfig(node.id, { outputs: outputs && Object.keys(outputs).length > 0 ? outputs : { text: "{{chat_1.output.text}}" } });
    } else {
      updateConfig(node.id, { outputs: [] });
    }
  };

  const setEntry = (oldKey: string, key: string, value: string) => {
    const next: Record<string, string> = {};
    Object.entries(outputs).forEach(([itemKey, itemValue]) => {
      next[itemKey === oldKey ? key : itemKey] = itemKey === oldKey ? value : itemValue;
    });
    updateConfig(node.id, { outputs: next });
  };

  return (
    <div>
      <div className="flex gap-1 mb-2">
        <button
          className={`px-2 py-1 rounded-sm text-[11px] ${!objectMode ? "bg-primary text-white" : "bg-white border border-line"}`}
          onClick={() => setObjectMode(false)}
        >
          列表
        </button>
        <button
          className={`px-2 py-1 rounded-sm text-[11px] ${objectMode ? "bg-primary text-white" : "bg-white border border-line"}`}
          onClick={() => setObjectMode(true)}
        >
          对象
        </button>
      </div>
      {objectMode ? (
        <div className="space-y-1.5">
          {Object.entries(outputs).map(([key, value]) => (
            <div key={key} className="flex items-center gap-1.5">
              <input
                className="field !py-1 w-[96px] font-mono"
                value={key}
                onChange={(event) => setEntry(key, event.target.value, value)}
              />
              <input
                className="field !py-1 font-mono"
                value={value}
                placeholder="{{chat_1.output.text}}"
                onChange={(event) => setEntry(key, key, event.target.value)}
              />
              <button
                className="text-ink-3 hover:text-danger"
                onClick={() => updateConfig(node.id, { outputs: Object.fromEntries(Object.entries(outputs).filter(([item]) => item !== key)) })}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          <button
            className="btn w-full !py-1"
            onClick={() => updateConfig(node.id, { outputs: { ...outputs, [`key_${Object.keys(outputs).length + 1}`]: "" } })}
          >
            <Plus size={11} className="inline mr-1 -mt-0.5" />添加输出
          </button>
        </div>
      ) : (
        <>
          <FieldLabel>输出路径（每行一个）</FieldLabel>
          <textarea
            className="field font-mono min-h-[80px]"
            value={Array.isArray(raw) ? (raw as string[]).join("\n") : ""}
            placeholder={"chat_1.output.text\nkb_1.output.text"}
            onChange={(event) => updateConfig(node.id, {
              outputs: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean),
            })}
          />
          <div className="mt-1 text-[10px] text-ink-3">
            列表模式下 key 取路径末段；留空自动取最后一个 Agent 的 text。对象模式可自定义 key。
          </div>
        </>
      )}
    </div>
  );
}

export function ConfigPanel() {
  const flow = useFlowStore((s) => s.flow);
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const setSelected = useFlowStore((s) => s.setSelected);
  const removeNode = useFlowStore((s) => s.removeNode);
  const duplicateNode = useFlowStore((s) => s.duplicateNode);
  const byType = useNodeTypeStore((s) => s.byType);

  const node = useMemo(
    () => flow.nodes.find((item) => item.id === selectedNodeId),
    [flow.nodes, selectedNodeId],
  );

  if (!node) {
    return (
      <aside className="w-[360px] flex-shrink-0 bg-white border-l border-line overflow-y-auto p-4">
        <div className="text-[13px] font-semibold">节点配置</div>
        <div className="text-[12px] text-ink-3 mt-2 leading-relaxed">
          点选画布上的节点查看配置。流程层只有开始、Agent、分支、循环、审批、结束六类；
          提示词、模型、工具、知识库都在 Agent 库里维护。
        </div>
        <div className="mt-4 border border-dashed border-line rounded-sm p-3 text-[11px] text-ink-3 leading-relaxed">
          <div className="text-ink font-medium mb-1">变量写法</div>
          <div className="font-mono">{"{{start.query}}"}</div>
          <div className="font-mono">{"{{chat_1.output.text}}"}</div>
          <div className="font-mono">{"{{nodes.chat_1.output.text}}"}</div>
        </div>
      </aside>
    );
  }

  const spec = byType[node.type];
  return (
    <aside className="w-[360px] flex-shrink-0 bg-white border-l border-line overflow-y-auto">
      <div className="px-4 py-3 border-b border-line sticky top-0 bg-white z-10">
        <div className="flex items-center gap-2">
          <span className="node-ico" style={{ background: spec?.color ?? "#94a3b8" }}>{spec?.icon ?? "?"}</span>
          <div className="min-w-0">
            <div className="text-[13px] font-semibold">{spec?.label ?? node.type}</div>
            <div className="text-[10px] font-mono text-ink-3">{node.id}</div>
          </div>
          <div className="ml-auto flex gap-2">
            <button className="text-ink-3 hover:text-primary" title="复制节点" onClick={() => duplicateNode(node.id)}>
              <Copy size={14} />
            </button>
            <button className="text-ink-3 hover:text-danger" title="删除节点" onClick={() => { removeNode(node.id); setSelected(null); }}>
              <Trash2 size={14} />
            </button>
          </div>
        </div>
        {spec?.description && <div className="text-[11px] text-ink-3 mt-1.5 leading-relaxed">{spec.description}</div>}
      </div>

      <div className="p-4">
        {node.type === "start" && <StartConfig node={node} />}
        {node.type === "agent" && <AgentConfigField node={node} />}
        {node.type === "condition" && <ConditionConfig node={node} />}
        {node.type === "loop" && <LoopConfig node={node} />}
        {node.type === "human" && <HumanConfig node={node} />}
        {node.type === "end" && <EndConfigField node={node} />}
      </div>
    </aside>
  );
}
