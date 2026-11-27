# AgentFlow Studio · 前端

React 18 + TypeScript + Vite 6 + React Flow 12 + Zustand 5 + Tailwind。

当前是 **Agent 库 + Flow v2** 前端：

- `/agents` Agent 库、`/agents/:id` 编辑器、`/agents/:id/chat` 作用域对话。
- Flow 画布只渲染 `start / agent / condition / loop / human / end` 六类节点。
- Agent 节点支持 Agent 下拉、`inputMap` 变量映射、编辑 / 对话入口。
- 开始变量、条件 true/false、循环 body/done、审批、结束 outputs 可配置。
- 运行输入弹窗按开始节点变量收集；运行历史按 `targetType/targetId` 展示。
- SSE 实时日志 / token / 指标 / 审批，按 seq 去重。
- 旧 DSL 流程显示提示并禁用运行。

## 本地启动

```bash
npm install
npm run dev      # http://localhost:5173
```

`/api` 由 Vite proxy 转发到 `http://127.0.0.1:8000`，需先启动后端。

## 构建验证

```bash
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
```

当前通过；仅有 607 kB chunk 体积提示。
