# AgentFlow v2 改造计划：Agent 作为一等资源

> 状态：步骤 1 数据重置、步骤 2 后端 Agent 层、步骤 3 Flow v2 编排与 Agent 对话、步骤 4 前端切换均已完成；后端全量 **58 passed**，真实 DeepSeek 冒烟覆盖串联/循环/条件/审批/会话隔离；前端 `tsc --noEmit` 与 `vite build` 通过，浏览器完成 Agent 新建/保存、Flow 两 Agent 映射运行、节点作用域对话（2026-11-27）。  
> **最终执行口径：不备份、不迁移旧流程、不做兼容；旧编排数据直接重置，资源库保留。以 §12 的五步为准。**  
> 目标：把「流程里的 prompt / llm / tool / mcp / knowledge 节点」收拢成一个可复用、可编辑、可对话的 **Agent 资源**；流程只负责编排 Agent。

## 0. 已确认的四个基线

| 决策 | 结论 |
|---|---|
| Agent 归属 | **全局 Agent 库**，多个流程引用同一个 `agentId`；改一次，所有引用生效 |
| 资源触发 | **混合模式**：`@` 强制；未 `@` 的 Tool/MCP 仍是模型的 FC 候选；知识库只有 `@` 才检索 |
| 变量/输出 | **类型化变量**（string/number/boolean/json，必选/可选/默认值）+ **可选输出 JSON Schema** |
| 旧流程 | **全量替换为 Agent 节点**；旧 R1–R5 流程做一次性迁移/归档，不再作为主要编辑对象 |

### 0.1 追加确认（本轮）

| 决策 | 结论 |
|---|---|
| Agent 引用方式 | **实时引用**：流程只存 `agentId`，Agent 改动立即影响所有引用；暂不做发布/版本锁 |
| Agent 对话历史 | **不全局共享**：作用域为 `agentId + flowId + nodeId`；从 Agent 库直接聊是 `agentId`，从流程节点聊是 `agentId + flowId + nodeId` |
| 条件/循环/审批 | **保留为编排节点**，只负责路由/循环/暂停，不塞进 Agent 内部 |

---

## 1. 目标形态

### 1.1 一个 Agent 包含什么

```json
{
  "id": "agent_xxx",
  "name": "售后知识库客服",
  "description": "只依据售后知识库回答退款、发票、物流问题；资料不足时明确说不知道。",
  "variables": [
    {
      "key": "query",
      "label": "用户问题",
      "type": "string",
      "required": true,
      "default": "",
      "description": "本轮用户输入"
    },
    {
      "key": "history",
      "label": "会话历史",
      "type": "string",
      "required": false,
      "default": "",
      "description": "同一会话的历史问答文本"
    }
  ],
  "prompt": {
    "system": "你是售后客服，回答简短、准确，只能使用提供的资料。",
    "template": "资料：\n@kb[售后知识库]\n\n历史：\n{{history}}\n\n用户问题：{{query}}"
  },
  "resources": [
    {
      "kind": "knowledge",
      "id": "kb_20261126_154242d719",
      "alias": "售后知识库",
      "queryVar": "query",
      "topK": 3,
      "rerank": true
    },
    {
      "kind": "tool",
      "id": "tool_xxx",
      "alias": "订单查询"
    },
    {
      "kind": "mcp",
      "id": "mcp_xxx",
      "alias": "售后 MCP",
      "tools": ["now", "add"]
    }
  ],
  "model": {
    "name": "",
    "temperature": 0.2,
    "maxTokens": 512,
    "maxToolRounds": 4
  },
  "output": {
    "description": "给下游 Agent 或用户看的最终回答",
    "schema": {
      "type": "object",
      "properties": {
        "text": { "type": "string" },
        "intent": { "type": "string" }
      },
      "required": ["text"]
    }
  }
}
```

约定：

- `description` 是资源目录/流程画布里展示的说明，不直接进入 prompt。
- `prompt.system` 是角色与硬约束；`prompt.template` 是任务模板，支持 `{{变量}}` 和 `@资源`。
- `variables` 是 Agent 的**输入契约**。流程里由上游映射填充；单 Agent 对话由表单 + 聊天消息填充。
- `output.schema` 为空时按 `{ "text": string }` 处理；有 schema 时做校验，失败重试一次后报 `AGENT_OUTPUT_INVALID`。
- `resources` 只存**引用**，不复制资源定义。资源库改名/改配置会同步影响 Agent；删除被引用的资源时，Agent 校验应报 `AGENT_RESOURCE_MISSING`，不能静默跑空。

### 1.2 Agent 内资源怎么触发

采用混合模式，规则必须可预测：

| 资源 | prompt 里没 `@` | prompt 里 `@` |
|---|---|---|
| Tool | 作为 FC 候选，模型可自选 | 强制作候选，并要求本轮至少调用一次 |
| MCP | 导入的工具作为 FC 候选 | 强制作候选，并要求本轮至少调用一次 |
| 知识库 | **不检索**，即使已导入 | 用 `queryVar` 检索，命中片段替换掉 `@kb[...]` 这个 token |

补充约束：

- `@kb[别名]` 是“在这里插入检索上下文”，不是普通文本；别名在 Agent 内唯一。
- Tool/MCP 的 `@` 不直接执行（参数需要模型填），而是进入 `force_tools`：
  - 只有一个强制工具时，请求里用 `tool_choice={"type":"function","function":{...}}`；
  - 多个强制工具时，用 `tool_choice="required"`，并在 prompt 末尾追加“必须调用 @ 的工具”；跑完检查调用记录，缺哪个就重试一次。
- 未 `@` 的工具仍是候选，由模型自己决定；这与“导入即自动使用”不同，避免 Agent 偷偷调用没在提示词里声明的能力。
- 每个 Agent 的 `maxToolRounds` 单独限制；整条流程仍有总预算，防循环。

