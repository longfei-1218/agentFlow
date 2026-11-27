# AgentFlow Studio 打包与部署方案

> 状态：方案稿，待确认后落地。当前项目是单用户本地原型：FastAPI + SQLite + LangGraph，前端 Vite/React。
> 目标：产出可复现、可升级、可回滚的交付包，同时保留版本/指纹追踪能力。
> 公网服务器、域名备案、Nginx TLS 等上线资源见 `docs/public-deployment-plan.md`；本文聚焦依赖锁定、构建产物与打包方式。

## 0. 推荐结论

| 方案 | 适用场景 | 建议 |
|---|---|---|
| **A. 单容器（FastAPI 托管前端）** | 单机、内网、演示、个人使用 | **默认推荐**，一个镜像 + 一个 `/data` 卷 |
| B. Nginx + 后端容器分离 | 需要 TLS、域名、多环境、静态缓存 | 可选，增加一个 Nginx 容器 |
| C. Windows 源码 zip + 启动脚本 | 客户机器不能装 Docker | 备选，依赖目标机 Python 3.10.10 |
| D. PyInstaller/Nuitka 单文件 | 完全免 Python 的 Windows 便携包 | **不推荐**，LangGraph/uvicorn/MCP 子进程动态导入风险高 |

核心约束：SQLite + 进程内 `run_manager`，**只能单 uvicorn worker、单副本**。不要用 `--workers 2+`，也不要把同一个库挂到多个容器。

## 1. 依赖版本锁定（已完成）

### 后端

- Python：`3.10.10`（`agentflow-backend/.python-version`）。
- 直接依赖：`requirements.txt` 已全部改为 `==` 精确 pin。
- 完整运行期传递依赖：`requirements.lock.txt`，由 Python 3.10.10 干净虚拟环境安装后 `pip freeze` 生成。
- 开发依赖：`requirements-dev.txt` 精确 pin `pytest 8.4.2`、`pytest-asyncio 0.26.0`、`httpx 0.29.0`。
- SQLite 运行时版本：3.39.4（当前环境）。

> 运行时升级提示：Python 3.10 已于 2026-10 停止安全维护。当前锁定与验证环境仍是 3.10.10；公网长期运行前，建议在 3.11/3.12 干净环境重跑 81 个测试，再切换 Dockerfile 的 Python 版本并重新生成 Linux lock。不要只改 Dockerfile 的版本号。

关键 pin：

```text
fastapi==0.162.5
uvicorn[standard]==0.34.3
websockets==12.0
aiosqlite==0.21.0
pydantic==2.14.4
pydantic-settings==2.15.0
sse-starlette==2.4.1
python-multipart==0.0.32
python-dotenv==1.2.4
orjson==3.13.0
pypdf==5.9.0
langgraph==0.2.76
langgraph-checkpoint-sqlite==2.0.9
```

### 前端

- Node：`22.23.2`，npm `10.9.8`（`agentflow-frontend/.nvmrc`）。
- `package.json` 全部依赖/开发依赖改为精确版本，无 `^`/`~`。
- `package-lock.json` 已按精确版本重建；构建/CI 必须使用 `npm ci`，不要用 `npm install`。
- 已移除未使用依赖 `react-hook-form`、`zod`。

### 锁定后的验收

- `pytest`：**81 passed**。
- `npm ci`：成功。
- `npm run build`（`tsc --noEmit && vite build`）：成功。
- `pip check`：No broken requirements found。

## 2. 交付物定义

每次发布产出：

```text
agentflow-studio-<version>-<short-sha>/
├── agentflow-image.tar          # 可选：docker save 的离线镜像
├── agentflow-frontend-dist.tar  # 可选：纯前端静态包
├── SHA256SUMS
└── RELEASE.md                   # 版本、commit、构建时间、镜像 digest、升级说明
```

镜像 tag 规则：

```text
agentflow-studio:1.1-<short-sha>
agentflow-studio:1.1
agentflow-studio:latest
```

不要只用 `latest`；回滚必须能定位到 `<version>-<sha>`。

## 3. 方案 A：单容器（推荐）

### 3.1 镜像结构

多阶段构建：

1. `node:22.23.2-bookworm-slim` 构建前端，产出 `dist/`。
2. `python:3.10.10-slim-bookworm` 安装 `requirements.lock.txt`，复制后端 `app/`、`resources/`、前端 `dist` 到 `web/dist`。
3. 非 root 用户运行；`/data` 作为唯一持久化目录；`uvicorn --workers 1`。

