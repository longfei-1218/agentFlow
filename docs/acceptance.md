# 验收清单（按轮次）

> 每轮结束都补齐本节内容：**自动化命令 + 手工步骤 + 期望结果 + 联调判断点**。
> 约定：后端命令都在 `agentflow-backend/` 下执行，前端都在 `agentflow-frontend/` 下执行。

## 环境准备（只做一次）

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 环境自检（2026-11-26 修复过一次启动崩溃）

本次事故：对已有 `.venv` 重跑 `python -m venv .venv`，解释器被换成 3.10，但 `Lib\site-packages` 还是 3.13 时代装的包，启动时报 `ImportError: cannot import name 'Self' from 'typing'`。

已做的修复，四项都要在：

| 项 | 判断方法 | 期望 |
|---|---|---|
| venv 解释器 | `.venv\Scripts\python.exe -V` | `Python 3.10.10`（3.10+ 均可） |
| 依赖无错配 | `pip list` 里 `websockets` / `uvicorn` | `12.0` / `0.34.3`（requirements 已锁区间） |
| 代码无 3.11 专有语法 | `Select-String -Path app\*.py,app\**\*.py -Pattern StrEnum` | 无命中（已改成 `str, Enum`） |
| 启动参数 | 后端启动命令 | 必须带 `--reload-dir app` |

重建 venv 的正确姿势（换解释器版本时）：

```powershell
Remove-Item -Recurse -Force .venv
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
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

状态：**已完成**（后端 + 前端切片，均已实测；实跑数据见下表「本轮实测」）

### 0. 这轮改了什么

后端：`app/nodes/registry.py`（11 类节点各一个 Pydantic 配置模型 → 反推 JSON Schema，同一份定义同时用于导出与校验）、`GET /api/node-types`、`settings` 表 + `GET/PUT /api/settings/llm`、`POST /api/settings/llm/test`、`app/services/llm.py`（OpenAI 兼容流式 + usage/成本校准）、`app/engine/loop.py`（手写 Agent Loop，`MAX_STEPS` 守卫 `StepLimitExceeded`）、`app/engine/common.py`（与 demo 共用的拓扑/状态/终态件）、`app/engine/executor.py`（`RUNNER=demo|loop` 选择）、未配置 Key 时运行返回 **409 `LLM_NOT_CONFIGURED`**。
前端：删掉 `src/registry/nodes.ts`（硬编码注册表），改为 `store/nodeTypeStore.ts` 从后端拉；Palette / 画布 / 配置面板 / 新增节点默认值全部吃后端 Schema；新增「模型设置」弹层（脱敏 Key、测试连接、保存）；顶部与编辑器出现「未配置模型」入口，运行被 409 拦下时自动弹设置；运行面板把「节点数」与「模型调用数」拆开显示。

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest          # 期望 32 passed（R1 的 15 + R2 新增 14 + 模型名/并发保存修复 3）

cd ..\agentflow-frontend
npm run typecheck                           # 期望无输出
npm run build                               # 期望 ✓ built
```

新增用例守什么：

| 用例文件 | 它守的是什么 |
|---|---|
| `test_node_types.py` | 11 类节点 Schema 齐全、`/node-types` 与注册表一致、坏配置能被校验逐条报出（nodeId + 字段） |
| `test_settings.py` | Key 只写不返回（只给 `sk-a…3456` 脱敏）、省略不动 / 空串清空、DB 配置压过 `.env`、连不通时给可读原因不抛 500 |
| `test_loop.py` | 真流式的 token 帧与 usage 校准（9 tokens 不多不少）、prompt 插值真的进了模型消息、`MAX_STEPS=1` 跑两段模型必失败且服务不崩、未配 Key 时 409 且无模型节点的流程照常能跑、审批中断续跑在 loop 下同样成立、**节点写死网关不认的模型时报错要说清「哪个模型/哪个节点/怎么改」** |
| `test_settings.py`（新增 1 条） | `GET /api/settings/llm/models` 会把网关列表和「当前默认模型是否被支持」一起给出；网关报错时返回 `ok:false` 而不是 500 |
| `test_flows.py`（新增 1 条） | **过期保存必须被挡住**：两个标签页拿同一个 `baseUpdatedAt` 先后 PUT，第二个回 409 `FLOW_STALE`，且服务端内容不被覆盖；不带 `baseUpdatedAt` 的老调用仍兼容 |

### B. 页面验收（**先看这节：打开哪个页面，验哪些功能**）

前置：两端都起（命令见根 README）。示例流程用 `flow_3c2a0e36`（input → llm → output），你自己的流程换成对应 id 即可。

