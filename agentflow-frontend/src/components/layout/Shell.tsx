import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { LlmSettingsModal } from "@/components/settings/LlmSettingsModal";
import { useNodeTypeStore } from "@/store/nodeTypeStore";
import { useSettingsStore } from "@/store/settingsStore";
import { useToolStore } from "@/store/toolStore";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function Shell() {
  const loadNodeTypes = useNodeTypeStore((s) => s.load);
  const refreshSettings = useSettingsStore((s) => s.refresh);
  const loadTools = useToolStore((s) => s.load);

  // 节点定义、模型配置、工具清单都是「全局一次」的资源，进应用就拉，切页面不重复请求
  useEffect(() => {
    void loadNodeTypes();
    void refreshSettings();
    void loadTools();
  }, [loadNodeTypes, refreshSettings, loadTools]);

  return (
    <div className="flex h-screen bg-bg">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <Topbar />
        <main className="flex-1 min-h-0 overflow-hidden">
          <Outlet />
        </main>
      </div>
      <LlmSettingsModal />
    </div>
  );
}