`app/main.py` 已经支持：如果 `agentflow-backend/web/dist` 存在，就把 `/` 挂成静态站点。因此单容器不需要额外改前端 API 地址：前端 `baseURL="/api"` 与后端同源。

### 3.2 Dockerfile 模板

```dockerfile
# syntax=docker/dockerfile:1.7

FROM node:22.23.2-bookworm-slim AS web
WORKDIR /web
COPY agentflow-frontend/package.json agentflow-frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY agentflow-frontend/ ./
RUN npm run build

FROM python:3.10.10-slim-bookworm AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN groupadd -r agentflow && useradd -r -g agentflow agentflow

COPY agentflow-backend/requirements.txt agentflow-backend/requirements.lock.txt ./
RUN pip install -r requirements.lock.txt

COPY agentflow-backend/app ./app
COPY agentflow-backend/resources ./resources
COPY --from=web /web/dist ./web/dist

RUN mkdir -p /data /data/artifacts /data/resources \
    && chown -R agentflow:agentflow /app /data

USER agentflow

ENV DATABASE_PATH=/data/agentflow.db \
    ARTIFACT_DIR=/data/artifacts \
    RESOURCE_DATA_DIR=/data/resources \
    RUNNER=graph

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

构建参数建议：

```dockerfile
ARG APP_VERSION=1.1
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.created=$BUILD_TIME
ENV APP_VERSION=$APP_VERSION GIT_COMMIT=$GIT_COMMIT BUILD_TIME=$BUILD_TIME
```

### 3.3 `.dockerignore`

```gitignore
.git
.github
.workbuddy
docs
learning
**/node_modules
**/dist
**/.venv
agentflow-backend/data
**/*.log
**/*.db
**/__pycache__
.pytest_cache
```

### 3.4 运行

```powershell
docker build `
  --build-arg APP_VERSION=1.1 `
  --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) `
  --build-arg BUILD_TIME=$(Get-Date -Format o) `
  -t agentflow-studio:1.1-$(git rev-parse --short HEAD) .

docker run -d --name agentflow `
  -p 127.0.0.1:8000:8000 `
  -v agentflow-data:/data `
  --env-file agentflow-backend/.env `
  --restart unless-stopped `
  agentflow-studio:1.1-<sha>
```

第一次启动会自动建库、迁移并创建基线版本。打开 `http://127.0.0.1:8000/`。

### 3.5 docker-compose

```yaml
services:
  agentflow:
    image: agentflow-studio:1.1-${GIT_SHA:-local}
    build:
      context: .
      args:
        APP_VERSION: "1.1"
        GIT_COMMIT: ${GIT_SHA:-unknown}
    ports:
      - "127.0.0.1:8000:8000"
    env_file:
      - agentflow-backend/.env
    environment:
      DATABASE_PATH: /data/agentflow.db
      ARTIFACT_DIR: /data/artifacts
      RESOURCE_DATA_DIR: /data/resources
      RUNNER: graph
    volumes:
      - agentflow-data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s

volumes:
  agentflow-data:
```

如果要直接备份/查看数据库，把 `agentflow-data` 换成绑定目录 `./data:/data`；Linux 下注意目录属主与容器用户一致。

## 4. 方案 B：Nginx + 后端分离

只在需要 TLS、域名或静态缓存时增加：

- Nginx 托管 `dist`，`/api` 反向代理到 `agentflow:8000`。
- SSE 必须关闭缓冲：

```nginx
location /api/ {
    proxy_pass http://agentflow:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    add_header X-Accel-Buffering no;
}

location / {
    try_files $uri /index.html;
}
```

前端仍是同源 `/api`，不需要改 baseURL。若前端独立域名，则要配置 `CORS_ORIGINS` 并重新构建/部署。

## 5. 方案 C：Windows 源码包

适用于不能安装 Docker 的机器：

```text
agentflow-studio-1.1/
├── app/                 # 后端 app
├── resources/           # MCP/工具资源
├── web/dist/            # 前端构建产物
├── requirements.txt
├── requirements.lock.txt
├── .env.example
├── start.ps1
└── data/                # 首次启动创建，不随包覆盖
```

`start.ps1`：

