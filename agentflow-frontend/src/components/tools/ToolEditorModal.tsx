import { useEffect, useMemo, useState } from "react";
import { Save, X } from "lucide-react";
import type { BuiltinInfo, ToolDef, ToolPayload } from "@/api/tools";
import { useToolStore } from "@/store/toolStore";

const EMPTY_SCHEMA = { type: "object", properties: {} };

function safeJson(text: string, fallback: unknown) {
  try {
    return { ok: true as const, value: text.trim() ? JSON.parse(text) : fallback };
  } catch (error) {
    return { ok: false as const, message: `JSON 不合法：${(error as Error).message}` };
  }
}

interface Props {
  tool: ToolDef | null;
  builtins: BuiltinInfo[];
  onClose: () => void;
}

export function ToolEditorModal({ tool, builtins, onClose }: Props) {
  const save = useToolStore((s) => s.save);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"http" | "builtin">("builtin");
  const [builtin, setBuiltin] = useState<"echo" | "now" | "calc">("echo");
  const [method, setMethod] = useState("GET");
  const [url, setUrl] = useState("");
  const [headersText, setHeadersText] = useState("{}");
  const [bodyText, setBodyText] = useState("");
  const [schemaText, setSchemaText] = useState(JSON.stringify(EMPTY_SCHEMA, null, 2));
  const [timeoutMs, setTimeoutMs] = useState(5000);
  const [retries, setRetries] = useState(1);
  const [backoffMs, setBackoffMs] = useState(400);
  const [idempotency, setIdempotency] = useState<"none" | "key">("key");
  const [ttl, setTtl] = useState(600);
  const [risk, setRisk] = useState<"low" | "medium" | "high">("low");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(tool?.name ?? "");
    setDescription(tool?.description ?? "");
    setKind(tool?.kind ?? "builtin");
    setBuiltin((tool?.builtin as "echo" | "now" | "calc") ?? "echo");
    setMethod(tool?.method ?? "GET");
    setUrl(tool?.url ?? "");
    setHeadersText(JSON.stringify(tool?.headers ?? {}, null, 2));
    setBodyText(tool?.bodyTemplate ?? "");
    setSchemaText(JSON.stringify(tool?.paramsSchema ?? EMPTY_SCHEMA, null, 2));
    setTimeoutMs(tool?.timeoutMs ?? 5000);
    setRetries(tool?.retries ?? 1);
    setBackoffMs(tool?.backoffMs ?? 400);
    setIdempotency(tool?.idempotency ?? "key");
    setTtl(tool?.idempotencyTtlS ?? 600);
    setRisk(tool?.risk ?? "low");
    setEnabled(tool?.enabled ?? true);
    setError(null);
  }, [tool]);

  const builtinInfo = useMemo(
    () => builtins.find((item) => item.name === builtin),
    [builtins, builtin],
  );

  const handleSave = async () => {
    setError(null);
    if (!name.trim()) {
      setError("工具名必填：它同时是模型看到的 function name，建议用英文与下划线");
      return;
    }
    if (kind === "http" && !url.trim()) {
      setError("HTTP 工具必须填 URL（支持 {{参数}} 插值）");
      return;
    }
    const headers = safeJson(headersText, {});
    if (!headers.ok) {
      setError(headers.message);
      return;
    }
    const schema = safeJson(schemaText, EMPTY_SCHEMA);
    if (!schema.ok) {
      setError(schema.message);
      return;
    }

    const payload: ToolPayload = {
      name: name.trim(),
      description: description.trim(),
      kind,
      builtin: kind === "builtin" ? builtin : null,
      method: kind === "builtin" ? "POST" : method.toUpperCase(),
      url: kind === "builtin" ? "" : url.trim(),
      headers: headers.value as Record<string, string>,
      bodyTemplate: bodyText.trim() ? bodyText : null,
      paramsSchema: (kind === "builtin" && builtinInfo ? builtinInfo.paramsSchema : schema.value) as Record<string, unknown>,
      timeoutMs,
      retries,
      backoffMs,
      idempotency,
      idempotencyTtlS: ttl,
      risk,
      enabled,
    };

    setBusy(true);
    try {
      await save(payload, tool?.id);
      onClose();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white rounded-md shadow-xl w-full max-w-[720px] max-h-[92vh] overflow-y-auto"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center px-5 py-3 border-b border-line sticky top-0 bg-white z-10">
          <div className="text-[15px] font-semibold">{tool ? "编辑工具" : "新建工具"}</div>
          <button className="ml-auto text-ink-3 hover:text-ink" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">工具名（function name）</span>
              <input className="field" value={name} placeholder="get_weather" onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">描述（给模型看的用途说明）</span>
              <input className="field" value={description} placeholder="查询指定城市的天气" onChange={(e) => setDescription(e.target.value)} />
            </label>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <span className="text-[12px] text-ink-2">类型</span>
            {([["builtin", "内置（无需网络）"], ["http", "HTTP 接口"]] as const).map(([value, label]) => (
              <label key={value} className="flex items-center gap-1 text-[12px]">
                <input type="radio" checked={kind === value} onChange={() => setKind(value)} />
                {label}
              </label>
            ))}
            <label className="ml-auto flex items-center gap-1.5 text-[12px]">
              <input type="checkbox" className="w-4 h-4 accent-primary" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              启用
            </label>
          </div>

          {kind === "builtin" ? (
            <div className="mt-3">
              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">内置实现</span>
                <select className="field" value={builtin} onChange={(e) => setBuiltin(e.target.value as "echo" | "now" | "calc")}>
                  {builtins.map((item) => (
                    <option key={item.name} value={item.name}>{item.name} — {item.description}</option>
                  ))}
                </select>
              </label>
              <div className="mt-2 text-[11px] text-ink-3">
                参数 Schema 由后端注册表提供，不可编辑：
                <pre className="mt-1 bg-slate-50 border border-line rounded-sm p-2 overflow-auto text-[11px]">
                  {JSON.stringify(builtinInfo?.paramsSchema ?? {}, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-[110px_1fr] gap-2">
                <label className="block">
                  <span className="block mb-1 text-[12px] text-ink-2">Method</span>
                  <select className="field" value={method} onChange={(e) => setMethod(e.target.value)}>
                    {["GET", "POST", "PUT", "PATCH", "DELETE"].map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="block mb-1 text-[12px] text-ink-2">URL（支持 {"{{参数}}"} 插值）</span>
                  <input className="field font-mono" value={url} placeholder="https://api.example.com/v1/weather?city={{city}}" onChange={(e) => setUrl(e.target.value)} />
                </label>
              </div>
              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">Headers（JSON）</span>
                <textarea className="field min-h-[64px] font-mono text-[12px]" value={headersText} onChange={(e) => setHeadersText(e.target.value)} />
              </label>
              <label className="block">
                <span className="block mb-1 text-[12px] text-ink-2">Body 模板（JSON，留空则把参数原样作为 body）</span>
                <textarea className="field min-h-[64px] font-mono text-[12px]" value={bodyText} placeholder='{"city": "{{city}}"}' onChange={(e) => setBodyText(e.target.value)} />
              </label>
            </div>
          )}

          {kind === "http" && (
            <label className="block mt-3">
              <span className="block mb-1 text-[12px] text-ink-2">参数 Schema（JSON Schema，用于校验 + 给模型看）</span>
              <textarea className="field min-h-[120px] font-mono text-[12px]" value={schemaText} onChange={(e) => setSchemaText(e.target.value)} />
            </label>
          )}

          <div className="mt-3 grid grid-cols-4 gap-3">
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">超时（ms）</span>
              <input className="field" type="number" min={100} max={60000} value={timeoutMs} onChange={(e) => setTimeoutMs(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">重试次数</span>
              <input className="field" type="number" min={0} max={5} value={retries} onChange={(e) => setRetries(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">退避（ms）</span>
              <input className="field" type="number" min={0} max={5000} value={backoffMs} onChange={(e) => setBackoffMs(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">风险等级</span>
              <select className="field" value={risk} onChange={(e) => setRisk(e.target.value as "low" | "medium" | "high")}>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">幂等策略</span>
              <select className="field" value={idempotency} onChange={(e) => setIdempotency(e.target.value as "none" | "key")}>
                <option value="key">key — 同参数 TTL 内复用上次成功结果</option>
                <option value="none">none — 每次都真的执行</option>
              </select>
            </label>
            <label className="block">
              <span className="block mb-1 text-[12px] text-ink-2">幂等 TTL（秒）</span>
              <input className="field" type="number" min={0} max={86400} value={ttl} onChange={(e) => setTtl(Number(e.target.value))} />
            </label>
          </div>

          {error && <div className="mt-3 border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">{error}</div>}

          <div className="mt-4 flex justify-end gap-2">
            <button className="btn" onClick={onClose}>取消</button>
            <button className="btn-primary" disabled={busy} onClick={() => void handleSave()}>
              <Save size={13} className="inline mr-1 -mt-0.5" />{busy ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
