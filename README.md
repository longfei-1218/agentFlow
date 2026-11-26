# agentFlow · AgentFlow Studio

Web 端 Agent 编排平台（本地单用户原型）：画布拖拽定义执行拓扑 → 右侧配置参数 → 运行并实时观测 token / 工具调用 / 中间结果 → 用评测集做回归。

**当前进度：R2 完成**（节点 Schema 化 + LLM 系统配置 + 手写 Agent Loop 真流式运行）。
下一步 R3：工具层（函数调用 CRUD + 超时/重试/幂等）。

---

## 目录

```
docs/
  agent-orchestrator-tech-design.md   技术设计 v1.1（数据模型 / API / 评测体系）
  agentflow-studio-ui.html            前端 UI 静态稿（浏览器直接打开，6 页可切换）
  backend-implementation-guide.md     后端实现步骤（P1–P5）
  frontend-implementation-guide.md    前端实现步骤（P1–P5）
  acceptance.md                       每轮验收清单（命令 + 期望结果）
agentflow-backend/                    FastAPI + SQLite + SSE 后端
  app/nodes/registry.py               11 类节点的配置模型（JSON Schema 的唯一定义处）
  app/engine/loop.py                  手写 Agent Loop（真调模型 + MAX_STEPS 守卫）
  tools/fake_llm.py                   本地假模型（OpenAI 兼容，仅离线验收用）
agentflow-frontend/                   React + TS + Vite + React Flow 前端
```

---

## 环境要求

| 项 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+（实测 3.10.10 与 3.13.18 均通过） | 后端 |
| Node.js | 18+ | 前端，`npm` 随装 |
| 端口 | 8000 / 5173 | 后端 / 前端 dev |

首次准备（**只在一个干净的 `.venv` 上做一次**）：

```powershell
cd agentflow-backend
py -3.10 -m venv .venv          # 或 python -m venv .venv，用你 PATH 上的 3.10+
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

cd ..\agentflow-frontend
npm install
```

> ⚠️ **不要在已有 `.venv` 上重复执行 `python -m venv .venv`**。它不会清空 `Lib\site-packages`，只会替换 `pyvenv.cfg` 和 `Scripts\python.exe`，结果就是「3.10 的解释器 + 之前 3.13 装的依赖」，一 import 就报错（典型是 `ImportError: cannot import name 'Self' from 'typing'`）。
> 要换解释器版本，先 `Remove-Item -Recurse -Force .venv` 再重建，然后重装依赖。

---

## 启动（两个终端）

### 终端 1 · 后端 `http://localhost:8000`

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

- 健康检查：`http://localhost:8000/api/health` → `{"status":"ok","version":"1.1"}`
- Swagger：`http://localhost:8000/docs`
- 数据库：`agentflow-backend/data/agentflow.db`（首次启动自动建表，含 8 张表）
- **`--reload-dir app` 别去掉**：默认 `--reload` 会监视整个后端目录（含 `.venv`、`data`），一旦 `.venv` 里有大量文件变动（重装依赖、删虚拟环境），reload 会卡死甚至留下僵尸进程占着 8000 端口。

> macOS / Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

### 终端 2 · 前端 `http://localhost:5173`

```powershell
cd agentflow-frontend
npm run dev
```

打开 `http://localhost:5173`（`http://127.0.0.1:5173` 同样可用），会自动跳到 `/flows`。Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，所以**不需要配 CORS、也不要把后端地址写进前端代码**。

> 代理目标故意写 `127.0.0.1` 而不是 `localhost`：Windows 上 `localhost` 常先解析到 IPv6 `::1`，而 uvicorn 默认只监听 IPv4，会表现为「页面能开、接口一直转圈到超时」。`vite.config.ts` 里已加 `server.host: true`，让 5173 同时接受 IPv4/IPv6。

前端页面：

| 路由 | 页面 |
|---|---|
| `/flows` | 流程列表（新建 / 复制 / 删除 / 导入导出 JSON） |
| `/flows/:id` | 编辑器（左节点库 / 中画布 / 右配置面板 + 底部运行抽屉） |
| `/runs` | 运行历史（按流程 / 状态筛选） |
| `/runs/:id` | 运行回放（事件时序 + 节点耗时 + 审批卡） |
| `/tools` `/knowledge` `/eval` | 资源与评测（R3 / R5 / R6 逐步实装） |

全局弹层：右上「模型设置」——填 Base URL / 默认模型 / API Key，可测连通、可清空 Key。未配置时顶部有黄色提示，点运行会被后端 409 拦下并自动弹出该弹层。

---

## 配置模型（R2 起必须做，否则含 `llm` 节点的流程会被 409 拦下）

**推荐：界面里配**。启动后点右上角「模型设置」，填 Base URL / 默认模型 / API Key → 「测试连接」→ 保存。
Key 只存后端数据库（`settings` 表），界面只回脱敏预览（`sk-a…3456`），优先级 **界面配置 > `.env` > 空**。

| 场景 | Base URL | API Key | 模型 |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `sk-...` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `sk-...` | `deepseek-chat` |
| 本地假模型（无 Key 也能验流式） | `http://127.0.0.1:8899/v1` | 任意非空 | `fake-model` |

本地假模型必须单独起一个进程（**只是开发桩，不配 Key 也不会自动降级到它**）：

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn tools.fake_llm:app --port 8899
```

也可以不用界面，直接写 `agentflow-backend/.env`（复制 `.env.example`）：

```ini
DATABASE_PATH=./data/agentflow.db
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_DEFAULT_MODEL=gpt-4o-mini
MAX_STEPS=8
RUNNER=loop
DEMO_STEP_DELAY=0.05
CORS_ORIGINS=["http://localhost:5173"]
```

| 变量 | 作用 |
|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_DEFAULT_MODEL` | 模型初始配置；界面上保存过之后就以界面为准 |
| `MAX_STEPS` | **模型调用次数**上限（不是节点数），防模型被工具结果喂进无限循环 |
| `RUNNER` | `loop` = 真调模型；`demo` = 确定性桩（不联网，用于回归） |
| `DEMO_STEP_DELAY` | 节点间停顿（秒）。想验证「停止」按钮，设成 `0.5` 再启动 |

