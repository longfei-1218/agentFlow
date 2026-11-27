# AgentFlow Studio · 后端

FastAPI + aiosqlite + sse-starlette + httpx + LangGraph。当前是 **Flow v2**：全局 Agent 库 + 六类编排节点 + Agent 作用域对话；步骤 5 已收尾，后端 70 条测试通过。

## 已实现

### Agent v2

- `app/models/agent.py`、`app/services/agent_repo.py`、`app/services/agent_service.py`、`app/api/agents.py`：全局 Agent 库，字段 `name / description / variables / prompt{system,template} / resources / model / output`，整份定义存 `agents.definition_json`。
- 变量可以为空：`variables=[]` 合法，新建 Agent 默认零变量。零变量 Agent 在对话中会把用户消息追加到模板末尾；有 `query` 或首个 string 变量时仍按变量注入。
- 校验：变量 key/类型/默认值、资源别名唯一、`@kb[alias]` / `@tool[alias]` / `@mcp[alias.tool]` 可解析、资源存在且启用、输出 Schema 形状；`/{id}/validate` 额外探测 MCP 工具清单。
- `app/engine/agent_runner.py`：变量合并/类型转换 → `@kb` 检索并注入上下文 → 未 `@` 的 Tool/MCP 作为 FC 候选、`@tool/@mcp` 强制调用 → FC 多轮 → 输出 JSON Schema 校验（失败重试一次）。工具失败回填 `tool` 消息；空回答区分 `finish_reason=length`、只有思维链等情况，报 `AGENT_EMPTY_ANSWER`。支持协作式 `stop`。
- API：`GET/POST /api/agents`、`GET/PUT/DELETE /api/agents/{id}`、`POST /api/agents/validate`、`POST /api/agents/{id}/validate`、`POST /api/agents/{id}/run`（同步）、`POST /api/agents/{id}/runs`（202 + SSE）。

### Flow v2

- `NodeType` 只有 `start / agent / condition / loop / human / end`；`GET /api/node-types` 导出六类 Schema。新建流程 `dslVersion=2`，默认 `start_1 -> end_1`。
- 旧 DSL 在 update / publish / validate / run 四个入口统一返回 HTTP 422 `FLOW_DSL_LEGACY`，`detail=null`；不迁移、不兼容。
- `agent` 节点配置 `{agentId, inputMap}`：`inputMap` 按 `{{start.x}}` / `{{<nodeId>.output.field}}` / `{{<nodeId>.text}}` 取值，产物写 `state.nodes.<nodeId> = {agentId, output, text}`；`end.outputs` 支持列表或对象，空列表回退最后一个 Agent 的 `text`。
- `app/services/flow_vars.py` 负责点路径模板；`app/engine/expr.py` 的 condition/loop 表达式同样支持点路径。
- `app/services/flow_service.py`：结构校验（start/end 唯一、condition true/false、loop body、孤立节点、环检测）＋运行期校验（Agent 存在、inputMap 键属于 Agent 变量、必选变量已映射、变量路径可解析）。必填变量没映射返回 `FLOW_INVALID` 并带 `nodeId`。
- `app/engine/graph_runner.py`：v2 流程走 LangGraph；`start` 注入 `inputs`，`agent` 调 `AgentRunner`，`end` 解析 outputs；condition/loop/human 保留编排语义。checkpoint 独立到 `data/agentflow_checkpoints.db`，业务库 `PRAGMA busy_timeout=5000`。
- `runs` 使用 `target_type = flow|agent` + `target_id` + `flow_version`；`GET /api/runs?flow_id=/agent_id=/target_type=/target_id=`；resume 仅允许 flow。

### 对话

- 会话作用域 `agent_id + flow_id + node_id`：库内直聊只有 `agent_id`；同一 Agent 在不同流程节点各聊各的。
- `POST /api/chat/conversations/{id}/turns`：每轮建一条 `target_type=agent` 的 run，历史只回灌当前会话已成功的 run；零变量 Agent 把消息追加到模板末尾。
- `app/services/chat_repo.py`：历史取最近 6 轮 / 3000 字，超出丢最旧后尾部硬切。

