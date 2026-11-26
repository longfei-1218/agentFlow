# AgentFlow Studio · 后端

FastAPI + aiosqlite + sse-starlette + httpx + LangGraph。当前进度：**B4 完成**（图执行器：条件边、有界循环、checkpointer 中断续跑）。

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
- 占位节点（mcp / skill / knowledge 直通并标 `skipped`）留到 B5
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
.venv\Scripts\python.exe -m pytest      # 54 passed
```

覆盖：Flow 版本语义与校验、节点配置校验、节点 Schema 导出、Key 脱敏与优先级、
SSE 到终态、筛选、节点统计、取消、审批续跑、序号恢复、真流式 token 帧与 usage 校准、
`MAX_STEPS` 守卫、未配 Key 的 409 与无模型流程照常可跑、
工具 CRUD 与重名 409、内置 Schema 覆盖、参数缺失拒绝、5xx 重试到第 3 次成功、**4xx 不重试**、
幂等命中、tool 节点真执行并落调用记录、工具不存在失败、**FC 两轮回路**、FC 逐轮计步、两次 run 的 state 隔离、
**图引擎线性执行**、条件分支只走一条、表达式变量缺失报错、有界循环跑满/退出条件提前退出、
**human 暂停后从 checkpoint 续跑且不重复 node_started**、取消不被后台任务改写、
思维链吃满预算的空回答提示、`finish_reason=length` 截断的空回答提示。

## 下一步

| 步 | 内容 |
|---|---|
| B3 ✅ | 工具注册表：FC 工具 CRUD、超时、重试、幂等、真 Function Calling |
| B4 ✅ | LangGraph 图执行器：条件边、有界循环、checkpointer 中断续跑 |
| B5 | MCP 客户端、RAG 知识库、skill 子流程 |
| B6 | 评测体系（三层采集器 / pass^k / judge / 门禁）与 Docker |
