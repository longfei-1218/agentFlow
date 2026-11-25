# AgentFlow Studio · 前端（P1 骨架）

React 18 + TypeScript + Vite 6 + React Flow 12 + Zustand + Tailwind。已实现：

- 六页面路由与全局侧栏布局（视觉 token 对齐 UI 设计稿）
- Flow 列表：新建 / 复制 / 删除 / 导入导出 JSON
- 编辑器三栏：节点库（11 类，按「基础/模型/工具/控制」分组）、React Flow 画布、Schema 驱动配置面板
- 画布：拖拽添加、连线、删除、缩放、MiniMap、校验状态与自动保存
- SSE 运行抽屉：实时日志 / 输出 / 指标，token 流式追加，按 seq 去重与断线续传
- 运行历史与事件回放、失败 Run 转 Case 入口

## 本地启动

```bash
npm install
npm run dev      # http://localhost:5173
```

`/api` 由 Vite proxy 转发到 `http://localhost:8000`，需先启动后端。

## 构建验证

```bash
npm run typecheck
npm run build
```

> P2 将把配置面板的表单校验切换到 RHF + Zod 完整联动，并把 `mock_runner` 产生的事件替换为真实手写 Agent Loop；P3/P4 页面当前为结构骨架。