| # | 打开哪个页面 | 做什么 | 期望 | 本轮实测 |
|---|---|---|---|---|
| 1 | `http://localhost:5173/flows` | 看右上角三个 chip | 「节点类型 **11**」；顶部有「模型设置」按钮 | ✅ 11、按钮在 |
| 2 | `http://localhost:5173/flows/flow_3c2a0e36` | 看左侧「节点库」 | 四组（基础/模型/工具/控制）共 11 项，与后端 `GET /api/node-types` 完全一致；tool / mcp / skill / knowledge / condition / loop 带**「占位」**小标 | ✅ 11 项、6 个占位标 |
| 3 | 同上，点画布里的「模型」节点 | 看右侧配置面板 | 面板标题下方出现后端给的节点描述「调用 OpenAI 兼容接口，流式吐 token」；表单字段 = 后端 Schema：**模型 / Temperature / Max tokens / System Prompt**，URL 里没加载完时不会出现空白面板 | ✅ 4 字段 + 描述 + `llm.config.v1` |
| 4 | 同上，**未配置 Key** 时看编辑器顶部 | 找黄色 chip | 显示「未配置模型 · 点此设置」；点它就打开设置弹层 | ✅ 出现并可点 |
| 5 | `http://localhost:5173/flows/{id}` 未配置 Key 时点「运行」 | 看顶部红条 + 弹层 | 红条写「尚未配置 LLM API Key，请先在「模型设置」里填写后再运行」；**设置弹层自动打开**；后端返回 409 而非创建一条必然失败的 run | ✅ 409 + 自动弹层 + 文案命中 |
| 6 | 任意页面右上「模型设置」 | 填 Base URL / 模型 / Key，点「测试连接」 | 成功显示「连接正常，可用模型 N 个（xx ms）」；失败显示具体原因（不弹 500）；来源行显示 `.env` / `界面配置` | ✅ 「连接正常，可用模型 1 个（56 ms）」 |
| 7 | 同一个弹层 | 保存后看 Key 输入框与来源 | 输入框被清空并提示「已存 sk-f…1234，留空则不修改」；来源变「界面配置」；**页面上任何地方都看不到明文 Key** | ✅ 脱敏 + 来源切换 |
| 8 | 回到编辑器，配好之后点「运行」 | 看「实时日志」 | `run_started → node_started → 一串 token（文本逐块出现）→ node_completed → run_completed`；llm 节点的 `node_completed` 里带 `usage`（provider 真实用量） | ✅ 25 条事件，逐块流式 |
| 9 | 运行抽屉切「指标成本」 | 看四张卡与节点表 | Token 用量 = 节点表 Token 之和（**不能两套数字**）；「模型调用」= `1 / 8`（8 = `MAX_STEPS`）；「节点执行」= 3；llm 节点耗时约 1s | ✅ Token 39 = 39；模型调用 1/8；节点 3 |
| 10 | `http://localhost:5173/runs/{runId}` | 回放页 | 事件按序加载完（不转圈）、节点维度卡有耗时/token、终态显示「成功」 | ✅ 事件 25 条、llm_1 983ms/39 tokens |
| 11 | 编辑器新建/拖一个节点 | 看默认配置 | 新节点默认值来自后端 `defaultConfig`（不是前端抄的一份）；`llm` 节点的「模型」默认是**空**（= 跟随系统默认），新建流程不会再带上某个厂商的模型名 | ✅ 空值 + 下拉显示「跟随系统默认」 |
| 12 | `http://localhost:5173/flows/{id}`，选中「模型」节点 | 看「模型」字段 | 是**下拉**不是输入框：第一项「跟随系统默认（当前默认模型）」，后面是网关 `/models` 返回的真实模型名；下方有一行「节点级模型优先于系统默认」 | ✅ 跟随 deepseek-flash / deepseek-flash / deepseek-v4-pro |
| 13 | 同上，节点里残留旧模型名（如 `gpt-4o-mini`） | 看红字 | select 里出现 `gpt-4o-mini（网关不支持）` 并提示「当前值 gpt-4o-mini 不在网关支持列表，点此改为跟随系统默认」；点一下即清空并自动保存，红字消失 | ✅ 点击后 select 回到「跟随系统默认」、后端 config `model` 为空 |
| 14 | 同上，点「运行」 | 看输出 | 用全局默认模型跑通（`state.model` = 默认模型）；若仍不匹配，`run_failed.error` 会自带「节点 llm_1 的配置里写死了模型 X，节点级模型优先于系统默认；把它清空就跟随…」 | ✅ deepseek-flash 跑通、107 tokens、¥0.000482 |
| 15 | **多标签页回滚**：两个标签页开同一条流程，A 页清空节点模型并等「已保存」，B 页（没有改动、状态是旧的）点「运行」 | 服务端配置是否被 B 页回滚 | B 页**不应该**把旧配置写回：`GET /api/flows/{id}` 的 `updatedAt` 不变、`model` 仍为空；B 页跑出来的 `state.model` 是全局默认模型 | ✅ 界面点运行后 `updatedAt` 未变、`model` 仍为空、run 成功 |
| 16 | 上面 B 页切回前台（点一下另一个窗口再回来） | 是否自动同步 | 未保存改动为 0 时，页面会静默重新加载成服务端最新内容（节点模型显示「跟随系统默认」）；有未保存改动时不动 | ✅ 焦点回来即刷新 |
| 17 | 强制让本地版本过期：A 页改点东西但别等保存，同时在别处 `PUT` 同一条流程，再让 A 页保存 | 冲突提示 | 顶部出现「该流程在别的窗口或标签页被修改过，已重新加载最新内容，本次修改没有覆盖上去」；服务器内容仍是别人的最新版本 | ✅ 409 `FLOW_STALE` + 自动重载 |

**只验后端、不打开页面的最快方式**：`http://localhost:8000/docs` →
`GET /api/node-types`（11 项）、`GET /api/settings/llm`（Key 只有脱敏预览）、`PUT /api/settings/llm`、`POST /api/settings/llm/test`。

### C. 没有真实 Key 时怎么验（本地假模型）

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn tools.fake_llm:app --port 8899
```

然后在「模型设置」里填：

| 字段 | 值 |
|---|---|
| Base URL | `http://127.0.0.1:8899/v1` |
| API Key | 任意非空（如 `sk-fake`） |
| 默认模型 | `fake-model` |

它只做两件事：`/v1/models` 返回一个假模型、`/v1/chat/completions` 逐字吐 SSE 并在最后一帧带 `usage`。
**它是开发桩，不是产品降级逻辑**：不配置就 409，绝不会偷偷返回假数据。

### D. 口径与已知说明

- **`MAX_STEPS` 数的是模型调用次数**，不是节点数：3 节点流程只算 1 步。要复现拦截，画两段 `llm` 串联并把 `MAX_STEPS` 调成 1，第二次调用会失败为 `run_failed{code:STEP_LIMIT_EXCEEDED}`，服务本身不受影响。
- **Token 会先估算后校准**：流式为实时性按字符估算（中文 1 字≈1 token），provider 返回 `usage` 后会补一帧差额（可能是负数），所以运行中看到的数字在结束时可能**回落**到真实值。最终 `runs.token_usage` 与 `/stats` 汇总保持一致。
- **占位节点不假装执行**：R2 期间 tool 会发 `tool_call` / `tool_result`（标注 `stub:true`）；**R3 起 tool 已经是真执行**，`stub` 字段不再出现。mcp / skill / knowledge / condition / loop 仍发 `node_completed{skipped:true}`，留到 R4–R5；`/api/node-types` 里 `implemented:false` 是同一事实的另一处体现。
- **后端 `--reload` 在这台机器上偶发不生效**（WatchFiles 打印 Reloading 但子进程没换）。改了 `app/` 下的代码后如果行为没变，直接重启后端，不要怀疑代码。
- **「模型」字段的优先级是：节点 config > 系统设置 > `.env`**。节点里留空才会走系统默认。默认模板已经改成留空；但如果你的流程是 R2 早期建的，节点里可能还留着 `gpt-4o-mini`，换成 DeepSeek 网关就会 400 —— 选中节点点一下红字那行即可修正。
- **网关模型列表来自 `GET /api/settings/llm/models`**（后端打一次 `/models`）。网关不实现该接口时下拉退回手填输入框，不影响保存与运行。
- **别在两个标签页里同时编辑同一条流程**。编辑器会自动保存整份 DSL，早先的实现是「点运行先无条件 save()」，一个开着不动的旧页面足以把别处改好的配置原地覆盖（本次 400 反复出现就是这么来的）。现在两道闸：`PUT` 带 `baseUpdatedAt`，过期回 409 `FLOW_STALE` 并自动重载；点运行时只在 `dirty` 为真才保存。改完配置如果界面没变化，先按 `Ctrl+R` 刷新页面再验。


