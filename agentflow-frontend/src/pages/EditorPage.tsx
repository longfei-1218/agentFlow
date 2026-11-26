import { useCallback, useEffect, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Rocket, Save, X } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, type ApiIssue } from "@/api/client";
import { flowsApi } from "@/api/flows";
import { runsApi } from "@/api/runs";
import { ConfigPanel } from "@/components/flow/ConfigPanel";
import { FlowCanvas } from "@/components/flow/FlowCanvas";
import { Palette } from "@/components/flow/Palette";
import { RunDrawer } from "@/components/flow/RunDrawer";
import { useFlowEvents } from "@/hooks/useFlowEvents";
import { useFlowStore } from "@/store/flowStore";
import { useRunStore } from "@/store/runStore";
import { useLlmConfigured, useSettingsStore } from "@/store/settingsStore";

interface ActionError {
  message: string;
  issues: ApiIssue[];
}

export function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [issueOpen, setIssueOpen] = useState(false);
  const [actionError, setActionError] = useState<ActionError | null>(null);

  const flow = useFlowStore((s) => s.flow);
  const dirty = useFlowStore((s) => s.dirty);
  const loading = useFlowStore((s) => s.loading);
  const loadError = useFlowStore((s) => s.loadError);
  const lastSavedAt = useFlowStore((s) => s.lastSavedAt);
  const validationErrors = useFlowStore((s) => s.validationErrors);
  const loadFlow = useFlowStore((s) => s.loadFlow);
  const save = useFlowStore((s) => s.save);
  const publish = useFlowStore((s) => s.publish);
  const validate = useFlowStore((s) => s.validate);
  const rename = useFlowStore((s) => s.rename);
  const setSelected = useFlowStore((s) => s.setSelected);

  const runId = useRunStore((s) => s.runId);
  const runStatus = useRunStore((s) => s.status);
  const reset = useRunStore((s) => s.reset);
  const setRunId = useRunStore((s) => s.setRunId);
  const setStatus = useRunStore((s) => s.setStatus);

  const openSettings = useSettingsStore((s) => s.openModal);
  const llmConfigured = useLlmConfigured();

  useFlowEvents(runId);

  useEffect(() => {
    if (id) void loadFlow(id);
  }, [id, loadFlow]);

  // 自动保存：后端 PUT 只写内容不递增 version，所以可以放心防抖保存
  useEffect(() => {
    if (!dirty || !flow.id) return;
    const timer = window.setTimeout(() => {
      void save().catch((error: unknown) => {
        setActionError({
          message: error instanceof Error ? error.message : "自动保存失败",
          issues: error instanceof ApiError ? error.detail : [],
        });
      });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [dirty, flow, save]);

  // 窗口重新获得焦点时同步一次：别的标签页/后端改过这条流程，就把本地刷成最新的
  // （有未保存改动时不动，避免吞掉用户正在编辑的内容）
  useEffect(() => {
    const onFocus = async () => {
      if (!flow.id || dirty) return;
      try {
        const latest = await flowsApi.get(flow.id);
        if (latest.updatedAt !== flow.updatedAt) void loadFlow(flow.id);
      } catch {
        // 拿不到就算了，下次操作还有 409 兜底
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [flow.id, flow.updatedAt, dirty, loadFlow]);

  const handleRun = useCallback(async () => {
    setActionError(null);
    const valid = await validate();
    if (!valid) {
      setIssueOpen(true);
      return;
    }
    try {
      // 只在有改动时保存：没动过的旧标签页直接跑服务端版本，
      // 否则它会把这里早已修好的配置（比如节点模型）原样覆盖回去
      if (dirty) await save();
      const run = await flowsApi.run(flow.id);
      reset();
      setRunId(run.id);
      setStatus(run.status);
    } catch (error) {
      if (error instanceof ApiError) {
        setActionError({ message: error.message, issues: error.detail });
        if (error.detail.length > 0) setIssueOpen(true);
        if (error.code === "LLM_NOT_CONFIGURED") openSettings();
        return;
      }
      setActionError({ message: "运行请求失败", issues: [] });
    }
  }, [validate, save, flow.id, dirty, reset, setRunId, setStatus, openSettings]);

  const handlePublish = async () => {
    setActionError(null);
    try {
      await publish();
      setIssueOpen(false);
    } catch (error) {
      if (error instanceof ApiError) {
        setActionError({ message: error.message, issues: error.detail });
        if (error.detail.length > 0) setIssueOpen(true);
        return;
      }
      setActionError({ message: "发布失败", issues: [] });
    }
  };

  const handleCancel = async () => {
    if (!runId) return;
    const run = await runsApi.cancel(runId);
    setStatus(run.status);
  };

  const handleApprove = async (approved: boolean) => {
    if (!runId) return;
    const run = await runsApi.resume(runId, approved);
    setStatus(run.status);
  };

  if (loadError) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="card p-6 max-w-[440px] text-center">
          <AlertTriangle className="mx-auto text-warn" size={22} />
          <div className="text-[14px] font-semibold mt-2">流程加载失败</div>
          <div className="text-[12px] text-ink-3 mt-1 break-all">{loadError}</div>
          <div className="flex gap-2 justify-center mt-4">
            <button className="btn" onClick={() => navigate("/flows")}>
              <ArrowLeft size={13} className="inline mr-1 -mt-0.5" />返回列表
            </button>
            <button className="btn-primary" onClick={() => void loadFlow(flow.id || (id as string))}>
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (loading || !flow.id) {
    return <div className="h-full flex items-center justify-center text-[13px] text-ink-3">加载流程中…</div>;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="h-[46px] flex-shrink-0 flex items-center gap-3 px-4 bg-white border-b border-line">
        <input
          className="text-[14px] font-semibold border-b border-transparent focus:border-primary outline-none w-[240px]"
          value={flow.name}
          onChange={(event) => rename(event.target.value)}
        />
        <span className="chip" title="发布版本：只有发布才 +1，自动保存不会变动">v{flow.version}</span>
        {!llmConfigured && (
          <button className="chip !text-warn !border-warn/40" onClick={openSettings} title="没有 API Key，含 llm 节点的流程无法运行">
            未配置模型 · 点此设置
          </button>
        )}
        {dirty ? (
          <span className="text-[11px] text-warn">自动保存中…</span>
        ) : (
          lastSavedAt && (
            <span className="text-[11px] text-ink-3">
              已保存 {new Date(lastSavedAt).toLocaleTimeString("zh-CN", { hour12: false })}
            </span>
          )
        )}
        {validationErrors.length > 0 && (
          <button className="text-[11px] text-danger hover:underline" onClick={() => setIssueOpen((value) => !value)}>
            {validationErrors.length} 个校验问题
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button className="btn" onClick={() => void validate().then(() => setIssueOpen(true))}>
            <CheckCircle2 size={13} className="inline mr-1 -mt-0.5" />校验
          </button>
          <button className="btn" onClick={() => void save()}>
            <Save size={13} className="inline mr-1 -mt-0.5" />保存草稿
          </button>
          <button className="btn-primary" onClick={() => void handlePublish()}>
            <Rocket size={13} className="inline mr-1 -mt-0.5" />发布
          </button>
        </div>
      </div>

      {actionError && (
        <div className="flex-shrink-0 border-b border-danger/30 bg-danger-50 px-4 py-2 flex items-start gap-2">
          <AlertTriangle size={14} className="text-danger mt-0.5" />
          <div className="text-[12px] text-danger flex-1">
            <b>{actionError.message}</b>
            {actionError.issues.length > 0 && (
              <ul className="list-disc pl-4 mt-1 space-y-0.5">
                {actionError.issues.map((issue, index) => (
                  <li key={index}>{issue.message}</li>
                ))}
              </ul>
            )}
          </div>
          <button className="text-ink-3 hover:text-ink" onClick={() => setActionError(null)}>
            <X size={14} />
          </button>
        </div>
      )}

      {issueOpen && validationErrors.length > 0 && (
        <div className="flex-shrink-0 border-b border-line bg-slate-50 px-4 py-2 max-h-[132px] overflow-y-auto">
          <div className="text-[11px] text-ink-3 mb-1">点击问题可定位到节点</div>
          <ul className="space-y-0.5">
            {validationErrors.map((issue, index) => (
              <li key={index}>
                <button
                  className="text-[12px] text-left hover:text-primary"
                  onClick={() => issue.nodeId && setSelected(issue.nodeId)}
                >
                  {issue.nodeId && <span className="font-mono text-info mr-2">{issue.nodeId}</span>}
                  <span className="text-danger">{issue.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        <Palette />
        <ReactFlowProvider>
          <FlowCanvas />
        </ReactFlowProvider>
        <ConfigPanel />
      </div>

      <RunDrawer
        onRun={() => void handleRun()}
        onCancel={() => void handleCancel()}
        onApprove={(approved) => void handleApprove(approved)}
        canRun={runStatus === "pending" || runStatus === "succeeded" || runStatus === "failed" || runStatus === "cancelled"}
      />
    </div>
  );
}
