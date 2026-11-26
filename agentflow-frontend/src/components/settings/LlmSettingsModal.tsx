import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { useSettingsStore } from "@/store/settingsStore";

type Feedback = { kind: "ok" | "error"; text: string } | null;

export function LlmSettingsModal() {
  const open = useSettingsStore((s) => s.open);
  const view = useSettingsStore((s) => s.view);
  const loading = useSettingsStore((s) => s.loading);
  const error = useSettingsStore((s) => s.error);
  const models = useSettingsStore((s) => s.models);
  const close = useSettingsStore((s) => s.closeModal);
  const refresh = useSettingsStore((s) => s.refresh);
  const loadModels = useSettingsStore((s) => s.loadModels);
  const save = useSettingsStore((s) => s.save);
  const test = useSettingsStore((s) => s.test);

  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [temperature, setTemperature] = useState("0.7");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);

  useEffect(() => {
    if (!open) return;
    setFeedback(null);
    void refresh();
    void loadModels();
  }, [open, refresh, loadModels]);

  useEffect(() => {
    if (!open || !view) return;
    setBaseUrl(view.baseUrl);
    setModel(view.model);
    setTemperature(String(view.temperature));
    setApiKey("");
  }, [open, view]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  const patch = () => ({
    baseUrl: baseUrl.trim(),
    model: model.trim(),
    temperature: Number(temperature) || 0,
    // 留空 = 不修改已存 Key（避免误清空）；要清空有单独按钮
    ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
  });

  const handleTest = async () => {
    setBusy("test");
    setFeedback(null);
    try {
      const result = await test(patch());
      setFeedback({
        kind: result.ok ? "ok" : "error",
        text: `${result.message}（${result.latencyMs} ms）`,
      });
    } catch (err) {
      setFeedback({ kind: "error", text: err instanceof Error ? err.message : "测试失败" });
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    setBusy("save");
    setFeedback(null);
    try {
      const saved = await save(patch());
      setApiKey("");
      setFeedback({
        kind: "ok",
        text: saved.configured ? "已保存，运行时会用这份配置" : "已保存，但 API Key 为空，仍然无法运行模型节点",
      });
    } catch (err) {
      setFeedback({ kind: "error", text: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setBusy(null);
    }
  };

  const handleClearKey = async () => {
    setBusy("save");
    try {
      const saved = await save({ apiKey: "" });
      setFeedback({ kind: saved.configured ? "error" : "ok", text: saved.configured ? "已清空库里的 Key，将回落到 .env" : "已清空 API Key" });
    } catch (err) {
      setFeedback({ kind: "error", text: err instanceof Error ? err.message : "清空失败" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={close}>
      <div
        className="card w-[480px] max-h-[90vh] overflow-y-auto p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-1">
          <div className="text-[15px] font-semibold">模型设置</div>
          <button className="text-ink-3 hover:text-ink" onClick={close}><X size={16} /></button>
        </div>
        <div className="text-[11px] text-ink-3 mb-4 leading-relaxed">
          OpenAI 兼容接口。Key 只存在后端数据库，界面只回脱敏预览；这里的配置优先于 <span className="font-mono">.env</span>。
        </div>

        <label className="block mb-3">
          <span className="block mb-1 text-[12px] text-ink-2">Base URL</span>
          <input className="field font-mono" value={baseUrl} placeholder="https://api.openai.com/v1" onChange={(e) => setBaseUrl(e.target.value)} />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block mb-3">
            <span className="block mb-1 text-[12px] text-ink-2">默认模型</span>
            <input
              className="field"
              list="llm-model-options"
              value={model}
              placeholder="gpt-4o-mini"
              onChange={(e) => setModel(e.target.value)}
            />
            <datalist id="llm-model-options">
              {models.map((item) => <option key={item} value={item} />)}
            </datalist>
            {models.length > 0 && model && !models.includes(model) && (
              <span className="block mt-1 text-[11px] text-warn">
                该网关支持：{models.slice(0, 4).join(" / ")}{models.length > 4 ? " …" : ""}
              </span>
            )}
          </label>
          <label className="block mb-3">
            <span className="block mb-1 text-[12px] text-ink-2">Temperature</span>
            <input className="field" type="number" min={0} max={2} step={0.1} value={temperature} onChange={(e) => setTemperature(e.target.value)} />
          </label>
        </div>

        <label className="block mb-2">
          <span className="block mb-1 text-[12px] text-ink-2">
            API Key
            {view?.hasApiKey && (
              <span className="ml-1 text-ink-3">· 已存 {view.apiKeyPreview}，留空则不修改</span>
            )}
          </span>
          <input
            className="field font-mono"
            type="password"
            value={apiKey}
            placeholder={view?.hasApiKey ? "留空保持不变" : "sk-..."}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </label>

        {view?.hasApiKey && (
          <button className="text-[11px] text-danger hover:underline mb-2" onClick={() => void handleClearKey()} disabled={busy !== null}>
            清除已保存的 Key
          </button>
        )}

        {(feedback || error) && (
          <div
            className={`mt-2 flex items-start gap-2 rounded-sm border px-3 py-2 text-[12px] ${
              feedback?.kind === "error"
                ? "border-danger/30 bg-danger-50 text-danger"
                : "border-ok/30 bg-emerald-50 text-ok"
            }`}
          >
            {feedback?.kind === "error" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
            <span className="break-all">{feedback?.text ?? error}</span>
          </div>
        )}

        <div className="text-[11px] text-ink-3 mt-3 leading-relaxed">
          没有真实 Key 时，可先跑本地假模型：<span className="font-mono">python -m uvicorn tools.fake_llm:app --port 8899</span>，
          再把 Base URL 填成 <span className="font-mono">http://127.0.0.1:8899/v1</span>、Key 填任意非空、模型填 <span className="font-mono">fake-model</span>。
        </div>

        <div className="flex items-center gap-2 mt-4">
          <span className="text-[11px] text-ink-3">
            {loading ? "读取中…" : view?.source === "db" ? "来源：界面配置" : view?.source === "env" ? "来源：.env" : "来源：未配置"}
          </span>
          <button className="btn ml-auto" onClick={() => void handleTest()} disabled={busy !== null}>
            {busy === "test" ? "测试中…" : "测试连接"}
          </button>
          <button className="btn-primary" onClick={() => void handleSave()} disabled={busy !== null}>
            {busy === "save" ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