## R3 · 工具层（B3） + 工具管理页

状态：**已完成**（后端 + 前端切片 + 真 FC 联调，均已实测）

### 0. 这轮改了什么

后端：新增 `app/models/tool.py`（ToolDef / 内置工具 Schema / 调用记录 / 试跑请求）、`app/services/tool_repo.py`（tools 与 tool_invocations 存取，**老库自动补列**，不用删库）、`app/services/tool_runner.py`（参数校验 → 幂等查缓存 → 带超时重试调用 → 落记录；内置 echo/now/calc 与 HTTP 两种实现）、`app/api/tools.py`（CRUD + `/{id}/test` + `/invocations` + `/builtins`）。

`app/services/llm.py`：`stream_completion` 支持 `tools`，并按 index 累积**分片**的 `delta.tool_calls`，整轮结束交出组装好的调用列表；参数分片的 token 也计入用量。`app/engine/loop.py`：llm 节点实现真 Function Calling 回路（模型要工具 → 执行 → 回填 tool 消息 → 再问一次），**MAX_STEPS 改成逐轮计数**；tool 节点改成真执行；工具错误在 FC 里回给模型、在 tool 节点里让 run 失败。`GET /api/node-types` 增加 `toolsCount`。

前端：新增 `api/tools.ts`、`store/toolStore.ts`、`components/tools/ToolEditorModal.tsx`、`components/tools/ToolTestModal.tsx`；`pages/ToolsPage.tsx` 从占位页改成真页面（列表 / 新建 / 编辑 / 试跑 / 调用记录 / 删除）；`ConfigPanel` 把 tool 节点的 `tool_id` 换成注册表下拉、llm 节点新增「绑定工具」勾选；`Shell` 启动加载工具清单。tool 节点在节点库不再带「占位」标。

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest          # 期望 43 passed（32 + R3 新增 11）

cd ..\agentflow-frontend
npm run typecheck                           # 无输出
npm run build                               # ✓ built
```

| 用例文件 | 守的是什么 |
|---|---|
| `test_tools.py`（11 条） | 工具 CRUD 与重名 409、内置工具 Schema 由后端覆盖、**必填参数缺失被拒**、503 连击按 retries 重试到第 3 次成功、**4xx 绝不重试**、幂等第二次命中且只打一次网络、tool 节点真执行并落调用记录（无 `stub`）、工具不存在时 run 失败且 code 可读、**FC 两轮回路**（工具结果作为 tool 消息回填）、**FC 轮次计入 MAX_STEPS**、两次 run 的 state 不共享（DEFAULT_STATE 浅拷贝踩坑） |

### B. 页面验收（**先看这节：打开哪个页面，验哪些功能**）

库里已备好：工具 `echo`（内置）、`now_time`（内置）；流程
- `flow_921e8b49`「R3 工具节点演示」：input → tool(echo, `{"text":"{{query}}"}`) → output
- `flow_fd2812d1`「R3 FC 演示（模型自选工具）」：input → llm(绑定 echo) → output

| # | 打开哪个页面 | 做什么 | 期望 | 本轮实测 |
|---|---|---|---|---|
| 1 | `http://127.0.0.1:5173/tools` | 看工具表 | 2 个工具，类型 builtin、目标 `builtin:echo` / `builtin:now`、超时/重试、幂等 `key·600s`、风险、启用状态齐全 | ✅ 2 条 |
| 2 | 同页，点「新建工具」 | 选「内置」→ 选 `calc` → 保存 | 列表 +1，名称即模型看到的 function name；参数 Schema 由后端给（只读展示） | ✅ 保存成功、Schema 只读 |
| 3 | 同页，随便一个工具点「试跑」 | 直接点「执行一次」 | 成功、尝试 **1** 次、耗时、结果 JSON；缺必填参数时给出「缺少必填参数: text」 | ✅ `{"echo":"test"}` |
| 4 | 同页试跑弹层 | 勾「走幂等缓存」→ 连点两次「执行一次」 | 第二次显示**幂等命中**、尝试 **0** 次、结果与第一次一致 | ✅ 尝试 0 / 幂等命中 |
| 5 | 同页新建 HTTP 工具 | URL 填 `http://127.0.0.1:9/x`、超时 500ms、重试 0 → 试跑 | 失败但不弹 500：显示状态、尝试 1、`HTTP 或连接失败` 原因，方便判断是不是超时设小了 | ✅ 可读失败原因 |
| 6 | 同页「最近调用记录」 | 看刚跑出来的行 | `tool_1` / `llm_1` 两种来源、attempts、耗时、幂等「命中」、可点 runId 跳到回放 | ✅ 三行、命中行 attempts 0 |
| 7 | `http://127.0.0.1:5173/flows/flow_921e8b49` | 选中画布里的「工具」节点 | 配置面板的「工具」是**注册表下拉**（echo · 内置 / now_time · 内置），不是手填 id；`参数模板` 是 JSON 文本域，插值示例在说明里 | ✅ 下拉 + `tool.config.v1` |
| 8 | 同页点「运行」 | 实时日志 | `tool_call`（`source:"node"`、带 args）→ `tool_result`（`ok:true`、`latencyMs`、`attempts`）；**没有 `stub`**；输出是 `{"echo": ...}` | ✅ 事件链路完整 |
| 9 | `http://127.0.0.1:5173/flows/flow_fd2812d1` | 选中「模型」节点 | 「绑定工具」是勾选列表，`echo` 已勾；底部写「已绑定 1 个 · 工具失败不中断运行」 | ✅ 勾选状态正确 |
| 10 | 同页点「运行」 | 运行面板 + 日志 | 「模型调用 **2/8**」（FC 两轮）；日志里 `tool_call` 的 `source:"llm"` 且带 `callId`，随后 `tool_result` 是 echo 的结果；最终答案基于工具返回内容 | ✅ 2/8、1274 tokens、¥0.0042 |
| 11 | `http://127.0.0.1:5173/runs/{runId}` | 回放 | 工具事件按 seq 出现在时间线里，终态「成功」 | ✅ |
| 12 | `http://127.0.0.1:8000/docs` | 接口自查 | `GET /api/tools`、`GET /api/tools/builtins`、`GET /api/tools/invocations`、`POST /api/tools`、`POST /api/tools/{id}/test`、`GET /api/node-types`（`toolsCount`） | ✅ 路由齐全 |

