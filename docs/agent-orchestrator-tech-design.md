# AgentFlow Studio — v2 技术设计

> 本地单用户原型：React + TypeScript + Vite 前端，FastAPI + SQLite + LangGraph 后端。
> 当前架构：**全局 Agent 库 + Flow v2 六类编排节点 + 目标化 Run + Agent 作用域对话**。

## 1. 定位与范围

一个本地 Web 应用：在 Agent 库里维护提示词、变量、模型、工具 / MCP / 知识库；在 Flow 画布上编排 `start / agent / condition / loop / human / end`；运行时通过 SSE 观察 token、工具调用、审批、指标；用运行历史回放。

范围外：多租户、账号体系、Agent 发布/版本锁、旧流程自动迁移、远程 MCP transport、向量检索、生产级权限与部署。

## 2. 架构

```text
Frontend (React)
  Agent 库 / Agent 编辑器 / 作用域对话
  Flow v2 画布 / 运行输入 / 运行历史 / 回放
        │ REST + SSE
Backend (FastAPI)
  /api/agents      Agent CRUD / validate / run
  /api/flows       Flow CRUD / validate / publish / run
  /api/chat        conversations + turns
  /api/runs        history / events / stats / cancel / resume
  /api/tools /mcp-servers /knowledge   资源库
        │
Execution
  LangGraph StateGraph
  AgentRunner（变量渲染 / 资源绑定 / FC / Schema）
  Checkpoint DB（独立 SQLite）
```

## 3. 数据模型

| 表 | 关键字段 | 说明 |
|---|---|---|
| `agents` | `id, name, definition_json, created_at, updated_at` | Agent 整份定义存 JSON |
| `flows` | `id, name, dsl_version, nodes_json, edges_json, version, ...` | v2 流程，`dsl_version=2` |
| `runs` | `id, target_type, target_id, flow_version, status, inputs_json, state_json, outputs_json, token_usage, cost, conversation_id` | Flow / Agent 统一运行记录 |
| `run_events` | `run_id, seq, type, node_id, payload_json` | SSE 事件与回放 |
| `conversations` | `id, agent_id, flow_id, node_id, title` | 作用域会话 |
| `chat_turns` | `id, conversation_id, user_content, run_id` | 用户消息到 run 的映射 |
| `tools` / `mcp_servers` / `knowledge_bases` / `kb_documents` / `kb_chunks` | 资源定义与文档 | 资源库 |
| `settings` | `key, value_json` | LLM Key 等，读接口脱敏 |

业务库 `data/agentflow.db` 开 WAL 并设 `PRAGMA busy_timeout=5000`；LangGraph checkpoint 独立到 `data/agentflow_checkpoints.db`，避免抢业务库写锁。

## 4. Agent 契约

```text
AgentCreate {
  name, description,
  variables[]: {key,label,type,required,default,description},
  prompt: {system,template},
  resources[]: {kind:"tool"|"mcp"|"knowledge",id,alias,tools[],queryVar,topK,rerank},
  model: {name,temperature,maxTokens,maxToolRounds},
  output: {description,schema}
}
```

- `variables` 可以为空。新建 Agent 默认零变量。
- 变量 key `^[a-zA-Z_][a-zA-Z0-9_]*$`；类型 `string|number|boolean|json`。
- 模板变量 `{{key}}`；资源 token `@kb[别名]`、`@tool[别名]`、`@mcp[别名.工具]`。
- 知识库 `queryVar` 必须在变量中；MCP 资源必须至少勾选一个工具。
- 校验失败 `AGENT_INVALID`（422），`detail={valid,errors,warnings}`。

### AgentRunner

```text
normalize variables
→ @kb 检索并注入 context
→ 绑定 Tool/MCP 为 FC 候选
→ @tool/@mcp 强制调用
→ FC 多轮
→ 输出 Schema 校验（失败重试一次）
```

工具失败回填 `tool` 消息；空回答区分 `finish_reason=length`、只有思维链等，返回 `AGENT_EMPTY_ANSWER`。取消用协作式 `stop`。

## 5. Flow v2 契约

```text
NodeType = start | agent | condition | loop | human | end
```

| 节点 | config | 出边 |
|---|---|---|
| start | `{variables}` | 普通 |
| agent | `{agentId, inputMap}` | 普通 |
| condition | `{expression}` | true / false |
| loop | `{maxRounds, exitCondition}` | body / done |
| human | `{message, timeout}` | 普通 |
| end | `{outputs}`：`list[str]` 或 `{key: template}` | 无 |

