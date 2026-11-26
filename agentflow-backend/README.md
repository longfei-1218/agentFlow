# AgentFlow Studio · 后端

FastAPI + aiosqlite + sse-starlette。当前进度：**B1 完成**（P1 骨架 + 地基修复）。

## 已实现

**Flow**
- CRUD、`POST /api/flows/{id}/validate`（唯一入口/出口、孤立节点、环检测、condition 双分支）
- 版本语义：`PUT` 只更新内容（草稿自动保存不递增 version），`POST /api/flows/{id}/publish` 才 +1
- `nodes/edges` 为 `null` 时补默认三节点；显式传 `[]` 是合法的空白画布
- `POST /api/flows/{id}/run`：先校验再执行，非法流程返回 422 `FLOW_INVALID` + 逐条问题

**Run**
- `GET /api/runs` 支持 `flow_id / status / started_after / started_before / limit`
- `GET /api/runs/{id}/stats`：按节点聚合 token、耗时、状态
- `GET /api/runs/{id}/events`：SSE，先补 `Last-Event-ID` 之后的历史，再跟随实时队列；run 已终态时补完历史即关闭
- `POST /api/runs/{id}/cancel`：协作式取消，等执行器自己写终态，不再出现「取消后又被改回 succeeded」
- `POST /api/runs/{id}/resume`：从 `runs.state_json` 快照真续跑（审批通过/拒绝）
- `POST /api/runs/{id}/to-case`：失败 Run 转评测 Case

**执行器**
- `app/engine/demo_runner.py`：确定性演示执行器，不调 LLM，用于打通运行/取消/审批/续跑链路与前端联调
- B2 起由 `app/engine/loop.py`（手写 Agent Loop）接管，B4 再迁 LangGraph

## 关键设计

| 问题 | 做法 |
|---|---|
| 取消停不掉执行 | `RunManager` 保存 task 句柄 + 每 run 一个 `asyncio.Event` 取消令牌，执行器在每个可中断点检查 |
| 重启后事件序号冲突 | `event_bus` 内存游标未命中时从 `run_events.MAX(seq)` 恢复，避免撞主键 |
| 每事件一条连接 | 改为共享连接 + 写锁；并发 `commit` 会互相提交对方中间状态，写操作统一走 `db.execute / db.transaction` |
| 僵尸 run | lifespan 关闭时先 `run_manager.shutdown()` 再关库，执行器留下 terminal 状态 |

## 本地启动

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt          # 运行时依赖
pip install -r requirements-dev.txt      # 测试依赖
uvicorn app.main:app --reload --port 8000
```

Swagger: http://localhost:8000/docs

## 测试

```bash
.venv\Scripts\python.exe -m pytest
```

15 个用例覆盖：Flow 版本语义与校验规则、SSE 事件流到终态、按流程筛选、节点统计、
取消后不再产生事件且状态不被改写、审批续跑、拒绝审批即取消、内存游标丢失后从库恢复序号。

## 下一步

| 步 | 内容 |
|---|---|
| B2 | 节点注册表（Pydantic + JSON Schema 导出）、LLM provider 与 `/api/settings/llm`、手写 Agent Loop |
| B3 | tool 节点：FC 工具 CRUD、超时、重试、幂等 |
| B4 | LangGraph 编译 + checkpointer 真中断续跑 |
| B5 | MCP 客户端、RAG 知识库、skill 子流程 |
| B6 | 评测体系（三层采集器 / pass^k / judge / 门禁）与 Docker |
