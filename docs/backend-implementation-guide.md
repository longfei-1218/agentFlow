# 后端实现步骤（AgentFlow Studio · FastAPI + Python）

> 严格对齐技术设计文档 v1.1 的数据模型、API 契约与分层架构，按 P1–P5 分阶段落地，每阶段附可验证标准。
> 分层原则：API 层只做校验/CRUD/触发/SSE；编译器只做 DSL→StateGraph；执行引擎不认识 HTTP；工具层屏蔽 FC/MCP/Skill 差异；可观测只收集事件不改变执行。

---

## P1 骨架阶段：工程搭建 + Flow CRUD + SSE 基础

### 阶段目标
完成后端工程骨架、数据库设计、流程全量 CRUD、SSE 事件推送基础能力，打通与前端的数据通路。

### 步骤 1：环境与项目初始化
```bash
mkdir agentflow-backend && cd agentflow-backend
python -m venv .venv
# Windows: .venv\Scripts\activate   # Mac/Linux: source .venv/bin/activate
pip install fastapi uvicorn aiosqlite pydantic-settings sse-starlette python-multipart
pip freeze > requirements.txt
```

### 步骤 2：目录结构
```
app/
├── main.py              # 应用入口，挂载路由、全局异常、lifespan
├── config.py            # 环境变量、全局配置
├── database.py          # SQLite 异步连接与建表
├── models/              # Pydantic 模型（与前端逐字段对齐）
│   ├── flow.py           # Flow / FlowNode / FlowEdge
│   └── run.py            # Run / RunEvent / RunStatus
├── api/                  # REST 路由层
│   ├── flows.py
│   └── runs.py
├── services/
│   ├── flow_service.py   # 流程业务校验（环检测、孤立节点、必填项）
│   └── event_bus.py      # SSE 事件总线（asyncio.Queue）
└── db/init.sql
```

### 步骤 3：数据模型（对齐文档 4.1 / 4.2）
- `models/flow.py`：`NodeType` 字面量联合、`FlowNode`、`FlowEdge`、`Flow`，字段与前端 TypeScript 定义一一对应。
- `models/run.py`：`RunStatus` 枚举（pending / running / waiting_human / succeeded / failed / cancelled）、`Run`、`RunEvent`（`seq` 单调递增、`type`、`node_id`、`payload`、`created_at`）。

### 步骤 4：数据库层
- `database.py`：基于 `aiosqlite` 的异步连接，应用启动自动执行 `init.sql` 建表。
- `init.sql`：P1 核心三张表 `flows`、`runs`、`run_events`；表结构按可迁移设计，不使用 SQLite 专有语法。

### 步骤 5：API 路由（`api/flows.py`）
- `GET /api/flows` 列表；`POST /api/flows` 创建；`GET /api/flows/{id}` 详情；`PUT /api/flows/{id}` 更新；`DELETE /api/flows/{id}` 删除。
- `POST /api/flows/{id}/validate`：必填入口/出口节点、孤立节点检测、环检测。

### 步骤 6：SSE 事件总线基础
- `services/event_bus.py`：`asyncio.Queue` 发布订阅，按 `run_id` 隔离通道，支持多订阅者。
- `api/runs.py`：`GET /api/runs/{id}/events` 用 `sse-starlette` 推送；事件格式对齐文档 7.2；`seq` 排序去重，支持断线续传（`Last-Event-ID`）。

### 本阶段验证标准
- `/docs` Swagger 可打开，所有接口可调用。
- 流程增删改查持久化到 SQLite，重启不丢失。
- SSE 端点可连接并推送符合协议的测试事件。
- 非法 DSL 返回 422；校验接口可识别环与孤立节点。

---

## P2 核心执行阶段：手写 Agent Loop + 5 类核心节点

### 阶段目标
手写 Agent 循环调度，支持 `input / llm / prompt / condition / output`，SSE 实时推送全链路事件。

### 步骤 1：LLM 能力封装
- 安装 `openai langchain-openai tiktoken`。
- 统一 LLM 客户端，兼容 OpenAI 协议接口，支持流式输出与 token 统计；按模型单价估算输入/输出成本。

