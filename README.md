# agentFlow · AgentFlow Studio

本地单用户 Web 端 Agent 编排平台。全局 Agent 库定义提示词、变量、模型、工具 / MCP / 知识库；Flow v2 只用六类编排节点引用 Agent，运行过程通过 SSE 实时展示 token、工具调用、审批与指标。

当前状态：**Flow v2 + 前端切换 + 步骤 5 收尾已完成**。后端 70 条测试通过，前端 `tsc --noEmit` 与 `vite build` 通过，真实 DeepSeek 网关已跑通单 Agent、知识库 Agent、零变量 Agent 和两 Agent 串联。

---

## 目录

```text
agentflow-backend/    FastAPI + SQLite + LangGraph
agentflow-frontend/   React + TypeScript + Vite + React Flow
docs/
  agent-refactor-plan.md    v2 最终实施记录与边界
  acceptance.md             v2 验收命令与检查表
  tool-mcp-extension-guide.md  新增工具 / MCP 与环境变量配置流程
  resource-package-architecture.md  资源包目录、导入验证与多人化边界
```

---

## 核心口径

- **Agent 是全局可复用资源**：`AgentCreate {name, description, variables, prompt{system,template}, resources, model, output}`。流程节点只存 `agentId`，不做版本锁，改 Agent 立即影响引用它的流程。
- **Agent 可以零变量**：`variables=[]` 合法。新建 Agent 默认零变量；Agent 直聊时用户消息会追加到模板末尾，不会静默丢弃。_这是步骤 5 前取消的限制。_
- **Flow v2 只有六类节点**：`start / agent / condition / loop / human / end`。`dslVersion=2`；旧 DSL 在 update / publish / validate / run 四个入口返回 `422 FLOW_DSL_LEGACY`。
- **Agent 节点显式映射**：`{agentId, inputMap}`；`inputMap` 支持 `{{start.x}}`、`{{<nodeId>.output.field}}`、`{{<nodeId>.text}}`、`{{nodes.<nodeId>.output.field}}`。必填变量未映射会在运行前被 `FLOW_INVALID` 拦截并定位到节点。
- **对话历史按作用域隔离**：`agentId + flowId + nodeId`；Agent 库直聊只有 `agentId`。每轮创建一条 `targetType=agent` 的 run。
- **Run 统一目标**：`runs.targetType=flow|agent` + `targetId`；运行历史、回放、统计都按目标展示。
- **旧 DSL 不迁移、不做前后兼容**：旧流程只用于回放；不备份、不自动迁移。

---

## 环境与启动

要求 Python 3.10+、Node.js 18+，后端 8000、前端 5173。

首次准备：

```powershell
cd agentflow-backend
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

cd ..\agentflow-frontend
npm install
```

两个终端：

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

```powershell
cd agentflow-frontend
npm run dev
```

健康检查：`GET http://localhost:8000/api/health` → `{"status":"ok","version":"1.1"}`。

> 不要在已有 `.venv` 上重跑 `python -m venv`，否则会把解释器换掉但保留旧依赖，典型报错 `ImportError: cannot import name 'Self' from 'typing'`。需要换版本时先删除 `.venv` 再重建。

---

## 页面

| 路由 | 用途 |
|---|---|
| `/agents` | Agent 库：新建、编辑、对话、删除；卡片显示变量数与资源徽标 |
| `/agents/:id` | Agent 编辑器：变量、system/template、资源导入、模型、输出契约 |
| `/agents/:id/chat` | Agent 直聊或流程节点作用域对话；支持 `?flowId=&nodeId=` |
| `/flows` | Flow 列表：新建、复制、删除、导入导出 |
| `/flows/:id` | Flow v2 画布：六类节点、Agent 下拉与 inputMap、运行输入 |
| `/runs` | 运行历史：按 Flow / Agent 目标筛选 |
| `/runs/:id` | 回放：事件时序、节点耗时、审批卡 |
| `/tools` `/mcp` `/knowledge` `/eval` | 工具、MCP、知识库、评测页 |

模型设置：右上角填 Base URL / 默认模型 / API Key，Key 只存库并回脱敏预览；未配置时运行 Agent 流程会返回 409 `LLM_NOT_CONFIGURED`。

---

## API 速览

**Agent**

- `GET/POST /api/agents`
- `GET/PUT/DELETE /api/agents/{id}`
- `POST /api/agents/validate`、`POST /api/agents/{id}/validate`
- `POST /api/agents/{id}/run`（同步调试）、`POST /api/agents/{id}/runs`（202 + SSE）

**Flow**

- `GET/POST /api/flows`、`GET/PUT/DELETE /api/flows/{id}`
- `POST /api/flows/{id}/validate`、`publish`、`run`
- `GET /api/node-types`：只返回六类节点 Schema

**Chat**

- `POST/GET /api/chat/conversations`
- `GET/DELETE /api/chat/conversations/{id}`
- `POST /api/chat/conversations/{id}/turns`：202，返回 `runId`

**Run**

- `GET /api/runs?target_type=&target_id=&flow_id=&agent_id=`
- `GET /api/runs/{id}`、`GET /api/runs/{id}/stats`、`GET /api/runs/{id}/events`
- `POST /api/runs/{id}/cancel`、`POST /api/runs/{id}/resume`

---

## 验证

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest
# 期望 70 passed

cd ..\agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
```

真实网关冒烟：

```powershell
cd agentflow-backend
.venv\Scripts\python.exe scripts\seed_v2_demo.py --smoke
```

详细验收命令、浏览器检查表和已知限制见 `docs/acceptance.md`。

---

## 已知限制

- `inputMap` 只校验路径可解析，不限制只能引用直接上游。
- Agent 资源逐条添加，MCP 工具靠探测勾选，没有批量导入。
- 运行历史不支持按名称搜索。
- Agent 实时引用无版本锁；编辑 Agent 会立即影响所有引用流程。
- 旧 DSL 只读回放，不支持编辑、发布、校验或运行。
- Flow v2 暂不支持并行扇出；分支用 condition 的 true/false 互斥边。
- 对话历史是近 6 轮 / 3000 字硬截断，不做摘要或向量记忆。
