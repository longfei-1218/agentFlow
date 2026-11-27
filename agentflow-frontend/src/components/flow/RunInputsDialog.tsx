import { useEffect, useMemo, useState } from "react";
import { Play, X } from "lucide-react";
import { startVariables, type Flow } from "@/types/flow";
import type { AgentVariable } from "@/types/agent";

interface Props {
  open: boolean;
  flow: Flow;
  busy?: boolean;
  onClose: () => void;
  onRun: (inputs: Record<string, unknown>) => void;
}

function initialText(variable: AgentVariable | ReturnType<typeof startVariables>[number]): string {
  const value = variable.default;
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function parseValue(type: string, text: string): unknown {
  if (text === "") return null;
  if (type === "number") {
    const value = Number(text);
    return Number.isNaN(value) ? text : value;
  }
  if (type === "boolean") return text === "true";
  if (type === "json") {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

/** 运行前收集开始节点声明的变量。必填项为空时直接拦住，避免后端返回 AGENT_INPUT_MISSING 再回来补。 */
export function RunInputsDialog({ open, flow, busy, onClose, onRun }: Props) {
  const startNode = flow.nodes.find((node) => node.type === "start");
  const variables = useMemo(
    () => startVariables(startNode?.config ?? {}),
    [startNode?.config],
  );
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    const next: Record<string, string> = {};
    variables.forEach((variable) => {
      next[variable.key] = initialText(variable);
    });
    setValues(next);
  }, [open, variables]);

  if (!open) return null;

  const missing = variables.filter((variable) => variable.required && !values[variable.key]?.trim());

  const submit = () => {
    if (missing.length > 0) return;
    const payload: Record<string, unknown> = {};
    variables.forEach((variable) => {
      const value = parseValue(variable.type, values[variable.key] ?? "");
      if (value !== null) payload[variable.key] = value;
    });
    onRun(payload);
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-6">
      <div className="bg-white rounded-md shadow-xl w-[520px] max-h-[86vh] flex flex-col">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-line">
          <Play size={15} className="text-primary" />
          <span className="font-semibold text-[14px]">运行流程</span>
          <span className="text-[11px] text-ink-3 font-mono">{flow.name}</span>
          <button className="ml-auto text-ink-3 hover:text-ink" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {!startNode ? (
            <div className="text-[12px] text-danger">流程缺少开始节点，先拖一个「开始」并连接下游。</div>
          ) : variables.length === 0 ? (
            <div className="text-[12px] text-ink-3">开始节点没有声明变量，本次以空输入运行。</div>
          ) : (
            <div className="space-y-3">
              {variables.map((variable) => (
                <div key={variable.key}>
                  <label className="flex items-center gap-2 mb-1 text-[12px] text-ink-2">
                    <span className="font-mono">{variable.key}</span>
                    {variable.label && <span className="text-ink-3">{variable.label}</span>}
                    {variable.required && <span className="text-danger">*</span>}
                    <span className="ml-auto text-[10px] text-ink-3">{variable.type}</span>
                  </label>
                  {variable.type === "boolean" ? (
                    <select
                      className="field"
                      value={values[variable.key] ?? ""}
                      onChange={(event) => setValues((prev) => ({ ...prev, [variable.key]: event.target.value }))}
                    >
                      <option value="">（未填）</option>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  ) : variable.type === "json" ? (
                    <textarea
                      className="field font-mono min-h-[64px]"
                      value={values[variable.key] ?? ""}
                      placeholder='{"key": "value"}'
                      onChange={(event) => setValues((prev) => ({ ...prev, [variable.key]: event.target.value }))}
                    />
                  ) : (
                    <input
                      className="field"
                      type={variable.type === "number" ? "number" : "text"}
                      value={values[variable.key] ?? ""}
                      placeholder={variable.description || variable.key}
                      onChange={(event) => setValues((prev) => ({ ...prev, [variable.key]: event.target.value }))}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
          {missing.length > 0 && (
            <div className="mt-3 text-[11px] text-danger">还有必填变量没填：{missing.map((item) => item.key).join("、")}</div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-line flex justify-end gap-2">
          <button className="btn" onClick={onClose}>取消</button>
          <button
            className="btn-primary"
            disabled={!!busy || !startNode || missing.length > 0}
            onClick={submit}
          >
            <Play size={13} className="inline mr-1 -mt-0.5" />{busy ? "提交中…" : "开始运行"}
          </button>
        </div>
      </div>
    </div>
  );
}
