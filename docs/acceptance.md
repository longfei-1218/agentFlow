# 验收清单（按轮次）

> 每轮结束都补齐本节内容：**自动化命令 + 手工步骤 + 期望结果 + 联调判断点**。
> 约定：后端命令都在 `agentflow-backend/` 下执行，前端都在 `agentflow-frontend/` 下执行。

## 环境准备（只做一次）

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## R1 · 后端地基（B1） + 前端对接版本语义

状态：**已完成**（后端 + 前端切片，均已实测）

### 0. 这轮改了什么

后端：`RunManager`（真取消）、`state_json` 快照真续跑、`seq` 从库恢复、共享连接 + 写锁、`PUT` 不递增版本 + `/publish`、`[]` 与 `null` 语义区分、SSE 终态自关、`/runs` 多条件筛选、`/runs/{id}/stats`。
前端：发布按钮与版本语义、422 逐条问题面板（可点节点定位）、AutoSave 状态、流式 token 追加输出区、执行步数、`/stats` 节点指标表、运行历史流程筛选与耗时/输入摘要、回放页节点耗时与审批卡、流程 404 空态。

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

前端：

```powershell
cd agentflow-frontend
npm run typecheck   # 期望无输出
npm run build       # 期望 "✓ built in ..."，只有 chunk >500kB 的提示
```

### B. 后端手工（Swagger `http://localhost:8000/docs`）

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

### C. 前端联调（需两端都启动）

```powershell
# 终端 1
cd agentflow-backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 终端 2
cd agentflow-frontend; npm run dev
```

| 检查 | 期望 | 本轮实测 |
|---|---|---|
| 编辑器改配置后停手 | 顶部 `v1` 不变，出现「自动保存中…」再消失 | ✅ 运行后仍为 `v1` |
| 点「发布」 | 徽标变 `v2`；校验不过则顶部红条列出问题 | ✅ `v1 → v2`，无报错 |
| 运行抽屉「输出结果」 | 运行中逐字追加 token 文本（带光标），结束后显示 JSON | ✅ 得到「你好，这是 流式 token 输出。」+ outputs |
| 运行抽屉「指标成本」 | 节点表：每节点 Token / 耗时 / 成本 | ✅ input_1 350ms、llm_1 10 tokens、output_1 73ms |
| 运行中点「停止」 | 3 秒内变「已取消」，步骤数与日志停止增长 | ✅ 运行中 → 已取消，步骤冻在 2 |
| `input → human → output` 运行 | 抽屉弹审批卡并显示节点配置的提示文案 | ✅ 显示「确认允许高风险工具调用？」 |
| 点「批准并续跑」 | 状态变「成功」，步骤 +1 | ✅ 等待审批 → 成功，步骤 3 |
| 运行历史按流程筛选 | 下拉列出流程名与版本，表格有流程名/输入摘要/耗时 | ✅ 3 条记录、流程名正确 |
| 终态 run 回放页 | 事件表直接加载完（13 条），不转圈 | ✅ 13 条事件 + 节点维度卡片 |
| 访问不存在的流程 | 显示「流程加载失败 + 返回列表 / 重试」 | ✅ 不再永久停在「加载流程中」 |

> 想复现「停止」逐帧效果：用 `DEMO_STEP_DELAY=0.5` 启动后端，运行会持续约 3 秒。
> PowerShell：`$env:DEMO_STEP_DELAY="0.5"; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`

### D. 已知说明

- 演示执行器（`app/engine/demo_runner.py`）不调 LLM，token 是固定片段；R2 换成真实流式后才会有真实内容与成本。
- 浏览器控制台偶发 `WebSocket ws://127.0.0.1:5173 failed`：这是 dev server 被重启后 HMR 套接字残留，刷新页面即消失，与业务代码无关。


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
