# agentFlow · AgentFlow Studio

Web 端 Agent 编排平台（本地单用户原型）：画布拖拽定义执行拓扑 → 右侧配置参数 → 运行并实时观测 token / 工具调用 / 中间结果 → 用评测集做回归。

**当前进度：R1 完成**（后端地基 + 前端对接版本语义、运行观测、历史回放）。
下一步 R2：执行引擎（节点 Schema 化 + LLM 配置 + 手写 Agent Loop）。

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
agentflow-frontend/                   React + TS + Vite + React Flow 前端
```

---

## 环境要求

| 项 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+（实测 3.13.14） | 后端 |
| Node.js | 18+ | 前端，`npm` 随装 |
| 端口 | 8000 / 5173 | 后端 / 前端 dev |

首次准备：

```powershell
cd agentflow-backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

cd ..\agentflow-frontend
npm install
```

---

## 启动（两个终端）

### 终端 1 · 后端 `http://localhost:8000`

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

- 健康检查：`http://localhost:8000/api/health` → `{"status":"ok","version":"1.1"}`
- Swagger：`http://localhost:8000/docs`
- 数据库：`agentflow-backend/data/agentflow.db`（首次启动自动建表，含 8 张表）
- `--reload` 只影响代码热加载；跑压测或测取消行为时建议去掉

> macOS / Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

### 终端 2 · 前端 `http://localhost:5173`

```powershell
cd agentflow-frontend
npm run dev
```

打开 `http://localhost:5173`，会自动跳到 `/flows`。Vite 把 `/api` 代理到 `http://localhost:8000`，所以**不需要配 CORS、也不要把后端地址写进前端代码**。

前端页面：

| 路由 | 页面 |
|---|---|
| `/flows` | 流程列表（新建 / 复制 / 删除 / 导入导出 JSON） |
| `/flows/:id` | 编辑器（左节点库 / 中画布 / 右配置面板 + 底部运行抽屉） |
| `/runs` | 运行历史（按流程 / 状态筛选） |
| `/runs/:id` | 运行回放（事件时序 + 节点耗时 + 审批卡） |
| `/tools` `/knowledge` `/eval` | 资源与评测（R3 / R5 / R6 逐步实装） |

---

## 配置（可选）

复制 `agentflow-backend/.env.example` 为 `agentflow-backend/.env`：

```ini
DATABASE_PATH=./data/agentflow.db
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_DEFAULT_MODEL=gpt-4o-mini
MAX_STEPS=8
DEMO_STEP_DELAY=0.05
CORS_ORIGINS=["http://localhost:5173"]
```

| 变量 | 作用 |
|---|---|
| `LLM_API_KEY` | R2 起真实调用模型；R1 的执行器不读它（走确定性演示桩） |
| `DEMO_STEP_DELAY` | 演示执行器每步延迟（秒）。想验证「停止」按钮，设成 `0.5` 再启动 |
| `MAX_STEPS` | Agent Loop 步数上限，防无限循环烧钱 |

`.env` 不提交；R2 会加 `PUT /api/settings/llm`，可在 Swagger 里直接填 key，不必改文件。

---

## 验证

```powershell
# 后端：15 个用例，覆盖版本语义、SSE 终态、取消、审批续跑、序号恢复
cd agentflow-backend
.venv\Scripts\python.exe -m pytest

# 前端：类型检查 + 生产构建
cd ..\agentflow-frontend
npm run typecheck
npm run build
```

逐轮手工验收步骤见 **[docs/acceptance.md](docs/acceptance.md)**：R1 已给出可复制的 curl/PowerShell 命令与界面判断点。

---

## 两端启动后的最小闭环（3 分钟）

1. `http://localhost:5173/flows` → 右上「新建流程」→ 自动生成 `input → llm → output`。
2. 编辑器里改 System Prompt，停手约 1 秒 → 顶部 `v1` **不变**（草稿自动保存不动 version）；点「发布」→ 变 `v2`。
3. 点「运行」→ 底部抽屉实时滚出 `run_started / node_started / token / run_completed`，输出页能看到流式文本与最终 outputs。
4. 切「指标成本」→ 出现按节点聚合的 Token / 耗时 / 成本表（数据来自 `GET /api/runs/:id/stats`）。
5. 打开「运行历史」→ 按流程筛选 → 点「回放」看到完整 13 条事件时序，加载完自带结束，不会一直转圈。
6. 想让审批卡出现：画一条 `input → human(人工) → output`，运行后状态变「等待审批」，点「批准并续跑」→ 变「成功」。

---

## 技术栈

前端 React 18 · TypeScript · Vite 6 · React Flow 12 · Zustand · Tailwind · RHF + Zod · fetch-event-source
后端 Python 3.13 · FastAPI · aiosqlite（SQLite + WAL）· sse-starlette · orjson

## 路线图

| 轮次 | 后端 | 前端 |
|---|---|---|
| **R1 ✅** | Flow CRUD + 版本语义、SSE、取消/续跑、测试基座 | 发布/问题面板、流式输出、指标、历史筛选、回放 |
| R2 | 节点 Schema 化、LLM 配置、手写 Agent Loop | 配置面板改拉后端 Schema |
| R3 | 工具层（超时 / 重试 / 幂等） | 工具管理页 |
| R4 | LangGraph 编译 + checkpointer | 中断续跑状态机 |
| R5 | MCP + RAG + Skill | 知识库页 |
| R6 | 评测体系 + Docker | 评测页 |
