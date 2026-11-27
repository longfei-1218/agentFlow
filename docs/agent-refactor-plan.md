# AgentFlow 重构计划与实施记录（v2）

> 状态：**完成**。旧的“流程内直接放 LLM / Tool / MCP / Knowledge / Skill 节点”的架构已整体替换为“全局 Agent 库 + Flow v2 六类编排节点”。
>
> 口径：全量替换，不备份、不迁移旧流程、不做前后兼容；旧 DSL 只能在回放入口只读查看。

## 1. 最终架构

```text
Agent 库（全局可复用）
  variables / prompt{system,template} / resources / model / output
        │
        ▼
Flow v2（dslVersion=2）
  start ─ agent ─ condition / loop / human ─ end
        │
        └─ agent 节点只存 {agentId, inputMap}

运行
  targetType=flow|agent + targetId
  事件：run / node / token / tool / knowledge / human / stats
```

Agent 是全局资源，实时引用、没有发布或版本锁；同一个 Agent 在 Agent 库直聊、不同流程节点各自拥有独立对话历史（`agentId + flowId + nodeId`）。

## 2. v2 契约

### 2.1 Agent

`AgentCreate`：

```text
{
  name, description,
  variables[]: {key,label,type,required,default,description},
  prompt: {system,template},
  resources[]: {kind:"tool"|"mcp"|"knowledge", id, alias, tools[], queryVar, topK, rerank},
  model: {name,temperature,maxTokens,maxToolRounds},
  output: {description,schema}
}
```

- `variables` 可以为空。零变量 Agent 合法；新建 Agent 默认 `variables=[]`。
- Agent 对话优先使用 `query`，否则第一个 `string` 变量；没有可填变量时，把用户消息追加到模板末尾，不再返回 422。
- 知识库资源的 `queryVar` 必须在 Agent 变量里；MCP 资源必须至少勾选一个工具。
- 校验错误 `AGENT_INVALID` 的 `detail` 是 `{valid,errors,warnings}` 对象；前端 `ApiError` 保留 `rawDetail`。

### 2.2 Flow

- `NodeType = start | agent | condition | loop | human | end`
- 新建流程 `dslVersion=2`，默认 `start_1 -> end_1`。
- `agent` config：`{agentId, inputMap}`。
- `condition` config：`{expression}`，出边 `true/false`。
- `loop` config：`{maxRounds, exitCondition}`，出边 `body/done`。
- `human` config：`{message, timeout}`。
- `end` config：`{outputs}`，支持 `list[str]` 或 `{key: template}`；空列表回退最后一个 Agent 的 `text`。
- 模板寻址：`{{start.x}}`、`{{<nodeId>.output.field}}`、`{{<nodeId>.text}}`、`{{nodes.<nodeId>.output.field}}`。
- Agent 产物：`state.nodes.<nodeId> = {agentId, output, text}`。
- 必填变量未映射：HTTP 422 `FLOW_INVALID`，`detail` 带 `nodeId` 与字段信息。
- 旧 DSL：update / publish / validate / run 统一返回 HTTP 422 `FLOW_DSL_LEGACY`，`detail=null`。

### 2.3 Run / Chat

- `runs.targetType=flow|agent` + `targetId`，Agent run 不使用版本锁。
- Agent 对话：`POST /api/chat/conversations` body `{agentId, flowId?, nodeId?, title}`；`POST /api/chat/conversations/{id}/turns` body `{content, variables?}`，返回 202 + `runId`。
- 每轮对话创建一条 `targetType=agent` 的 run；助手回复不单独落表，读取时按 `chat_turns.run_id` 关联 run 输出。
- 历史只回灌当前会话已成功的 run，近 6 轮 / 3000 字硬截断。

## 3. 步骤执行记录

| 步骤 | 内容 | 结果 |
|---|---|---|
| 1 | 清空旧编排数据，保留工具 / MCP / 知识库资源；冻结 v2 契约 | 完成 |
| 2 | Agent 模型、repo、service、API、`AgentRunner`、单 Agent 同步 run；真实网关覆盖纯文本 / `@tool` / 双工具 / `@kb` / `@mcp` / Schema | 完成 |
| 3 | Flow v2 六类节点、`inputMap`、点路径、`runs.targetType/targetId`、Agent 作用域对话、LangGraph v2 执行器、Agent 异步 run + SSE | 完成 |
| 3 补充 | 旧 DSL 专用错误码 `FLOW_DSL_LEGACY` | 完成 |
| 4 | 前端一次性切换：Agent 库 / 编辑器 / 对话、Flow v2 画布、运行目标化、运行输入弹窗、删除旧页面和旧配置表单 | 完成 |
| 5 | 取消零变量限制；后端全量测试、前端 tsc/build、真实网关冒烟、浏览器检查、文档收成 v2 | 完成 |