### 1.3 Flow DSL v2

流程只保留**编排语义**，不再承载 prompt/llm/tool/kb 细节：

| 节点 | 作用 |
|---|---|
| `start` | 定义流程外部输入变量（必选/可选/类型） |
| `agent` | 引用一个全局 Agent，配置输入映射 |
| `condition` | 分支（沿用现有表达式求值与 true/false 出口） |
| `loop` | 有界循环（沿用现有 body/done 出口） |
| `human` | 人工审批（沿用现有暂停/续跑） |
| `end` | 汇总输出 |

被删除的旧节点：`input`、`prompt`、`llm`、`tool`、`mcp`、`knowledge`、`skill`、`output`。它们的能力全部进入 Agent：

- `input` → `start.variables`
- `prompt` + `llm.system` → `agent.prompt`
- `llm` → `agent.model`
- `tool` / `mcp` / `knowledge` → `agent.resources`
- `output` → `agent.output`
- `skill` → 直接引用另一个 Agent 节点，不再有子流程内联

Flow JSON：

```json
{
  "id": "flow_xxx",
  "name": "售后工单分流",
  "dslVersion": 2,
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "position": { "x": 80, "y": 200 },
      "config": {
        "variables": [
          { "key": "query", "type": "string", "required": true, "default": "" }
        ]
      }
    },
    {
      "id": "classify_1",
      "type": "agent",
      "position": { "x": 320, "y": 200 },
      "config": {
        "agentId": "agent_classify",
        "inputMap": { "query": "{{start.query}}" }
      }
    },
    {
      "id": "reply_1",
      "type": "agent",
      "position": { "x": 620, "y": 200 },
      "config": {
        "agentId": "agent_reply",
        "inputMap": {
          "query": "{{start.query}}",
          "intent": "{{classify_1.output.intent}}"
        }
      }
    },
    {
      "id": "end_1",
      "type": "end",
      "position": { "x": 900, "y": 200 },
      "config": { "outputs": ["reply_1.output"] }
    }
  ],
  "edges": [
    { "id": "e1", "source": "start_1", "target": "classify_1" },
    { "id": "e2", "source": "classify_1", "target": "reply_1" },
    { "id": "e3", "source": "reply_1", "target": "end_1" }
  ]
}
```

变量寻址统一为：

- 流程输入：`{{start.<var>}}`
- Agent 产物：`{{<nodeId>.output.<field>}}`
- 当前 Agent 自己的模板：`{{<var>}}`（本地变量）

`inputMap` 只允许引用**直接上游**和 `start`，避免跨层引用导致拓扑校验复杂；后续要跨层再接“显式变量池”。

---

## 2. 执行语义

### 2.1 单 Agent 运行

新增 `AgentRunner`，不依赖 Flow：

```
resolve inputs -> validate required/type -> resolve @resources
-> render prompt -> LLM (+FC loop) -> validate output -> return {text, ...}
```

单 Agent 对话复用同一条链路：每轮用户消息创建一次 run，`query`（或 Agent 配置的 `chatInputVariable`）由消息填充，其余变量由对话页的“变量面板”预先填好。

### 2.2 流程运行

`agent` 节点执行时：

1. 解 `inputMap`，按 Agent 变量定义做类型转换与必选校验。
2. 调 `AgentRunner`。
3. 把输出写入 `nodes.<nodeId>.output`；同时把 `text` 写到 `nodes.<nodeId>.text`，方便条件表达式继续用短路径。
4. 有 `output.schema` 时先校验再落盘，避免把坏结构传给下游。

事件协议尽量复用现有：

- `node_started` / `node_completed` 带 `nodeId` + `agentId`
- 工具复用 `tool_call` / `tool_result`，带 `source:"tool"|"mcp"`
- 知识库复用 `knowledge_retrieved`
- 新增 `agent_output_invalid`（只用于诊断，不替代 `run_failed`）

### 2.3 错误码

| code | 场景 |
|---|---|
| `AGENT_NOT_FOUND` | 流程引用的 Agent 被删 |
| `AGENT_INPUT_MISSING` | 必选变量没填/映射为空 |
| `AGENT_INPUT_TYPE` | 变量类型转换失败 |
| `AGENT_RESOURCE_MISSING` | 引用的 KB/Tool/MCP 不存在或停用 |
| `AGENT_PROMPT_RESOURCE_UNKNOWN` | prompt 里的 `@别名` 没在 resources 里声明 |
| `AGENT_FORCED_TOOL_NOT_CALLED` | `@` 工具重试一次仍未调用 |
| `AGENT_OUTPUT_INVALID` | 输出不符合 schema |
| `FLOW_VAR_UNBOUND` | 流程校验期发现必选变量没映射 |
| `FLOW_DSL_LEGACY` | 旧 DSL 流程被要求编辑/运行 |

---

## 3. 后端改造清单

