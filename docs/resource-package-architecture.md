# 资源包架构：MCP / 工具 / 知识库与主 Agent 解耦

## 1. 目标与已定边界

目标是把「MCP Server、HTTP 工具、知识库文档」从主 Agent 代码里拆出来，变成可导入、可验证、可归属到某个上传者的资源；主程序只依赖统一目录和 Catalog，不再直接 `import` 某个具体资源。

已确认的边界：

| 决策 | 当前落地 |
| --- | --- |
| 外部可导入类型 | 只允许 `mcp` 和 `http_tool`，不允许上传 Python 内置工具 |
| MCP 传输 | 本地 `stdio` + 远程 `http`（JSON-RPC，兼容 JSON / SSE 响应） |
| 隔离级别 | 简单隔离：独立子进程、staging 探测、独立用户目录；不做容器 / 虚拟机 |
| 登录 / 租户 | 先不做登录，`owner` 固定为 `local` |
| 知识库 | 文档落用户资源目录，SQLite 继续做 chunk 检索索引 |

## 2. 目录结构

```text
agentflow-backend/
  resources/                         # 随代码发布、受信任的资源包
    builtin_tools/
      render_interview_repo/
        manifest.json
        tool.py
    mcp/
      parse_document/
        manifest.json
        server.py
    knowledge/
      README.md                      # 运行时知识库落在 data/resources，不放仓库
  data/resources/                    # 运行时上传 / 用户资源，应加入 .gitignore
    staging/                         # 导入临时目录，验证失败即清理
    users/
      local/
        mcp/
          <resource>-<rand>/         # 安装后的本地 MCP 包
            manifest.json
            server.py
        knowledge/
          <kb_id>/
            manifest.json
            documents/<doc_id>.md
```

- `resources/` 是「可信代码包」：只能由开发者提交，Catalog 从这里加载内置工具。
- `data/resources/` 是「用户资源」：由导入 API / 知识库 API 写入，按 `owner` 隔离，不参与代码发布。
- 主 Agent 运行时只通过 `catalog`、`tool_repo`、`mcp_repo`、`knowledge_repo` 拿能力，不直接引用某个资源的具体实现。

## 3. Manifest 约定

所有资源包根目录必须有 `manifest.json`，`schemaVersion=1`。

内置工具 `resources/builtin_tools/render_interview_repo/manifest.json`：

```json
{
  "schemaVersion": 1,
  "kind": "builtin_tool",
  "name": "render_interview_repo",
  "aliases": ["render_interview_report"],
  "runtime": { "type": "python", "entrypoint": "tool.py" },
  "paramsSchema": { "type": "object", "properties": {} },
  "permissions": { "fsWrite": ["${ARTIFACT_DIR}"] }
}
```

本地 MCP `resources/mcp/parse_document/manifest.json`：

```json
{
  "schemaVersion": 1,
  "kind": "mcp",
  "name": "parse-document",
  "transport": "stdio",
  "runtime": { "type": "python", "entrypoint": "server.py" },
  "timeoutS": 20,
  "envSchema": [
    { "key": "AGENTFLOW_DOC_ROOTS", "required": true, "secret": false }
  ],
  "permissions": { "fsRead": ["${AGENTFLOW_DOC_ROOTS}"], "network": false }
}
```

远程 MCP manifest（导入时提交）：

```json
{
  "schemaVersion": 1,
  "kind": "mcp",
  "name": "remote-search",
  "transport": "http",
  "url": "https://mcp.example.com/mcp",
  "headers": { "Authorization": "Bearer ${MCP_TOKEN}" },
  "timeoutS": 20
}
```

HTTP 工具 manifest（导入时提交）：

```json
{
  "schemaVersion": 1,
  "kind": "http_tool",
  "name": "lookup_order",
  "description": "按订单号查询订单状态",
  "method": "GET",
  "url": "https://api.example.com/orders/{{orderId}}",
  "headers": { "Authorization": "Bearer ${API_TOKEN}" },
  "paramsSchema": {
    "type": "object",
    "properties": { "orderId": { "type": "string" } },
    "required": ["orderId"]
  }
}
```

`{{参数名}}` 是模型传参插值，`${VAR}` 是环境变量展开，由后端 `env_config` 解析。密钥不要写进 manifest，写占位符，真实值放进程环境或 `.env`。

## 4. 导入与验证流程

### 4.1 本地 MCP zip

1. 上传 zip（最大 100MB；解压后最大 200MB；最多 500 个文件）。
2. 安全解压到 `data/resources/staging/mcp_<rand>`：拒绝绝对路径、`..`、符号链接、越界写入。
3. 在 staging 里找唯一 `manifest.json`，校验 `kind=mcp`、`transport=stdio`、`entrypoint` 在包内。
4. 用当前后端 Python 启动子进程，真实执行 `initialize` + `tools/list`。
5. 探测通过后移动到 `data/resources/users/<owner>/mcp/<id>-<rand>/`，写入 MCP 注册表，记录 `packagePath/source/status/verifiedAt`。
6. 探测失败或名称冲突：返回 `ok=false`，清理 staging，不写注册表。