```powershell
$env:DATABASE_PATH = Join-Path $PSScriptRoot "data\agentflow.db"
$env:ARTIFACT_DIR = Join-Path $PSScriptRoot "data\artifacts"
$env:RESOURCE_DATA_DIR = Join-Path $PSScriptRoot "data\resources"
Set-Location $PSScriptRoot
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

前提：目标机安装 Python 3.10.10，并提前执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

离线机器先在联网同平台机器执行 `pip download -r requirements.lock.txt -d wheelhouse`，再把 `wheelhouse` 一起放进包，安装时加 `--no-index --find-links wheelhouse`。

**不建议 PyInstaller 单文件**：MCP 需要启动子进程，LangGraph/uvicorn 有动态导入，单文件包很容易出现“开发能跑、打包后找不到模块”。如果确实要做免安装包，优先 `--onedir` 并单独验证 MCP、PDF 解析、SSE 三条链路。

## 6. 版本与指纹

单容器没有 `.git`，当前 `app/services/code_meta.py` 的 `git rev-parse` 会返回 `None`，导致版本快照里的 commit 丢失。落地镜像时必须补一条 fallback：

1. 构建时传入 `GIT_COMMIT` 和 `APP_VERSION`；
2. `code_meta.git_meta()` 在 git 命令失败时读取 `GIT_COMMIT` / `APP_VERSION`，`dirty` 默认 `false`；
3. `/api/health` 返回 `APP_VERSION`、`GIT_COMMIT`、`BUILD_TIME`；
4. 版本快照和 `run_manifest` 继续记录 commit，保证 R6 质量归因可定位。

这是打包前必须做的小改动，否则镜像里的版本指纹只剩配置指纹，没有代码 commit。

## 7. 数据、迁移与回滚

- `/data` 必须持久化：`agentflow.db`、`agentflow.db-wal`、`agentflow_checkpoints.db`、`artifacts/`、`resources/` 都在这里。
- SQLite 不要放 NFS/网络盘；单容器单进程写入。
- 升级前备份：用 `sqlite3.backup` 复制，不要直接 `cp`（WAL 模式下可能拿到不一致快照）。
- 启动自动迁移；本次清理已经做了物理删列，**回滚旧镜像不能只换 tag**，必须恢复升级前数据库或执行逆向补列。
- 回滚流程：
  1. 停止新容器；
  2. 恢复备份数据库到 `/data`；
  3. 启动上一个镜像 tag；
  4. 检查 `/api/health`、`/api/versions`、一条 Flow/Agent 运行。
- 建议后续把迁移改成显式版本表 + 升级/降级脚本，避免只靠 `_migrate()` 隐式执行。

## 8. CI/CD 流水线

```text
1. 后端：python -m pip install -r requirements-dev.txt
2. 后端：pytest
3. 前端：npm ci
4. 前端：npm run build
5. 构建镜像：docker build --build-arg GIT_COMMIT=<sha> ...
6. 启动临时容器 + 空数据卷
7. 冒烟：GET /api/health、GET /api/versions、创建 Agent、发布、运行一条 Flow
8. 推送镜像：<registry>/agentflow-studio:<version>-<sha>
9. 产出 SHA256SUMS + RELEASE.md
```

CI 机必须使用 Linux 构建镜像；`requirements.lock.txt` 当前是在 Windows/Python 3.10.10 生成，Linux 镜像构建时如果发现平台差异，应在 Linux builder 里重新生成 `requirements.lock.linux.txt` 并提交，而不是在运行阶段临时解析版本。

## 9. 验收清单

- [ ] `npm ci` 在干净目录成功，`package-lock.json` 不再出现 `^`/`~` 解析。
- [ ] `pytest` 全绿（当前 81 passed）。
- [ ] `npm run build` 成功，`dist/index.html` 被复制到 `/app/web/dist`。
- [ ] 空卷首次启动能建库、迁移、打开 `/`。
- [ ] `/api/health`、`/api/versions`、`/api/tools`、`/api/mcp-servers` 正常。
- [ ] 创建/发布 Agent、发布 Flow、运行、查看版本快照、回滚指针全部可用。
- [ ] 重启容器后数据仍在。
- [ ] 升级旧库副本成功，行数/完整性检查通过。
- [ ] 回滚到上一镜像 + 恢复数据库后能启动。
- [ ] 镜像内没有 `.env`、API Key、`.git`、`data/` 和测试缓存。
- [ ] `docker image inspect` 能看到 `APP_VERSION`、`GIT_COMMIT`、`BUILD_TIME`。

## 10. 待确认

1. 目标运行环境是否统一用 Docker/Linux？如果主要是 Windows 本机，是否要同时产出源码 zip？
2. 对外访问方式是 `127.0.0.1:8000` 本机，还是需要局域网/域名 + Nginx TLS？
3. SQLite 数据卷用 Docker named volume，还是绑定到宿主机 `./data` 方便备份？
4. 是否需要完全离线安装包（wheelhouse + `docker save` 镜像 tar）？