| 文件/模块 | 改动 |
|---|---|
| `app/models/agent.py`（新） | `Agent`、`AgentVariable`、`AgentResource`、`AgentModelConfig`、`AgentOutput`、`AgentCreate/Update` |
| `app/services/agent_repo.py`（新） | Agent CRUD；整份定义存 `agents.definition_json`，便于快速迭代 |
| `app/services/agent_service.py`（新） | 校验变量 key 唯一、别名唯一、资源存在、`@` 都能解析、输出 schema 合法 |
| `app/api/agents.py`（新） | `GET/POST /api/agents`、`GET/PUT/DELETE /api/agents/{id}`、`POST /api/agents/{id}/validate`、`POST /api/agents/{id}/run` |
| `app/engine/agent_runner.py`（新） | 变量解析、资源解析、prompt 渲染、FC 循环、输出校验；复用 `llm.py` / `tool_runner.py` / `knowledge_rag.py` / `mcp_client.py` |
| `app/engine/graph_runner.py` | 节点类型收窄为 `start/agent/condition/loop/human/end`；`agent` 调 `AgentRunner`；条件/循环/审批逻辑保留 |
| `app/models/flow.py` | `NodeType` 改为 v2 六类；`Flow.dsl_version`；`FlowNode.config` 仍为自由 JSON，但由 registry 校验 |
| `app/services/flow_service.py` | v2 校验：必需变量映射、Agent 存在、资源存在、断线/环检测；旧 DSL 返回 `FLOW_DSL_LEGACY` |
| `app/db/init.sql` | 新增 `agents`；`flows.dsl_version`；`runs.agent_id`、`runs.flow_id` 允许为空（SQLite 需重建表）；`conversations` 拆成 Agent 会话表或加 `agent_id` |
| `app/database.py` | 启动迁移：加 `agents`、`dsl_version`、`runs.agent_id`；旧数据补 `dsl_version=1` |
| `app/api/chat.py` | 新增 Agent 对话路由；每轮 run 用 `agent_id`，不再要求 `flow_id` |
| `scripts/migrate_legacy_flows.py`（新） | 一次性把旧流程迁移成 Agent + v2 流程；无法自动迁移的标记 `migration_status=manual` |
| `tests/test_agents.py`（新） | CRUD、变量校验、资源引用、@ 解析、输出 schema |
| `tests/test_agent_runner.py`（新） | @KB 检索、未 @ 不检索、@Tool 强制、未 @ Tool 候选、FC 重试、输出校验 |
| `tests/test_flow_v2.py`（新） | Agent 节点映射、必选变量、条件/循环仍可跑、旧 DSL 拒绝 |
| `tests/test_chat.py` | 从 flow 会话迁到 agent 会话；保留历史回灌/隔离用例 |

### 3.1 数据表

```sql
-- Agent 定义整体存 JSON，避免为 prompt/resources 反复加列
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    definition_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 流程 DSL 版本；旧流程保留用于回放/迁移
ALTER TABLE flows ADD COLUMN dsl_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE flows ADD COLUMN migration_status TEXT NOT NULL DEFAULT 'ok';

-- 单 Agent run：flow_id 允许为空；SQLite 需要重建 runs 表
-- runs(id, flow_id NULL, agent_id NULL, ..., conversation_id NULL)
```

Agent 会话：

- 方案 A：新建 `agent_conversations` / `agent_chat_turns`，与旧 flow 会话完全隔离。
- 方案 B：把 `conversations` 改成 `target_type/target_id`，旧 flow 会话迁为 `flow`。

计划采用 **方案 A**：全量替换后 Agent 对话是一等入口，旧 flow 会话保留只读，迁移风险最低。后续如果还要 flow 对话，再抽公共会话服务。

---

## 4. 前端改造清单

### 4.1 页面

| 路由 | 页面 |
|---|---|
| `/agents` | Agent 库：卡片展示名称、描述、变量数、模型、资源徽标；每张卡有「编辑」「对话」 |
| `/agents/:id` | Agent 编辑器 |
| `/agents/:id/chat` | 单 Agent 对话（左侧历史会话，右侧气泡） |
| `/flows` | 流程列表（v2 流程 + 迁移状态） |
| `/flows/:id` | 流程编排编辑器（Agent 节点为唯一执行单元） |

### 4.2 Agent 编辑器

按用户列出的六块组织，顺序固定：

1. **基本信息**：名称、描述（必填，会显示在 Agent 卡片/流程节点上）。
2. **变量定义**：表格列 `key / 显示名 / 类型 / 必选 / 默认值 / 说明`；`key` 必须 `^[a-zA-Z_]\w*$`；支持上移下移。
3. **提示词**：
   - `system` 多行；
   - `template` 多行，支持 `{{变量}}` 自动补全、`@` 资源补全；
   - `@` 插入为可视化 chip（底层存 `@kb[别名]` / `@tool[别名]` / `@mcp[别名.tool]`）；
   - 右侧“可用变量 / 已导入资源”列表，点一下插入。
4. **资源**：从资源库导入，不新建资源：
   - 选择 Tool（多选）；
   - 选择 MCP Server 后再选该 Server 下的工具；
   - 选择知识库，配置 `queryVar / topK / rerank`；
   - 导入后生成 Agent 内别名，可改别名；
   - 显示“已导入但提示词未 @”的知识库警告。
5. **模型**：默认模型、temperature、maxTokens、maxToolRounds；显示“沿用全局默认”状态。
6. **输出**：输出描述（必填）+ 可选 JSON Schema（JSON 编辑器，实时校验）；右侧预览下游可引用的字段。

保存前统一 `POST /api/agents/{id}/validate`，把错误定位到具体字段/chip。

### 4.3 流程编辑器

- 左侧 Palette 改为：开始 / Agent / 条件 / 循环 / 审批 / 结束。
- 拖入 Agent 节点后，配置面板：
  - Agent 下拉（搜索 + 显示描述），旁边「编辑」「对话」按钮；
  - 变量映射表：Agent 每个变量 → 选择 `start.xxx` 或直接上游 `nodeId.output.field`；必选未映射标红；
  - 显示 Agent 的资源与输出 Schema 只读摘要。
- 连线规则：
  - `start` 只能出、`end` 只能入；
  - `agent` 不能自连，不能形成环（除非在 `loop` body 内）；
  - 条件/循环出口沿用 `sourceHandle`。
- 运行抽屉：先弹“流程输入”表单（来自 `start.variables`），再跑。

### 4.4 单 Agent 对话

- 进入 `/agents/:id/chat` 先读 Agent：变量 > 1 时显示“变量面板”，`query` 默认绑定聊天输入框；
- 非 `query` 变量在首轮前填好，后续轮次沿用；
- 会话作用域**不按 Agent 全局共享**：
  - 从 Agent 库进入：`agentId` + 空 `flowId/nodeId`；
  - 从流程节点进入：`agentId + flowId + nodeId`，同一个 Agent 被不同流程/节点复用时各聊各的；
  - 会话列表、历史回灌都按作用域过滤；
