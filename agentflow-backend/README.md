# AgentFlow Studio · 后端

FastAPI + aiosqlite + sse-starlette + httpx + LangGraph。当前进度：**B5 + R5.1 完成**（MCP stdio 客户端、知识库 BM25 检索、skill 子流程内联；对话模式）。

## 已实现

**Flow**
- CRUD、`POST /api/flows/{id}/validate`（结构规则 + **逐节点按注册表 Schema 校验配置**）
- 版本语义：`PUT` 只更新内容（草稿自动保存不递增 version），`POST /api/flows/{id}/publish` 才 +1
- `nodes/edges` 为 `null` 时补默认三节点；显式传 `[]` 是合法的空白画布
- `POST /api/flows/{id}/run`：先校验再执行；非法流程 422 `FLOW_INVALID`；**未配置模型 409 `LLM_NOT_CONFIGURED`**

**节点与设置（R2）**
- `app/nodes/registry.py`：11 类节点各一个 Pydantic 配置模型，`GET /api/node-types` 直接导出 JSON Schema + `defaultConfig` + `implemented`
- `GET /api/settings/llm` / `PUT /api/settings/llm` / `POST /api/settings/llm/test` / `GET /api/settings/llm/models`：Key 存库（`settings` 表），只回脱敏预览；优先级 **DB > .env**；`/models` 把网关支持的模型清单交给前端做下拉（网关不支持该接口时返回 `ok:false`，前端退回手填）
- `app/services/llm.py`：OpenAI 兼容 `/chat/completions` 流式（httpx，不引 SDK）；优先用 provider 的 `usage` 计费，拿不到按字符估算并在收尾补校准帧；支持 `tools` 数组与**分片**的 `delta.tool_calls` 累积

**工具（R3）**
- `app/models/tool.py` + `app/services/tool_repo.py`：工具定义（`kind=http|builtin`、method/url/headers/body 模板、`params_schema`、超时、重试、退避、幂等 TTL、风险、启用）存 `tools.definition_json`；调用记录存 `tool_invocations`
- `app/api/tools.py`：`GET/POST /api/tools`、`PUT/DELETE /api/tools/{id}`、`GET /api/tools/builtins`、`GET /api/tools/invocations`、`POST /api/tools/{id}/test`
- `app/services/tool_runner.py`：按 `params_schema` 校验必填/类型/enum → 幂等查缓存（`sha1(tool_id + 排序参数)` + TTL）→ 带超时与指数退避重试地调用（**只重试连接错误/超时/5xx，4xx 立即失败**）→ 落调用记录；内置 `echo` / `now` / `calc`（`calc` 用 AST 白名单，不用 `eval`）
- `app/engine/loop.py`：tool 节点真执行（参数模板 `{{var}}` 插值 → JSON 解析 → 调用）；llm 节点真 Function Calling（模型要工具 → 执行 → 回填 `tool` 消息 → 再问一次），**MAX_STEPS 逐轮计数**；FC 里的工具失败回给模型继续，tool 节点失败则 run 失败

**扩展能力（R5）**
- `app/models/mcp.py` + `app/services/mcp_repo.py` + `app/services/mcp_client.py`：MCP Server 只支持 `stdio`（command/args/env/cwd/timeout/enabled，整份定义存 `mcp_servers.definition_json`）。客户端是**同步 `subprocess.Popen` + 后台线程 + `asyncio.to_thread`**：`initialize`（protocolVersion 2024-11-05）→ `notifications/initialized` → `tools/list` / `tools/call`，`threading.Timer` watchdog 超时 kill，stderr 收集末 3 行拼进错误。
- `app/api/mcp.py`：`/api/mcp-servers` CRUD、`GET /{id}/tools`（探测）、`POST /{id}/call`（试跑）。配置期失败一律 **200 + `ok:false` + code**（`MCP_SPAWN_FAILED / MCP_TIMEOUT / MCP_SERVER_EXITED / MCP_RPC_ERROR / MCP_TOOL_ERROR / MCP_NOT_CONFIGURED / MCP_TRANSPORT_UNSUPPORTED`）。
- `app/models/knowledge.py` + `app/services/knowledge_rag.py` + `app/services/knowledge_repo.py` + `app/api/knowledge.py`：知识库/文档 CRUD、切块（按句 → 按字数打包 → 超长句带 overlap 硬切）、BM25（k1=1.2 / b=0.75）、MMR 去冗余（0.7 相关性 − 0.3 Jaccard）、空库/无命中 hint；`kb_documents` / `kb_chunks` 两表，删文档先删块再删文档（否则外键失败），计数实时重算。
- `app/engine/extra_nodes.py` + `app/engine/subflow.py`：mcp / knowledge / skill 三类节点。skill 用 `MemorySaver` **内联编译**子流程（不开事件、不落 runs、不写检查点），outputs 合并回父变量、tokens/cost 累加；限 3 层、拒自递归、拒含 `human` 的子流程。错误统一为 `NodeError(code)`，由 `graph_runner` / `loop` 落 `run_failed` 并带 `nodeId`。
- `app/services/event_bus.py`：`run_id` 为空时只返回临时事件，**不写 `run_events`、不推 SSE**——这是子流程复用节点实现的前提。
- `scripts/mcp_demo_server.py`：纯标准库的最小 MCP stdio server（`echo/add/now`），联调与验收用。