### 资源库与运行

- 工具、MCP、知识库仍作为独立资源库：`/api/tools`、`/api/mcp-servers`、`/api/knowledge`；Agent 通过 `resources[]` 引用。
- **工具环境变量**：`ToolDef.env` + URL / Headers / Body 里的 `${VAR}`，运行时合并进程环境、`.env` 与资源 `env`；缺失报 `TOOL_ENV_MISSING`。
- **MCP 环境变量**：`MCPServerDef.env` 以及 command / args / cwd 里的 `${VAR}`，启动子进程前展开；缺失报 `MCP_ENV_MISSING`。
- **内置工具**：核心 `echo / now / calc` + 资源包 Catalog 扫描 `resources/builtin_tools/*`。`render_interview_repo` 在 `resources/builtin_tools/render_interview_repo/tool.py`，用固定模板把结构化面试结果渲染成 HTML，写入 `ARTIFACT_DIR`（默认 `./data/artifacts`），返回 `path` + `downloadUrl`。
- **产物下载**：`GET /api/artifacts`、`GET /api/artifacts/{fileName}`。
- **parse_document MCP**：`resources/mcp/parse_document/server.py`，支持 txt/md/csv/json/html/docx/pdf；根目录由 `AGENTFLOW_DOC_ROOTS` 控制，PDF 依赖 `pypdf`。
- **资源导入**：`GET /api/resources`、`POST /api/resources/import`，支持本地 MCP zip、远程 HTTP MCP、HTTP 工具；外部只允许 MCP + HTTP 工具，不允许上传内置 Python 工具。运行时资源落 `data/resources/users/<owner>/`。
- 新增工具 / MCP 的完整步骤见 `docs/tool-mcp-extension-guide.md`，资源包与导入架构见 `docs/resource-package-architecture.md`。
- `seed_v2_demo.py` 写入两个演示 Agent 与两条演示流程，`--smoke` 跑真实 DeepSeek 冒烟。

## 本地启动

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

健康检查：`GET /api/health` → `{"status":"ok","version":"1.1"}`。Swagger：`http://localhost:8000/docs`。

`--reload-dir app` 不要省：默认会监视 `.venv`、`data`，重装依赖时 reload 会卡死并留下占端口进程。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest
```

期望 **70 passed**，覆盖：

- Flow v2 默认 start/end、六类节点 Schema、结构校验、condition 分支、loop、human 暂停/批准/取消、旧 DSL `FLOW_DSL_LEGACY`；
- Agent CRUD、零变量 Agent 保存与对话、变量渲染、`@tool` 强制、输出 Schema 重试、空回答、Agent 异步 run + SSE；
- 两个 Agent 经 `inputMap` 串联、必填变量未映射、Agent 作用域对话与历史隔离；
- Run 生命周期、取消、序号恢复、工具/MCP/知识库/设置；
- 工具 / MCP 的 `${VAR}` 展开与缺失报错、`.env` 合并、面试报告 HTML 落盘与下载、`parse_document` 路径边界；
- 资源包 Catalog、本地 MCP zip 导入 + 探测、远程 HTTP MCP 导入 + 调用、HTTP 工具 manifest 导入、知识库文档落盘。

真实冒烟：

```powershell
.venv\Scripts\python.exe scripts\seed_v2_demo.py --smoke
```

## 已知限制

- `inputMap` 只校验路径可解析，不限制只能引用直接上游。
- Agent 资源逐条添加；MCP 工具靠探测勾选，没有批量导入。
- 旧 DSL 只能回放，不能编辑、发布、校验或运行。
- 实时引用无版本锁，改 Agent 立即影响引用流程。
- 对话记忆是硬截断，不做摘要或向量检索。
- 旧的 demo / loop 执行代码仍留在仓库作离线对照，但 v2 API 只接受 `dslVersion=2`，正常入口走 LangGraph。