**最快只验后端**：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/tools/builtins
Invoke-RestMethod "http://127.0.0.1:8000/api/tools/invocations?limit=5"
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/tools/{id}/test -Method Post -ContentType application/json -Body '{"args":{"text":"hi"}}'
```

### C. 口径与已知说明

- **超时 / 重试 / 幂等是「工具定义」的属性，不是节点属性**：同一个工具在任何流程里行为一致。节点只填 `tool_id` 与参数模板。
- **重试只发生在「可重试」的失败上**：连接错误、超时、5xx 重试；**4xx 立即失败**（参数/鉴权问题重试只是重复挨骂）。
- **幂等 key = sha1(工具 id + 排序后的参数)**，TTL 内同参数直接复用上次成功结果，记一行 `idemHit=true / attempts=0`。它证明的是「重复调用不会重复执行」，不是业务幂等（订单去重那种要业务自己给幂等键）。
- **工具失败的两种处理**：`tool` 节点失败 → 整个 run 失败（`TOOL_NOT_FOUND` / `TOOL_ARGS_INVALID` / `TOOL_TIMEOUT` / `TOOL_INVOKE_FAILED`），错误里带节点 id；FC 里的工具失败 → 作为 `tool` 消息回给模型，让它自己改参数重试，run 继续（失败同时出现在「调用记录」里）。
- **FC 的每一轮模型调用都算一步**：`MAX_STEPS=1` 时第二轮会被拦，错误文案写明「已进行 N 轮工具调用」。
- **工具执行没有沙箱**：HTTP 工具能打任意地址（这是本地原型，别指向不可信内网）。`high` 风险工具请在流程里加 human 节点审批。
- MCP server 列表页与 mcp 节点仍是 R5；knowledge / skill / condition / loop 仍是占位。

## R4 · LangGraph（B4）

状态：**已完成**（图执行器 + 条件边 + 有界循环 + checkpointer 中断续跑，真实网关实测）

### 0. 这轮改了什么

后端：
- `app/engine/graph_runner.py`（新）：把 DSL 编译成 `StateGraph`。普通边按 DSL 连，`condition` / `loop` 用条件边路由，`human` 停在检查点上等人批；节点包装仍发 R1 那套 `node_started / node_completed / tool_*` 事件，**前端不需要区分谁在跑**。
- `app/engine/expr.py`（新）：条件表达式求值。`{{var}}` 先替换成 Python 字面量（字符串带引号、数字原样），再过 AST 白名单（只允许比较/布尔/四则/下标），禁函数调用与属性访问；变量缺失、语法错、类型错都给可读文案。
- `app/engine/executor.py`：`RUNNER=graph|loop|demo`，默认 `graph`；`app/config.py` 同步默认值。
- `app/nodes/registry.py`：`condition` / `loop` 的 `implemented` 改 true；`InputConfig.default` 改为 `Any`（原来写死 `str`，声明 `type=number` 的入参会校验失败）。
- `app/services/flow_service.py`：`loop` 必须有 `body` 分支连线；环检测改为「忽略以 loop 节点为终点的回边」，合法循环不再被误判成环。
- `app/services/llm.py` + `app/engine/loop.py`：支持 `reasoning_content` / `reasoning` 分片（推理模型的思维链单独透出、照样计费）；节点完成事件带 `reasoningChars` / `finishReason`，正文为空时按「思维链吃满预算」或「撞 Max tokens 被截断」给不同 `hint`（附 `emptyAnswer`）。
- `app/api/nodes.py`：`GET /api/node-types` 增加 `engine` / `engines`。

前端：
- `utils/flow.ts`：连线标签按 `sourceHandle` 显示（真/假/循环体/退出）。
- `FlowNodeView`：`loop` 节点变成两个出口锚点 `body`（蓝）/ `done`（绿）。
- `flowStore.onConnect` 接受 loop 的 `body/done`，新增 `updateEdgeHandle`（改分支归属不用删线重拉）。
- `ConfigPanel`：`condition` / `loop` 节点新增「分支连线」下拉，缺分支直接标黄提示。
- `Topbar` / `RunDrawer`：显示当前引擎（LangGraph / 手写 Loop）与本次运行的引擎徽标；输出页对「思维链吃满预算」的空回答显示警告条。

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest          # 54 passed（43 + 图执行器 9 + 空回答诊断 2）

cd ..\agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit   # 无输出
node node_modules\vite\bin\vite.js build        # ✓ built
```

| 用例 | 守的是什么 |
|---|---|
| `test_graph.py`（9 条） | 图引擎线性流程的 token/usage/engine、**条件只走一条分支**（真/假参数化）、表达式变量缺失的可读报错、循环体按 `max_rounds` 跑满再退出、退出条件为真提前退出、**暂停/续跑**（checkpoint 落库、续跑不重复 `node_started`）、取消后状态不被改写回 succeeded、`node-types` 的 engine 与控制节点 implemented |
| `test_loop.py` 新增 2 条 | ①只有思维链、正文为空：必须给 `reasoningChars` + `emptyAnswer` + 思维链口径的 `hint`；②`finish_reason="length"` 且正文为空：`finishReason` 要落库、`hint` 要说「撞到 Max tokens 被截断」。两种情况都不能静默吞掉 |

### B. 页面验收（**先看这节：打开哪个页面，验哪些功能**）

库里已备好三条 R4 演示流程（都在真实 DB 里，可直接点运行）：

| 流程 | id | 结构 |
|---|---|---|
| R4 分支演示（condition 真/假） | `flow_1c485778` | input(score) → condition(`{{score}} > 0.8`) →（真）prompt_high → llm_high /（假）prompt_low → llm_low → output |
| R4 循环演示（有界 3 轮） | `flow_43e2f4ba` | input(query) → loop(max_rounds=3) → body: prompt(第 {{loop_round}} 轮) → llm → 回到 loop → done: output |
| R4 中断续跑演示（human 审批） | `flow_78b1ae68` | input(query) → human → output(approved, query) |

