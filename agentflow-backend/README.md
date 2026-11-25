# AgentFlow Studio · 后端（P1 骨架）

FastAPI + aiosqlite + sse-starlette。已实现：

- 配置（`.env`）、SQLite 建表（8 张表，P1 只用前三张）
- Flow CRUD + `/api/flows/{id}/validate`（唯一入口/出口、孤立节点、环检测、condition 双分支）
- Run 创建、详情、历史、SSE 事件流（`Last-Event-ID` 断点续推）
- `/api/runs/{id}/cancel`、`/resume`、`/to-case` 的前置数据通路
- P1 演示执行器 `app/engine/mock_runner.py`：按拓扑顺序推送 node/token/run 事件，不调用真实 LLM

## 本地启动

```bash
python -m venv .venv
# Windows Git Bash:
source .venv/Scripts/activate
# PowerShell:
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000/docs 查看 Swagger。

## 快速验证

```bash
# 1. 健康检查
curl http://localhost:8000/api/health

# 2. 新建流程（不传 nodes 会自动生成 input → llm → output 三节点）
curl -X POST http://localhost:8000/api/flows -H "Content-Type: application/json" -d '{"name":"演示流程"}'

# 3. 触发运行（返回 run_id）
curl -X POST http://localhost:8000/api/flows/<flow_id>/run -H "Content-Type: application/json" -d '{"inputs":{"query":"你好"}}'

# 4. 订阅事件流（另一个终端）
curl -N http://localhost:8000/api/runs/<run_id>/events
```

> P2 将用 `app/engine/loop.py` 的手写 Agent Loop 替换演示执行器；P3 迁 LangGraph 并接入工具/RAG/MCP。
