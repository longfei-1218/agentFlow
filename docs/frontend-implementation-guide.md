# 前端实现步骤（AgentFlow Studio · React + TypeScript + Vite）

> 严格对齐技术设计文档 v1.1 的页面结构、交互设计与数据契约，按 P1–P5 分阶段落地，与后端字段一一对应。

---

## P1 骨架阶段：工程搭建 + 画布基础 + Flow CRUD

### 阶段目标
前端工程初始化、路由框架、编辑器三栏骨架、画布基础能力、流程 CRUD 全链路对接。

### 步骤 1：项目初始化
```bash
npm create vite@latest agentflow-frontend -- --template react-ts
cd agentflow-frontend
npm install react-router-dom zustand @xyflow/react react-hook-form zod @microsoft/fetch-event-source axios
npm install -D tailwindcss postcss autoprefixer @types/node
```
配置 Tailwind、路径别名 `@`、shadcn/ui；Vite proxy 把 `/api` 转发到 `http://localhost:8000`。

### 步骤 2：目录结构
```
src/
├── pages/              # FlowList / Editor / RunHistory / Tools / Knowledge / Eval
├── components/
│   ├── layout/         # 侧边导航、全局布局
│   ├── flow/           # 画布、节点、配置面板
│   └── ui/             # shadcn 基础组件
├── store/flowStore.ts  # Zustand 状态
├── types/flow.ts       # 与后端逐字段对齐的 DSL 类型
├── api/                # 请求封装 flow.ts / run.ts / eval.ts
└── utils/
```

### 步骤 3：类型与 API 封装
- `types/flow.ts` 完整定义 Flow DSL，与后端 Pydantic 模型逐字段对齐。
- 封装请求客户端，实现 Flow CRUD，统一错误处理与 loading。

### 步骤 4：路由与基础页面
- React Router 对应文档 8.1 六个页面：`/flows`、`/flows/:id`、`/runs`、`/tools`、`/knowledge`、`/eval`。
- 全局侧边导航布局；流程列表卡片网格、新建、删除、导入导出入口。

### 步骤 5：编辑器三栏骨架与画布基础
- 三栏：左侧节点库 / 中间画布 / 右侧配置面板。
- 集成 React Flow：拖拽、缩放、框选、MiniMap、连线。
- 拖拽添加：`onDragStart` 写 `dataTransfer`，画布 `onDrop` 用 `screenToFlowPosition` 定位。
- `flowStore` 基础结构对齐文档 8.3；画布变更防抖保存。

### 本阶段验证标准
- 六个页面路由正常切换，布局稳定。
- 可新建流程、进入编辑器，画布可增删节点与连线。
- 刷新后流程状态从后端拉取，不丢失。

---

## P2 核心执行阶段：节点体系 + 配置面板 + 运行抽屉

### 阶段目标
11 类节点注册渲染、Schema 驱动动态配置面板、运行抽屉与 SSE 实时日志。

### 步骤 1：节点注册体系（对齐 5.2）
- 定义 `NodeDefinition`：`type / label / category / color / configSchema / defaultConfig / inputs / outputs`。
- 注册表机制：新增节点仅注册一次，不改画布核心代码；左侧节点库按「基础 / 模型 / 工具 / 控制」分类渲染。

### 步骤 2：定制节点组件
- 每类节点定制 React Flow 节点组件：图标、名称、状态标识。
- 条件节点双输出 Handle（true / false）；选中态、运行中高亮态、错误态样式。

### 步骤 3：右侧动态配置面板
- 选中节点后按 `configSchema` 用 RHF + Zod 动态渲染表单。
- 变更实时写回 store，防抖同步后端；校验错误实时提示，非法字段高亮。

### 步骤 4：底部运行抽屉与 SSE 对接
- 可收起抽屉：运行 / 停止、状态指示。
- `@microsoft/fetch-event-source` 对接 SSE；按事件类型渲染不同颜色日志（节点启动 / token 流 / 工具调用 / 完成 / 失败）。
- 实时统计 token、预估成本、执行步数。

