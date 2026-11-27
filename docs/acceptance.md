# AgentFlow v2 验收清单

> 适用口径：Flow v2（`dslVersion=2`，六类节点 `start/agent/condition/loop/human/end`）+ 全局 Agent 库 + Agent 作用域对话。旧 DSL 只在回放入口可见，不能编辑、发布、校验或运行。
>
> 后端命令在 `agentflow-backend/` 执行，前端命令在 `agentflow-frontend/` 执行。

## 步骤 5 验收（全量验证与收尾）

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest
# 期望 80 passed

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

## R6.0 版本管理验收（2026-11-27 已实现）

### A. 自动化

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest tests\test_versions.py -q
# 期望 11 passed

.venv\Scripts\python.exe -m pytest -q
# 期望 81 passed
```

覆盖点：

| # | 用例 | 期望 |
|---|---|---|
| 1 | Agent 同配置连发两次 | 两次都成功，生成 v1 / v2，`configHash` 相同、版本名可区分 |
| 2 | 发布不填版本名 | 422 `VERSION_NAME_REQUIRED`；说明留空可正常发布 |
| 3 | 改草稿后查 publish-state | `ahead=true`、指针仍是旧版本 |
| 4 | Flow 发布时 Agent 未发布 | 422 `AGENT_VERSION_MISSING`，detail 带 nodeId |
| 5 | Flow 发布 | manifest `agentRefs` 记录 `agentId + version + configHash` |
| 6 | Agent 草稿新增必填变量但未发布 | Flow 发布按已绑定快照校验，422 拦住 inputMap |
| 7 | 回滚 Agent | 指针回 v1、草稿回 v1、v2 历史仍在；再发布得 v3 |
| 8 | 回滚 Flow | 指针回 v2，Agent 版本与历史完全不动 |
| 9 | 运行清单 | 改 Agent 草稿后 run 标 `versionMode=draft`，记录 currentHash / publishedVersion |
| 10 | 基线回填 | 存量 Agent / v2 Flow 各生成 v1，二次启动不重复 |
| 11 | 统一列表 | `/api/versions` 返回两类资源与发布状态 |

### B. 迁移冒烟（真实库副本）

```powershell
# 用 sqlite backup 复制 data/agentflow.db 到临时路径，再以 DATABASE_PATH 指向副本启动
# 2026-11-27 结果：agents 3 / agent_versions 3；flows 2 / flow_versions 2；
# unpublished agents 0；flows without published hash 0；flow runs without target_version 0
```

### B2. 接口级验收（真实库副本，2026-11-27 已执行，含版本名口径复测）

以 `sqlite3.backup` 复制真实库、`DATABASE_PATH` 指向副本、另起 8011 端口跑真实 HTTP 请求：

| 步骤 | 结果 |
|---|---|
| `GET /api/versions` | 3 个 Agent（基线 v1，`ahead=false`）+ 2 个 Flow（基线 v1） |
| Flow 版本详情 | snapshot 含 6 nodes / 7 edges、`dslVersion=2`；manifest 含 `code.commit=408581b`、`dirty=true`、`agentRefs` 绑定 v1 |
| Agent 同配置再发 | 200，生成 v2；`configHash` 与 v1 相同，历史保留 `2,1` |
| 发布不填版本名 | 422 `VERSION_NAME_REQUIRED`；只填版本名、说明留空可正常发布 |
| Flow 同配置再发 | 200，生成 v2；`configHash` 不变，`name=同配置流程补发`、`note` 落库 |
| 改提示词 → 发布 → 回滚 v1 | 发布得 v2，回滚后指针/草稿回 v1，历史保留 `2,1`，state `pub=1 latest=2` |
| Flow 改 end outputs → 发布 → 回滚 v1 | 发布得 v2，回滚后名称/配置回 v1，历史 `2,1`；Agent 指针仍 v1、历史未增 |
| v2 快照时间戳 | 与发布行一致（修复了 dsl_json 沿用旧 `updatedAt` 导致乐观锁比对失准的问题） |

### C. 浏览器检查（重启后端后执行）


> 2026-11-27 23:07 已用 `--reload` 重启后端（8000 在线，`GET /api/versions` 返回 5 条）。已用浏览器确认 `/versions` 正常加载、发布弹窗「版本名必填、空名时确认按钮禁用、填写后可用」；其余交互项待逐条点验。

| # | 入口 | 检查 |
|---|---|---|
| 1 | `/agents/:id` | 顶栏显示 `vN` 或「未发布」；改提示词后出现「有未发布改动」；点「发布版本」必须填版本名（说明可空），发布成功后版本变 vN+1 |
| 2 | `/flows/:id` | 顶栏 `vN` 可点进版本页；Agent 节点未发布时发布报错列出节点；发布后 manifest 绑定 Agent 版本 |
| 3 | `/versions` | Agent / 流程两个 tab；左侧资源列表显示发布指针、草稿领先、已回滚；右侧时间线可切换版本 |
| 4 | `/versions` 详情 | 版本名与说明分开展示；配置快照按提示词 / 变量 / 资源 / 节点结构化展示；指纹、commit、工具指纹、Agent 绑定齐全 |
| 5 | `/versions` 回滚 | 确认框说明「不改 Agent 版本」；回滚后指针与草稿同步，历史仍在，再发布按 MAX+1 |
| 6 | `/runs` | 显示 `Flow vN` / `Agent vN`；草稿运行有「草稿」标签 |
| 7 | `/runs/:id` | 「版本清单」折叠块可看到 configHash、agentRefs、code.commit |

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
- 运行使用当前保存的配置；发布版本用于快照与质量归因，本期不做版本 diff。
- 旧 DSL 只读回放，不支持编辑、发布、校验、运行。
- 对话历史近 6 轮 / 3000 字硬截断。
- Flow v2 暂不支持并行扇出。