### 步骤 2：手写 Agent 执行引擎（核心必做，对齐文档 6.1）
- 新建 `app/engine/loop.py`，实现 `run_agent`：步数上限控制、工具调用分发、Pydantic 参数校验、异常捕获降级。
- 节点执行器注册表：每个节点类型对应独立执行函数。
- 流程拓扑解析器：按依赖关系串行调度。
- **先手写裸 Loop 跑通，P3 再迁 LangGraph**，保留手写版本作对照。

### 步骤 3：5 类核心节点
| 节点 | 实现要点 |
|---|---|
| input | 读取入参写入全局变量表，推送节点完成事件 |
| prompt | Jinja2 风格 `{{var}}` 模板渲染，变量插值校验 |
| llm | 调 LLM，流式 token 逐块推 SSE，统计 token 与成本 |
| condition | 表达式解析，判断 true/false 分支走向 |
| output | 提取变量表指定字段作为最终 outputs |

### 步骤 4：运行实例生命周期
- `POST /api/flows/{id}/run`：创建 Run，后台异步触发执行。
- 全流程生成 `RunEvent`，同时落库与推事件总线。
- `GET /api/runs/{id}` 返回状态、输入输出、成本统计；全局异常捕获，失败写 `error` 并推 `run_failed`。

### 步骤 5：基础可靠性
- 全局 `MAX_STEPS=8`，防无限循环烧钱。
- 节点异常不中断主进程，错误信息作为结果回写。

### 本阶段验证标准（对齐 6.1 三条用例）
1. 正常问答：LLM 正确返回，SSE 流式推 token。
2. 步数限制：`max_steps=1` 跑多轮任务，抛 `StepLimitExceeded`。
3. 异常容错：错误参数不崩进程，返回失败事件与错误详情。

---

## P3 工具与知识阶段：LangGraph 迁移 + 工具 / RAG / MCP / Skill

### 阶段目标
执行引擎迁移到 LangGraph，实现 `tool / mcp / skill / knowledge`，完成 RAG 与 MCP 接入。

### 步骤 1：迁移 LangGraph
- 安装 `langgraph langchain langchain-core`。
- 实现 `compile_flow`（对齐 6.2）：Flow DSL → `StateGraph`；定义 `AgentState`（`variables`、`messages`、`step_count`、`token_usage`、`cost`、`current_node`）。
- P2 五类节点适配为 LangGraph 节点函数；条件边、起止点完整映射；`SqliteSaver` 做 checkpointer。
- 对比迁移前后执行结果一致。

### 步骤 2：Tool 节点与 Function Calling
- `tools` 表 CRUD；参数用 JSON Schema 定义，执行前强校验。
- `asyncio.wait_for` 超时封装；指数退避默认重试 2 次；`tool_call_id` 作幂等键。
- **异常降级**：工具异常结果回写，不中断流程。

### 步骤 3：MCP 接入
- 安装 `mcp fastmcp`；`mcp_servers` 表 CRUD，支持 stdio / sse。
- `mcp` 节点运行时动态发现工具列表并调用；管理 MCP 子进程生命周期，异常自动回收。

### 步骤 4：Skill 子流程节点
- `skill` 节点：指定 Flow 编译为 LangGraph Subgraph 嵌入父流程。
- 输入输出参数映射，强校验输入；子流程事件透传主流程 SSE 链路。

### 步骤 5：RAG 知识库
- 安装 `chromadb langchain-chroma sentence-transformers`。
- 知识库 CRUD：创建、上传文档、分块向量化（chunk_size / overlap 可配）。
- `knowledge` 节点：向量召回、可选 rerank、返回 context；`POST /api/knowledge-bases/{id}/ingest` 入库。

### 本阶段验证标准
- 跑通「查知识库 → 调工具 → LLM 总结 → 输出答案」完整链路。
- 条件分支正确，循环节点有独立步数上限。
- MCP Server 可注册并动态发现工具；RAG 能召回私有文档指定内容。

---

## P4 可靠与评测阶段：可靠性增强 + v1.1 评测体系

### 阶段目标
补齐可靠性机制与人工审批；落地三层采集器、pass^k、一致性分布、每次成功成本、LLM 裁判校准、一键转 Case 与 CI 门禁。

