# AgentFlow v2 验收清单

> 适用口径：Flow v2（`dslVersion=2`，六类节点 `start/agent/condition/loop/human/end`）+ 全局 Agent 库 + Agent 作用域对话。旧 DSL 只在回放入口可见，不能编辑、发布、校验或运行。
>
> 后端命令在 `agentflow-backend/` 执行，前端命令在 `agentflow-frontend/` 执行。

## 步骤 5 验收（全量验证与收尾）

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest
# 期望 70 passed

cd ..\agentflow-frontend
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
# 期望 tsc 0 错误；Vite build 成功，仅有 chunk 体积提示
```

### B. 真实网关冒烟（DeepSeek，2026-11-27 已执行）

```powershell
cd agentflow-backend
.venv\Scripts\python.exe scripts\seed_v2_demo.py --smoke
```

本轮另外直调运行接口，结果：

| 场景 | 结果 |
|---|---|
| 零变量 Agent 对话 | `succeeded`，回复 `零变量冒烟成功`，144 tokens |
| 知识库 Agent 对话 | `succeeded`，按售后知识库回答退款政策，432 tokens |
| 两 Agent 串联 `flow_917b6615` | `succeeded`，293 tokens，end outputs 正常 |
| 浏览器零变量 Agent 对话 | `succeeded`，回复 `零变量AI对话成功`，104 tokens |
| 浏览器两 Agent 串联 | `succeeded`，4 节点 / 2 次模型调用 / 368 tokens / 3.2s |

### C. 浏览器 / 接口检查（真实环境，2026-11-27 已执行）

| # | 入口 | 检查 | 结果 |
|---|---|---|---|
| 1 | `/agents` → 新建 Agent | 新建后变量为 0；编辑器显示「没有变量也可以保存：对话消息会追加到模板末尾」；保存提示「已保存」 | 通过 |
| 2 | `/agents/:id` 资源导入 | 选择知识库、填别名、插入 `@kb[售后知识库]`；删除资源后点「校验」提示 `@kb[售后知识库] 没有对应的知识库资源` | 通过 |
| 3 | `/agents/:id/chat` 零变量 | 输入「请只回复：零变量AI对话成功」可发送；回复成功；刷新后历史仍在 | 通过 |
| 4 | `/flows/flow_917b6615` | 画布显示六类节点；两个 Agent 节点显示映射；点运行填 `query` 后跑通，日志 `chat_1` 输出进入 `kb_1` 的 inputMap | 通过 |
| 5 | 接口：必填变量未映射 | 新建 `start(query) -> agent(无 inputMap) -> end`，`POST /run` 返回 422 `FLOW_INVALID`，detail 定位 `nodeId=a1`，message「Agent 必选变量 query 没有映射」 | 通过 |
| 6 | 接口：旧 DSL | 直接插入 `dsl_version=1` 的流程，validate/publish/run/update 均返回 422 `FLOW_DSL_LEGACY` | 通过 |

### D. 本轮清理

- 删除冒烟用的临时 Agent、临时会话和临时 Flow。
- 文档已收成 v2 口径；历史段落已删除。
- 前端构建产物已重新生成。

### E. 工具 / MCP 扩展（2026-11-27 已执行）

| # | 入口 | 检查 | 结果 |
|---|---|---|---|
| 1 | 接口：`GET /api/tools/builtins` | 返回 `echo / now / calc / render_interview_repo / render_interview_report`，后两者 Schema 相同 | 通过 |
| 2 | 接口：注册 `render_interview_repo` | `tool_20261127_0845404cca`，`kind=builtin` | 通过 |
| 3 | 接口：试跑面试报告 | `ok=true`，落盘 `interview_report_20261127_164601_1dd6de.html`（6584 bytes），`downloadUrl` 可下载 | 通过 |
| 4 | 接口：注册 `parse-document` MCP | `mcp_20261127_084540c725`，stdio，env 含 `AGENTFLOW_DOC_ROOTS` | 通过 |
| 5 | 接口：探测 `parse-document` | `ok=true`，495 ms，工具清单为 `parse_document` | 通过 |
| 6 | 接口：解析 README | `ok=true`，3969 chars，超过 `maxChars=1200` 时 `truncated=true` | 通过 |
| 7 | 接口：产物下载 | `GET /api/artifacts/{fileName}` 返回 200，`text/html; charset=utf-8`，包含报告标题 | 通过 |

### F. 资源包解耦与外部导入（2026-11-27 已执行）

| # | 入口 | 检查 | 结果 |
|---|---|---|---|
| 1 | 目录：`resources/builtin_tools/render_interview_repo/` | `manifest.json + tool.py`，Catalog 动态加载，主程序不再硬编码 renderer | 通过 |
| 2 | 目录：`resources/mcp/{demo,parse_document}/` | MCP server + manifest 已从 `scripts/` 迁入资源包，旧脚本已删除 | 通过 |
| 3 | 接口：导入本地 MCP zip | `mcp_20261127_1215113720`，安装到 `data/resources/users/local/mcp/parse-document-import-20261127-b6debcb8`，探测到 `parse_document`（验证后已清理） | 通过 |
| 4 | 接口：调用导入的 MCP | 解析安装包内 `manifest.json`，999 chars，`truncated=false`，527 ms | 通过 |
| 5 | 接口：导入 HTTP 工具 manifest | `tool_20261127_1215235ac7`，`source=import`，`paramsSchema.required=["orderId"]`（验证后已清理） | 通过 |
| 6 | 接口：`GET /api/resources` | 返回 `ownerId=local`、Catalog 内置工具、工具、MCP、知识库总览 | 通过 |
| 7 | 前端：工具页 / MCP 页 | 新增「导入 HTTP 工具」「导入 MCP」入口；工具页实际导入 `lookup_order`，MCP 页显示本地包 / 远程两个页签 | 通过 |
| 8 | 自动化 | 资源导入 / 远程 HTTP MCP / 知识库文件落盘 4 条新测试，合计 70 passed | 通过 |

## 步骤 4 验收（前端一次性切换，已完成）

- 路由：`/agents`、`/agents/:id`、`/agents/:id/chat`；删除旧 `/flows/:id/chat`。
- Flow 画布只显示六类节点；Agent 节点支持下拉、inputMap、编辑/对话入口；开始变量、条件 true/false、循环 body/done、审批、结束 outputs 可配置。
- 运行输入弹窗按开始节点变量收集；旧 DSL 编辑器提示并禁用运行。
- 运行历史按 `targetType/targetId` 展示 Flow 或 Agent。

## 步骤 3 验收（Flow v2 + Agent 对话，已完成）

- 两 Agent `inputMap` 串联、condition 只走 true、loop 跑满 body 后 done、human 暂停/批准/拒绝。
- Agent run SSE、协作式取消、会话三作用域隔离。
- 旧 DSL 四入口返回 `FLOW_DSL_LEGACY`。

## 步骤 2 验收（Agent 资源层与 Runner，已完成）

- Agent CRUD 与定义校验；`@kb` 检索、`@tool` / `@mcp` 强制调用、输出 Schema 重试、空回答错误码。
- 真实 DeepSeek 冒烟覆盖纯文本、工具、双工具、知识库、MCP、Output Schema。

## 步骤 1 验收（数据清理与契约冻结，已完成）

- 清空旧编排数据，保留工具 / MCP / 知识库资源。
- 冻结 Flow v2 六类节点与 Agent 契约。

## 环境准备

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

| 项 | 判断方法 | 期望 |
|---|---|---|
| venv 解释器 | `.venv\Scripts\python.exe -V` | Python 3.10+ |
| 后端启动 | uvicorn 命令 | 带 `--reload-dir app`，8000 端口 |
| 前端启动 | `npm run dev` | 5173 端口，`/api` 代理到 8000 |
| 模型配置 | 右上「模型设置」 | Key 只显示脱敏预览，测试连接成功 |

## 已知限制

- `inputMap` 只校验路径可解析，不限制只能引用直接上游。
- Agent 资源逐条添加；MCP / HTTP 工具已支持外部导入，内置工具仍只允许随代码发布。
- 运行历史不支持名称搜索。
- 实时引用无版本锁；编辑 Agent 立即影响引用流程。
- 旧 DSL 只读回放，不支持编辑、发布、校验、运行。
- 对话历史近 6 轮 / 3000 字硬截断。
- Flow v2 暂不支持并行扇出。