| # | 打开哪个页面 | 做什么 | 期望 | 本轮实测 |
|---|---|---|---|---|
| 1 | 任意页看右上角 | 找引擎 chip | 显示「引擎 LangGraph」；`GET /api/node-types` 里 `engine="graph"`、`engines` 含 graph/loop/demo | ✅ |
| 2 | `http://127.0.0.1:5173/flows/flow_1c485778` | 选中「分支」节点 | 右侧有**两个锚点**（真=绿、假=红）；配置面板出现「分支连线」，两条出边分别标注真/假，可下拉改归属；缺分支会标黄 | ✅ |
| 3 | 同页点「运行」，输入 `score` 填 `0.95` | 看日志 | `condition_1` 的 `node_completed` 带 `branch:"true"`；只出现 `llm_high` 的 `node_started`，`llm_low` **一次都没跑**；模型调用 1/8 | ✅ run_e5805207：branch=true、steps=1、180 tokens |
| 4 | 同页再运行，`score` 填 `0.2` | 看日志 | `branch:"false"`，只跑 `llm_low`，答案是安慰+建议的语气 | ✅ run_487b7061：branch=false、255 tokens |
| 5 | `http://127.0.0.1:5173/flows/flow_43e2f4ba` | 选中「循环」节点 | 两个锚点 body / done；配置面板「分支连线」里 body 必填、done 可选；`最大轮次 3`、`退出条件` 留空 | ✅ |
| 6 | 同页点「运行」 | 看日志与运行面板 | `loop_1` 连续 3 次 `node_completed`（round 1/2/3，前两次 `branch:"body"`、最后一次 `"done"`）；模型调用 **3/8**（每轮一次）；最后一轮文本进输出 | ✅ run_de643d5e：3 轮、steps=3、647 tokens、输出「第3轮：…」 |
| 7 | 同页把「退出条件」改成 `{{loop_round}} >= 2` 再运行 | 看日志 | 只跑 2 轮就走 done（退出条件优先于最大轮次） | 口径已由单测覆盖 |
| 8 | `http://127.0.0.1:5173/flows/flow_78b1ae68` 点运行 | 看运行面板 | 状态变「等待审批」，出现紫条 `human_required`，日志停在 human_1 | ✅ run_c540fe3f：waiting_human、`state.human_pending=human_1` |
| 9 | 同页点「批准并续跑」 | 看日志 | 变「成功」；输出 `{"approved": true, "query": "…"}`；**`human_1` 的 `node_started` 只有一条**（重入不重复发） | ✅ |
| 10 | `http://127.0.0.1:5173/flows/flow_921e8b49`（R3 工具流程） | 直接运行 | 引擎换成 graph 后工具节点照旧：`tool_call(source:"node")` → `tool_result` → 输出 echo 结果 | ✅ run_ad1bb110 |
| 11 | `http://127.0.0.1:5173/flows/flow_fd2812d1`（R3 FC 流程） | 直接运行 | 模型调用 **2/8**、`tool_call(source:"llm")` + `tool_result`、最终答案基于 echo 结果 | ✅ run_3becaf9c：steps=2、953 tokens、¥0.002502 |
| 12 | 随便一个 llm 流程，把 Max tokens 调到 `8` 再运行 | 看「输出结果」页 | 正文为空时顶部出黄色警告条，文案分两种：预算被 `reasoning_content` 吃满（「模型把输出预算用在了推理内容上…」）或被截断（「撞到 Max tokens 上限…」）；节点完成事件里有 `finishReason`，token 帧里有 `reasoning` | ✅ 旧案 run_78d8d9da（128 tokens 恰好用完、正文空）；新证据 run_15dfce1b：`reasoningChars=136`、`finishReason=stop`、381 个思维链帧 → 该类模型确实先花预算在思维链上 |
| 13 | `http://127.0.0.1:8000/docs` | 接口自查 | `/api/node-types` 带 `engine`；checkpoint 表由 `langgraph-checkpoint-sqlite` 自动建在同一个 SQLite 里 | ✅ |