### 步骤 1：可靠性机制
- 幂等：`tool_call_id` 幂等键，重试不重复扣费/下单。
- 断点续跑：checkpointer 持久化 GraphState 快照。
- `human` 节点：挂起 Run，状态置 `WAITING_HUMAN`；`POST /api/runs/{id}/resume` 审批后续跑；`POST /api/runs/{id}/cancel` 取消。

### 步骤 2：运行历史与回放
- 历史列表按状态/时间/流程筛选；单 Run 事件按 `seq` 排序回放；按节点统计耗时、token、成本。

### 步骤 3：评测数据模型（对齐 4.3 / 10.2.2）
- 表：`eval_sets`（含 `rubric_version`）、`eval_results`（含 pass^k 与成本指标）、`eval_trials`（`result_id, case_id, trial`，含 `outcome_ok / tool_ok / judge_score / steps / tokens / cost / trace_ref`）。
- `EvalCase`：`input`、`expected_outcome`、`required_tools`、`forbidden_tools`、`rubric`。
- `Score`：`case_id`、`trial`、`outcome_ok`、`tool_ok`、`judge_score`、`steps`、`tokens`、`cost`。

### 步骤 4：三层采集器（对齐 10.2.3）
- **结果层 Outcome**：查最终状态不轻信自述；`expected_outcome` 终态断言。
- **轨迹层 Trajectory**：复用 `run_events`；必要工具集合包含检查（非序列比对）、禁止工具零命中、参数 Schema 校验。
- **系统层 System**：从 `runs` 聚合 steps / token / cost / 延迟；重点算**每次成功成本**（总成本 ÷ 成功次数）。

### 步骤 5：可靠性指标 pass^k（对齐 10.2.4）
- 每个 case 跑 `K=3` 次；`pass_power_k` = 三次全过的 case 占比。
- 报告同时输出：任务成功率（headline，会高估可靠性）、pass^3、工具调用正确率、一致性分布（每 case 通过次数直方图）、每次成功成本。

### 步骤 6：LLM 裁判（对齐 10.2.5）
- 仅评代码评不了的主观维度；judge 用与被评 Agent 不同模型族、`temperature=0`；输出结构化 JSON（score / pass / evidence）。
- 版本化：judge model / prompt / rubric / 输出格式一起版本化；人工校准 20 条样本，分歧率 < 15%，分歧可追溯到 rubric 条款。

### 步骤 7：评测 API 与生命周期
- `CRUD /api/eval-sets`；`POST /api/eval-sets/{id}/run`（参数 `repeats=k`，返回指标与 trial 明细）。
- `POST /api/runs/{id}/to-case`：失败 Run 一键转 Case。
- `POST /api/eval/compare`：两次结果按 flow_version / prompt 版本对比；`GET /api/eval-sets/{id}/report` 导出 HTML/JSON 报告（含准确率 vs 成本曲线）。

### 步骤 8：CI 发布门禁（对齐 10.2.8）
- 硬门禁：任务成功率 ≥ 0.85；`pass^3` ≥ 0.70；工具调用正确率 ≥ 0.95。
- 软门禁：每次成功成本 ≤ baseline × 1.2（告警不阻断）。

### 本阶段验证标准
- 10 个 case × 3 次：报告同时出现 `pass^3` 与一致性分布，不只有单一成功率。
- judge 与人工同批 20 条打分，分歧率 < 15%，分歧定位到 rubric 条款。
- `forbidden_tools` 设常用工具时 `tool_ok` 必须为 False。
- 调低 max_steps 跑全套：成功率与成本同步变化，可画出 Pareto 曲线。
- 失败 Run 可一键转 Case；CI 门禁能阻断成功率与工具正确率回归。

---

## P5 部署阶段：容器化打包

### 实现步骤
1. 后端 Dockerfile：Python 3.11 基础镜像，uvicorn 启动，非 root 运行。
2. `docker-compose.yml` 含 backend 服务；SQLite / Chroma 挂 volume 持久化。
3. README 含本地开发与容器启动说明。

### 验证标准
- 新环境 `docker compose up backend` 正常启动；重启后流程、运行记录、知识库数据不丢失。