### 步骤 5 变更明细

- 后端 `app/api/chat.py`：不再对无 string 变量 Agent 返回 422；计算 `chatText`，交给 `start_agent_run`。
- 后端 `app/engine/agent_task.py` / `app/engine/agent_runner.py`：`start_agent_run`、`run_agent` 增加可选 `chat_text`，零变量或无模板引用时追加到模板末尾。
- 前端 `types/agent.ts`：`emptyAgentPayload()` 默认 `variables=[]`，模板改为「请根据下面的用户消息作答。」
- 前端 `AgentEditorPage.tsx`：零变量提示从“聊天模式需要至少一个 string 变量”改为“没有变量也可以保存”。
- 前端 `AgentChatPage.tsx`：没有 chatVar 时不再禁用输入和发送；提示消息会追加到模板末尾。
- 新增测试：`test_chat_agent.py::test_zero_variable_agent_chat_appends_message`。
- 清理：删除临时 Agent、临时会话、临时 Flow；重新构建前端。

## 4. 验收结果

### 自动化

| 命令 | 结果 |
|---|---|
| `cd agentflow-backend; .venv\Scripts\python.exe -m pytest` | **60 passed** |
| `cd agentflow-frontend; node node_modules\typescript\bin\tsc --noEmit` | 0 错误 |
| `cd agentflow-frontend; node node_modules\vite\bin\vite.js build` | 成功，仅 607 kB chunk 体积提示 |

### 真实网关

| 场景 | 结果 |
|---|---|
| 零变量 Agent 对话（接口） | `succeeded`，144 tokens |
| 知识库 Agent 对话（接口） | `succeeded`，432 tokens |
| 两 Agent 串联（接口） | `succeeded`，293 tokens |
| 零变量 Agent 对话（浏览器） | `succeeded`，104 tokens，¥0.000400，刷新后历史仍在 |
| 两 Agent 串联（浏览器） | `succeeded`，4 节点、2 次模型调用、368 tokens、3.2s |

### 页面与接口检查

- `/agents` 新建 Agent 后变量为 0，保存成功。
- Agent 编辑器导入知识库、插入 `@kb[...]`；删除资源后校验失败并提示未解析别名。
- 零变量 Agent 对话可发送，消息追加到模板末尾。
- `flow_917b6615` 在浏览器运行成功；`chat_1.output.text` 正确进入 `kb_1.inputMap.query`。
- 必填变量未映射：`422 FLOW_INVALID`，detail 定位到 Agent 节点。
- 旧 DSL：四入口返回 `422 FLOW_DSL_LEGACY`。

## 5. 已实现清单

- 全局 Agent 库 CRUD、定义校验、运行时资源探测。
- 零变量 / 固定提示词 Agent；Agent 直聊和流程节点作用域对话。
- Flow v2 六类节点、inputMap、点路径变量、条件表达式、循环、审批、结束 outputs。
- Flow v2 的 LangGraph 执行、checkpoint 独立 DB、协作式取消、SSE。
- 单 Agent 同步 run、异步 run + SSE。
- Agent 资源：内置 / HTTP 工具、MCP stdio、知识库 BM25 + MMR。
- 运行历史 / 回放按 Flow / Agent 目标展示。
- 旧 DSL 四入口专用错误码。
- Agent 库 / 编辑器 / 对话页、Flow v2 画布、运行输入弹窗。

## 6. 未实现清单

- Agent / Flow 的发布、版本锁、回滚。
- 旧流程自动迁移、备份、前后兼容。
- Agent 资源批量导入。
- 运行历史按名称搜索。
- Flow v2 并行扇出。
- 对话摘要、长期记忆、向量记忆。
- 向量检索；知识库仍为 BM25 + MMR。
- MCP 远程 SSE / HTTP transport，仅支持 stdio。
- Agent 引用数提示与变更记录。

## 7. 已知限制

- Agent 实时引用：改一个 Agent 会立即影响所有引用它的流程，没有版本隔离。
- `inputMap` 只校验路径可解析，不限制只能引用直接上游。
- 零变量 Agent 直聊是“固定模板 + 追加用户消息”；如果需要结构化输入，仍应声明变量。
- 知识库 `queryVar` 必须在 Agent 变量中；零变量 Agent 导入知识库前必须补一个 string 变量。
- 旧 DSL 只能回放，不能编辑、发布、校验或运行。
- 旧的 demo / loop 执行代码留在仓库作离线对照，v2 正常入口只走 LangGraph。