- 历史仍走 `build_history`，后续记忆改造只换这个函数；
- 左侧卡片/流程 Agent 节点都有「对话」入口。

---

## 5. 旧流程迁移（全量替换）

### 5.1 原则

- **不原地改旧 DSL**：旧流程保留原始 `dsl_json` 和 `dsl_version=1`，只用于回放/对照。
- 新表 `agents` 由迁移脚本生成，新 v2 流程引用它们。
- 迁移失败的流程标 `migration_status='manual'`，前端显示“需手工重建”，禁止运行。

### 5.2 自动迁移映射

| 旧结构 | v2 结果 |
|---|---|
| `input → prompt → llm → output` | 1 个 Agent（prompt/system/llm/output 合并） |
| `input → knowledge → prompt → llm → output` | 1 个 Agent（knowledge 导入为资源，prompt 里插入 `@kb[别名]`） |
| `input → mcp → output` | 1 个 Agent（MCP 工具导入，prompt 要求调用） |
| `input → tool → output` | 1 个 Agent（Tool 导入） |
| `input → skill → output` | 1 个 Agent 节点，指向被调子流程迁移出的 Agent |
| 含 `condition/loop/human` | 把每个连续的非编排段折叠成 Agent，保留编排节点与边 |

已知需要手工处理的：

- 一个旧流程里有多个互不相关的 prompt/llm 段，无法判断是否应合并；
- skill 父子流程 tokens/steps 语义变化（v2 不再有内联子流程）；
- 旧流程里 `output.fields` 与下游变量名不一致的映射。

### 5.3 迁移后的演示流程

| 新流程 | 内容 |
|---|---|
| `售后知识库问答` | Agent：变量 `query/history`，资源 KB，输出 `text` |
| `MCP 时间查询` | Agent：资源 MCP `now`，输出 `text` |
| `客服话术润色` | Agent：变量 `query`，输出 `text` |
| `父子 Agent 编排` | 父流程两个 Agent 节点，子能力改为直接引用 Agent |

迁移脚本要支持 `--dry-run` 输出“将创建哪些 Agent / 哪些流程无法自动迁移”，确认后再写库。

---

## 6. 分阶段实施

| 阶段 | 内容 | 交付/验收 |
|---|---|---|
| **P0 契约冻结**（0.5–1d） | 定稿 Agent JSON、@ 语法、Flow v2 节点集、变量寻址、错误码；写本计划附录 | 本文档评审通过；不再改字段名 |
| **P1 Agent 资源层**（2d） | `agents` 表、模型、repo、校验、CRUD API；资源引用校验；前端可先只做 API 联调 | `pytest tests/test_agents.py`：CRUD、重复 key、别名冲突、资源不存在、schema 非法 |
| **P2 AgentRunner**（3d） | 变量解析、@KB/@Tool/@MCP、FC 循环、输出 schema；单 Agent run API | `test_agent_runner.py`：@KB 命中、未 @ 不检索、@Tool 强制、未 @ Tool 可自选、坏 schema 报错 |
| **P3 Flow v2 执行**（3d） | `start/agent/condition/loop/human/end`；`inputMap`；节点产物寻址；事件 | `test_flow_v2.py`：两 Agent 串联、必选变量缺失、条件分支、循环、审批续跑 |
| **P4 迁移与切换**（2d） | 迁移脚本 dry-run/apply；旧流程标记；移除旧节点注册与执行分支；旧 DSL 拒绝运行 | 旧 R1–R5 演示全部有 v2 对应版本；无法迁移的有清单；旧流程回放仍可看 |
| **P5 前端**（5d） | Agent 库/编辑器/资源导入/提示词 chip/流程 Agent 节点/对话页 | 页面验收：见 §8；`tsc`、`build`、真实网关跑通 |
| **P6 文档与清理**（1d） | README、acceptance、API 文档；删除旧组件/死代码；测试基线更新 | 全量测试通过；文档与实现一致 |

单人可以按 P1 → P2 → P3 → P4 → P5 串行；P5 的 Agent 库页面可以在 P1 后先做，提前联调。

---

## 7. 测试矩阵

| 层 | 用例 |
|---|---|
| Agent 校验 | 变量 key 重复/非法、必选无默认、别名重复、资源被删、`@` 未声明、schema 非法 |
| @ 资源 | KB 命中注入、KB 无命中不硬编、未 @ KB 不检索、@Tool 强制调用、未 @ Tool 模型自选、MCP 多工具 |
| 变量 | 类型转换、必选缺失、默认值、上游映射、同名自动建议 |
| 输出 | 无 schema 走 text、有 schema 成功、schema 失败重试一次、二次失败 `AGENT_OUTPUT_INVALID` |
| Flow | 两 Agent 串联、条件分支、循环、human 暂停/续跑、断线、环检测、旧 DSL 拒绝 |
| Chat | 每 Agent 会话隔离、历史回灌、变量面板、刷新恢复、删除会话 |
| 迁移 | dry-run 报告、线性流程自动迁移、含编排节点保留、无法迁移标记 manual |

---

## 8. 页面级验收（P5 完成后）

1. `/agents` 新建 Agent → 填描述、两个变量（一个必选）→ 保存 → 卡片出现，变量数与资源徽标正确。
2. 点「编辑」→ 从资源库导入知识库、Tool、MCP 工具 → 提示词里 `@` 插入 chip → 删掉资源应提示未解析。
3. 点「对话」→ 先填非 `query` 必选变量 → 发消息 → 气泡流式输出；刷新后历史还在；换一个 Agent 不串会话。
4. `/flows` 新建 v2 流程 → 拖两个 Agent → 映射第一个的 `output.text` 到第二个的 `query` → 运行，第二个拿到第一个输出。
5. 必选变量不映射 → 保存/运行被拦，错误定位到具体节点变量。
6. 旧 R1–R5 流程 → 显示“旧 DSL/迁移状态”；迁移成功的打开是 v2 图；未迁移的只能回放，不能运行。

