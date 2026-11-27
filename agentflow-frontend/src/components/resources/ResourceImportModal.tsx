import { useState } from "react";
import { Upload, X } from "lucide-react";
import {
  resourcesApi,
  type ResourceImportKind,
  type ResourceImportResult,
} from "@/api/resources";

interface Props {
  defaultKind?: ResourceImportKind;
  allowedKinds?: ResourceImportKind[];
  onClose: () => void;
  onImported: (result: ResourceImportResult) => void;
}

const TABS: Array<{ kind: ResourceImportKind; label: string; hint: string }> = [
  {
    kind: "mcp_local",
    label: "本地 MCP 包",
    hint: "上传 zip，根目录必须有 manifest.json，entrypoint 指向包内脚本",
  },
  {
    kind: "mcp_remote",
    label: "远程 MCP",
    hint: "粘贴 manifest，transport=http + url；可选 headers 做鉴权",
  },
  {
    kind: "http_tool",
    label: "HTTP 工具",
    hint: "粘贴 manifest，声明 method/url/paramsSchema，不执行任何代码",
  },
];

const SAMPLES: Record<ResourceImportKind, string> = {
  mcp_local: "",
  mcp_remote: JSON.stringify(
    {
      schemaVersion: 1,
      kind: "mcp",
      name: "remote-mcp",
      transport: "http",
      url: "https://example.com/mcp",
      headers: { Authorization: "Bearer ${MCP_TOKEN}" },
      timeoutS: 20,
    },
    null,
    2,
  ),
  http_tool: JSON.stringify(
    {
      schemaVersion: 1,
      kind: "http_tool",
      name: "lookup_order",
      description: "按订单号查询订单状态",
      method: "GET",
      url: "https://api.example.com/orders/{{orderId}}",
      headers: { Authorization: "Bearer ${API_TOKEN}" },
      env: { API_TOKEN: "${MY_API_TOKEN}" },
      paramsSchema: {
        type: "object",
        properties: { orderId: { type: "string" } },
        required: ["orderId"],
      },
    },
    null,
    2,
  ),
};

export function ResourceImportModal({
  defaultKind = "mcp_local",
  allowedKinds,
  onClose,
  onImported,
}: Props) {
  const visibleTabs = allowedKinds ? TABS.filter((tab) => allowedKinds.includes(tab.kind)) : TABS;
  const [kind, setKind] = useState<ResourceImportKind>(defaultKind);
  const [file, setFile] = useState<File | null>(null);
  const [manifest, setManifest] = useState(SAMPLES[defaultKind]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResourceImportResult | null>(null);

  const switchKind = (next: ResourceImportKind) => {
    setKind(next);
    setError(null);
    setResult(null);
    setManifest(SAMPLES[next]);
  };

  const submit = async () => {
    setError(null);
    setResult(null);
    if (kind === "mcp_local" && !file) {
      setError("请选择 MCP zip 包");
      return;
    }
    if (kind !== "mcp_local" && !manifest.trim()) {
      setError("请粘贴 manifest JSON");
      return;
    }
    setBusy(true);
    try {
      const imported =
        kind === "mcp_local"
          ? await resourcesApi.importPackage(kind, file as File)
          : await resourcesApi.importManifest(kind, manifest);
      setResult(imported);
      if (imported.ok) onImported(imported);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white rounded-md shadow-xl w-full max-w-[760px] max-h-[92vh] overflow-y-auto"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center px-5 py-3 border-b border-line sticky top-0 bg-white z-10">
          <div className="text-[15px] font-semibold">导入外部资源</div>
          <button className="ml-auto text-ink-3 hover:text-ink" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div className="flex gap-2">
            {visibleTabs.map((tab) => (
              <button
                key={tab.kind}
                className={`px-3 py-1.5 rounded border text-[12px] ${
                  kind === tab.kind
                    ? "border-primary bg-primary-soft text-primary"
                    : "border-line text-ink-2 hover:bg-slate-50"
                }`}
                onClick={() => switchKind(tab.kind)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="text-[11px] text-ink-3">{visibleTabs.find((tab) => tab.kind === kind)?.hint}</div>

          {kind === "mcp_local" ? (
            <label className="block border border-dashed border-line rounded-sm px-4 py-6 text-center cursor-pointer hover:bg-slate-50">
              <input
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <Upload size={18} className="mx-auto text-ink-3" />
              <div className="mt-2 text-[12px] text-ink-2">{file ? file.name : "点击选择 MCP zip 包"}</div>
              <div className="mt-1 text-[11px] text-ink-3">上传后先解压到 staging，探测 tools/list 通过才安装</div>
            </label>
          ) : (
            <textarea
              className="field min-h-[260px] font-mono text-[12px]"
              value={manifest}
              onChange={(event) => setManifest(event.target.value)}
              spellCheck={false}
            />
          )}

          {error && (
            <div className="border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">{error}</div>
          )}

          {result && (
            <div
              className={`border rounded-sm px-3 py-2 text-[12px] ${
                result.ok
                  ? "border-ok/30 bg-emerald-50 text-emerald-800"
                  : "border-danger/30 bg-danger-50 text-danger"
              }`}
            >
              <div className="font-semibold">
                {result.ok ? `已安装：${result.name}` : `导入失败：${result.code ?? "RESOURCE_IMPORT_FAILED"}`}
              </div>
              {result.message && <div className="mt-1">{result.message}</div>}
              {result.ok && (
                <div className="mt-1 text-[11px]">
                  targetId={result.targetId ?? "—"}；探测到 {result.tools.length} 个工具
                  {result.packagePath ? `；目录=${result.packagePath}` : ""}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button className="btn" onClick={onClose}>关闭</button>
            <button className="btn-primary" disabled={busy} onClick={() => void submit()}>
              <Upload size={13} className="inline mr-1 -mt-0.5" />
              {busy ? "导入并验证中…" : "导入并验证"}
            </button>
          </div>

          <div className="text-[11px] text-ink-3 leading-relaxed">
            当前是简单隔离：本地 MCP 用独立子进程，zip 只解压到 staging，验证通过后移动到 users/&lt;owner&gt;/mcp；
            远程 MCP 会真实调用一次 initialize + tools/list。不要导入来源不明的可执行包。
          </div>
        </div>
      </div>
    </div>
  );
}
