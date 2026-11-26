# AgentFlow Studio · 后端

FastAPI + aiosqlite + sse-starlette + httpx。当前进度：**B2 完成**（节点 Schema + LLM 配置 + 手写 Agent Loop）。

## 已实现

**Flow**
- CRUD、`POST /api/flows/{id}/validate`（结构规则 + **逐节点按注册表 Schema 校验配置**）
- 版本语义：`PUT` 只更新内容（草稿自动保存不递增 version），`POST /api/flows/{id}/publish` 才 +1
- `nodes/edges` 为 `null` 时补默认三节点；显式传 `[]` 是合法的空白画布
- `POST /api/flows/{id}/run`：先校验再执行；非法流程 422 `FLOW_INVALID`；**未配置模型 409 `LLM_NOT_CONFIGURED`**

**节点与设置（R2）**
- `app/nodes/registry.py`：11 类节点各一个 Pydantic 配置模型，`GET /api/node-types` 直接导出 JSON Schema + `defaultConfig` + `implemented`
- `GET /api/settings/llm` / `PUT /api/settings/llm` / `POST /api/settings/llm/test` / `GET /api/settings/llm/models`：Key 存库（`settings` 表），只回脱敏预览；优先级 **DB > .env**；`/models` 把网关支持的模型清单交给前端做下拉（网关不支持该接口时返回 `ok:false`，前端退回手填）
- `app/services/llm.py`：OpenAI 兼容 `/chat/completions` 流式（httpx，不引 SDK）；优先用 provider 的 `usage` 计费，拿不到按字符估算并在收尾补校准帧

**Run**
- `GET /api/runs` 支持 `flow_id / status / started_after / started_before / limit`
- `GET /api/runs/{id}/stats`：按节点聚合 token、耗时、成本、状态
- `GET /api/runs/{id}/events`：SSE，先补 `Last-Event-ID` 之后的历史，再跟随实时队列；run 已终态时补完历史即关闭
- `POST /api/runs/{id}/cancel`：协作式取消，等执行器自己写终态
- `POST /api/runs/{id}/resume`：从 `runs.state_json` 快照真续跑（审批通过/拒绝）
- `POST /api/runs/{id}/to-case`：失败 Run 转评测 Case

**执行器**
- `app/engine/executor.py`：`RUNNER=loop|demo` 选择器
- `app/engine/loop.py`：手写 Agent Loop。input / prompt / llm / output / human 真执行；`MAX_STEPS` 数 **模型调用次数**，超限抛 `StepLimitExceeded` → `run_failed{code:STEP_LIMIT_EXCEEDED}`（服务不崩）
- `app/engine/common.py`：拓扑排序、state 快照、可取消等待、终态收尾（demo 与 loop 共用）
- `app/engine/demo_runner.py`：确定性桩，不联网，用于回归与前端联调
- 占位节点（tool 发 stub 事件；mcp / skill / knowledge / condition / loop 直通并标 `skipped`）留到 B3–B5
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

## 本地启动

```bash
python -m venv .venv            # 只用 Python 3.10+；不要在已有 .venv 上重跑这条
pip install -r requirements.txt  # 运行时依赖（uvicorn/websockets 已锁 3.10 可用区间）
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --reload-dir app --port 8000
```

`--reload-dir app` 别省：默认会监视 `.venv`，重装依赖时 reload 会卡死并留下占住端口的僵尸进程。

Swagger: http://localhost:8000/docs

## 测试

```bash
.venv\Scripts\python.exe -m pytest      # 32 passed
```

覆盖：Flow 版本语义与校验、节点配置校验、节点 Schema 导出、Key 脱敏与优先级、
SSE 到终态、筛选、节点统计、取消、审批续跑、序号恢复、真流式 token 帧与 usage 校准、
`MAX_STEPS` 守卫、未配 Key 的 409 与无模型流程照常可跑。

## 下一步

| 步 | 内容 |
|---|---|
| B3 | tool 节点：FC 工具 CRUD、超时、重试、幂等 |
| B4 | LangGraph 编译 + checkpointer 真中断续跑（condition / loop 交给图引擎） |
| B5 | MCP 客户端、RAG 知识库、skill 子流程 |
| B6 | 评测体系（三层采集器 / pass^k / judge / 门禁）与 Docker |