---

## 9. 已拍板与剩余边界

已拍板：

1. **Agent 实时引用**：MVP 不做发布/版本锁，改完立即生效；UI 显示“被 N 个流程/节点引用”。
2. **对话历史不全局共享**：作用域 `agentId + flowId + nodeId`；Agent 库直聊为 `agentId`。
3. **条件/循环/审批保留为编排节点**：Agent 内部不处理分支和审批。
4. 变量映射采用 Agent 节点上的显式 `inputMap`，UI 可先按同名自动填充。
5. 旧流程中的线性部分自动迁移；含编排节点的流程保留编排、折叠 Agent 段；无业务意义的验证流程（如 `环检测验证`）归档，不强行迁移。

仍需在落地时留意的边界：

- 实时引用下，编辑 Agent 会立即影响所有引用它的流程；先在 UI 上显示引用数并给出“影响 N 个节点”的保存提示。
- 迁移脚本必须先 `--dry-run`，输出无法自动迁移清单，再执行写库。

---

## 10. 风险

- **@ 语法与资源别名**：别名是 Agent 内稳定标识，底层存 ID；资源改名不能改别名，否则 prompt 解析断。
- **强制工具调用的模型差异**：不同 OpenAI 兼容网关对 `tool_choice` 支持不一致；需要“调用记录核对 + 一次重试”兜底，不能只信请求参数。
- **输出 schema 与推理成本**：强制 JSON 可能降低自然语言质量；默认不填 schema，需要结构化交接时才开。
- **全量替换的破坏面**：旧 DSL 运行、旧前端组件、旧测试、旧聊天数据都要一次性切换；迁移脚本必须先 dry-run，保留旧表只读。
- **全局 Agent 的联动修改**：没有版本锁时，改一个 Agent 可能同时改变多条流程的行为；MVP 靠“引用数提示 + 变更记录”降低误伤，后续补版本。

---

## 11. 一天内迁移的执行步骤（压缩版）

### 11.1 先说明一天能交付到什么程度

完整 v2（含精细 UI、版本体系、全量迁移、生产级验收）按正常估算是 15–17 天。压到一天必须做 **MVP 裁剪**，今天承诺的是：

**今天必须完成（可运行迁移）**

- `agents` 表 + Agent CRUD/校验 API。
- `AgentRunner`：变量、`@kb` 检索、`@tool/@mcp` 混合触发、输出 Schema 校验。
- Flow v2：`start / agent / condition / loop / human / end`，`inputMap` 映射可执行。
- 旧流程迁移：9 条线性流程 + 4 条含编排节点的流程迁移为 v2；`环检测验证` 归档。
- 基础前端：Agent 库、Agent 编辑器（表单版）、流程 Agent 节点、单 Agent 对话（按 `agentId + flowId + nodeId` 隔离）。
- 后端测试 + `tsc` + `build` + 至少 2 条真实网关冒烟。

**今天不做（不影响迁移可用）**

- Agent 发布/版本锁（已确认实时引用）。
- 富文本 prompt 编辑器（用“插入变量/插入资源”按钮 + 纯文本 token，不做 chip 富文本）。
- 可视化 JSON Schema 构建器（用 JSON 文本域 + 校验）。
- Agent 列表的精美卡片、流程图自动布局。
- 旧流程回放 UI 重做（保留原回放页）。
- 第 5 条以外的高级迁移规则（判断不了的标 `manual`）。

> 如果今天剩余时间不足 13 小时，我会把“文档收尾”顺延，但不压缩测试与真实冒烟；会在下一次回复给出实际完成度和未完成清单，不虚报。

### 11.2 13 小时执行顺序（一人串行）

| 时段 | 动作 | 完成判据 |
|---|---|---|
| H0–H0.5 | 冻结契约：Agent JSON、Flow v2、scope key、迁移矩阵 | 本文档 §0/§3 不再改字段 |
| H0.5–H1.5 | 备份 DB；写 `agents`、`flows.dsl_version/migration_status`、`runs.agent_id`、Agent 会话表；启动迁移兼容旧表 | 启动 `uvicorn` 不报错；旧数据可读 |
| H1.5–H3.5 | Agent 模型/repo/service/API；变量、资源别名、`@`、schema 校验；`test_agents.py` | CRUD + 校验用例通过 |
| H3.5–H5.5 | `AgentRunner`；接入现有 llm/tool/knowledge/mcp；`test_agent_runner.py` | `@kb` 命中、未 @ 不检索、`@tool` 强制、未 @ 可自选 |
| H5.5–H7.5 | Flow v2 编译：`start`/`agent`/`condition`/`loop`/`human`/`end`；`inputMap`；事件；`test_flow_v2.py` | 两 Agent 串联 + 条件/循环/审批各 1 条通过 |
| H7.5–H9 | 迁移脚本 `--dry-run` → 写库；9 条线性 + 4 条编排流程；归档验证流程 | 迁移报告：13 成功、0 manual、1 归档 |
| H9–H11.5 | 前端：`/agents`、`/agents/:id` 表单编辑器、资源导入、流程 Agent 节点与映射表、`/agents/:id/chat` + 流程节点对话作用域 | 页面能建 Agent、拖 Agent、跑通两 Agent、聊到真实回复 |
| H11.5–H12.5 | 全量测试、`tsc`、`build`、真实网关冒烟、修回归 | 后端全绿；前端 build 0；2 条真实链路成功 |
| H12.5–H13 | 更新 README/acceptance；记录未完成项 | 文档数字与实现一致 |

### 11.3 迁移矩阵（按现有 14 条流程）