### 4.2 远程 MCP

1. 提交 manifest，校验 `transport=http` 和 `url`。
2. 真实调用一次 `initialize` + `tools/list`，支持 `application/json` 与 `text/event-stream`，保留 `Mcp-Session-Id`。
3. 探测通过后写入 MCP 注册表；当前不做 URL 白名单 / SSRF 防护，只允许受信任的人导入。

### 4.3 HTTP 工具

1. 校验 `kind=http_tool`、`url`、`paramsSchema`。
2. 写入工具注册表，标记 `source=import`、`verifiedAt`。
3. 当前「验证」只做 manifest / schema 校验，不强制真实试跑；需要真实连通性时，后续增加 `testArgs` 再调用一次。

### 4.4 知识库

- 创建知识库：建 `data/resources/users/<owner>/knowledge/<kb_id>/manifest.json`。
- 添加文档：写 `documents/<doc_id>.md`，正文是 `# 标题` + 原文；SQLite 继续存 `kb_documents` / `kb_chunks`。
- 删除文档 / 知识库：同步清理目录。SQLite 仍是检索索引，文件目录是可读、可备份、可迁移的源数据。

## 5. API 与前端入口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/resources` | 资源总览：owner、内置工具、工具、MCP、知识库 |
| `POST` | `/api/resources/import` | multipart 导入，`kind=mcp_local/mcp_remote/http_tool` |
| `GET` | `/api/tools/builtins` | 内置目录：核心 echo/now/calc + Catalog 扫描结果 |
| `GET` | `/api/mcp-servers` | MCP 列表（含 `transport/url/packagePath/source/status`） |
| `POST` | `/api/mcp-servers/{id}/probe` | 重新探测 MCP 工具清单 |
| `POST` | `/api/mcp-servers/{id}/call` | 试跑 MCP 工具 |

前端：

- 「工具」页新增「导入 HTTP 工具」；
- 「MCP 服务」页新增「导入 MCP」，支持本地 zip 和远程 manifest；
- 同一个导入弹窗按类型切换，导入结果直接显示 `targetId / packagePath / 探测工具数`。

## 6. 主程序依赖关系

```text
tool_runner._builtin_call
  -> catalog.invoke_builtin(name, args, context)
       -> resources/builtin_tools/<name>/tool.py:run()

tool_repo._normalize
  -> catalog.list_builtins() / catalog.get_spec(name)
  -> 不再硬编码 BuiltinName 与 BUILTIN_SCHEMAS

mcp_client
  -> _session_for(server) 选择 StdioMCPSession / HTTPMCPSession

knowledge_repo
  -> knowledge_store：文件目录
  -> SQLite：检索索引
```

## 7. 当前验证结果

- 后端 `pytest -q`：**70 passed**。
- 本地 MCP 真实导入：`parse-document-import-20261127`，安装到 `data/resources/users/local/mcp/parse-document-import-20261127-b6debcb8`，`tools/list` 探测到 `parse_document`（验证后已清理测试资源）。
- 导入后的 MCP 真实调用成功：解析包内 `manifest.json`，返回 999 chars，`truncated=false`。
- HTTP 工具真实导入：`lookup_order_import_test`，`tool_20261127_1215235ac7`（验证后已清理测试资源）。
- 前端 `tsc --noEmit && vite build` 通过，产物 `index-CYBVRM6T.js`（614.88 kB）。

## 8. 已知边界与下一版

当前是「简单隔离」，以下能力明确留到多人版本：

- 没有登录 / 租户，`owner` 固定 `local`；上传者身份、配额、审批流未做。
- 远程 MCP 没有 URL 白名单 / SSRF 防护。
- 本地 MCP 与主后端共享同一 Python 环境，没有 per-resource venv / 容器 / seccomp。
- MCP 的 `envSchema.required=true` 目前不强制在导入时填值，只在运行时缺变量报 `MCP_ENV_MISSING`。
- 安装目录移动后如果注册表写入失败，当前可能留下孤儿目录，尚未做事务回滚清理。
- 没有资源版本、签名、审核状态机；`status` 目前只有 `installed/rejected` 的简单语义。
- HTTP 工具导入只校验 schema，不做真实试跑。

下一版优先级建议：

1. 资源表加 `owner_id / visibility / review_status / version / checksum`，并做 owner 鉴权。
2. 远程 MCP URL 允许列表 + 私网地址拦截。
3. 本地 MCP 安装事务：先写 DB 再移动，失败回滚。
4. HTTP 工具导入支持 `testArgs` 真实试跑。
5. 资源包签名 / 审核，阻止任意代码直接进 `resources/`。
