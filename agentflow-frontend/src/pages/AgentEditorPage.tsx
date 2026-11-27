import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, CheckCircle2, Database, MessageSquare, Plug, Plus, Save, Trash2, Wrench } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { ApiError } from "@/api/client";
import { knowledgeApi, type KnowledgeBase } from "@/api/knowledge";
import { mcpApi, type MCPServer, type MCPToolInfo } from "@/api/mcp";
import { toolsApi, type ToolDef } from "@/api/tools";
import { useSettingsStore } from "@/store/settingsStore";
import {
  VARIABLE_TYPES,
  emptyVariable,
  resourceToken,
  type AgentPayload,
  type AgentResource,
  type AgentValidationResult,
  type ResourceKind,
  type VariableType,
} from "@/types/agent";

interface ResourceOption {
  id: string;
  name: string;
}

const KIND_META: Record<ResourceKind, { label: string; icon: typeof Wrench }> = {
  tool: { label: "工具", icon: Wrench },
  mcp: { label: "MCP", icon: Plug },
  knowledge: { label: "知识库", icon: Database },
};

function emptyResource(kind: ResourceKind = "tool"): AgentResource {
  return { kind, id: "", alias: "", tools: [], queryVar: "query", topK: 4, rerank: false };
}

function schemaError(value: string): string | null {
  if (!value.trim()) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? null : "Schema 必须是 JSON 对象";
  } catch {
    return "Schema 不是合法 JSON";
  }
}