**对话模式（R5.1）**
- `app/models/chat.py` + `app/services/chat_repo.py` + `app/api/chat.py`：会话 CRUD、`chat_turns`（用户消息到 run 的映射）、`build_history`（只取 succeeded run，最近 6 轮 / 3000 字，超出丢最旧后尾部硬切）、`answer_text`（`outputs.text → result → answer → 首个非空字符串 → JSON`）。
- `POST /api/chat/conversations/{id}/turns`：校验流程 → 拒绝 `human` 流程（409 `CHAT_HUMAN_UNSUPPORTED`）→ 有 llm 节点则检查 Key（409 `LLM_NOT_CONFIGURED`）→ 拼 history → 建 Run（`runs.conversation_id`）→ 写 turn → 首轮改标题 → 异步执行，返回 202 + `runId`。
- **助手回复不落表**：读取会话时按 `chat_turns.run_id` 关联 `runs.outputs_json` 动态拼；run 失败时消息带 `status=failed` 与 `runs.error`。
- 表：`conversations(id, flow_id, title, created_at, updated_at)`（flow_id 外键 `ON DELETE CASCADE`）、`chat_turns(id, conversation_id, user_content, run_id, created_at)`；`runs` 新增 `conversation_id`，`_migrate` 自动补列。

**Run**
- `GET /api/runs` 支持 `flow_id / status / started_after / started_before / limit`
- `GET /api/runs/{id}/stats`：按节点聚合 token、耗时、成本、状态
- `GET /api/runs/{id}/events`：SSE，先补 `Last-Event-ID` 之后的历史，再跟随实时队列；run 已终态时补完历史即关闭
- `POST /api/runs/{id}/cancel`：协作式取消，等执行器自己写终态
- `POST /api/runs/{id}/resume`：从 `runs.state_json` 快照真续跑（审批通过/拒绝）
- `POST /api/runs/{id}/to-case`：失败 Run 转评测 Case

**执行器**
- `app/engine/executor.py`：`RUNNER=graph|loop|demo` 选择器，**默认 graph**
- `app/engine/graph_runner.py`（R4）：把 DSL 编译成 `StateGraph`。普通边照连；`condition` / `loop` 用条件边按 `edge.sourceHandle`（true/false、body/done）路由；`human` 抛 `HumanPause` 停下，checkpoint 留在 `langgraph-checkpoint-sqlite` 的 `checkpoints` 表。superstep 上限按节点数与最大轮次估算，触发时报 `GRAPH_RECURSION_LIMIT`
- `app/engine/expr.py`（R4）：条件表达式求值。`{{var}}` 渲染成 Python 字面量后过 AST 白名单（比较/布尔/四则/下标），禁函数调用与属性访问；变量缺失、语法错、求值失败都转成可读 `CONDITION_INVALID`
- `app/engine/loop.py`：R2 手写 Agent Loop，保留做对照（线性拓扑、不支持条件分支与回边）；其 `_run_llm_node` / `_run_tool_node` 被图执行器复用，保证两种引擎的模型/工具行为完全一致
- `app/engine/common.py`：拓扑排序、state 快照、可取消等待、终态收尾
- `app/engine/demo_runner.py`：确定性桩，不联网，用于回归与前端联调
- `build_graph(emit_events=True, persist_state=True)` 两个开关：顶层运行全开；`subflow` 内联编译时全关（不发事件、不写 `runs.state`），所以子流程能复用同一套节点实现而不污染父 run
- 11 类节点到 B5 全部实装，`PLACEHOLDER_NODES` 已清空
- `tools/fake_llm.py`：本地假模型（OpenAI 兼容，仅验收用，不参与产品逻辑）

## 关键设计

