# 前端实现指南（AgentFlow Studio v2）

> 当前口径：React 18 + TypeScript + Vite + React Flow。前端已切到 **Agent 库 + Flow v2 六类编排节点**；不再提供流程内直接编辑提示词、模型、工具、MCP、知识库节点的旧界面。

## 1. 路由

| 路由 | 页面 |
|---|---|
| `/agents` | Agent 库 |
| `/agents/:id` | Agent 编辑器 |
| `/agents/:id/chat` | Agent 直聊 / 节点作用域对话（`?flowId=&nodeId=`） |
| `/flows` | Flow 列表 |
| `/flows/:id` | Flow v2 画布 |
| `/runs` | 运行历史（Flow / Agent 目标） |
| `/runs/:id` | 运行回放 |
| `/tools` `/mcp` `/knowledge` `/eval` | 资源库与评测 |

侧栏分组：编排（Agent 库 / 流程编排 / 运行历史）、资源（工具 / MCP / 知识库）、质量（评测回归）。

## 2. 核心模块

```text
src/
  types/agent.ts          Agent 变量 / 资源 / 模型 / 输出契约
  types/flow.ts           Flow v2 六类节点、inputMap、end outputs
  types/run.ts            targetType / targetId
  api/agents.ts           Agent CRUD / validate / run
  api/chat.ts             Agent 作用域会话与 turns
  api/flows.ts            Flow CRUD / validate / run
  api/runs.ts             Run 查询 / SSE / cancel / resume
  pages/AgentsPage.tsx
  pages/AgentEditorPage.tsx
  pages/AgentChatPage.tsx
  pages/FlowListPage.tsx
  pages/EditorPage.tsx
  pages/RunsPage.tsx
  pages/RunReplayPage.tsx
  components/flow/Palette.tsx
  components/flow/ConfigPanel.tsx
  components/flow/RunInputsDialog.tsx
  store/flowStore.ts
```

## 3. Agent 库与编辑器

- 新建 Agent 默认 **零变量**，保存合法；需要结构化输入时再添加变量。
- 变量 key 必须满足 `^[a-zA-Z_][a-zA-Z0-9_]*$`；类型支持 string / number / boolean / json。
- Template 中使用 `{{key}}`；资源引用必须独立成 token：`@kb[别名]`、`@tool[别名]`、`@mcp[别名.工具]`。
- 资源导入逐条添加：
  - 工具：选注册工具，填别名；
  - MCP：选 Server，探测工具后勾选至少一个；
  - 知识库：选库，指定 `queryVar`（必须在变量里）、topK、rerank。
- 保存后调用 `POST /agents/{id}/validate` 做运行时资源校验；`AGENT_INVALID` 的 `detail` 是对象，使用 `ApiError.rawDetail` 读取。
- 编辑器零变量提示为「没有变量也可以保存：对话消息会追加到模板末尾」，不阻塞保存。

## 4. Agent 对话

- 会话作用域：`agentId`，或 `agentId + flowId + nodeId`；同一 Agent 在不同流程节点各自独立历史。
- 对话变量选择：优先 `query`，否则第一个 `string` 变量；都没有时不阻止发送。
- 零变量 / 模板未引用聊天变量时，后端把用户消息追加到模板末尾；前端输入框和发送按钮保持可用。
- 每轮创建一条 `targetType=agent` 的 run；前端订阅该 run 的 SSE，token 只追加到当前会话当前消息。
- React StrictMode 下会话初始化用 `initializingRef` 串行，避免 `list(0) + create` 创建两条空会话。

## 5. Flow v2 画布

- Palette 只使用后端 `GET /api/node-types` 下发的六类：`start / agent / condition / loop / human / end`。
- Agent 节点配置：
  - Agent 下拉；
  - `inputMap` 左列是 Agent 变量，右列写流程路径表达式；
  - 「编辑 Agent」「对话」入口带 `flowId/nodeId`。
- 条件节点：表达式 + true/false 出边。
- 循环节点：`maxRounds`、`exitCondition`、body/done 出边。
- 审批节点：message、timeout。
- 结束节点：outputs 列表或对象。
- 运行前弹 `RunInputsDialog`，按开始节点变量收集输入。
- `flowToNodes` 对全零坐标的演示/导入流程按数组顺序横向铺开，仅展示层兜底；用户拖动后写回真实坐标。
- 旧 DSL 流程显示黄色提示并禁用运行。

## 6. 运行历史与回放

- 列表按 `targetType/targetId` 展示 Flow 或 Agent；Agent 不伪造 flowVersion。
- Flow 跳 `/flows/:id`，Agent 跳 `/agents/:id`。
- 回放复用 SSE / 指标 / 审批卡，事件按 seq 展示。

## 7. 构建与验证

```powershell
cd agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
```

当前通过；Vite 仅有 607 kB chunk 体积提示。

## 8. 已知限制

- `inputMap` 不限制只能引用直接上游。
- 资源无批量导入。
- 运行历史不支持名称搜索。
- 旧 DSL 只读回放。
- 无版本锁；编辑 Agent 立即影响引用流程。
