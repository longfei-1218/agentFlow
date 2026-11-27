# 工具 / MCP 扩展指南

本文只讲「怎么新增」。目录分层、导入事务、多人化边界见 `docs/resource-package-architecture.md`。

---

## 1. 先分清三类资源

| 类型 | 谁能上传 | 放在哪 | 是否执行代码 |
| --- | --- | --- | --- |
| 内置工具 `builtin_tool` | 只能随代码提交 | `agentflow-backend/resources/builtin_tools/<name>/` | 是，进程内 Python |
| 本地 MCP `mcp` + `stdio` | 平台用户导入 zip | `agentflow-backend/data/resources/users/<owner>/mcp/<id>-<rand>/` | 是，独立子进程 |
| 远程 MCP `mcp` + `http` | 平台用户提交 manifest | 只存注册表 | 否，HTTP JSON-RPC |
| HTTP 工具 `http_tool` | 平台用户提交 manifest | 只存注册表 | 否，后端发 HTTP |

外部导入不允许 `builtin_tool`。内置工具是受信任代码，不能通过上传接口进入主进程。

---

## 2. 新增一个内置工具

以 `render_interview_repo` 为例，新增目录：

```text
agentflow-backend/resources/builtin_tools/render_interview_repo/
  manifest.json
  tool.py
```

### 2.1 manifest.json

```json
{
  "schemaVersion": 1,
  "kind": "builtin_tool",
  "name": "render_interview_repo",
  "description": "把结构化面试结果渲染成固定模板 HTML 并落盘，返回下载路径",
  "aliases": ["render_interview_report"],
  "runtime": { "type": "python", "entrypoint": "tool.py" },
  "paramsSchema": {
    "type": "object",
    "properties": {
      "title": { "type": "string" },
      "candidate": { "type": "string" }
    }
  },
  "permissions": { "fsWrite": ["${ARTIFACT_DIR}"] }
}
```

`name` 是主名，`aliases` 是兼容别名。`paramsSchema` 会成为模型看到的参数定义，`tool_repo` 会强制用它覆盖请求体，前端不能伪造。

### 2.2 tool.py

```python
from pathlib import Path


def run(args: dict, context: dict) -> dict:
    artifact_dir = Path(context["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / "report.html"
    target.write_text("<html>...</html>", encoding="utf-8")
    return {
        "ok": True,
        "path": str(target),
        "fileName": target.name,
        "downloadUrl": f"/api/artifacts/{target.name}",
    }
```

约定：

- 入口固定 `run(args, context)`，返回 `dict`；
- 参数已由 `tool_runner.invoke()` 按 Schema 校验；
- 失败抛 `ToolError(message, code=...)`，不要返回半成品；
- 产物写 `context["artifact_dir"]`，不要写仓库目录；
- 模板、转义、文件名由代码固定，模型只填结构化字段。

### 2.3 不需要改主程序

`app/resources/catalog.py` 会自动扫描 `resources/builtin_tools/*/manifest.json`，动态加载 `tool.py` 并缓存模块。`GET /api/tools/builtins`、`tool_repo._normalize`、`tool_runner._builtin_call` 都走 Catalog，不需要再改 `BuiltinName` 或 `BUILTIN_SCHEMAS`。

### 2.4 测试

`agentflow-backend/tests/test_tools.py` 至少覆盖：

- 通过 `POST /api/tools` 用 `kind=builtin` 保存成功；
- `POST /api/tools/{id}/test` 返回 `ok:true`；
- 产物真的落盘、内容正确、用户文本被 HTML 转义。

---

## 3. 导入 HTTP 工具

### 3.1 前端

「工具」页 → 右上「导入 HTTP 工具」→ 粘贴 manifest → 导入并验证。

### 3.2 manifest

```json
{
  "schemaVersion": 1,
  "kind": "http_tool",
  "name": "lookup_order",
  "description": "按订单号查询订单状态",
  "method": "GET",
  "url": "https://api.example.com/orders/{{orderId}}",
  "headers": { "Authorization": "Bearer ${API_TOKEN}" },
  "env": { "API_TOKEN": "${MY_API_TOKEN}" },
  "paramsSchema": {
    "type": "object",
    "properties": { "orderId": { "type": "string" } },
    "required": ["orderId"]
  },
  "timeoutMs": 5000,
  "retries": 1,
  "risk": "low"
}
```

`{{orderId}}` 是模型传参插值，`${API_TOKEN}` 是环境变量展开。`env` 里的值也可以再引用 `.env` / 进程变量。

当前导入只校验 manifest 与 schema，不强制真实试跑；需要连通性验证时，先保存后在工具页「试跑」。

### 3.3 API

```powershell
curl.exe -F "kind=http_tool" -F "manifest=<manifest.json" http://127.0.0.1:8000/api/resources/import
```

成功返回：

```json
{
  "ok": true,
  "kind": "http_tool",
  "status": "installed",
  "name": "lookup_order",
  "targetId": "tool_...",
  "verifiedAt": "2026-..."
}
```

---

## 4. 导入本地 MCP（stdio）

### 4.1 zip 目录

zip 根目录必须有唯一一个 `manifest.json`：

```text
my_mcp.zip
  manifest.json
  server.py
```

`manifest.json`：