### 本阶段验证标准
- 11 类节点均可拖拽入画布，样式统一。
- 选中节点显示对应配置项，修改实时生效。
- 运行后 SSE 实时推日志，token 流式追加；失败信息正确展示不白屏。

---

## P3 工具与知识阶段：扩展节点 + 管理页面

### 阶段目标
工具 / 知识库 / MCP 管理页，补齐高级节点配置，支持 DSL 导入导出。

### 步骤 1：资源管理页面
- 工具管理：FC 工具注册、参数 Schema、启停；MCP Server 注册、传输方式、工具列表预览。
- 知识库：新建库、上传文档、分块参数、召回测试（相似度分数 + 片段）。

### 步骤 2：高级节点配置
| 节点 | 配置项 |
|---|---|
| tool / mcp | 下拉选择已注册工具、参数映射、超时/重试、异常降级说明 |
| knowledge | 选择知识库、top_k、rerank 开关 |
| skill | 选择子流程、输入输出参数映射 |
| loop | 最大轮次、退出条件表达式 |
| human | 审批提示文案、超时时间 |

### 步骤 3：DSL 导入导出
- 导出：当前 Flow JSON 下载本地文件。
- 导入：选 JSON，Schema 校验后替换画布；非法 DSL 给明确错误提示。

### 本阶段验证标准
- 可注册工具 / MCP / 知识库，并在对应节点选择使用。
- 导出 JSON 后导入，画布状态完全还原。
- 知识库可上传文档并做召回测试，展示分数与片段。

---

## P4 可靠与评测阶段：运行历史 + 人工审批 + v1.1 评测中心

### 阶段目标
运行历史回放、人工审批交互、评测指标可视化（含 pass^k、一致性分布、成本 Pareto、门禁状态）。

### 步骤 1：运行历史页面
- 记录表格按状态 / 时间 / 流程筛选；点击查看详情与事件时序回放。
- 节点维度统计耗时、token、成本。
- **失败行提供「转 Case」按钮**（`POST /api/runs/{id}/to-case`）。

### 步骤 2：人工审批交互
- 遇 `human` 节点，抽屉弹出审批卡片；同意 / 拒绝调 `resume` 继续；审批状态与结果同步日志。

### 步骤 3：评测中心页面（对齐 10.2 / 7.1）
- **评测集头部**：Case 数、`repeats=k`、Rubric 版本、Judge 模型 / Prompt 版本、温度、人工校准分歧率。
- **CI 门禁卡片**：任务成功率、pass^3、工具调用正确率（硬门禁，通过 / 阻断）；每次成功成本（软门禁，告警）；逐项显示当前值 vs 阈值。
- **主指标**：任务成功率、pass^3、工具调用正确率、每次成功成本；次指标：幻觉率、平均 Token、平均耗时、平均步数。
- **一致性分布**：同一 Case 跑 k 次的通过次数直方图（0/1/…/k 次通过的 Case 数）。
- **Pareto 图**：准确率 vs 每次成功成本散点折线，标注各版本 / 步数档位。
- **版本对比**：两次评测指标并排条形图；明细表含 pass^3、每次成功成本列。
- 一键回归（`repeats=k`）、管理评测集、导出报告（HTML/JSON）。

### 本阶段验证标准
- 可查看历史记录并回放完整事件流。
- 人工审批节点可交互，审批后流程继续。
- 评测页同时呈现 pass^3、一致性分布、成本 Pareto 与门禁状态，不只是单一成功率。

---

## P5 部署阶段：容器化打包

### 实现步骤
1. 前端 Dockerfile：多阶段构建，nginx 托管静态资源。
2. nginx 反向代理 `/api` 到后端服务。
3. `docker-compose.yml` 加入 frontend 服务；验证生产构建产物正常。

### 验证标准
- `docker compose up` 后通过 3000 端口访问完整应用。
- 前后端通信正常无跨域；刷新页面路由不 404。
