import { useEffect, useMemo, useState } from "react";
import { FlaskConical, X } from "lucide-react";
import { toolsApi, type ToolDef, type ToolTestResult } from "@/api/tools";

function sampleFromSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = (schema?.properties ?? {}) as Record<string, { type?: string; enum?: string[]; description?: string }>;
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

interface Props {
  tool: ToolDef | null;
  onClose: () => void;
}

export function ToolTestModal({ tool, onClose }: Props) {
  const [argsText, setArgsText] = useState("{}");
  const [useIdem, setUseIdem] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ToolTestResult | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    if (!tool) return;
    setResult(null);
    setParseError(null);
    setArgsText(JSON.stringify(sampleFromSchema(tool.paramsSchema), null, 2));
  }, [tool]);

  const hint = useMemo(() => {
    const schema = tool?.paramsSchema as { required?: string[] } | undefined;
    const required = schema?.required ?? [];
    return required.length ? `必填：${required.join(", ")}` : "无必填参数";
  }, [tool]);

  if (!tool) return null;

  const handleRun = async () => {
    setParseError(null);
    let args: Record<string, unknown>;
    try {
      args = argsText.trim() ? JSON.parse(argsText) : {};
      if (!args || Array.isArray(args) || typeof args !== "object") throw new Error("参数必须是 JSON 对象");
    } catch (error) {
      setParseError(`参数不是合法 JSON：${(error as Error).message}`);
      return;
    }
    setBusy(true);
    try {
      setResult(await toolsApi.test(tool.id, args, useIdem));
    } catch (error) {
      setResult({
        ok: false,
        status: "error",
        attempts: 0,
        latencyMs: 0,
        idemHit: false,
        error: error instanceof Error ? error.message : "试跑失败",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white rounded-md shadow-xl w-full max-w-[640px] max-h-[92vh] overflow-y-auto"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center px-5 py-3 border-b border-line">
          <FlaskConical size={15} className="text-ok mr-2" />
          <div className="text-[15px] font-semibold">试跑 · {tool.name}</div>
          <span className="badge badge-gray ml-2">{tool.kind}</span>
          <button className="ml-auto text-ink-3 hover:text-ink" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4">
          <div className="text-[11px] text-ink-3 mb-2">
            和运行期共用同一个执行器；只默认不查幂等缓存，所以每次都能看到真实耗时与尝试次数。
          </div>
          <textarea
            className="field min-h-[120px] font-mono text-[12px]"
            value={argsText}
            onChange={(e) => setArgsText(e.target.value)}
          />
          <div className="mt-1 flex items-center gap-3 text-[11px] text-ink-3">
            <span>{hint}</span>
            <label className="flex items-center gap-1.5 text-[12px] text-ink-2 ml-auto">
              <input
                type="checkbox"
                className="w-4 h-4 accent-primary"
                checked={useIdem}
                onChange={(e) => setUseIdem(e.target.checked)}
              />
              走幂等缓存（连点两次可看命中）
            </label>
          </div>
          {parseError && <div className="mt-2 text-[12px] text-danger">{parseError}</div>}

          <button className="btn-primary mt-3" disabled={busy} onClick={() => void handleRun()}>
            {busy ? "执行中…" : "执行一次"}
          </button>

          {result && (
            <div className="mt-4 border border-line rounded-sm">
              <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-slate-50 border-b border-line text-[12px]">
                <span className={`badge ${result.ok ? "badge-green" : "badge-red"}`}>{result.ok ? "成功" : "失败"}</span>
                <span className="text-ink-2">尝试 <b>{result.attempts}</b> 次</span>
                <span className="text-ink-2">耗时 <b>{result.latencyMs}</b> ms</span>
                {result.httpStatus != null && <span className="text-ink-2">HTTP <b>{result.httpStatus}</b></span>}
                {result.idemHit && <span className="badge badge-purple">幂等命中</span>}
                {result.code && <span className="font-mono text-ink-3">{result.code}</span>}
              </div>
              <pre className="p-3 text-[12px] font-mono whitespace-pre-wrap max-h-[240px] overflow-auto">
                {result.ok ? JSON.stringify(result.result, null, 2) : result.error}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
