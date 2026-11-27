import type { ReactNode } from "react";
import type { VersionDetail } from "@/types/version";

type Rec = Record<string, unknown>;

function rec(value: unknown): Rec | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Rec) : null;
}

function text(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-b border-line last:border-0 py-3">
      <div className="text-[11px] text-ink-3 mb-2">{title}</div>
      {children}
    </div>
  );
}

function AgentConfig({ snapshot }: { snapshot: Rec }) {
  const prompt = rec(snapshot.prompt) ?? {};
  const model = rec(snapshot.model) ?? {};
  const output = rec(snapshot.output) ?? {};
  const variables = Array.isArray(snapshot.variables) ? snapshot.variables : [];
  const resources = Array.isArray(snapshot.resources) ? snapshot.resources : [];

  return (
    <div>
      <Section title="提示词">
        <div className="text-[11px] text-ink-3 mb-1">System</div>
        <pre className="text-[12px] whitespace-pre-wrap break-words bg-slate-50 border border-line rounded-sm p-2 max-h-[180px] overflow-y-auto">
          {text(prompt.system, "（空）")}
        </pre>
        <div className="text-[11px] text-ink-3 mt-2 mb-1">Template</div>
        <pre className="text-[12px] whitespace-pre-wrap break-words bg-slate-50 border border-line rounded-sm p-2 max-h-[180px] overflow-y-auto">
          {text(prompt.template, "（空）")}
        </pre>
      </Section>

      <Section title={`变量（${variables.length}）`}>
        {variables.length === 0 ? (
          <div className="text-[12px] text-ink-3">没有变量</div>
        ) : (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-ink-3 text-left">
                <th className="py-1 font-normal">key</th>
                <th className="py-1 font-normal">类型</th>
                <th className="py-1 font-normal">必填</th>
                <th className="py-1 font-normal">默认值</th>
              </tr>
            </thead>
            <tbody>
              {variables.map((item, index) => {
                const variable = rec(item) ?? {};
                return (
                  <tr key={index} className="border-t border-line">
                    <td className="py-1 font-mono">{text(variable.key)}</td>
                    <td className="py-1">{text(variable.type)}</td>
                    <td className="py-1">{variable.required === false ? "否" : "是"}</td>
                    <td className="py-1 break-all">{text(variable.default)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="模型">
        <div className="text-[12px] text-ink-2">
          {text(model.name, "跟随全局默认")} · temperature {text(model.temperature)} · maxTokens {text(model.maxTokens)} · tool rounds {text(model.maxToolRounds)}
        </div>
      </Section>

      <Section title={`资源（${resources.length}）`}>
        {resources.length === 0 ? (
          <div className="text-[12px] text-ink-3">没有绑定资源</div>
        ) : (
          <ul className="space-y-1 text-[12px]">
            {resources.map((item, index) => {
              const resource = rec(item) ?? {};
              return (
                <li key={index} className="flex items-center gap-2">
                  <span className="chip">{text(resource.kind)}</span>
                  <span className="font-mono text-ink-2">{text(resource.alias)}</span>
                  <span className="text-ink-3 break-all">{text(resource.id)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title="输出">
        <div className="text-[12px] text-ink-2">{text(output.description, "无描述")}</div>
        <pre className="text-[11px] whitespace-pre-wrap break-words bg-slate-50 border border-line rounded-sm p-2 mt-1 max-h-[140px] overflow-y-auto">
          {output.schema ? JSON.stringify(output.schema, null, 2) : "（无结构化 schema）"}
        </pre>
      </Section>
    </div>
  );
}

function FlowConfig({ snapshot }: { snapshot: Rec }) {
  const nodes = Array.isArray(snapshot.nodes) ? snapshot.nodes : [];
  const edges = Array.isArray(snapshot.edges) ? snapshot.edges : [];

  return (
    <div>
      <Section title={`节点（${nodes.length}）`}>
        <div className="space-y-2">
          {nodes.map((item, index) => {
            const node = rec(item) ?? {};
            const config = rec(node.config) ?? {};
            return (
              <div key={index} className="border border-line rounded-sm p-2">
                <div className="flex items-center gap-2 text-[12px]">
                  <span className="chip">{text(node.type)}</span>
                  <span className="font-mono text-ink-2">{text(node.id)}</span>
                </div>
                <pre className="text-[11px] whitespace-pre-wrap break-words bg-slate-50 border border-line rounded-sm p-2 mt-2 max-h-[180px] overflow-y-auto">
                  {JSON.stringify(config, null, 2)}
                </pre>
              </div>
            );
          })}
        </div>
      </Section>

      <Section title={`连线（${edges.length}）`}>
        <ul className="space-y-1 text-[12px] text-ink-2">
          {edges.map((item, index) => {
            const edge = rec(item) ?? {};
            return (
              <li key={index} className="font-mono">
                {text(edge.source)} → {text(edge.target)}
                {edge.sourceHandle ? `（${text(edge.sourceHandle)}）` : ""}
              </li>
            );
          })}
        </ul>
      </Section>
    </div>
  );
}

/** 版本详情里的「配置快照」：按 Agent / 流程结构化展示，原始 JSON 折叠保留。 */
export function VersionSnapshot({ detail }: { detail: VersionDetail }) {
  const snapshot = rec(detail.snapshot) ?? {};

  return (
    <div>
      {detail.kind === "agent" ? <AgentConfig snapshot={snapshot} /> : <FlowConfig snapshot={snapshot} />}
      <details className="pt-3">
        <summary className="text-[11px] text-ink-3 cursor-pointer">原始快照 JSON</summary>
        <pre className="text-[11px] whitespace-pre-wrap break-words bg-slate-50 border border-line rounded-sm p-2 mt-2 max-h-[260px] overflow-y-auto">
          {JSON.stringify(detail.snapshot, null, 2)}
        </pre>
      </details>
    </div>
  );
}
