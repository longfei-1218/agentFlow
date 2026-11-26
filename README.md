# agentFlow

AgentFlow Studio — Web 端 Agent 编排平台（本地单用户原型）

## 目录
- `docs/agent-orchestrator-tech-design.md` — v1.1 技术设计文档（数据模型 / API / 评测体系）
- `docs/agentflow-studio-ui.html` — 前端 UI 静态设计稿（浏览器直接打开，6 个页面可切换）
- `docs/backend-implementation-guide.md` — 后端实现步骤（FastAPI，P1–P5）
- `docs/frontend-implementation-guide.md` — 前端实现步骤（React + TS + Vite，P1–P5）
- `agentflow-backend/` — 后端工程（**B1 完成**：Flow CRUD + 版本语义、SSE 事件流、取消/审批续跑、15 个 pytest 用例）
- `agentflow-frontend/` — 前端工程（P1 骨架已初始化，React + TS + Vite + React Flow）

## 快速启动（P1）
```bash
# 终端 1：后端（http://localhost:8000，Swagger: /docs）
cd agentflow-backend
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 终端 2：前端（http://localhost:5173）
cd agentflow-frontend
npm install
npm run dev
```
Vite 会把 `/api` 代理到后端。

## 技术栈
后端 Python 3.11 · FastAPI · LangGraph · SQLite · Chroma · MCP
前端 React 18 · TypeScript · Vite · React Flow · Zustand · Tailwind