| 问题 | 做法 |
|---|---|
| 取消停不掉执行 | `RunManager` 保存 task 句柄 + 每 run 一个 `asyncio.Event` 取消令牌，执行器在每个可中断点检查 |
| 重启后事件序号冲突 | `event_bus` 内存游标未命中时从 `run_events.MAX(seq)` 恢复，避免撞主键 |
| 每事件一条连接 | 改为共享连接 + 写锁；并发 `commit` 会互相提交对方中间状态，写操作统一走 `db.execute / db.transaction` |
| 僵尸 run | lifespan 关闭时先 `run_manager.shutdown()` 再关库，执行器留下 terminal 状态 |
| 前后端两份节点定义 | 配置模型只在 `app/nodes/registry.py` 写一次：导出给前端渲染、后端拿同一份校验 |
| Key 泄露 | 只写库、读接口给脱敏预览；`public_llm_view` 是唯一出口 |
| token 两套数字 | 所有帧（含无文本的用量校准帧）都进事件流，`runs.token_usage` == `/stats` 汇总 |
| 估算 token 与真实用量不一致 | 收尾补一帧带符号差额，最终以 provider `usage` 为准 |
| 节点写死模型名 → 换网关就 400 | 优先级 **节点 config > 系统设置 > `.env`**，默认模板里 `model` 留空；失败时 `run_failed` 带 `model / nodeId / modelFromNode / hint`，错误文案直接说清「哪个节点覆盖了什么、怎么改」 |
| 旧标签页把配置覆盖回去 | `PUT` 接受可选 `baseUpdatedAt`（调用方加载时的 `updatedAt`）；不一致回 409 `FLOW_STALE` 且不写库。前端点运行只在 `dirty` 时保存，并在窗口获得焦点时静默同步 |
| 工具定义与执行参数散成两套 | `tools.definition_json` 存整份 ToolDef，name/kind/schema/endpoint 只是冗余列；节点只引用 `tool_id`，超时/重试/幂等永远跟着工具走 |
| 老库升级要删数据 | `Database.connect()` 里按 `PRAGMA table_info` 补列（R3 给 `tools` 加了 `definition_json`/`created_at`/`updated_at`），不删库 |
| 重复调用造成副作用 | 幂等 key = `sha1(tool_id + 排序参数)`，TTL 内命中直接复用上次成功结果，记录 `idemHit=1/attempts=0`；`none` 策略可关掉 |
| 工具失败要不要弄挂 run | 区分意图：tool 节点是用户写死的调用，失败即 `run_failed`；FC 里的失败作为 `tool` 消息回给模型，让它改参数重试 |
| 两次 run 的 state 串味 | `DEFAULT_STATE` 里 `tool_calls/tool_errors` 是 list，浅拷贝会共享；改成 `copy.deepcopy` 并在测试里守住 |
| 线性执行器做不了条件分支 | 拓扑序会把真假两条分支都跑一遍。R4 换成 `StateGraph`：condition 用 `add_conditional_edges` 只走一条，分支归属来自边的 `sourceHandle` |
| 回边会被当成非法环 | 环检测只忽略「以 loop 节点为终点」的边；loop 自己的 `body` 边照常参与排序，校验还要求 body 分支必须连线 |
| 同步 `interrupt()` 用不了 | Python 3.10 没有 `asyncio.create_task(context=...)`，langchain-core 的 config contextvar 进不去异步节点，官方 `interrupt()` 必抛 `Called get_config outside of a runnable context`。改为抛 `HumanPause` 暂停 + `aupdate_state` 灌回 state + `ainvoke(None)` 从检查点续跑；用 `run.state.human_pending` 判断续跑的是哪个节点，节点重入时不重复发 `node_started` |
| 图状态与我方 state 两套 | 图里只有一个字段 `data`（R1 起的 state 字典），节点原地改这个 dict 并返回它；每步都 `write_state` 落 `runs.state_json`，checkpoint 只负责「执行位置」。两套都写，回放与续跑各取所需 |
| 推理模型正文为空 | `delta.content` 之外还有 `reasoning_content`（deepseek-flash 实测会先吐思维链）：现在单独透出（token 帧的 `reasoning`）、照样计费，节点完成事件带 `reasoningChars` 与 `finishReason`；正文为空时按「思维链吃满预算」或「`finish_reason=length` 截断」两种成因给不同 `emptyAnswer` + `hint` |
| MCP 在 Windows 上起不来子进程 | `asyncio.create_subprocess_exec` 在 uvicorn 的 SelectorEventLoop 上直接 `NotImplementedError`；改成同步 `Popen` + 线程 + `to_thread`，超时用 `threading.Timer` kill 进程，并把 stderr 末 3 行拼进错误 |
| MCP 配置错误不该是 500 | 探测/试跑是「配置期」操作，失败回 200 + `ok:false` + 错误码，前端才能就地提示；只有节点执行期失败才让 run 挂掉 |
| 知识库检索不引模型 | BM25 就是零成本基线：中文按字符 bigram、英文按词；`rerank=MMR` 只做去冗余（相关性 − 与已选块的 Jaccard）。`embedding_model` 字段已留，向量检索后置 |
| 子流程会污染父 run | 内联执行时 `run_id` 置空（事件总线只发临时事件、不写 `run_events`），并用 `MemorySaver` 而非共享 checkpointer；子流程不落 `runs` 表，token/cost 由父节点累加 |
| 子流程无限套娃/卡审批 | 深度上限 3 层、`flow_id == 当前 flow` 直接 `SKILL_RECURSION`、子流程含 `human` 直接 `SKILL_HUMAN_UNSUPPORTED`（父 run 无法替子流程接审批） |
| 删知识库文档报外键错 | `kb_chunks` 引用 `kb_documents`，必须先删块再删文档；删完重算 `docCount/chunkCount` |