export function AgentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [form, setForm] = useState<AgentPayload | null>(null);
  const [schemaText, setSchemaText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [validation, setValidation] = useState<AgentValidationResult | null>(null);

  const [tools, setTools] = useState<ToolDef[]>([]);
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [mcpTools, setMcpTools] = useState<Record<string, MCPToolInfo[]>>({});
  const [probeError, setProbeError] = useState<Record<string, string>>({});
  const [probing, setProbing] = useState<Record<string, boolean>>({});

  const models = useSettingsStore((s) => s.models);
  const loadModels = useSettingsStore((s) => s.loadModels);

  useEffect(() => {
    void loadModels();
    void Promise.all([
      toolsApi.list().then(setTools).catch(() => []),
      mcpApi.list().then(setServers).catch(() => []),
      knowledgeApi.list().then(setKnowledgeBases).catch(() => []),
    ]);
  }, [loadModels]);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    agentsApi.get(id)
      .then((agent) => {
        const payload: AgentPayload = {
          name: agent.name,
          description: agent.description,
          variables: agent.variables,
          prompt: agent.prompt,
          resources: agent.resources,
          model: agent.model,
          output: agent.output,
        };
        setForm(payload);
        setSchemaText(agent.output.schema ? JSON.stringify(agent.output.schema, null, 2) : "");
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Agent 加载失败"))
      .finally(() => setLoading(false));
  }, [id]);

  // MCP 资源选中后探测工具清单；探测失败只提示，不阻塞保存
  useEffect(() => {
    if (!form) return;
    form.resources.forEach((resource) => {
      if (resource.kind !== "mcp" || !resource.id || mcpTools[resource.id] || probing[resource.id]) return;
      setProbing((prev) => ({ ...prev, [resource.id]: true }));
      mcpApi.probe(resource.id)
        .then((result) => {
          setMcpTools((prev) => ({ ...prev, [resource.id]: result.tools }));
          if (!result.ok) setProbeError((prev) => ({ ...prev, [resource.id]: result.error ?? "MCP 探测失败" }));
        })
        .catch((err) => {
          setMcpTools((prev) => ({ ...prev, [resource.id]: [] }));
          setProbeError((prev) => ({ ...prev, [resource.id]: err instanceof Error ? err.message : "MCP 探测失败" }));
        })
        .finally(() => setProbing((prev) => ({ ...prev, [resource.id]: false })));
    });
  }, [form, mcpTools, probing]);

  const resourceOptions = useMemo(() => {
    const map: Record<ResourceKind, ResourceOption[]> = {
      tool: tools.map((tool) => ({ id: tool.id, name: tool.name })),
      mcp: servers.map((server) => ({ id: server.id, name: server.name })),
      knowledge: knowledgeBases.map((kb) => ({ id: kb.id, name: kb.name })),
    };
    return map;
  }, [tools, servers, knowledgeBases]);

  const stringVariables = form?.variables.filter((variable) => variable.type === "string") ?? [];

  const patch = (values: Partial<AgentPayload>) => {
    setForm((prev) => prev ? { ...prev, ...values } : prev);
    setDirty(true);
    setNotice(null);
  };

  const patchVariable = (index: number, values: Partial<AgentPayload["variables"][number]>) => {
    if (!form) return;
    patch({ variables: form.variables.map((item, i) => (i === index ? { ...item, ...values } : item)) });
  };

  const patchResource = (index: number, values: Partial<AgentResource>) => {
    if (!form) return;
    patch({ resources: form.resources.map((item, i) => (i === index ? { ...item, ...values } : item)) });
  };

  const changeResourceKind = (index: number, kind: ResourceKind) => {
    if (!form) return;
    patchResource(index, { ...emptyResource(kind), queryVar: stringVariables[0]?.key ?? "query" });
  };

  const changeResourceTarget = (index: number, targetId: string) => {
    if (!form) return;
    const resource = form.resources[index];
    const option = resourceOptions[resource.kind].find((item) => item.id === targetId);
    patchResource(index, { id: targetId, alias: resource.alias || option?.name || "", tools: [] });
  };

  const appendToken = (token: string) => {
    if (!form) return;
    patch({ prompt: { ...form.prompt, template: `${form.prompt.template}${form.prompt.template.endsWith("\n") ? "" : "\n"}${token}` } });
  };

  const save = async () => {
    if (!id || !form) return;
    const schemaProblem = schemaError(schemaText);
    if (schemaProblem) {
      setError(schemaProblem);
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const schema = schemaText.trim() ? JSON.parse(schemaText) as Record<string, unknown> : null;
      const payload: AgentPayload = { ...form, output: { ...form.output, schema } };
      await agentsApi.update(id, payload);
      setForm(payload);
      setDirty(false);
      setNotice("已保存");
      const runtime = await agentsApi.validateSaved(id);
      setValidation(runtime);
    } catch (err) {
      applyError(err);
    } finally {
      setSaving(false);
    }
  };

  const validate = async () => {
    if (!form) return;
    const schemaProblem = schemaError(schemaText);
    if (schemaProblem) {
      setError(schemaProblem);
      return;
    }
    setError(null);
    setNotice(null);
    try {
      const schema = schemaText.trim() ? JSON.parse(schemaText) as Record<string, unknown> : null;
      const result = await agentsApi.validateDefinition({ ...form, output: { ...form.output, schema } });
      setValidation(result);
    } catch (err) {
      applyError(err);
    }
  };

  const applyError = (err: unknown) => {
    if (err instanceof ApiError) {
      setError(`${err.message}${err.code ? `（${err.code}）` : ""}`);
      const raw = err.rawDetail as AgentValidationResult | null;
      if (raw && Array.isArray(raw.errors)) setValidation(raw);
      return;
    }
    setError(err instanceof Error ? err.message : "操作失败");
  };

  if (loading) {
    return <div className="h-full flex items-center justify-center text-[13px] text-ink-3">加载 Agent…</div>;
  }

  if (!form) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="card p-6 text-center max-w-[400px]">
          <div className="text-danger font-semibold">Agent 加载失败</div>
          <div className="text-[12px] text-ink-3 mt-1">{error ?? "Agent 不存在"}</div>
          <Link className="btn mt-4 inline-flex" to="/agents"><ArrowLeft size={13} className="inline mr-1 -mt-0.5" />返回 Agent 库</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-canvas">
      <div className="max-w-[1060px] mx-auto p-6">
        <div className="flex items-center gap-3 mb-5">
          <Link className="btn" to="/agents"><ArrowLeft size={13} className="inline mr-1 -mt-0.5" />Agent 库</Link>
          <Bot size={18} className="text-primary" />
          <input
            className="text-[18px] font-semibold bg-transparent border-b border-transparent focus:border-primary outline-none w-[320px]"
            value={form.name}
            onChange={(event) => patch({ name: event.target.value })}
          />
          <span className="chip font-mono">{id}</span>
          {dirty && <span className="text-[11px] text-warn">未保存</span>}
          <div className="ml-auto flex gap-2">
            <Link className="btn" to={`/agents/${id}/chat`}><MessageSquare size={13} className="inline mr-1 -mt-0.5" />对话调试</Link>
            <button className="btn" onClick={() => void validate()}><CheckCircle2 size={13} className="inline mr-1 -mt-0.5" />校验</button>
            <button className="btn-primary" disabled={saving} onClick={() => void save()}>
              <Save size={13} className="inline mr-1 -mt-0.5" />{saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>

        {error && <div className="border border-danger/30 bg-danger-50 text-[12px] text-danger rounded-sm px-3 py-2 mb-3">{error}</div>}
        {notice && <div className="border border-ok/30 bg-ok-50 text-[12px] text-ok rounded-sm px-3 py-2 mb-3">{notice}</div>}

        {validation && (
          <div className={`border rounded-sm px-3 py-2 mb-3 text-[12px] ${validation.valid ? "border-ok/30 bg-ok-50 text-ok" : "border-danger/30 bg-danger-50 text-danger"}`}>
            <div className="font-semibold">{validation.valid ? "校验通过" : "校验未通过"}</div>
            {validation.errors.map((issue, index) => (
              <div key={`${issue.field}-${index}`}>{issue.field ? `${issue.field}: ` : ""}{issue.message}</div>
            ))}
            {validation.warnings.map((warning, index) => <div key={`w-${index}`} className="text-warn">提示：{warning}</div>)}
          </div>
        )}

        <div className="grid grid-cols-[1fr_320px] gap-4 items-start">
          <div className="space-y-4">
            <section className="card p-4">
              <div className="section-title">基本信息</div>
              <div className="mt-3">
                <label className="block text-[12px] text-ink-2 mb-1">描述</label>
                <textarea
                  className="field min-h-[62px]"
                  value={form.description}
                  placeholder="这个 Agent 负责什么、适合放到流程的哪一步"
                  onChange={(event) => patch({ description: event.target.value })}
                />
              </div>
            </section>

            <section className="card p-4">
              <div className="flex items-center gap-2">
                <div className="section-title flex-1">输入变量</div>
                <button
                  className="btn !py-1"
                  onClick={() => patch({ variables: [...form.variables, { ...emptyVariable(`var_${form.variables.length + 1}`), required: false }] })}
                >
                  <Plus size={12} className="inline mr-1 -mt-0.5" />添加变量
                </button>
              </div>
              <div className="text-[11px] text-ink-3 mt-1 mb-2">key 只能字母/数字/下划线且不能数字开头；流程节点的 inputMap 按 key 注入。</div>
              <div className="space-y-2">
                {form.variables.map((variable, index) => (
                  <div key={index} className="border border-line rounded-sm p-2.5 bg-slate-50/50">
                    <div className="grid grid-cols-[1fr_1fr_92px_auto_auto] gap-2 items-center">
                      <input className="field !py-1 font-mono" value={variable.key} placeholder="key" onChange={(event) => patchVariable(index, { key: event.target.value })} />
                      <input className="field !py-1" value={variable.label} placeholder="展示名" onChange={(event) => patchVariable(index, { label: event.target.value })} />
                      <select className="field !py-1" value={variable.type} onChange={(event) => patchVariable(index, { type: event.target.value as VariableType })}>
                        {VARIABLE_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                      </select>
                      <label className="flex items-center gap-1 text-[11px] whitespace-nowrap">
                        <input type="checkbox" className="w-3.5 h-3.5 accent-primary" checked={variable.required} onChange={(event) => patchVariable(index, { required: event.target.checked })} />
                        必填
                      </label>
                      <button className="text-ink-3 hover:text-danger" onClick={() => patch({ variables: form.variables.filter((_, i) => i !== index) })}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                      <input className="field !py-1" value={variable.description} placeholder="说明" onChange={(event) => patchVariable(index, { description: event.target.value })} />
                      <input
                        className="field !py-1"
                        value={variable.default === null || variable.default === undefined ? "" : String(variable.default)}
                        placeholder="默认值（留空为 null）"
                        onChange={(event) => patchVariable(index, { default: event.target.value === "" ? null : event.target.value })}
                      />
                    </div>
                  </div>
                ))}
                {form.variables.length === 0 && <div className="text-[12px] text-ink-3">没有变量也可以保存：对话消息会追加到模板末尾。</div>}
              </div>
            </section>

            <section className="card p-4">
              <div className="section-title">提示词</div>
              <div className="mt-3">
                <label className="block text-[12px] text-ink-2 mb-1">System</label>
                <textarea className="field min-h-[88px]" value={form.prompt.system} onChange={(event) => patch({ prompt: { ...form.prompt, system: event.target.value } })} />
              </div>
              <div className="mt-3">
                <label className="block text-[12px] text-ink-2 mb-1">Template（用户消息 / 变量注入）</label>
                <textarea className="field font-mono min-h-[110px]" value={form.prompt.template} onChange={(event) => patch({ prompt: { ...form.prompt, template: event.target.value } })} />
              </div>
              <div className="text-[11px] text-ink-3 mt-1 leading-relaxed">
                变量写 {"{{key}}"}。资源引用要独立成 token：{"@kb[别名]"}、{"@tool[别名]"}、{"@mcp[别名.工具]"}；引用不存在的别名会在校验时失败。
              </div>
            </section>
          </div>

          <div className="space-y-4">
            <section className="card p-4">
              <div className="flex items-center gap-2">
                <div className="section-title flex-1">资源导入</div>
                <button className="btn !py-1" onClick={() => patch({ resources: [...form.resources, emptyResource()] })}>
                  <Plus size={12} className="inline mr-1 -mt-0.5" />添加
                </button>
              </div>
              <div className="space-y-2 mt-2">
                {form.resources.map((resource, index) => {
                  const Icon = KIND_META[resource.kind].icon;
                  const options = resourceOptions[resource.kind];
                  const selected = options.find((item) => item.id === resource.id);
                  const knownTools = mcpTools[resource.id] ?? [];
                  return (
                    <div key={index} className="border border-line rounded-sm p-2 bg-slate-50/50">
                      <div className="flex items-center gap-1.5">
                        <Icon size={13} className="text-primary" />
                        <select className="field !py-1 w-[72px]" value={resource.kind} onChange={(event) => changeResourceKind(index, event.target.value as ResourceKind)}>
                          {(Object.keys(KIND_META) as ResourceKind[]).map((kind) => <option key={kind} value={kind}>{KIND_META[kind].label}</option>)}
                        </select>
                        <select className="field !py-1 flex-1" value={resource.id} onChange={(event) => changeResourceTarget(index, event.target.value)}>
                          <option value="">选择{resource.kind === "knowledge" ? "知识库" : resource.kind === "mcp" ? " MCP" : "工具"}</option>
                          {options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                          {resource.id && !selected && <option value={resource.id}>{resource.id}（不存在）</option>}
                        </select>
                        <button className="text-ink-3 hover:text-danger" onClick={() => patch({ resources: form.resources.filter((_, i) => i !== index) })}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                      <div className="grid grid-cols-[1fr_auto] gap-2 mt-2">
                        <input className="field !py-1" value={resource.alias} placeholder="prompt 里的别名" onChange={(event) => patchResource(index, { alias: event.target.value })} />
                        <button className="btn !py-1" disabled={!resource.alias || !resource.id} onClick={() => appendToken(resourceToken(resource))}>
                          插入引用
                        </button>
                      </div>

                      {resource.kind === "mcp" && (
                        <div className="mt-2">
                          {probing[resource.id] && <div className="text-[11px] text-ink-3">探测 MCP 工具…</div>}
                          {probeError[resource.id] && <div className="text-[11px] text-warn">{probeError[resource.id]}</div>}
                          {!probing[resource.id] && knownTools.length > 0 && (
                            <div className="border border-line rounded-sm bg-white max-h-[116px] overflow-y-auto">
                              {knownTools.map((tool) => {
                                const checked = resource.tools.includes(tool.name);
                                return (
                                  <label key={tool.name} className="flex items-center gap-1.5 px-2 py-1 text-[11px] hover:bg-slate-50 cursor-pointer">
                                    <input
                                      type="checkbox"
                                      className="w-3.5 h-3.5 accent-primary"
                                      checked={checked}
                                      onChange={() => {
                                        const next = checked
                                          ? resource.tools.filter((item) => item !== tool.name)
                                          : [...resource.tools, tool.name];
                                        patchResource(index, { tools: next });
                                        if (next.length === 1) appendToken(`@mcp[${resource.alias || "别名"}.${tool.name}]`);
                                      }}
                                    />
                                    <span className="font-mono truncate">{tool.name}</span>
                                  </label>
                                );
                              })}
                            </div>
                          )}
                          {resource.id && !probing[resource.id] && knownTools.length === 0 && !probeError[resource.id] && (
                            <div className="text-[11px] text-ink-3">没有探测到工具，MCP 资源必须勾选至少一个工具。</div>
                          )}
                        </div>
                      )}

                      {resource.kind === "knowledge" && (
                        <div className="grid grid-cols-3 gap-1.5 mt-2">
                          <select className="field !py-1" value={resource.queryVar} onChange={(event) => patchResource(index, { queryVar: event.target.value })}>
                            {stringVariables.map((variable) => <option key={variable.key} value={variable.key}>{variable.key}</option>)}
                            {!stringVariables.some((variable) => variable.key === resource.queryVar) && <option value={resource.queryVar}>{resource.queryVar}</option>}
                          </select>
                          <input type="number" min={1} max={20} className="field !py-1" value={resource.topK} onChange={(event) => patchResource(index, { topK: Number(event.target.value) })} />
                          <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" className="w-3.5 h-3.5 accent-primary" checked={resource.rerank} onChange={(event) => patchResource(index, { rerank: event.target.checked })} />rerank</label>
                        </div>
                      )}
                    </div>
                  );
                })}
                {form.resources.length === 0 && <div className="text-[11px] text-ink-3">纯提示词 Agent 可以不导入资源；工具 / MCP / 知识库都在这里挂载。</div>}
              </div>
            </section>

            <section className="card p-4">
              <div className="section-title">模型</div>
              <div className="space-y-2 mt-2">
                <label className="block text-[12px] text-ink-2">
                  模型名（留空跟随模型设置）
                  <input className="field mt-1" list="agent-models" value={form.model.name} onChange={(event) => patch({ model: { ...form.model, name: event.target.value } })} />
                  <datalist id="agent-models">{models.map((model) => <option key={model} value={model} />)}</datalist>
                </label>
                <div className="grid grid-cols-3 gap-2">
                  <label className="block text-[11px] text-ink-2">temperature
                    <input type="number" step="0.1" min={0} max={2} className="field mt-1 !py-1" value={form.model.temperature} onChange={(event) => patch({ model: { ...form.model, temperature: Number(event.target.value) } })} />
                  </label>
                  <label className="block text-[11px] text-ink-2">maxTokens
                    <input type="number" min={1} className="field mt-1 !py-1" value={form.model.maxTokens} onChange={(event) => patch({ model: { ...form.model, maxTokens: Number(event.target.value) } })} />
                  </label>
                  <label className="block text-[11px] text-ink-2">工具轮次
                    <input type="number" min={0} max={16} className="field mt-1 !py-1" value={form.model.maxToolRounds} onChange={(event) => patch({ model: { ...form.model, maxToolRounds: Number(event.target.value) } })} />
                  </label>
                </div>
              </div>
            </section>

            <section className="card p-4">
              <div className="section-title">输出契约</div>
              <div className="mt-2">
                <label className="block text-[12px] text-ink-2 mb-1">描述</label>
                <input className="field" value={form.output.description} placeholder="说明输出文本 / 字段" onChange={(event) => patch({ output: { ...form.output, description: event.target.value } })} />
              </div>
              <div className="mt-3">
                <label className="block text-[12px] text-ink-2 mb-1">JSON Schema（可选）</label>
                <textarea
                  className="field font-mono min-h-[122px]"
                  value={schemaText}
                  placeholder={'{\n  "type": "object",\n  "properties": { "text": { "type": "string" } }\n}'}
                  onChange={(event) => { setSchemaText(event.target.value); setDirty(true); setNotice(null); }}
                />
                <div className="text-[10px] text-ink-3 mt-1">留空时输出固定为 {"{text: string}"}；填 Schema 后节点产物按字段读取。</div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