| 旧流程 | 节点形态 | 迁移方式 |
|---|---|---|
| `flow_47c506fe` R5 子流程-润色 | input,prompt,llm,output | 1 个 Agent，自动 |
| `flow_3fc2aca8` R5 知识库问答 | input,knowledge,prompt,llm,output | 1 个 Agent + `@kb`，自动 |
| `flow_03b8009e` R5 MCP 直连 | input,mcp,output | 1 个 Agent + `@mcp`，自动 |
| `flow_9ef0ee08` 子流程调用 | input,skill,output | 引用润色 Agent，自动 |
| `flow_fd2812d1` R3 FC | input,llm,output | 1 个 Agent（Tool 导入但未 @，走候选），自动 |
| `flow_921e8b49` R3 工具节点 | input,tool,output | 1 个 Agent + `@tool`，自动 |
| `flow_3c2a0e36` 未命名 | input,llm,output | 1 个 Agent，自动 |
| `flow_ee19528c` R1 长流程 | input,llm,output | 1 个 Agent，自动 |
| `flow_bf874e8f` P1 验证 | input,llm,output | 1 个 Agent，自动 |
| `flow_43e2f4ba` R4 循环 | input,loop,prompt,llm,output | `start → loop → agent → end`，保留 loop |
| `flow_1c485778` R4 分支 | input,condition,两条 prompt/llm,output | `start → condition → agent A/B → end`，保留 condition |
| `flow_78b1ae68` R4 审批 | input,human,output | `start → human → end`，保留 human |
| `flow_a12bc341` R1 审批 | input,human,output | `start → human → end`，保留 human |
| `flow_c1583d6b` 环检测验证 | input,prompt,prompt,output,tool | 测试用途，归档，不迁移 |

### 11.4 今天的验收命令

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest -q

cd ..\agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build

