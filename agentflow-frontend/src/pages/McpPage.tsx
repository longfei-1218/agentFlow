import { useEffect, useMemo, useState } from "react";
import { Play, Plus, RefreshCw, Server, Trash2, Wand2 } from "lucide-react";
import { mcpApi, type MCPCallResult, type MCPServer, type MCPToolInfo } from "@/api/mcp";
import { useMcpStore } from "@/store/mcpStore";

interface Draft {
  id?: string;
  name: string;
  command: string;
  argsText: string;
  env: Record<string, string>;
  cwd: string | null;
  timeoutS: number;
  enabled: boolean;
}

const EMPTY: Draft = { name: "", command: "python", argsText: "[]", env: {}, cwd: null, timeoutS: 15, enabled: true };

function sampleFromSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = (schema?.properties ?? {}) as Record<
    string,
    { type?: string; enum?: string[] }
  >;
  const sample: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(properties)) {
    if (prop.enum?.length) sample[key] = prop.enum[0];
    else if (prop.type === "number" || prop.type === "integer") sample[key] = 1;
    else if (prop.type === "boolean") sample[key] = true;
    else if (prop.type === "array") sample[key] = [];
    else sample[key] = "test";
  }
  return sample;
}

export function McpPage() {
  const servers = useMcpStore((s) => s.servers);
  const loading = useMcpStore((s) => s.loading);
  const storeError = useMcpStore((s) => s.error);
  const load = useMcpStore((s) => s.load);
  const clearProbe = useMcpStore((s) => s.clearProbe);

  const [selectedId, setSelectedId] = useState<string>("");
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [tools, setTools] = useState<MCPToolInfo[]>([]);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probeLatency, setProbeLatency] = useState<number>(0);
  const [toolName, setToolName] = useState("");
  const [argsText, setArgsText] = useState("{}");
  const [callResult, setCallResult] = useState<MCPCallResult | null>(null);

  const selected = useMemo(
    () => servers.find((server) => server.id === selectedId) ?? null,
    [servers, selectedId],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  const probe = async (server: MCPServer) => {
    setBusy(true);
    setProbeError(null);
    setCallResult(null);
    try {
      const result = await mcpApi.probe(server.id);
      setTools(result.tools);
      setProbeLatency(result.latencyMs);
      if (!result.ok) {
        setProbeError(`${result.error ?? "探测失败"}${result.code ? `（${result.code}）` : ""}`);
        setTools([]);
      } else if (result.tools.length > 0) {
        const first = result.tools[0];
        setToolName(first.name);
        setArgsText(JSON.stringify(sampleFromSchema(first.inputSchema), null, 2));
      }
    } catch (error) {
      setProbeError(error instanceof Error ? error.message : "探测失败");
      setTools([]);
    } finally {
      setBusy(false);
    }
  };

  const selectServer = (server: MCPServer) => {
    setSelectedId(server.id);
    setEditing(false);
    setProbeError(null);
    setTools([]);
    setProbeLatency(0);
    setCallResult(null);
    void probe(server);
  };

  const startCreate = () => {
    setSelectedId("");
    setEditing(true);
    setDraft(EMPTY);
    setFormError(null);
    setTools([]);
    setProbeError(null);
    setCallResult(null);
  };

  const startEdit = (server: MCPServer) => {
    setEditing(true);
    setFormError(null);
    setDraft({
      id: server.id,
      name: server.name,
      command: server.command,
      argsText: JSON.stringify(server.args ?? [], null, 2),
      env: server.env ?? {},
      cwd: server.cwd ?? null,
      timeoutS: server.timeoutS,
      enabled: server.enabled,
    });
  };

  const save = async () => {
    setFormError(null);
    let args: string[];
    try {
      const parsed = JSON.parse(draft.argsText.trim() || "[]");
      if (!Array.isArray(parsed)) throw new Error("args 必须是 JSON 数组");
      args = parsed.map((item) => String(item));
    } catch (error) {
      setFormError(`args 不是合法 JSON 数组：${(error as Error).message}`);
      return;
    }
    if (!draft.name.trim() || !draft.command.trim()) {
      setFormError("名称与启动命令必填");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        name: draft.name.trim(),
        transport: "stdio" as const,
        command: draft.command.trim(),
        args,
        env: draft.env,
        cwd: draft.cwd,
        timeoutS: draft.timeoutS,
        enabled: draft.enabled,
      };
      const saved = draft.id
        ? await mcpApi.update(draft.id, payload)
        : await mcpApi.create(payload);
      clearProbe(saved.id);
      await load(true);
      setEditing(false);
      setSelectedId(saved.id);
      setDraft(EMPTY);
      void probe(saved);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (server: MCPServer) => {
    if (!window.confirm(`删除 MCP Server ${server.name}？引用它的 mcp 节点会在运行时失败。`)) return;
    await mcpApi.remove(server.id);
    clearProbe(server.id);
    if (selectedId === server.id) {
      setSelectedId("");
      setTools([]);
      setCallResult(null);
    }
    await load(true);
  };

  const callTool = async () => {
    if (!selected || !toolName) return;
    setCallResult(null);
    setProbeError(null);
    let args: Record<string, unknown>;
    try {
      args = argsText.trim() ? JSON.parse(argsText) : {};
      if (!args || Array.isArray(args) || typeof args !== "object") {
        throw new Error("参数必须是 JSON 对象");
      }
    } catch (error) {
      setProbeError(`参数不是合法 JSON：${(error as Error).message}`);
      return;
    }
    setBusy(true);
    try {
      setCallResult(await mcpApi.call(selected.id, toolName, args));
    } catch (error) {
      setCallResult({
        ok: false,
        latencyMs: 0,
        error: error instanceof Error ? error.message : "调用失败",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-start gap-3">
        <div>
          <h1 className="text-[20px] font-semibold">MCP 服务</h1>
          <p className="text-[12px] text-ink-3 mt-1">
            注册本地 MCP Server（stdio JSON-RPC）。画布里的 mcp 节点会先 initialize 握手，再 tools/call；
            这里可以探测工具清单并单独试跑。
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="btn" onClick={() => void load(true)}>
            <RefreshCw size={13} className="inline mr-1 -mt-0.5" />刷新
          </button>
          <button className="btn-primary" onClick={startCreate}>
            <Plus size={13} className="inline mr-1 -mt-0.5" />注册 Server
          </button>
        </div>
      </div>

      {(storeError || formError) && (
        <div className="mt-3 border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">
          {storeError || formError}
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] gap-4 mt-4">
        <section className="card overflow-hidden self-start">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
            <Server size={15} className="text-ok" />
            <span className="font-semibold text-[13px]">Server 列表</span>
            <span className="badge badge-gray">{servers.length}</span>
            {loading && <span className="text-[11px] text-ink-3">加载中…</span>}
          </div>

          {servers.length === 0 ? (
            <div className="py-12 text-center text-[12px] text-ink-3 leading-relaxed">
              还没有 Server。<br />
              可以先用仓库自带的演示 server：<br />
              <span className="font-mono text-[11px]">scripts/mcp_demo_server.py</span>
            </div>
          ) : (
            <table className="w-full text-[12px]">
              <thead className="bg-slate-50 text-ink-3">
                <tr>
                  {["名称", "命令", "超时", "状态", "操作"].map((head) => (
                    <th key={head} className="text-left px-3 py-1.5 font-medium whitespace-nowrap">{head}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {servers.map((server) => (
                  <tr
                    key={server.id}
                    className={`border-t border-line cursor-pointer ${selectedId === server.id ? "bg-primary-soft" : ""}`}
                    onClick={() => selectServer(server)}
                  >
                    <td className="px-3 py-2 font-mono">{server.name}</td>
                    <td className="px-3 py-2 font-mono text-[11px] text-ink-2 break-all max-w-[220px]">
                      {server.command} {(server.args ?? []).join(" ")}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{server.timeoutS}s</td>
                    <td className="px-3 py-2">
                      {server.enabled ? <span className="badge badge-green">启用</span> : <span className="badge badge-gray">停用</span>}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button
                        className="text-ink-2 hover:text-primary mr-2"
                        onClick={(event) => {
                          event.stopPropagation();
                          startEdit(server);
                        }}
                      >
                        编辑
                      </button>
                      <button
                        className="text-danger hover:underline"
                        onClick={(event) => {
                          event.stopPropagation();
                          void remove(server);
                        }}
                      >
                        <Trash2 size={12} className="inline -mt-0.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card p-4 space-y-3">
          {editing ? (
            <>
              <div className="font-semibold text-[13px]">{draft.id ? "编辑 Server" : "注册 Server"}</div>
              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">名称</span>
                <input className="field" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="如 demo-mcp" />
              </label>
              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">启动命令</span>
                <input className="field font-mono" value={draft.command} onChange={(e) => setDraft({ ...draft, command: e.target.value })} placeholder="python / npx / uvx" />
              </label>
              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">
                  args
                  <span className="ml-1 text-ink-3">· JSON 数组，逐项传给命令</span>
                </span>
                <textarea
                  className="field min-h-[72px] font-mono"
                  value={draft.argsText}
                  onChange={(e) => setDraft({ ...draft, argsText: e.target.value })}
                  placeholder='["scripts/mcp_demo_server.py"]'
                />
              </label>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
                  超时
                  <input
                    type="number"
                    className="field !w-24 !py-1"
                    min={1}
                    max={300}
                    value={draft.timeoutS}
                    onChange={(e) => setDraft({ ...draft, timeoutS: Number(e.target.value) })}
                  />
                  秒
                </label>
                <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-primary"
                    checked={draft.enabled}
                    onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                  />
                  启用
                </label>
                <button className="btn-primary ml-auto" disabled={busy} onClick={() => void save()}>
                  保存
                </button>
                <button className="btn" onClick={() => setEditing(false)}>取消</button>
              </div>
              <div className="text-[11px] text-ink-3 leading-relaxed">
                只支持 stdio：命令由本机执行，请确认来源可信。args 里的相对路径按「后端进程的工作目录」解析。
              </div>
            </>
          ) : selected ? (
            <>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-[13px]">{selected.name}</span>
                <span className="badge badge-blue">stdio</span>
                <button className="ml-auto text-[11px] text-ink-3 hover:text-primary" onClick={() => void probe(selected)}>
                  <Wand2 size={12} className="inline mr-1" />重新探测
                </button>
              </div>
              <div className="font-mono text-[11px] text-ink-3 break-all">
                {selected.command} {(selected.args ?? []).join(" ")}
              </div>

              {probeError && (
                <div className="border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">
                  {probeError}
                </div>
              )}

              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[12px] text-ink-2">工具清单</span>
                  <span className="badge badge-gray">{tools.length}</span>
                  {probeLatency > 0 && <span className="text-[11px] text-ink-3">探测 {probeLatency} ms</span>}
                </div>
                {tools.length === 0 ? (
                  <div className="border border-dashed border-line rounded-sm py-6 text-center text-[11px] text-ink-3">
                    没有探测到工具（或还没探测）
                  </div>
                ) : (
                  <div className="border border-line rounded-sm divide-y divide-line max-h-[180px] overflow-y-auto">
                    {tools.map((tool) => (
                      <button
                        key={tool.name}
                        className={`w-full text-left px-2.5 py-1.5 hover:bg-slate-50 ${toolName === tool.name ? "bg-primary-soft" : ""}`}
                        onClick={() => {
                          setToolName(tool.name);
                          setArgsText(JSON.stringify(sampleFromSchema(tool.inputSchema), null, 2));
                          setCallResult(null);
                        }}
                      >
                        <div className="font-mono text-[12px]">{tool.name}</div>
                        <div className="text-[11px] text-ink-3 truncate">{tool.description || "—"}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">试跑参数（JSON）</span>
                <textarea
                  className="field min-h-[80px] font-mono"
                  value={argsText}
                  onChange={(e) => setArgsText(e.target.value)}
                />
              </label>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-ink-3 font-mono">{toolName || "未选工具"}</span>
                <button className="btn-primary ml-auto" disabled={busy || !toolName} onClick={() => void callTool()}>
                  <Play size={13} className="inline mr-1 -mt-0.5" />调用
                </button>
              </div>

              {callResult && (
                <div className={`rounded-sm px-3 py-2 text-[12px] ${callResult.ok ? "bg-ok-50 text-ok" : "bg-danger-50 text-danger"}`}>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{callResult.ok ? "成功" : "失败"}</span>
                    <span className="text-[11px]">{callResult.latencyMs} ms</span>
                    {callResult.code && <span className="badge badge-gray">{callResult.code}</span>}
                  </div>
                  <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[11px] text-ink-2 max-h-[160px] overflow-y-auto">
                    {callResult.ok ? String(callResult.result) : callResult.error}
                  </pre>
                </div>
              )}
            </>
          ) : (
            <div className="py-12 text-center text-[12px] text-ink-3 leading-relaxed">
              左侧选一个 Server 探测工具，或点右上「注册 Server」。
              <br />
              mcp 节点调用时会重新握手，不会复用这里的探测结果。
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
