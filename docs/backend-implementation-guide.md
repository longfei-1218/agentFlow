# 后端实现指南（AgentFlow Studio v2）

> 当前口径：FastAPI + SQLite + LangGraph，**Agent 库 + Flow v2 六类编排节点 + 目标化 Run + Agent 作用域对话**。

## 1. 分层

```text
app/api/          REST + SSE 入口，只做参数校验、CRUD、触发
app/models/       Agent / Flow v2 / Run / Chat / 资源 Pydantic 模型
app/services/     repo、业务校验、事件总线、LLM / 工具 / MCP / 知识库
app/engine/       graph_runner、agent_runner、expr、flow_vars
app/db/init.sql   表结构
```

## 2. 目录

```text
app/
├── main.py
├── config.py
├── database.py
├── models/
│   ├── agent.py          Agent / 变量 / 资源 / 输出契约
│   ├── flow.py           Flow v2 六类节点
│   ├── run.py            Run / RunEvent / RunStatus
│   ├── chat.py           Conversation / ChatTurn
│   ├── tool.py / mcp.py / knowledge.py
├── api/
│   ├── agents.py
│   ├── flows.py
│   ├── chat.py
│   ├── runs.py
│   ├── tools.py / mcp.py / knowledge.py
│   ├── settings.py / nodes.py
├── services/
│   ├── agent_repo.py / agent_service.py
│   ├── flow_repo.py / flow_service.py / flow_vars.py
│   ├── chat_repo.py
│   ├── run_manager.py / run_repo.py / event_bus.py
│   ├── llm.py / tool_runner.py / mcp_client.py / knowledge_rag.py
├── engine/
│   ├── graph_runner.py   LangGraph 执行器
│   ├── agent_runner.py   单 Agent 执行入口
│   ├── expr.py           条件 / 循环表达式
│   ├── common.py         状态与收尾
└── db/init.sql
```

## 3. Agent 实现

- `AgentCreate` 定义 `name / description / variables / prompt{system,template} / resources / model / output`，整份存 `agents.definition_json`。
- `variables=[]` 合法；零变量 Agent 在对话时把用户消息追加到模板末尾。
- `agent_service.validate_agent` 校验变量、资源别名、`@` token、知识库 queryVar、输出 Schema。
- `agent_runner.run_agent`：
  1. `normalize_variables`；
  2. `@kb` 检索注入；
  3. Tool / MCP 绑定为 FC 候选；
  4. 强制工具调用；
  5. 输出 Schema 校验与一次重试；
  6. 空回答诊断、协作式 stop。
- 支持可选 `chat_text`：没有可填变量或模板未引用聊天变量时追加到 prompt 末尾。

## 4. Flow v2 实现

- `models/flow.py` 的 `NodeType = start|agent|condition|loop|human|end`，`dsl_version=2`。
- `flow_service` 做结构校验：start/end 唯一、condition true/false、loop body、孤立节点、环检测。
- 运行期校验：Agent 存在、`inputMap` 键属于 Agent 变量、必填变量已映射、路径可解析。
- `graph_runner` 编译 `StateGraph`：条件边、有界循环、human checkpoint、Agent 节点。
- `runs.target_type=flow|agent` + `target_id`。

## 5. 对话实现

- `conversations.agent_id` 必填，`flow_id/node_id` 可空；scope 校验指向该 Agent 节点。
- `POST /api/chat/conversations/{id}/turns`：
  1. 选择聊天变量：`query` → 第一个 string 变量 → 无；
  2. 有变量则注入，无变量则设 `chat_text`；
  3. 注入 `history`；
  4. 创建 Agent run；
  5. 写 `chat_turns`，异步执行，返回 202。
- `build_history` 只取当前会话已成功 run，最近 6 轮 / 3000 字。

## 6. API

| 组 | 接口 |
|---|---|
| Agent | `GET/POST /api/agents`、`GET/PUT/DELETE /api/agents/{id}`、`validate`、`run`、`runs` |
| Flow | `GET/POST /api/flows`、CRUD、`validate/publish/run`、`GET /api/node-types` |
| Chat | `GET/POST /api/chat/conversations`、`GET/DELETE /{id}`、`POST /{id}/turns` |
| Run | `GET /api/runs`、`/{id}`、`/stats`、`/events`、`cancel`、`resume` |
| 资源 | `/api/tools`、`/api/mcp-servers`、`/api/knowledge` |
| 设置 | `/api/settings/llm` |

## 7. 错误码

- `AGENT_INVALID` 422：定义/资源校验失败，detail 为对象。
- `AGENT_NOT_FOUND` 404。
- `AGENT_INPUT_MISSING` 422：必填变量缺失。
- `AGENT_EMPTY_ANSWER`：run 失败，正文为空。
- `FLOW_INVALID` 422：Flow 校验失败，detail 带 nodeId。
- `FLOW_DSL_LEGACY` 422：旧 DSL。
- `FLOW_STALE` 409：并发保存。
- `CHAT_SCOPE_INVALID` 422：flowId/nodeId 不匹配。
- `LLM_NOT_CONFIGURED` 409。

## 8. 数据库与并发

- 业务库 `data/agentflow.db`，WAL + `PRAGMA busy_timeout=5000`。
- checkpoint 独立 `data/agentflow_checkpoints.db`。
- `runs` / `run_events` 支持 SSE 断点补发。
- 取消由 `run_manager` 的协作式 stop 完成，不直接强写终态。

## 9. 验证

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest          # 70 passed
.venv\Scripts\python.exe scripts\seed_v2_demo.py --smoke
```

## 10. 边界

- 本地单用户，无鉴权。
- 旧 DSL 只读回放。
- Agent 实时引用，无版本锁。
- MCP 只支持 stdio。
- 知识库是 BM25 + MMR，不是向量检索。
- Flow v2 不支持并行扇出。