## 本地启动

```bash
python -m venv .venv            # 只用 Python 3.10+；不要在已有 .venv 上重跑这条
pip install -r requirements.txt  # 运行时依赖（uvicorn/websockets 已锁 3.10 可用区间）
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --reload-dir app --port 8000
```

`--reload-dir app` 别省：默认会监视 `.venv`，重装依赖时 reload 会卡死并留下占住端口的僵尸进程。

**装依赖时的两个坑**（都在 `requirements.txt` 里锁好了，手动 `pip install langgraph` 时要留意）：
1. pip 会把 `websockets` 顶到 16.1，`uvicorn 0.34` 在 Python 3.10 上随即起不来 → 补 `pip install "websockets>=12,<13"`（pip 会警告 `langsmith requires websockets>=15`，本项目不用 LangSmith tracing，忽略）。
2. `aiosqlite 0.22` 删掉了 `Connection.is_alive`，checkpointer 2.x 启动即 `AttributeError` → 锁 `aiosqlite==0.21.0`。
3. `langgraph` 官方 `interrupt()` 在 3.10 的异步节点里不可用（config contextvar 进不去），本项目用「抛 `HumanPause` + `aupdate_state` + `ainvoke(None)`」实现同样的真中断，见 `graph_runner.py` 注释。

Swagger: http://localhost:8000/docs

## 测试

```bash
.venv\Scripts\python.exe -m pytest      # 71 passed（约 25s）
```

覆盖：Flow 版本语义与校验、节点配置校验、节点 Schema 导出、Key 脱敏与优先级、
SSE 到终态、筛选、节点统计、取消、审批续跑、序号恢复、真流式 token 帧与 usage 校准、
`MAX_STEPS` 守卫、未配 Key 的 409 与无模型流程照常可跑、
工具 CRUD 与重名 409、内置 Schema 覆盖、参数缺失拒绝、5xx 重试到第 3 次成功、**4xx 不重试**、
幂等命中、tool 节点真执行并落调用记录、工具不存在失败、**FC 两轮回路**、FC 逐轮计步、两次 run 的 state 隔离、
**图引擎线性执行**、条件分支只走一条、表达式变量缺失报错、有界循环跑满/退出条件提前退出、
**human 暂停后从 checkpoint 续跑且不重复 node_started**、取消不被后台任务改写、
思维链吃满预算的空回答提示、`finish_reason=length` 截断的空回答提示、
**MCP 真起子进程探测 + 调用（add=42）**、spawn 失败回错误码、mcp 节点发 `tool_call(source=mcp)`、空 server 配置失败、停用 Server 运行期被拒、
**知识库切块/BM25 排序/MMR**、空库 hint、knowledge 节点注入 `context`、删文档重算计数、
**子流程 outputs 合并 + tokens 计入父 run**、自递归被拦、含 human 子流程被拒。

## 下一步

| 步 | 内容 |
|---|---|
| B3 ✅ | 工具注册表：FC 工具 CRUD、超时、重试、幂等、真 Function Calling |
| B4 ✅ | LangGraph 图执行器：条件边、有界循环、checkpointer 中断续跑 |
| B5 ✅ | MCP stdio 客户端 / 知识库切块 + BM25/MMR / skill 子流程内联 |
| B6 | 评测体系（三层采集器 / pass^k / judge / 门禁）与 Docker |