# 迁移报告
cd ..\agentflow-backend
.venv\Scripts\python.exe scripts\migrate_legacy_flows.py --dry-run
```

浏览器验收：

1. `/agents` 新建 Agent → 变量、导入 KB/Tool、提示词 `@` → 保存。
2. `/agents/:id/chat` 发消息 → 有真实回复；换 Agent 会话不串。
3. `/flows` 打开迁移后的“售后知识库问答” → 是 `start → agent → end`，能运行。
4. 打开“R5 子流程调用演示” → 引用润色 Agent，能运行。
5. 同一个 Agent 从两个不同流程节点各自点「对话」→ 两边历史互不共享。

---

## 12. 最终五步（无备份、无迁移、无兼容）

> 覆盖 §5、§6、§11 的旧口径：项目未上线，旧流程/旧 run/旧对话不做迁移，直接清空重建。

### 12.0 执行记录（2026-11-27）

**步骤 1 已完成的部分**

- 8000 后端已停；清理后重新在 **8000** 启动，未改端口，CORS 继续放行 `localhost / 127.0.0.1` 的 5173、8000。
- `agentflow-backend/data/agentflow.db` 已删除编排数据：`flows` 14→0、`runs` 53→0、`run_events` 3911→0、`conversations` 3→0、`chat_turns` 4→0，`checkpoints` / `writes` 一并清空。
- 资源库原样保留：`settings`（DeepSeek）、`tools` 3 条、`mcp_servers` 1 条、`knowledge_bases` 2 条；`agents` 表已建，当前 0 条。
- **旧节点代码没有在步骤 1 删除**：现在删 `NodeType / registry / engine` 会让旧 Flow API 和前端停在半成品状态，改为并到步骤 3 与 Flow v2 引擎一次性替换。这是本轮唯一从步骤 1 挪走的动作，已在“未完成”里标明。

**步骤 2 已完成**

- 新增 `app/models/agent.py`、`app/services/agent_repo.py`、`app/services/agent_service.py`、`app/api/agents.py`、`app/engine/agent_runner.py`。
- `init.sql` 新增 `agents(id,name,description,definition_json,created_at,updated_at)`；`app/main.py` 注册 `/api/agents`。
- `llm.stream_completion` 增加 `tool_choice` 参数，保持旧调用默认 `auto`。
- API：`GET/POST /api/agents`、`GET/PUT/DELETE /api/agents/{id}`、`POST /api/agents/validate`、`POST /api/agents/{id}/validate`、`POST /api/agents/{id}/run`。
- 执行器覆盖：变量合并/类型转换、`@kb` 检索、未 `@` 的 Tool/MCP 作为 FC 候选、`@tool/@mcp` 强制、MCP 探测与执行、输出 JSON Schema 校验+一次重试。
- 测试：新增 `tests/test_agents.py`（6 条）、`tests/test_agent_runner.py`（4 条）；后端全量 **81 条通过**。
- 真实网关冒烟（DeepSeek，全部通过后已删除测试 Agent）：纯文本 Agent、`@tool[echo]` 强制工具、`@kb` 知识库检索、`@mcp[demo.echo]`、输出 Schema。`/api/agents/{id}/run` 返回 `toolCalls` / `knowledgeCalls`、tokens、cost、steps。

**步骤 2 明确没做**

- 单 Agent run 不落 `runs`，也不写 `run_events`；`runs` 仍是 `flow_id NOT NULL`，等步骤 3 改成 `targetType/targetId` 再统一接。
- 没有 Agent 会话表；`agentId + flowId + nodeId` 的对话隔离在步骤 3 做。
- 没有前端；Agent 库/编辑器/对话页面在步骤 4。

**步骤 3 已完成（2026-11-27）**

- Flow DSL v2：`NodeType` 只剩 `start / agent / condition / loop / human / end`；`Flow.dslVersion` 新建=2，旧 DSL 只回一条「不支持编辑/运行」错误；新建流程默认 `start_1 -> end_1`。
- `app/nodes/registry.py` 重写为 6 类配置：`StartConfig.variables`、`AgentConfig.agentId/inputMap`、`ConditionConfig`、`LoopConfig`、`HumanConfig`、`EndConfig.outputs`；同时接受 snake_case 与 camelCase，默认配置按 camel 输出。
- `app/services/flow_vars.py`：`{{start.x}}`、`{{nodeId.output.field}}`、`{{nodeId.text}}` 点路径；整段单路径保留类型，混合文本转字符串，缺失抛 `LookupError`。`expr.py` 同步支持点路径。
- `flow_service.validate_flow`：唯一 start/end、节点配置、condition true/false、loop body、孤立节点、环检测（loop 回边忽略）；`validate_flow_runtime`：Agent 存在、`inputMap` 键属于 Agent 变量、必选变量已映射、变量路径可解析。
- `graph_runner` v2：`start` 注入 `inputs` 并写 `start/variables`；`agent` 解析 `inputMap` → `run_agent` → `nodes.<nodeId>={agentId,output,text}`，累加 tokens/cost/steps/toolCalls；`end` 按列表/对象解析最终 outputs，空列表回退最后一个 Agent 的 `text`；condition/loop/human 保持原语义。`AgentRunError RUN_CANCELLED` 转 `GraphCancelled`。
- `AgentRunner` 增加：token `emit`、协作式 `stop`（取消后不再写回 succeeded）、空回答检测 `AGENT_EMPTY_ANSWER`（区分 `finish_reason=length` 与只有思维链）。
- `runs` 改为 `target_type=flow|agent` + `target_id` + `flow_version`；`run_repo`/API 按 target 过滤，resume 仅 flow。新增 `POST /api/agents/{id}/runs`（202 + SSE），`start_agent_run` 发 `run_started/node_started/token/node_completed/run_completed`。
- 会话改为 `agent_id + flow_id + node_id` 作用域：库内直聊只有 agent，流程节点必须指向该 Agent 的 agent 节点；每轮建一条 agent run，历史只回灌当前会话已成功 run。
- DB：`runs`、`run_events`、`conversations`、`chat_turns`、`checkpoints`、`writes` 已 DROP 重建；清理了残留旧 `flow_0661902f`；资源库保留。LangGraph checkpoint 改存独立 `data/agentflow_checkpoints.db`，并给业务库加 `busy_timeout=5000`，解决并发 run 抢 SQLite 锁。
- 测试：新增 `test_flow_v2.py`（6 条）、`test_chat_agent.py`（3 条）；重写 `test_runs.py` / `test_flows.py` / `test_node_types.py`；删除旧节点专用的 `test_chat.py`、`test_graph.py`、`test_loop.py`、`test_skill.py`，裁剪 `test_tools.py` / `test_mcp.py` / `test_knowledge.py` 的旧节点用例。全量 **57 passed，连续两次通过**。
- 演示数据 + 真实冒烟：`scripts/seed_v2_demo.py` 写入 `agent_554411d8e1b5`（通用对话）、`agent_4747f1dc562a`（售后知识库问答）、`flow_917b6615`（两 Agent 串联）、`flow_01c7011f`（循环+条件+审批）。DeepSeek 真实运行：串联返回知识库退款口径；审批流程 `waiting_human` → 批准 → succeeded；同一 Agent 在库内、流程 A `chat_1`、流程 B `chat_1` 各两轮，历史只含自己的内容。冒烟产生的 runs/conversations/events 已清空，只保留 2 Agent + 2 Flow 供开箱验证。
- 仍留给后续：`end.outputs` 列表模式的 key 取路径末段（`a1.output.text` → `text`），前端口径已按此展示；`inputMap` 尚未限制只能引用直接上游；SSE 只做历史+实时，前端已联调。

**步骤 3 补充：旧 DSL 专用错误码（2026-11-27）**

- `app/api/flows.py` 新增 `FLOW_DSL_LEGACY`：`PUT /api/flows/{id}`、`POST /publish`、`POST /validate`、`POST /run` 在 `dsl_version != 2` 时统一返回 HTTP 422 + `{code:"FLOW_DSL_LEGACY", message:"该流程是旧 DSL…", detail:null}`；`_invalid_flow_response` 对首条 issue 为无 nodeId 的「旧 DSL」也转成该错误码。
- `tests/test_flows.py` 新增 `test_legacy_flow_uses_dedicated_error_code`，直接向临时 DB 插入 `dsl_version=1` 的 Flow，覆盖 validate/publish/run/put 四个入口。
- 全量测试 **58 passed**（原 57 + 1）。

**步骤 4 已完成：前端一次性切换（2026-11-27）**

- 路由：新增 `/agents`（Agent 库）、`/agents/:id`（表单编辑器）、`/agents/:id/chat`（Agent 作用域对话）；删除 `/flows/:id/chat` 与 `ChatPage`，侧栏新增「Agent 库」。
- 类型/API 对齐 v2：`NodeType=start|agent|condition|loop|human|end`、`Flow.dslVersion`、`Run.targetType/targetId`；新增 `api/agents.ts`、`types/agent.ts`；`chatApi` 改为 agentId + flowId/nodeId 作用域；`runsApi` 支持 target 过滤。
- Agent 库：卡片展示变量数/模型/资源/Schema，带「编辑」「对话」「删除」；新建默认 `query` 变量 + 空资源，直接进入编辑器。
- Agent 编辑器：变量表、system/template、资源导入（tool/MCP/知识库，MCP 勾选工具、知识库 queryVar/topK/rerank）、模型、输出描述/JSON Schema；保存后调用 `POST /agents/{id}/validate` 做资源运行时校验；错误同时读取 `AGENT_INVALID` 的 `detail.errors`。
- Flow 画布：Palette 只渲染后端下发的 6 类节点；`ConfigPanel` 重写为 v2 专用面板——开始变量、Agent 下拉 + 变量映射 + 编辑/对话入口、条件表达式 + true/false 出边、循环 maxRounds/exitCondition + body/done、审批、结束 outputs 列表/对象；删除旧 Tool/MCP/Knowledge/Skill/Model/Branch 表单与 `utils/schema.ts`。
- 运行：新增「运行输入」弹窗，按开始节点变量收集输入；旧 DSL 编辑器显示黄色提示并禁用运行；运行面板复用 SSE/审批/指标。`flowToNodes` 对全部在 (0,0) 的演示/导入流程按数组顺序横向铺开，仅展示层兜底。
- 运行历史/回放：按 `targetType/targetId` 展示 Flow 或 Agent 名称与跳转；Flow 保留版本，Agent 不再伪造版本。
- 修复：AgentChatPage 在 React StrictMode 下并发 `list(0)+create` 会凭空建两条空会话，改为 `initializingRef` 串行初始化。
- 验证：`node node_modules\typescript\bin\tsc --noEmit` 通过；`node node_modules\vite\bin\vite.js build` 通过；浏览器真实 DeepSeek 跑通 Agent 新建→保存→校验、Flow 两 Agent `inputMap` 串联（360 tokens / 3.1s）、节点作用域对话（129 tokens）；冒烟产生的 runs / conversations / events / 临时 Agent / checkpoint 已清空，保留 2 Agent + 2 Flow。

**步骤 4 明确没做 / 已知限制**

- 未迁移任何旧 DSL 流程；旧流程只显示提示，不能编辑、发布、运行。
- Agent 编辑器资源导入暂不支持一键从资源库批量选择，逐个添加；MCP 工具靠探测接口勾选。
- `inputMap` 前端不限制「只能引用直接上游」，由后端按变量路径可解析性校验。
- 运行历史暂不支持按 Agent 名称搜索，只有目标下拉 + 状态筛选。
- 验收清单 §8 的完整五条浏览器回归留到步骤 5。

### 步骤 1：停旧服务、清编排数据、冻结 v2 契约

- 停 8000 后端；保留 `settings`、`tools`、`mcp_servers`、`kb_documents`、`kb_chunks`，这些是资源库，不重建。
- 直接删编排类表：`flows`、`runs`、`run_events`、`conversations`、`chat_turns`；LangGraph 的 `checkpoints` / `writes` 一并清掉。
- 旧节点类型代码（`input / prompt / llm / tool / mcp / knowledge / skill / output`）先保留，等步骤 3 替换 Flow 引擎时一次性删除，避免现在把旧 Flow API/前端打断。
- 写入最终契约：
  - `Agent = { name, description, variables, prompt{system,template}, resources, model, output }`
  - `Flow v2` 节点只剩 `start / agent / condition / loop / human / end`
  - 对话作用域 `agentId + flowId + nodeId`

**完成判据（本轮）**：编排数据全部清空、资源库保留、`agents` 表可写；旧节点删除与 `LEGACY_REMOVED` 报错随步骤 3 一起交付。

### 步骤 2：后端 Agent 资源层 + 执行器

- 新增 `agents` 表与 `app/models/agent.py`、`agent_repo.py`、`agent_service.py`、`api/agents.py`。
- 校验：变量类型/必选/默认值、资源别名唯一、`@别名` 必须能在 resources 里解析、资源必须存在且启用、输出 Schema 合法。
- 新增 `AgentRunner`：变量解析 → `@kb` 检索 → `@tool/@mcp` 混合触发（未 @ 仍可被模型自选，@ 强制）→ FC 循环 → 输出 Schema 校验。
- 单 Agent run 与单 Agent 对话都走 `AgentRunner`，不复制第二套执行逻辑。

**完成判据**：`tests/test_agents.py`、`tests/test_agent_runner.py` 通过；真实网关能跑一个带 `@kb` 的 Agent。

### 步骤 3：Flow v2 编排 + 资源对话

- `NodeType` 收窄为 `start / agent / condition / loop / human / end`；`agent` 节点配置 `{agentId, inputMap}`。
- 执行：`start` 注入外部变量 → `agent` 调 `AgentRunner` → 产物写 `nodes.<nodeId>.output` → 下游按 `inputMap` 取值；条件/循环/审批沿用现有逻辑。
- `runs` 改成 `targetType = flow|agent` + `targetId`；Agent 对话不再要求 `flowId`。
- 会话表带 `agent_id / flow_id / node_id`，同一 Agent 在不同流程/节点各聊各的。
- 写入 2 个演示 Agent（通用对话、知识库问答）和 2 条 v2 流程，保证开箱可验。

**完成判据**：两 Agent 串联、条件分支、循环、审批各跑通一条；同一 Agent 在两个流程节点聊天，历史不串。

### 步骤 4：前端一次性切换（已完成 2026-11-27）

- `/agents`：Agent 库，卡片带「编辑」「对话」。
- `/agents/:id`：表单版编辑器——描述、变量表、`system/template`、资源导入、模型、输出描述/Schema。
- `/agents/:id/chat`：变量面板 + 气泡；从流程节点进入时带 `flowId/nodeId`，会话隔离。
- `/flows/:id`：Palette 改成 `开始/Agent/条件/循环/审批/结束`；Agent 节点配置 Agent 下拉 + 变量映射表 + 「编辑」「对话」。
- 删除旧节点配置面板、旧 flow 对话页、旧 node registry。

**完成判据**：`tsc`、`vite build` 通过；页面能新建 Agent、拖两个 Agent、映射变量并跑通。

### 步骤 5：全量验证与收尾

- 后端全量测试；前端 `tsc` + `build`。
- 真实网关冒烟：单 Agent 对话、KB Agent、两 Agent 串联各 1 条。
- 删掉旧 DSL 的类型、测试、文档段落；README/acceptance 改成 v2。
- 给出最终清单：已实现、未实现、已知限制。

**完成判据**：所有命令 0 失败；浏览器完成 §8 的五条验收；文档不再出现旧节点口径。
