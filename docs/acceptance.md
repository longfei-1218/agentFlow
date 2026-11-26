# 验收清单（按轮次）

> 每轮结束都补齐本节内容：**自动化命令 + 手工步骤 + 期望结果 + 联调判断点**。
> 约定：后端命令都在 `agentflow-backend/` 下执行，前端都在 `agentflow-frontend/` 下执行。

## 环境准备（只做一次）

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## R1 · 后端地基（B1） + 前端对接版本语义

状态：**后端已完成，前端切片待做**

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest
```

期望：`15 passed`。失败时先看是哪个断言：

| 用例 | 它守的是什么 |
|---|---|
| `test_put_keeps_version_and_publish_bumps_it` | 自动保存不得递增 version |
| `test_cancel_stops_background_runner` | 取消后事件数不再增长、状态不被改写回 succeeded |
| `test_resume_continues_after_human_approval` | 审批后续跑真能跑完，末条事件是 `run_completed` |
| `test_seq_recovers_from_database_after_bus_restart` | 重启后 seq 接着库里的最大值走，不撞主键 |

### B. 手工（Swagger `http://localhost:8000/docs`，或下面 curl）

先启动：

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

| # | 操作 | 期望 |
|---|---|---|
| 1 | `POST /api/flows` body `{"name":"验收流程"}` | 201，`nodes` 为 input/llm/output 三节点，`version=1` |
| 2 | 连续 3 次 `PUT /api/flows/{id}`（只改 name） | 每次返回 `version` 都是 `1` |
| 3 | `POST /api/flows/{id}/publish` | 200，`version=2` |
| 4 | `POST /api/flows` body `{"name":"空","nodes":[],"edges":[]}` 再 `POST .../run` | 建流程成功且 `nodes=[]`；run 返回 **422**，`code=FLOW_INVALID`，`detail` 列出缺入口等问题 |
| 5 | 用 #1 的流程 `POST /run`，立刻 `POST /api/runs/{id}/cancel` | 返回 `status=cancelled`；再等 5 秒 `GET /api/runs/{id}` 仍是 `cancelled`、`outputs=null` |
| 6 | 画一条 `input → human → output` 的流程并运行，`GET /api/runs/{id}` | 停在 `waiting_human`；`POST /api/runs/{id}/resume` body `{"approved":true}` 后变 `succeeded`，`state.humanPending=null` |
| 7 | `curl.exe -N http://localhost:8000/api/runs/{id}/events`（终态 run） | 打印完整历史后**连接自行结束**，不会一直挂着 keep-alive |

一条可直接复制的串行验证（PowerShell）：

```powershell
$base = "http://localhost:8000/api"
$flow = Invoke-RestMethod "$base/flows" -Method Post -ContentType "application/json" -Body '{"name":"验收流程"}'
$run  = Invoke-RestMethod "$base/flows/$($flow.id)/run" -Method Post -ContentType "application/json" -Body '{"inputs":{"query":"你好"}}'
Start-Sleep -Milliseconds 300
Invoke-RestMethod "$base/runs/$($run.id)/cancel" -Method Post -ContentType "application/json" -Body '{}' | Select-Object status, outputs
```

期望最后一行 `status : cancelled`、`outputs :`（空）。

### C. 前端联调判断点（R1 前端切片完成后）

| 检查 | 期望 |
|---|---|
| 编辑器改节点配置，停手 1 秒 | 顶部 `v1` 徽标**不变**（自动保存只写内容） |
| 点「发布」 | 徽标变 `v2`，且校验不通过的流程发布被拦下并提示 |
| 运行抽屉「指标」页 | token / 成本来自 `/api/runs/{id}/stats`，节点维度有耗时 |
| 运行中点停止 | 3 秒内状态变「已取消」，日志不再滚动 |
| 运行历史页 | 可按流程筛选，不只是状态 |
| 终态 run 的回放页 | 事件表加载完不会一直转圈 |

## R2 · 后端执行引擎（B2） + 前端 Schema 对接

状态：待做。验收清单在本轮结束时补。

## R3 · 工具层（B3） + 工具管理页

状态：待做。

## R4 · LangGraph（B4）

状态：待做。

## R5 · MCP + RAG + Skill（B5） + 知识库页

状态：待做。

## R6 · 评测与部署（B6） + 评测页

状态：待做。
