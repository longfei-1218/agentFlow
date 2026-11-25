import { useCallback, useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { CheckCircle2, Save } from "lucide-react";
import { useParams } from "react-router-dom";
import { flowsApi } from "@/api/flows";
import { runsApi } from "@/api/runs";
import { FlowCanvas } from "@/components/flow/FlowCanvas";
import { ConfigPanel } from "@/components/flow/ConfigPanel";
import { Palette } from "@/components/flow/Palette";
import { RunDrawer } from "@/components/flow/RunDrawer";
import { useFlowEvents } from "@/hooks/useFlowEvents";
import { useFlowStore } from "@/store/flowStore";
import { useRunStore } from "@/store/runStore";

export function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const flow = useFlowStore((s) => s.flow);
  const dirty = useFlowStore((s) => s.dirty);
  const loading = useFlowStore((s) => s.loading);
  const validationErrors = useFlowStore((s) => s.validationErrors);
  const loadFlow = useFlowStore((s) => s.loadFlow);
  const save = useFlowStore((s) => s.save);
  const validate = useFlowStore((s) => s.validate);
  const rename = useFlowStore((s) => s.rename);

  const runId = useRunStore((s) => s.runId);
  const runStatus = useRunStore((s) => s.status);
  const reset = useRunStore((s) => s.reset);
  const setRunId = useRunStore((s) => s.setRunId);
  const setStatus = useRunStore((s) => s.setStatus);

  useFlowEvents(runId);

  useEffect(() => {
    if (id) void loadFlow(id);
  }, [id, loadFlow]);

  useEffect(() => {
    if (!dirty || !flow.id) return;
    const timer = window.setTimeout(() => void save(), 800);
    return () => window.clearTimeout(timer);
  }, [dirty, flow, save]);

  const handleRun = useCallback(async () => {
    const valid = await validate();
    if (!valid) return;
    await save();
    const run = await flowsApi.run(flow.id);
    reset();
    setRunId(run.id);
    setStatus(run.status);
  }, [validate, save, flow.id, reset, setRunId, setStatus]);

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
        <span className="chip">v{flow.version}</span>
        {dirty && <span className="text-[11px] text-warn">未保存（自动保存中…）</span>}
        {validationErrors.length > 0 && (
          <span className="text-[11px] text-danger">{validationErrors.length} 个校验问题</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button className="btn" onClick={() => void validate()}>
            <CheckCircle2 size={13} className="inline mr-1 -mt-0.5" />校验
          </button>
          <button className="btn" onClick={() => void save()}>
            <Save size={13} className="inline mr-1 -mt-0.5" />保存
          </button>
        </div>
      </div>

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
        canRun={validationErrors.length === 0}
      />
    </div>
  );
}
