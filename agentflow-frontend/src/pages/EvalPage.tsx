import { Activity, BarChart3, FlaskConical, ShieldCheck } from "lucide-react";

const gates = [
  { label: "任务成功率", value: "—", threshold: "≥ 0.85", hard: true },
  { label: "pass^3", value: "—", threshold: "≥ 0.70", hard: true },
  { label: "工具调用正确率", value: "—", threshold: "≥ 0.95", hard: true },
  { label: "每次成功成本", value: "—", threshold: "≤ baseline × 1.2", hard: false },
];

export function EvalPage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-[20px] font-semibold">评测回归</h1>
          <p className="text-[12px] text-ink-3 mt-1">结果 / 轨迹 / 系统三层指标，多次运行取分布而非单次 pass/fail。</p>
        </div>
        <span className="badge badge-purple">P4</span>
      </div>

      <div className="card px-4 py-3 mb-4 flex flex-wrap gap-5 text-[12px] text-ink-2">
        <span>Case 数 <b className="text-ink">—</b></span>
        <span>repeats <b className="text-ink">k=3</b></span>
        <span>Rubric 版本 <b className="text-ink">v1</b></span>
        <span>Judge 模型 <b className="text-ink">异模型族</b></span>
        <span>人工校准分歧率 <b className="text-ink">—</b></span>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-4">
        {gates.map((gate) => (
          <div key={gate.label} className="card p-4">
            <div className="flex items-center gap-2 text-[12px] text-ink-2">
              <ShieldCheck size={14} className={gate.hard ? "text-danger" : "text-warn"} />
              {gate.label}
              <span className={`badge ml-auto ${gate.hard ? "badge-red" : "badge-orange"}`}>
                {gate.hard ? "硬门禁" : "软门禁"}
              </span>
            </div>
            <div className="text-[22px] font-semibold mt-2">{gate.value}</div>
            <div className="text-[11px] text-ink-3 mt-1">{gate.threshold}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="card p-4">
          <div className="flex items-center gap-2 text-[13px] font-semibold mb-6">
            <BarChart3 size={15} className="text-info" />一致性分布（0/1/2/3 次通过）
          </div>
          <div className="h-[160px] flex items-end justify-around gap-3 opacity-40">
            {[35, 60, 90, 45].map((height, index) => (
              <div key={index} className="w-12 bg-primary rounded-t-sm" style={{ height: `${height}%` }} />
            ))}
          </div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-2 text-[13px] font-semibold mb-6">
            <Activity size={15} className="text-ok" />准确率 vs 每次成功成本（Pareto）
          </div>
          <div className="h-[160px] border border-dashed border-line rounded-sm flex items-center justify-center text-[12px] text-ink-3">
            运行评测后显示版本 / 步数档位散点
          </div>
        </div>
      </div>

      <div className="card p-4 text-[12px] text-ink-3 flex items-center gap-2">
        <FlaskConical size={15} />
        一键回归、评测集管理、失败 Run 转 Case 与报告导出将在 P4 接入后端评测 API。
      </div>
    </div>
  );
}