---

## 验证

```powershell
# 后端：32 个用例，覆盖版本语义、SSE 终态、取消、审批续跑、序号恢复、节点 Schema、Key 脱敏、MAX_STEPS 守卫、模型名不匹配时的可读报错、并发保存的乐观锁
cd agentflow-backend
.venv\Scripts\python.exe -m pytest

# 前端：类型检查 + 生产构建
cd ..\agentflow-frontend
npm run typecheck
npm run build
```

逐轮手工验收步骤见 **[docs/acceptance.md](docs/acceptance.md)**：R1 已给出可复制的 curl/PowerShell 命令与界面判断点。

---

## 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| 启动即 `ImportError: cannot import name 'Self' from 'typing'`（栈里是 `websockets`/`uvicorn`） | 解释器与依赖版本错配（多半是对旧 `.venv` 重跑了 `python -m venv`）。删掉 `.venv` 重建并重装依赖 |
| `ModuleNotFoundError: No module named 'app'` | 没在 `agentflow-backend` 目录下启动 uvicorn |
| 运行返回 409 `LLM_NOT_CONFIGURED` | 还没配模型。点右上「模型设置」填 Base URL / Key / 模型，或用 `.env` |
| 运行 500 且 error 里是 `模型接口返回 4xx` | Base URL 少了 `/v1`、Key 无效、模型名不存在 |
| 报错说「你传了 gpt-4o-mini，但网关只支持 X」 | **节点里写死了模型名**，节点级模型优先于系统设置。打开编辑器选中该「模型」节点，点红字「点此改为跟随系统默认」即可；新建流程默认已留空 |
| 明明改好了、再运行又变回旧配置 | 是**旧标签页**把它覆盖回去了。现在 `PUT` 带 `baseUpdatedAt`，过期会被 409 `FLOW_STALE` 拒绝并自动重载；界面还显示旧值就按 `Ctrl+R` 刷新 |
| 改了后端代码但行为没变 | `--reload` 在这台机器上偶发不生效（日志有 `Reloading` 但子进程没换），手动重启后端 |
| 前端页面能开但接口 502 / 一直转圈到超时 | ①后端没起或没监听 8000；②代理走了 `::1`（见上文说明） |
| 8000 端口显示在监听、但所有请求都超时 | 僵死的 reloader 占着端口、子进程已挂。按命令行找出并杀掉：`Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Select ProcessId,CommandLine` |
| 端口被占 | `Get-NetTCPConnection -LocalPort 8000` 查进程，`Stop-Process -Id <pid>` |
| 运行没有流式 token | 正常：R1 的执行器是本地演示桩，不调模型。R2 接真实 LLM 后才有真 token |

---

## 两端启动后的最小闭环（3 分钟）

1. `http://localhost:5173/flows` → 右上「模型设置」→ 填 Base URL / Key / 模型 → 「测试连接」通过 → 保存。顶部黄色「未配置模型」消失。
2. 右上「新建流程」→ 自动生成 `input → llm → output`。左侧节点库的 11 类节点由后端 Schema 下发，工具/控制类带「占位」标。
3. 编辑器里改 System Prompt，停手约 1 秒 → 顶部 `v1` **不变**（草稿自动保存不动 version）；点「发布」→ 变 `v2`。
4. 点「运行」→ 底部抽屉逐块滚出**真实模型**的 token（`node_completed` 里带 `usage`），顶部显示「模型调用 1/8」。
5. 切「指标成本」→ Token 用量与节点表合计一致；点「刷新指标」拉 `GET /api/runs/:id/stats`。
6. 打开「运行历史」→ 按流程筛选 → 点「回放」看到完整事件时序、节点耗时、终态不转圈。
7. 想让审批卡出现：画一条 `input → human → output`，运行后状态变「等待审批」，点「批准并续跑」→ 变「成功」。

---

## 技术栈

前端 React 18 · TypeScript · Vite 6 · React Flow 12 · Zustand · Tailwind · RHF + Zod · fetch-event-source
后端 Python 3.10+ · FastAPI · aiosqlite（SQLite + WAL）· sse-starlette · orjson · httpx（模型流式调用，不引 openai SDK）<br>
依赖版本说明：`uvicorn>=0.30,<0.35` + `websockets>=12,<13`。uvicorn 0.35+ 换用的 websockets-sansio 需要 `websockets>=14`，而它依赖 `typing.Self`（3.11+），在 3.10 上启动即崩，所以锁在这个区间；用 3.11+ 解释器时可以放开。

## 路线图

| 轮次 | 后端 | 前端 |
|---|---|---|
| **R1 ✅** | Flow CRUD + 版本语义、SSE、取消/续跑、测试基座 | 发布/问题面板、流式输出、指标、历史筛选、回放 |
| **R2 ✅** | 节点 Schema 注册表、`/api/settings/llm`、OpenAI 兼容流式、手写 Agent Loop + `MAX_STEPS` 守卫 | 节点库/配置面板改吃后端 Schema、模型设置弹层、未配置拦截与引导、节点数 vs 模型调用数拆分 |
| R3 | 工具层（超时 / 重试 / 幂等） | 工具管理页 |
| R4 | LangGraph 编译 + checkpointer | 中断续跑状态机 |
| R5 | MCP + RAG + Skill | 知识库页 |
| R6 | 评测体系 + Docker | 评测页 |