```json
{
  "schemaVersion": 1,
  "kind": "mcp",
  "name": "my-mcp",
  "transport": "stdio",
  "runtime": { "type": "python", "entrypoint": "server.py" },
  "timeoutS": 20,
  "envSchema": [
    { "key": "MY_ROOT", "required": true, "secret": false }
  ],
  "permissions": { "fsRead": ["${MY_ROOT}"], "network": false }
}
```

服务端协议要求：

- `initialize`：返回 `protocolVersion`、`capabilities`、`serverInfo`；
- `notifications/initialized`：通知，不回包；
- `tools/list`：返回 `{tools: [{name, description, inputSchema}]}`；
- `tools/call`：返回 `{content: [{type: "text", text: "..."}], isError: false}`；
- 只往 `stdout` 写 JSON-RPC，一条一行并 `flush`，日志走 `stderr`。

### 4.2 导入流程

1. 上传 zip，限制 100MB、解压后 200MB、最多 500 个文件；
2. 安全解压到 `data/resources/staging/mcp_<rand>`，拒绝绝对路径、`..`、符号链接、越界写入；
3. 在 staging 里真实启动子进程，执行 `initialize` + `tools/list`；
4. 通过后移动到 `data/resources/users/<owner>/mcp/<id>-<rand>/`；
5. 写 MCP 注册表，记录 `packagePath / source=import / status / verifiedAt`；
6. 失败清理 staging，不写注册表。

### 4.3 API / UI

「MCP 服务」页 → 「导入 MCP」→ 选「本地 MCP 包」→ 上传 zip。

```powershell
curl.exe -F "kind=mcp_local" -F "file=@my_mcp.zip;type=application/zip" http://127.0.0.1:8000/api/resources/import
```

---

## 5. 导入远程 MCP（HTTP）

manifest：

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

导入时会真实调用 `initialize` + `tools/list`，兼容 `application/json` 与 `text/event-stream`，并保留 `Mcp-Session-Id`。当前没有 URL 白名单 / SSRF 防护，只允许受信任的人导入。

```powershell
curl.exe -F "kind=mcp_remote" -F "manifest=<remote-mcp.json" http://127.0.0.1:8000/api/resources/import
```

---

## 6. 手工注册（调试用）

不经过导入，也可以直接写注册表。stdio 示例：

```powershell
$body = @{
  name = "demo-mcp"
  transport = "stdio"
  command = "E:\workplace\workplaceReactNative\agentFlow\agentflow-backend\.venv\Scripts\python.exe"
  args = @("E:\workplace\workplaceReactNative\agentFlow\agentflow-backend\resources\mcp\demo\server.py")
  env = @{}
  timeoutS = 20
  enabled = $true
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/mcp-servers -ContentType "application/json" -Body $body
```

远程 HTTP 示例把 `transport` 改成 `http`、填 `url` / `headers`，`command` 留空。

---

## 7. 环境变量约定（工具与 MCP 共用）

配置文本里用 `${NAME}` 引用环境变量，运行时由后端解析，不会把占位符发给上游。

| 位置 | 支持 `${NAME}` 的字段 |
| --- | --- |
| 工具 | `url`、`headers` 的每个值、`bodyTemplate`、`env` 的每个值 |
| MCP | `command`、`args[]`、`cwd`、`env` 的每个值、远程 `url` / `headers` |

合并顺序，后者覆盖前者：

1. 后端进程环境变量；
2. 后端工作目录下的 `.env`（`AGENTFLOW_ENV_FILE` 可指定）；
3. 资源自己的 `env`。

缺失变量直接报错：

- 工具：`TOOL_ENV_MISSING`
- MCP：`MCP_ENV_MISSING`

```dotenv
# agentflow-backend/.env
MY_API_TOKEN=sk-real-secret
DOC_ROOT=E:\workplace\workplaceReactNative\agentFlow\docs
```

```json
{ "AGENTFLOW_DOC_ROOTS": "${DOC_ROOT}" }
```

注意：

- 资源 `env` 的 key 会覆盖同名进程变量；不要把值写成对自身的引用（`"TOKEN": "${TOKEN}"`）。
- 当前只做一层替换，不支持 `${VAR:-default}`。
- 明文密钥会随 `definition_json` 存进 SQLite；私密常量优先写 `${...}`。

---

## 8. 验收命令

```powershell
cd agentflow-backend
.venv\Scripts\python.exe -m pytest -q
# 期望 70 passed

cd ..\agentflow-frontend
npm run build
```

真实接口检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/resources
Invoke-RestMethod http://127.0.0.1:8000/api/tools/builtins
Invoke-RestMethod http://127.0.0.1:8000/api/artifacts
```

---

## 9. 已知边界

- 外部不能上传内置工具；内置工具必须走代码评审。
- 本地 MCP 与主后端共享同一 Python 环境，没有 per-resource venv / 容器。
- 远程 MCP 没有 URL 白名单 / SSRF 防护。
- MCP 的 `envSchema.required=true` 目前不强制导入时填值，运行时缺变量才报 `MCP_ENV_MISSING`。
- 安装目录移动后注册表写入失败，当前可能留下孤儿目录，未做事务回滚。
- HTTP 工具导入不做真实试跑，只校验 manifest / schema。
- `${VAR}` 一层替换，不支持默认值。
