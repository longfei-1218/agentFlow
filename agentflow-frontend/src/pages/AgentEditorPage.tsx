import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, CheckCircle2, Database, Plug, Plus, Rocket, Save, Trash2, Wrench } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { ApiError } from "@/api/client";
import { knowledgeApi, type KnowledgeBase } from "@/api/knowledge";
import { mcpApi, type MCPServer, type MCPToolInfo } from "@/api/mcp";
import { toolsApi, type ToolDef } from "@/api/tools";
import { AgentChatPanel } from "@/components/agents/AgentChatPanel";
import { PublishDialog } from "@/components/versions/PublishDialog";
import { useSettingsStore } from "@/store/settingsStore";
import {
  VARIABLE_TYPES,
  emptyVariable,
  resourceToken,
  textToVariable,
  variableToText,
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

interface OutputVariable {
  key: string;
  type: VariableType;
  required: boolean;
}

const KIND_META: Record<ResourceKind, { label: string; icon: typeof Wrench }> = {
  tool: { label: "工具", icon: Wrench },
  mcp: { label: "MCP", icon: Plug },
  knowledge: { label: "知识库", icon: Database },
};

// 新建资源只允许 MCP / 工具；已有知识库资源仍会显示，避免编辑老 Agent 时丢配置。
const ADDABLE_KINDS: ResourceKind[] = ["tool", "mcp"];
const KEY_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

function emptyResource(kind: ResourceKind = "tool"): AgentResource {
  return { kind, id: "", alias: "", tools: [], queryVar: "query", topK: 4, rerank: false };
}

function emptyOutputVariable(index: number): OutputVariable {
  return { key: `output_${index}`, type: "string", required: false };
}

function asVariableType(value: unknown): VariableType {
  return value === "string" || value === "number" || value === "boolean" || value === "json"
    ? value
    : "json";
}

function schemaToOutputVariables(schema: Record<string, unknown> | null): OutputVariable[] {
  if (!schema) return [];
  const properties = schema.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
  const required = Array.isArray(schema.required)
    ? schema.required.filter((item): item is string => typeof item === "string")
    : [];
  return Object.entries(properties as Record<string, unknown>).map(([key, raw]) => {
    const property = raw && typeof raw === "object" && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : {};
    return { key, type: asVariableType(property.type), required: required.includes(key) };
  });
}

function outputVariablesToSchema(variables: OutputVariable[]): Record<string, unknown> | null {
  const rows = variables.filter((item) => item.key.trim());
  if (rows.length === 0) return null;
  const properties: Record<string, unknown> = {};
  for (const item of rows) {
    properties[item.key.trim()] = item.type === "json" ? { type: "object" } : { type: item.type };
  }
  const required = rows.filter((item) => item.required).map((item) => item.key.trim());
  return { type: "object", properties, ...(required.length ? { required } : {}) };
}

function outputVariablesError(variables: OutputVariable[]): string | null {
  const seen = new Set<string>();
  for (const item of variables) {
    const key = item.key.trim();
    if (!key) continue;
    if (!KEY_RE.test(key)) return `输出变量「${key}」只能使用字母、数字、下划线，且不能以数字开头`;
    if (seen.has(key)) return `输出变量「${key}」重复`;
    seen.add(key);
  }
  return null;
}

export function AgentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const [form, setForm] = useState<AgentPayload | null>(null);
  const [outputVariables, setOutputVariables] = useState<OutputVariable[]>([]);
  const [outputEdited, setOutputEdited] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [validation, setValidation] = useState<AgentValidationResult | null>(null);
  const [chatReloadToken, setChatReloadToken] = useState(0);
  // 发布指针与指纹：来自服务端列，和可编辑的 form 分开，避免保存草稿把版本号带进 DSL
  const [meta, setMeta] = useState<{ version: number; draftHash: string | null; publishedHash: string | null }>({
    version: 0,
    draftHash: null,
    publishedHash: null,
  });
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);

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
        setMeta({
          version: agent.version,
          draftHash: agent.draftHash,
          publishedHash: agent.publishedHash,
        });
        setOutputVariables(schemaToOutputVariables(agent.output.schema));
        setOutputEdited(false);
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

  const patchOutputVariable = (index: number, values: Partial<OutputVariable>) => {
    setOutputVariables((prev) => prev.map((item, i) => (i === index ? { ...item, ...values } : item)));
    setOutputEdited(true);
    setDirty(true);
    setNotice(null);
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

  const resolvedOutputSchema = () => {
    if (!form) return null;
    return outputEdited ? outputVariablesToSchema(outputVariables) : form.output.schema;
  };

  const preparePayload = (): AgentPayload | null => {
    if (!form) return null;
    const outputProblem = outputEdited ? outputVariablesError(outputVariables) : null;
    if (outputProblem) {
      setError(outputProblem);
      return null;
    }
    return {
      ...form,
      output: { ...form.output, schema: resolvedOutputSchema() },
    };
  };

  const save = async () => {
    if (!id || !form) return;
    const payload = preparePayload();
    if (!payload) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await agentsApi.update(id, payload);
      setForm(payload);
      setMeta({
        version: updated.version,
        draftHash: updated.draftHash,
        publishedHash: updated.publishedHash,
      });
      setDirty(false);
      setNotice("已保存");
      setChatReloadToken((value) => value + 1);
      const runtime = await agentsApi.validateSaved(id);
      setValidation(runtime);
    } catch (err) {
      applyError(err);
    } finally {
      setSaving(false);
    }
  };

  const publish = async (versionName: string, note: string) => {
    if (!id) return;
    if (!preparePayload()) return;
    setPublishing(true);
    setError(null);
    setNotice(null);
    try {
      // 发布取服务端已保存内容：有未保存改动时先落盘，避免发出去的快照和屏幕不一致
      if (dirty) await save();
      const published = await agentsApi.publish(id, { name: versionName, note });
      setMeta({
        version: published.version,
        draftHash: published.draftHash,
        publishedHash: published.publishedHash,
      });
      setPublishOpen(false);
      setNotice(`已发布 v${published.version}，快照与指纹已写入版本记录`);
      setChatReloadToken((value) => value + 1);
    } catch (err) {
      setPublishOpen(false);
      applyError(err);
    } finally {
      setPublishing(false);
    }
  };

  const validate = async () => {    if (!form) return;
    const payload = preparePayload();
    if (!payload) return;
    setError(null);
    setNotice(null);
    try {
      const result = await agentsApi.validateDefinition(payload);
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
    <div className="h-full flex flex-col bg-canvas">
      <div className="h-[48px] flex-shrink-0 flex items-center gap-2 px-3 bg-white border-b border-line">
        <Link className="btn !py-1" to="/agents"><ArrowLeft size={13} className="inline mr-1 -mt-0.5" />Agent 库</Link>
        <Bot size={17} className="text-primary" />
        <input
          className="text-[15px] font-semibold bg-transparent border-b border-transparent focus:border-primary outline-none min-w-[120px] flex-1"
          value={form.name}
          onChange={(event) => patch({ name: event.target.value })}
        />
        {dirty && <span className="text-[11px] text-warn whitespace-nowrap">未保存</span>}
        <Link
          className={`chip whitespace-nowrap ${meta.version > 0 ? "hover:border-primary hover:text-primary" : "!text-ink-3"}`}
          to={`/versions?kind=agent&id=${id ?? ""}`}
          title="查看该 Agent 的发布版本、配置快照与工具指纹"
        >
          {meta.version > 0 ? `v${meta.version}` : "未发布"}
        </Link>
        {meta.publishedHash && meta.draftHash !== meta.publishedHash && (
          <span className="badge-yellow whitespace-nowrap" title="草稿与发布版不一致；对话仍使用当前保存的草稿">
            有未发布改动
          </span>
        )}
        <div className="flex gap-1.5 ml-auto">
          <button className="btn !py-1" onClick={() => void validate()}><CheckCircle2 size={13} className="inline mr-1 -mt-0.5" />校验</button>
          <button className="btn !py-1" onClick={() => setPublishOpen(true)}>
            <Rocket size={13} className="inline mr-1 -mt-0.5" />发布版本
          </button>
          <button className="btn-primary !py-1" disabled={saving} onClick={() => void save()}>
            <Save size={13} className="inline mr-1 -mt-0.5" />{saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-w-0 border-r border-line">
          <AgentChatPanel
            agentId={id ?? ""}
            embedded
            reloadToken={chatReloadToken}
            beforeSend={() => dirty ? "编辑有未保存修改，请先保存再对话。" : null}
            sendWarning={dirty ? "编辑有未保存修改，发送前请先保存。" : null}
          />
        </div>

        <aside className="w-[360px] xl:w-[400px] flex-shrink-0 min-h-0 overflow-y-auto bg-canvas">
          <div className="p-3">
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

            <div className="card overflow-hidden">
          <section className="px-5 py-4 border-b border-line">
            <div className="section-title">基本信息</div>
            <div className="mt-3">
              <textarea
                className="field min-h-[62px]"
                value={form.description}
                placeholder="这个 Agent 负责什么、适合放到流程的哪一步"
                onChange={(event) => patch({ description: event.target.value })}
              />
            </div>
            <details className="mt-3 rounded-sm border border-line bg-slate-50/50 px-3 py-2">
              <summary className="cursor-pointer text-[12px] text-ink-2">模型参数（可选，留空跟随全局）</summary>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
                <label className="block text-[11px] text-ink-2 md:col-span-2">
                  模型名
                  <input className="field mt-1 !py-1" list="agent-models" value={form.model.name} onChange={(event) => patch({ model: { ...form.model, name: event.target.value } })} />
                  <datalist id="agent-models">{models.map((model) => <option key={model} value={model} />)}</datalist>
                </label>
                <label className="block text-[11px] text-ink-2">
                  temperature
                  <input type="number" step="0.1" min={0} max={2} className="field mt-1 !py-1" value={form.model.temperature} onChange={(event) => patch({ model: { ...form.model, temperature: Number(event.target.value) } })} />
                </label>
                <label className="block text-[11px] text-ink-2">
                  maxTokens
                  <input type="number" min={1} className="field mt-1 !py-1" value={form.model.maxTokens} onChange={(event) => patch({ model: { ...form.model, maxTokens: Number(event.target.value) } })} />
                </label>
                <label className="block text-[11px] text-ink-2">
                  工具轮次
                  <input type="number" min={0} max={16} className="field mt-1 !py-1" value={form.model.maxToolRounds} onChange={(event) => patch({ model: { ...form.model, maxToolRounds: Number(event.target.value) } })} />
                </label>
              </div>
            </details>
          </section>

          <section className="px-5 py-4 border-b border-line">
            <div className="section-title">提示词</div>
            <div className="mt-3">
              <label className="block text-[12px] text-ink-2 mb-1">System</label>
              <textarea className="field min-h-[96px]" value={form.prompt.system} onChange={(event) => patch({ prompt: { ...form.prompt, system: event.target.value } })} />
            </div>
            <div className="mt-3">
              <label className="block text-[12px] text-ink-2 mb-1">Template（用户消息 / 变量注入）</label>
              <textarea className="field font-mono min-h-[140px]" value={form.prompt.template} onChange={(event) => patch({ prompt: { ...form.prompt, template: event.target.value } })} />
            </div>
            <div className="text-[11px] text-ink-3 mt-1 leading-relaxed">
              变量写 {"{{key}}"}。资源引用要独立成 token：{"@kb[别名]"}、{"@tool[别名]"}、{"@mcp[别名.工具]"}；不写 token 时，工具/MCP 仍作为模型可自行选择的候选。
            </div>
          </section>

          <section className="px-5 py-4 border-b border-line">
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
            <div className="space-y-1.5">
              {form.variables.map((variable, index) => (
                <div key={index} className="flex items-center gap-1">
                  <input className="field !py-1 font-mono min-w-0 flex-[0.9] !text-[11px]" title={variable.key} value={variable.key} placeholder="变量名" onChange={(event) => patchVariable(index, { key: event.target.value })} />
                  <select
                    className="field !py-1 w-[72px] shrink-0 !text-[11px]"
                    value={variable.type}
                    onChange={(event) => {
                      const type = event.target.value as VariableType;
                      patchVariable(index, { type, default: textToVariable(type, variableToText(variable)) });
                    }}
                  >
                    {VARIABLE_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                  <input
                    className="field !py-1 min-w-0 flex-1 !text-[11px]"
                    title={variableToText(variable)}
                    value={variableToText(variable)}
                    placeholder="默认值（可选）"
                    onChange={(event) => patchVariable(index, { default: textToVariable(variable.type, event.target.value) })}
                  />
                  <label className="flex items-center gap-0.5 text-[10px] whitespace-nowrap shrink-0">
                    <input type="checkbox" className="w-3.5 h-3.5 accent-primary" checked={variable.required} onChange={(event) => patchVariable(index, { required: event.target.checked })} />
                    必填
                  </label>
                  <button className="text-ink-3 hover:text-danger shrink-0" onClick={() => patch({ variables: form.variables.filter((_, i) => i !== index) })}>
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
              {form.variables.length === 0 && <div className="text-[12px] text-ink-3">没有变量也可以保存：对话消息会追加到模板末尾。</div>}
            </div>
          </section>

          <section className="px-5 py-4 border-b border-line">
            <div className="flex items-center gap-2">
              <div className="section-title flex-1">输出契约</div>
              <button
                className="btn !py-1"
                onClick={() => {
                  setOutputVariables((prev) => [...prev, emptyOutputVariable(prev.length + 1)]);
                  setOutputEdited(true);
                  setDirty(true);
                  setNotice(null);
                }}
              >
                <Plus size={12} className="inline mr-1 -mt-0.5" />添加输出变量
              </button>
            </div>
            <div className="mt-3">
              <label className="block text-[12px] text-ink-2 mb-1">输出描述</label>
              <input className="field" value={form.output.description} placeholder="说明输出文本 / 字段" onChange={(event) => patch({ output: { ...form.output, description: event.target.value } })} />
            </div>
            <div className="text-[11px] text-ink-3 mt-3 mb-1">输出变量（可选，不填时输出固定为 {"{text: string}"}）</div>
            <div className="space-y-1.5">
              {outputVariables.map((variable, index) => (
                <div key={index} className="flex items-center gap-1">
                  <input className="field !py-1 font-mono min-w-0 flex-[0.9] !text-[11px]" title={variable.key} value={variable.key} placeholder="输出变量名" onChange={(event) => patchOutputVariable(index, { key: event.target.value })} />
                  <select className="field !py-1 w-[72px] shrink-0 !text-[11px]" value={variable.type} onChange={(event) => patchOutputVariable(index, { type: event.target.value as VariableType })}>
                    {VARIABLE_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                  <label className="flex items-center gap-0.5 text-[10px] whitespace-nowrap shrink-0">
                    <input type="checkbox" className="w-3.5 h-3.5 accent-primary" checked={variable.required} onChange={(event) => patchOutputVariable(index, { required: event.target.checked })} />
                    必填
                  </label>
                  <button
                    className="text-ink-3 hover:text-danger shrink-0"
                    onClick={() => {
                      setOutputVariables((prev) => prev.filter((_, i) => i !== index));
                      setOutputEdited(true);
                      setDirty(true);
                      setNotice(null);
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
              {outputVariables.length === 0 && <div className="text-[12px] text-ink-3">没有输出变量时，节点产物保持 {"{text: string}"}。</div>}
            </div>
          </section>

          <section className="px-5 py-4">
            <div className="flex items-center gap-2">
              <div className="section-title flex-1">资源导入（MCP &amp; 工具）</div>
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
                const kindOptions: ResourceKind[] = resource.kind === "knowledge" ? ["knowledge", ...ADDABLE_KINDS] : ADDABLE_KINDS;
                return (
                  <div key={index} className="border border-line rounded-sm p-2 bg-slate-50/50">
                    <div className="flex items-center gap-1.5">
                      <Icon size={13} className="text-primary" />
                      <select className="field !py-1 w-[78px]" value={resource.kind} onChange={(event) => changeResourceKind(index, event.target.value as ResourceKind)}>
                        {kindOptions.map((kind) => <option key={kind} value={kind}>{KIND_META[kind].label}</option>)}
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
              {form.resources.length === 0 && <div className="text-[11px] text-ink-3">纯提示词 Agent 可以不导入资源；这里默认挂 MCP 和工具，已有知识库资源仍可保留。</div>}
            </div>
          </section>
            </div>
          </div>
        </aside>
      </div>

      <PublishDialog
        open={publishOpen}
        title={`发布 ${form.name} 新版本`}
        description="发布会生成不可变配置快照，并记录配置指纹、工具指纹与代码 commit；对话仍然使用当前保存的草稿。"
        busy={publishing}
        onClose={() => setPublishOpen(false)}
        onConfirm={(versionName, note) => void publish(versionName, note)}
      />
    </div>
  );
}