**最快只验后端**：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/node-types | Select-Object engine,engines
# 条件分支：同一个流程两次运行，branch 分别是 true / false
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/flows/flow_1c485778/run -Method Post -ContentType application/json -Body '{"inputs":{"score":0.95}}'
```

### C. 口径与已知说明

- **事件协议没变**：图执行器复用 `_run_llm_node` / `_run_tool_node`，`node_started` / `token` / `tool_call` / `tool_result` / `human_required` 与 R3 完全一致，前端只是多了「引擎」标识。
- **两处状态都是真的**：`runs.state_json` 是给我方回放/续跑读的；LangGraph 的 `checkpoints` 表是图引擎自己的断点。续跑时先看 `run.state.human_pending` 找被暂停的节点，再把 state 用 `aupdate_state` 灌回图里，然后 `ainvoke(None)` 从断点继续。
- **为什么不用官方 `interrupt()`**：它内部 `get_config()` 依赖 langchain-core 的 contextvar，而 Python 3.10 没有 `asyncio.create_task(context=...)`，异步节点的 config 上下文进不去，调用必抛 `RuntimeError: Called get_config outside of a runnable context`（langgraph 0.2 / 0.3 都能复现）。改成本项目自己的「抛异常暂停 + aupdate_state + ainvoke(None)」，语义一样是真中断，且不依赖 3.11。
- **condition 表达式**：`{{score}} > 0.8`、`{{name}} == "张三"`、`{{done}} == true`；变量先渲染成字面量，所以字符串不用自己加引号；只允许比较/布尔/四则/下标，出现函数调用会被拒。变量没被上游写入时报「表达式引用了不存在的变量」并列出可用变量。
- **loop 语义**：`max_rounds` 数的是**循环体执行次数**（3 表示循环体跑 3 次）；每进一次 loop 节点先判断退出（已跑满或退出条件为真），否则计一轮并走 `body`。`body` 分支必须连线，`done` 可缺省（缺省即流程结束）。回边（目标为 loop 节点的边）不算非法环。
- **superstep 上限**：`_recursion_limit` 按节点数 + 最大轮次算（封顶 500）。触发时报 `GRAPH_RECURSION_LIMIT`，文案直接说「多半是回边没在 max_rounds 内退出」。
- **并行分支暂不支持**：一个普通节点连多条出边会 fan-out，两条分支共享同一份 state 会互相覆盖。当前用条件边做互斥分支是安全的；真正的并行扇出留到 R5。
- **推理模型**：`deepseek-flash` 实测会先输出思维链（`run_15dfce1b` 里 381 个 `reasoning` 帧、136 字），`completionTokens` 被它吃掉时正文就是空串——`run_78d8d9da` 把 `max_tokens=128` 恰好用完、正文为空，调大后正常。现在节点完成事件带 `reasoningChars` 与 `finishReason`，token 帧带 `reasoning`，输出页对空正文出警告条；两种成因（思维链吃满 / `length` 截断）提示文案不同，照着提示调 `Max tokens` 即可。
- **依赖坑**：`pip install langgraph` 会把 `websockets` 顶到 16 并卸载 12，uvicorn 0.34 在 3.10 上随即起不来；同时 `langsmith` 声明需要 `websockets>=15`，pip 会报一条冲突警告（本项目不用 LangSmith tracing，忽略即可）。装完务必补一句 `pip install "websockets>=12,<13" "aiosqlite==0.21.0"`。
- MCP / 子流程 / 知识库已在 R5 实装；`demo` 引擎保留给离线回归。

## R5 · MCP + RAG + Skill（B5） + 知识库页

状态：**已完成**（MCP stdio 客户端 + 知识库切块/BM25/MMR + 子流程内联，4 条真实流程跑通真实网关）

### 0. 这轮改了什么

后端：
- `app/models/mcp.py` / `app/services/mcp_repo.py`（新）：MCP Server 定义只允许 `stdio`（command/args/env/cwd/timeout/enabled），`mcp_servers.definition_json` 是唯一真相，name/command/enabled 只是冗余列。
- `app/services/mcp_client.py`（新）：**同步 `subprocess.Popen` + 线程 + `asyncio.to_thread`** 实现 JSON-RPC 会话（`initialize` → `notifications/initialized` → `tools/list` / `tools/call`），`threading.Timer` 做 watchdog 超时 kill，stderr 后台线程收集末 3 行拼进错误。**不能用 `asyncio.create_subprocess_exec`**：Windows + uvicorn 的 SelectorEventLoop 会直接 `NotImplementedError`。
- `app/api/mcp.py`（新）：`/api/mcp-servers` CRUD + `GET /{id}/tools`（探测）+ `POST /{id}/call`（试跑）。探测/试跑失败也回 **200 + `ok:false` + 错误码**，前端不用靠 500 猜原因。
- `app/models/knowledge.py` / `app/services/knowledge_repo.py` / `app/services/knowledge_rag.py`（新）：知识库与文档 CRUD、切块（按句切 → 按字数打包 → 超长句带 overlap 硬切）、中文按**字符 bigram**、英文按词、BM25（k1=1.2 / b=0.75）、可选 MMR 去冗余（0.7 相关性 − 0.3 与已选片段的 Jaccard）。空库/无命中都带可执行的 `hint`；全零分不硬凑结果。
- `app/engine/extra_nodes.py`（新）：`run_mcp_node`（发 `tool_call` / `tool_result`，`source:"mcp"`，写 `variables.result`、`mcp_calls`）、`run_knowledge_node`（渲染 query 模板，写 `context` / `citations` / `knowledge_calls`，发 `knowledge_retrieved`）、`run_skill_node`（校验 flow_id、自递归、3 层深度、子流程含 human → 拒绝；`inputs_template` 插值；跑完把子流程 outputs 合并进父变量并写 `result` JSON）。
- `app/engine/subflow.py`（新）：用 `MemorySaver` **内联编译**子流程（`emit_events=False, persist_state=False`），因此子流程不落 `runs` 表、不发 SSE、不占 run 名额；tokens/cost 回传给父节点累计。
- `app/engine/graph_runner.py` / `app/engine/loop.py`：两种引擎都接上 mcp / knowledge / skill；`PLACEHOLDER_NODES` 清空（graph 侧只剩 condition/loop 的特判）；`extra_nodes.NodeError` 统一落 `run_failed` 并带 `code + nodeId`。
- `app/services/event_bus.py`：`run_id` 为空时**只返回临时事件、不写 `run_events`、不推 SSE**——子流程复用节点实现的关键，否则外键校验直接失败。
- `app/db/init.sql` + `app/database.py`：新增 `mcp_servers.definition_json`、`kb_documents`、`kb_chunks`（+ 索引），老库按 `PRAGMA table_info` 补列不删数据。
- `app/nodes/registry.py` / `app/api/nodes.py`：mcp/skill/knowledge `implemented=true` 并补必填项；`/api/node-types` 多给 `mcpServersCount` / `knowledgeBasesCount`，配置面板据此显示「还没有可选项」。
- `scripts/mcp_demo_server.py`（新）：纯标准库的最小 MCP stdio server（`echo` / `add` / `now`），联调和验收都用它，不依赖 npx/网络。

前端：
- `src/api/mcp.ts` / `src/api/knowledge.ts` / `src/store/mcpStore.ts` / `src/store/knowledgeStore.ts`（新）：类型与请求封装，探测结果按 serverId 缓存。
- `src/pages/McpPage.tsx`（新）：左表右表单。注册/编辑（名称、命令、args JSON、超时、启用）、**探测工具**、工具下拉 + 参数 JSON 试跑（按 `inputSchema` 生成示例参数）、结果/错误码展示。
- `src/pages/KnowledgePage.tsx`（重写）：新建知识库（chunkSize/overlap）、列表（docCount/chunkCount）、加文档（标题+正文，显示字数）、删文档、召回测试（query/topK/rerank，展示分数、片段、hint、引擎）。
- `src/components/flow/ConfigPanel.tsx`：新增三个引用选择器——`MCPRefField`（server 下拉 + 探测后 tool 下拉，探测失败允许手填）、`KnowledgeRefField`（kb 下拉 + 空库引导）、`SkillRefField`（流程下拉、排除当前流程、显示版本）；三个模板字段（`args_template` / `query_template` / `inputs_template`）改用多行输入。
- `src/components/layout/Sidebar.tsx` / `src/App.tsx`：资源组新增「MCP 服务」，挂 `/mcp` 路由。
- `src/types/run.ts` / `src/components/flow/RunDrawer.tsx`：新增 `knowledge_retrieved` 事件与青色徽标。
- `src/pages/ToolsPage.tsx`：底部卡片从「R5 未实装」改成「R5 已实装」并跳 `/mcp`。

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest          # 66 passed（约 24s；54 + MCP 5 + 知识库 4 + 子流程 3）

cd ..\agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit   # 无输出
node node_modules\vite\bin\vite.js build        # ✓ built（仅 chunk>500kB 的既有告警）
```

