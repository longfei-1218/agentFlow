import { Activity, Bot, Database, FlaskConical, GitBranch, History, Plug, Wrench } from "lucide-react";
import { NavLink } from "react-router-dom";

const groups = [
  { title: "编排", items: [
    { to: "/agents", label: "Agent 库", icon: Bot },
    { to: "/flows", label: "流程编排", icon: GitBranch },
    { to: "/versions", label: "版本管理", icon: History },
    { to: "/runs", label: "运行历史", icon: Activity },
  ] },
  { title: "资源", items: [
    { to: "/tools", label: "工具管理", icon: Wrench },
    { to: "/mcp", label: "MCP 服务", icon: Plug },
    { to: "/knowledge", label: "知识库", icon: Database },
  ] },
  { title: "质量", items: [
    { to: "/eval", label: "评测回归", icon: FlaskConical },
  ] },
];

export function Sidebar() {
  return (
    <aside className="w-[228px] flex-shrink-0 bg-side text-slate-200 flex flex-col">
      <div className="flex items-center gap-2.5 px-4 py-[18px] border-b border-side-hover">
        <div className="w-[30px] h-[30px] rounded-sm bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center text-white font-bold text-[15px]">
          AF
        </div>
        <div>
          <div className="text-[14px] font-semibold text-white">AgentFlow</div>
          <div className="text-[11px] text-slate-400">Studio · 本地原型</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {groups.map((group) => (
          <div key={group.title} className="mb-4">
            <div className="px-4 mb-1.5 text-[11px] uppercase tracking-wider text-slate-500">
              {group.title}
            </div>
            {group.items.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 mx-2 px-3 py-2 rounded-sm text-[13px] transition-colors ${
                    isActive ? "bg-primary text-white" : "text-slate-300 hover:bg-side-hover"
                  }`
                }
              >
                <Icon size={15} />
                <span>{label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="px-4 py-3 border-t border-side-hover text-[11px] text-slate-500">
        单用户本地原型 · v1.1
      </div>
    </aside>
  );
}