- 新建流程 `dslVersion=2`，默认 `start_1 -> end_1`。
- Agent 节点产物：`state.nodes.<nodeId> = {agentId, output, text}`。
- 模板：`{{start.x}}`、`{{<nodeId>.output.field}}`、`{{<nodeId>.text}}`、`{{nodes.<nodeId>.output.field}}`。
- `end.outputs` 空列表回退最后一个 Agent 的 `text`。
- 必填变量未映射：422 `FLOW_INVALID`，`detail` 带 `nodeId`。
- 旧 DSL（`dslVersion != 2`）：update / publish / validate / run 返回 422 `FLOW_DSL_LEGACY`，`detail=null`；不迁移、不兼容。

## 6. 执行

`graph_runner` 把 Flow v2 编译为 LangGraph `StateGraph`：

- `start` 注入开始变量；
- `agent` 调 `AgentRunner`；
- `condition` 只走 true/false 一条边；
- `loop` 按 `maxRounds` / `exitCondition` 驱动 body/done；
- `human` 暂停并写 checkpoint / `runs.state`，批准或拒绝后续跑；
- `end` 解析 outputs。

事件：`run_started / node_started / token / tool_call / tool_result / knowledge_retrieved / human_required / node_completed / run_completed / run_failed`。

## 7. 对话

会话作用域：

```text
Agent 库直聊：agentId
流程节点对话：agentId + flowId + nodeId
```

`POST /api/chat/conversations/{id}/turns`：

1. 取会话绑定的 Agent；
2. 选择聊天变量：优先 `query`，否则第一个 `string` 变量；
3. 没有可填变量时，把用户消息追加到模板末尾；
4. 注入 `history`（若 Agent 声明）；
5. 建 `targetType=agent` 的 run；
6. 写 `chat_turns`，异步执行，返回 202 + `runId`。

历史只取当前会话已成功的 run，最近 6 轮 / 3000 字。

## 8. API

| 组 | 接口 |
|---|---|
| Agent | `GET/POST /api/agents`、`GET/PUT/DELETE /api/agents/{id}`、`POST /api/agents/validate`、`POST /api/agents/{id}/validate`、`POST /api/agents/{id}/run`、`POST /api/agents/{id}/runs` |
| Flow | `GET/POST /api/flows`、`GET/PUT/DELETE /api/flows/{id}`、`POST /api/flows/{id}/validate`、`publish`、`run`、`GET /api/node-types` |
| Chat | `GET/POST /api/chat/conversations`、`GET/DELETE /api/chat/conversations/{id}`、`POST /api/chat/conversations/{id}/turns` |
| Run | `GET /api/runs`、`GET /api/runs/{id}`、`/stats`、`/events`、`POST /api/runs/{id}/cancel`、`/resume` |
| 资源 | `/api/tools`、`/api/mcp-servers`、`/api/knowledge` |
| 设置 | `GET/PUT /api/settings/llm`、`POST /api/settings/llm/test`、`GET /api/settings/llm/models` |

## 9. 前端

- `/agents`、`/agents/:id`、`/agents/:id/chat`、`/flows`、`/flows/:id`、`/runs`、`/runs/:id`。
- Flow 画布只渲染六类节点；Palette 读后端 Schema。
- Agent 编辑器资源逐条导入，保存后调 `/{id}/validate`。
- 运行输入按 start 变量收集；运行历史按 `targetType/targetId` 展示。
- SSE 局部缓冲，按 seq 去重，避免多会话串流。

## 10. 错误码

| code | HTTP | 场景 |
|---|---|---|
| `AGENT_INVALID` | 422 | Agent 定义或资源校验失败 |
| `AGENT_NOT_FOUND` | 404 | Agent 不存在 |
| `AGENT_INPUT_MISSING` | 422 | 必填变量缺失 |
| `AGENT_EMPTY_ANSWER` | run_failed | 模型正文为空 |
| `FLOW_INVALID` | 422 | Flow 结构 / 运行期校验失败 |
| `FLOW_DSL_LEGACY` | 422 | 旧 DSL |
| `FLOW_STALE` | 409 | 并发保存冲突 |
| `CHAT_SCOPE_INVALID` | 422 | flowId/nodeId 与 Agent 不匹配 |
| `CONVERSATION_NOT_FOUND` | 404 | 会话不存在 |
| `LLM_NOT_CONFIGURED` | 409 | 未配置模型 Key |
| `RUN_CANCELLED` | run 终态 | 协作式取消 |

## 11. 安全与边界

- 本地单用户，无鉴权；不要直接暴露到公网。
- MCP stdio 等于允许执行本机命令；只注册可信 Server。
- HTTP 工具可访问任意地址，本地原型不设网络沙箱。
- LLM Key 只写库，读接口仅返回脱敏预览。
- Agent 实时引用无版本锁，编辑会立即影响所有引用流程。
- Flow v2 暂不支持并行扇出。
- 旧 DSL 只能回放。
- 知识库仍为 BM25 + MMR，不是向量检索。

## 12. 验证

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest          # 60 passed
cd ..\agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
```

真实验收见 `docs/acceptance.md`。