| 用例 | 守的是什么 |
|---|---|
| `test_mcp.py`（5 条） | 真起子进程完成 `initialize/tools/list/tools/call`（`add 19+23=42`）；命令不存在时回 `MCP_SPAWN_FAILED` 而不是 500；流程里的 mcp 节点发 `tool_call/tool_result(source=mcp)` 并写 `result`；空 server_id 时 run 失败且带 `MCP_NOT_CONFIGURED`；**停用的 Server 运行期被拒**（「停用」开关不是摆设） |
| `test_knowledge.py`（4 条） | 文档切块 + 检索排序（相关块排第一）+ rerank 不改变「有结果」的事实；空库搜索给可执行 hint；knowledge 节点把 `context/citations` 注入下游变量；删文档后 `docCount/chunkCount` 重算 |
| `test_skill.py`（3 条） | 子流程 outputs 合并进父变量且 tokens 计入父 run；flow_id 指向自己时被 `SKILL_RECURSION` 拦下；子流程含 `human` 被 `SKILL_HUMAN_UNSUPPORTED` 拒绝 |
| `test_node_types.py` / `test_graph.py` | mcp/skill/knowledge 的 `implemented` 翻成 true 后，Schema 与图引擎执行仍然一致 |
| `tests/conftest.py` | 每用例重建 `db._write_lock` / `event_bus._lock` 并重置 SSE 全局状态，teardown 先 `run_manager.shutdown()` 再关库——修掉跨用例「Lock bound to a different event loop」与僵尸 run |

### B. 页面验收（**先看这节：打开哪个页面，验哪些功能**）

本机库里已备好（可直接点，不用重建）：

| 对象 | id | 内容 |
|---|---|---|
| MCP Server | `mcp_20261126_153603b785` | `demo-mcp`：venv python 跑 `scripts/mcp_demo_server.py`，tools = echo/add/now，timeout 20s |
| 知识库 | `kb_20261126_154242d719` | `售后知识库`：chunk 300 / overlap 40，3 篇文档（退款政策、发票说明、配送说明），3 chunks |
| 流程 | `flow_03b8009e` | `R5 MCP 直连演示`：input → mcp(now) → output(result) |
| 流程 | `flow_3fc2aca8` | `R5 知识库问答演示`：input → knowledge({{query}}, top3, rerank) → prompt(资料+问题) → llm(0.2/512) → output(text) |
| 流程 | `flow_47c506fe` | `R5 子流程-润色`：input → prompt(改客服口吻) → llm → output(text) |
| 流程 | `flow_9ef0ee08` | `R5 子流程调用演示`：input → skill(调上面的润色) → output(text,result) |

| # | 打开哪个页面 | 做什么 | 期望 | 本轮实测 |
|---|---|---|---|---|
| 1 | `http://127.0.0.1:5173/mcp` | 看左侧列表 | 有 `demo-mcp`：命令是 `.venv\Scripts\python.exe`，参数指向 `scripts\mcp_demo_server.py`，超时 20，状态「启用」 | ✅ |
| 2 | 同页选中 `demo-mcp` 点「探测工具」 | 看工具清单 | 出 `echo / add / now` 三个工具，各带描述与参数 Schema；探测耗时几百毫秒 | ✅ `ok=true`、374ms、3 个工具 |
| 3 | 同页工具选 `add`，参数填 `{"a":19,"b":23}` 点「试跑」 | 看结果 | 返回 `42`；失败会显示错误码而不是 HTTP 500 | ✅ `ok=true`、result=42 |
| 4 | 同页「注册 Server」新建一个测试项：命令填 `agentflow-not-a-command`，点探测（验完删掉） | 看错误 | 红色提示 `MCP_SPAWN_FAILED`，文案说「找不到命令，检查是否在 PATH」；HTTP 仍是 200，不是 500 | ✅ 实测同一文案 |
| 5 | `http://127.0.0.1:5173/knowledge` | 选中「售后知识库」 | 文档 3 / 片段 3；三篇文档都在列表里，可删 | ✅ |
| 6 | 同页底部「召回测试」填 `退款多久到账`、topK 3 | 看命中 | 第一条是「退款政策」片段，分数 `5.5097`，`tookMs=0`、`totalChunks=3`、引擎 `bm25` | ✅ 实测 1 条命中、5.5097 |
| 7 | 同页勾上「MMR 重排」再搜一次 | 看结果 | 结果不空、顺序稳定；同义重复块会被压掉（本例只有 1 条命中，主要靠单测覆盖多块去冗余） | ✅ 接口返回 `rerank:true` |
| 8 | 同页「添加文档」贴一段新内容 | 看计数 | `docCount/chunkCount` 立即 +1（长文按 300 字切多块）；删掉它计数回落 | 口径已由单测覆盖 |
| 9 | `http://127.0.0.1:5173/flows/flow_03b8009e` | 选中 MCP 节点 | 配置面板是**下拉**：Server=`demo-mcp`、工具=`now`（点探测后才有工具选项）；参数模板 `{}` | ✅ |
| 10 | 同页点「运行」 | 看实时日志与输出 | `tool_call(source:"mcp")` → `tool_result(ok:true, latencyMs≈380)`；输出是带 `iso/timestamp` 的 JSON；模型调用 0 次 | ✅ run_866d73a8：`latencyMs=381`、`iso=2026-11-26T23:43:22+0800` |
| 11 | `http://127.0.0.1:5173/flows/flow_3fc2aca8` 点「运行」 | 看日志顺序 | `knowledge_retrieved`（kbId、query、hits、topScore、totalChunks）先出 → prompt → LLM → 输出；回答只依据资料并带 `[1]` 引用 | ✅ run_28684249：hits=1、topScore=5.5097、268 tokens；回答「微信 1–3 个工作日、银行卡最长 7 个工作日 [1]」 |
| 12 | 同页把问题改成资料里没有的（如「你们支持开专票吗」） | 看回答 | 模型说「资料里没有」，不编。知识节点仍会返回 hint；**不会**因为没命中就硬塞假片段 | 口径由 BM25「零分不硬凑」+ hint 保证 |
| 13 | `http://127.0.0.1:5173/flows/flow_47c506fe` 点「运行」 | 看输出 | 一句话客服口吻改写（子流程单独也能跑） | ✅ run_5ddf7b22：287 tokens |
| 14 | `http://127.0.0.1:5173/flows/flow_9ef0ee08` | 选中「子流程」节点 | 配置面板是**流程下拉**：列出可选的已保存流程、**不含当前流程**、带版本号；入参模板 `{"query": "{{query}}"}` | ✅ |
| 15 | 同页点「运行」 | 看日志与输出 | skill 节点只发一条 `node_completed`，payload 带 `skillFlow / skillFlowName / inputs / outputs / steps / tokens / cost / depth:1`；子流程的 `node_started` **不会**出现在父 run 的事件流里；父 run tokens = 子流程 tokens，但**父 run 的模型调用数仍是 0/8**（子流程的调用记在它自己的 steps 上） | ✅ run_15e557c9：depth=1、tokens=465、cost=0.00253、outputs.text 已合并为 `result`，父输出同时有 `text/result`、父 steps=0 |
| 16 | 同页把子流程节点指向自己（或指到含 human 的流程）再运行 | 看失败原因 | `run_failed` 带 `SKILL_RECURSION` / `SKILL_HUMAN_UNSUPPORTED`，文案说清是哪种禁止 | 口径已由单测覆盖（下拉已排除自身，需用 API 构造） |
| 17 | `http://127.0.0.1:5173/tools` | 拉到页面底部 | MCP 卡片写「R5 已实装」，点链接跳 `/mcp` | ✅ |
| 18 | `http://127.0.0.1:8000/docs` | 接口自查 | `/api/mcp-servers`、`/api/mcp-servers/{id}/tools`、`/api/knowledge`、`/api/knowledge/{id}/search` 都在；`/api/node-types` 带 `mcpServersCount=1`、`knowledgeBasesCount=1` | ✅ |
| 19 | `http://127.0.0.1:5173/mcp` 取消勾选 `demo-mcp` 的「启用」并保存 → 回 `flows/flow_03b8009e` 点运行（验完记得启用回来） | 看运行结果 | run 变成失败；`run_failed` 事件的 `payload.code = MCP_NOT_CONFIGURED`，`run.error` 文案是「已停用，先在 MCP 服务页启用」；**不会**偷偷调用 | ✅ run_b52a51bb：status=failed、payload.code=MCP_NOT_CONFIGURED、nodeId=mcp_1 |

**最快只验后端**：

```powershell
$base="http://127.0.0.1:8000/api"
# 1) 探测 + 试跑 MCP
Invoke-RestMethod "$base/mcp-servers/mcp_20261126_153603b785/tools" | Select-Object ok,latencyMs,@{n="tools";e={$_.tools.name}}
Invoke-RestMethod -Method Post -Uri "$base/mcp-servers/mcp_20261126_153603b785/call" -ContentType "application/json" -Body '{"toolName":"add","args":{"a":19,"b":23}}'
# 2) 知识库召回
Invoke-RestMethod -Method Post -Uri "$base/knowledge/kb_20261126_154242d719/search" -ContentType "application/json" -Body '{"query":"退款多久到账","topK":3,"rerank":true}' | Select-Object totalChunks,@{n="top";e={$_.hits[0].title}}
# 3) 跑 MCP 流程 / 知识库流程 / 父子流程
foreach($f in "flow_03b8009e","flow_3fc2aca8","flow_9ef0ee08"){
  Invoke-RestMethod -Method Post -Uri "$base/flows/$f/run" -ContentType "application/json" -Body '{"inputs":{"query":"退款多久到账"}}'
}
```

### C. 口径与已知说明

- **MCP 只支持 stdio**：command/args 直接起本机进程，等价于「允许这台机器执行这条命令」。本地单用户原型可以接受；远程 URL / SSE transport 会明确回 `MCP_TRANSPORT_UNSUPPORTED`，留到 R6 之后。每次探测/调用都新起进程（没有长连接池），冷启动实测 300–400ms，所以 `latencyMs` 里包含进程启动时间。
- **Windows 上的异步子进程坑**：`asyncio.create_subprocess_exec` 在 uvicorn 的 SelectorEventLoop 上必抛 `NotImplementedError`（`base_events._make_subprocess_transport`）。实现已改成同步 `Popen` 放线程里跑，超时用 `threading.Timer` kill，别改回去。
- **知识库不是向量库**：当前是 BM25 关键词检索，中文按字符 bigram 切词（「退款」→「退款」+ 相邻二元组），所以同义改写（「钱什么时候回来」）召回弱于原词命中。`embedding_model` 字段已预留，向量检索留到 R6 之后；`rerank` 是**零成本 MMR 去冗余**，不是模型重排。
- **切块参数影响观感**：默认 `chunk_size=400`；本次演示库用 300/40，三篇短文档各只切出 1 块，所以 `docCount=chunkCount=3`、召回只可能命中 1 条。想看多块排序，把文档写长一点或把 chunk 调到 120。
- **子流程语义**：内联执行、不建 run、不发事件、不写 checkpointer（`MemorySaver` 只在本进程内存里）；tokens/cost 累加进父 run，`steps` 是子流程内部完成的模型调用数，**不计入父 run 的 steps**（父子各自受 `MAX_STEPS` 约束，父流程不会因为多套一层就绕过上限）。嵌套上限 3 层，自递归直接拒；子流程里出现 `human` 也拒（父 run 没法替子流程接审批）。子流程按**当前保存的 DSL** 编译，改了子流程记得保存后再跑父流程。
- **事件协议只加不减**：新增 `knowledge_retrieved`；mcp 复用 `tool_call/tool_result` 并带 `source:"mcp"`；skill 复用 `node_completed` 并带 `skillFlow/depth/tokens`。前端 RunDrawer 靠这些字段展示，不需要新的抽屉。
- **失败口径**：mcp / knowledge / skill 节点本身失败 → 整个 run 失败（`run_failed` 带错误码与 `nodeId`）；探测、试跑、召回这些「配置期」接口失败仍回 200 + `ok:false`，方便前端就地提示。
- **`--reload` 又会骗人**：本轮改完 `mcp_client.py` 后探针仍报旧的 `NotImplementedError`，实际是 reloader 没换子进程。验收时若「代码明明改了但行为没变」，先按 README 的端口清理步骤杀掉 reloader + worker 再重启，别先怀疑实现。

## R6 · 评测与部署（B6） + 评测页

状态：待做。
