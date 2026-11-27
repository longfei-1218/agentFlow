# Agent / Flow 版本管理（R6.0 实现说明）

> 状态：2026-11-27 已落地。后端 `app/services/version_repo.py` + `run_manifest.py`，前端 `/versions`。
>
> 目标：R6 质量评价开始前，让每个发布版本都能定位「配置指纹 / 工具指纹 / 代码 commit / 绑定的 Agent 版本」，并支持按版本回滚。

---

## 1. 三条最终口径

1. **运行使用当前保存的版本**。发布不改变运行时读取路径；运行只额外记录一份版本清单，用来回答「这次跑的是哪一版配置」。
2. **Flow 发布绑定 Agent 版本**。发布时把每个 `agent` 节点指向的 Agent 发布指针（`agentId + version + configHash`）写进 Flow 版本 manifest；运行清单也记录同一组绑定，便于归因。
3. **回滚只回退发布指针**。把 `published_version` / `flows.version` 指回目标版本，并把该版本快照写回草稿；不新增版本、不删除历史、不改任何 Agent 的版本号。之后的发布按 `MAX(version)+1` 继续，不会撞号。

**本期不做**：版本 diff。版本详情直接提供完整配置快照，前端按提示词 / 变量 / 资源 / 节点分组展示。

---

## 2. 数据模型

```sql
-- Agent 草稿层新增发布指针与指纹缓存
ALTER TABLE agents ADD COLUMN published_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agents ADD COLUMN draft_hash TEXT;
ALTER TABLE agents ADD COLUMN published_hash TEXT;

-- Flow 草稿层：version 就是发布指针
ALTER TABLE flows ADD COLUMN draft_hash TEXT;
ALTER TABLE flows ADD COLUMN published_hash TEXT;

-- 运行期版本清单
ALTER TABLE runs ADD COLUMN target_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN version_mode TEXT NOT NULL DEFAULT 'published';  -- published | draft
ALTER TABLE runs ADD COLUMN manifest_json TEXT;
```

版本表（只追加）：

```sql
CREATE TABLE agent_versions (
  id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, version INTEGER NOT NULL,
  config_hash TEXT NOT NULL, bundle_hash TEXT NOT NULL,
  snapshot_json TEXT NOT NULL, manifest_json TEXT NOT NULL,
  code_commit TEXT, code_dirty INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  restored_from INTEGER, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_agent_versions ON agent_versions(agent_id, version);
-- flow_versions 同构，列名 flow_id
```

`version_count` 与 `latest_version` 分开：指针可能因回滚小于历史最大版本，页面据此显示「已回滚 · 最高 vN」。

### 版本号规则

- Agent 从 0 开始，第一次发布 = v1；
- Flow 草稿初始 `version=1`，第一次发布 = v2（与 R1 既有口径一致）；
- 回滚后指针变小，下一次发布取 `MAX(历史最大, 指针) + 1`；
- **发布不检查内容是否有改动**：同一配置也能再发一版（用于「同配置换评测场景 / 补记录」），版本号照常 +1；
- **版本名必填、说明可留空**：版本名写进版本行 `name`，空串或纯空白返回 `422 VERSION_NAME_REQUIRED`；老版本行 `name` 为空，页面回退显示 `vN`。

---

## 3. 指纹

- 规范化：`orjson.dumps(OPT_SORT_KEYS)` → `sha256` 前 12 位。
- **Agent 语义配置**：`variables / prompt / resources / model / output`；排除 `name / description / 时间戳`。
- **Flow 语义配置**：`dslVersion / nodes[{id,type,config}] / edges`；排除 `position`（拖画布不算改动）与缓存的 hash 字段。
- **bundleHash**：`configHash + 资源指纹列表 + code.commit`，用于表格里一行式标识。
- **工具 / MCP / 知识库**：发布时按内容算指纹，只落 `id + name/alias + fingerprint + updatedAt`，不落 `definition_json`（里面可能有 header / env 密钥）。知识库指纹含 `chunkSize / overlap / embeddingModel / docCount / chunkCount`。
- **代码**：`git rev-parse --short HEAD`、`--abbrev-ref HEAD`、`status --porcelain`（缓存 10s）。工作区脏允许发布，但 `dirty=true` 会写进版本与页面，评测报告应提示「不可复现」。

---

## 4. 发布

`POST /api/agents/{id}/publish`

1. 校验 Agent 定义（不联网探测 MCP）；
2. 校验 `name` 非空，空则 422 `VERSION_NAME_REQUIRED`；
3. 生成快照 + manifest，写 `agent_versions`，同步更新草稿层的 `published_version / published_hash / draft_hash`。

`POST /api/flows/{id}/publish`

1. 校验 `name` 非空，空则 422 `VERSION_NAME_REQUIRED`；
2. 先按当前草稿校验结构（`validate_flow_runtime`）；
3. 解析每个 Agent 节点的发布指针与快照，缺失则 422 `AGENT_VERSION_MISSING`，detail 带 `nodeId / agentId / reason`；
4. **用绑定的 Agent 发布快照再校验一次 inputMap**：草稿 Agent 加了必填变量但没发布时，发布会被拦住，避免发出去一个跑不动的流程；
5. 生成 Flow 快照 + manifest（含 `agentRefs`、资源指纹、commit），写 `flow_versions`；
6. 更新 `flows.version = 新版本`、`published_hash`、`draft_hash`、`dsl_json` 中的 version 字段。

manifest 结构：

```json
{
  "schemaVersion": 1,
  "kind": "flow",
  "resourceId": "flow_x",
  "version": 3,
  "publishedAt": "2026-11-27T14:00:00+00:00",
  "configHash": "9f2c1a7b3d54",
  "bundleHash": "a71d0c9e2b88",
  "code": { "commit": "408581b", "branch": "main", "dirty": false },
  "llm": { "model": "deepseek-chat", "temperature": 0.2 },
  "agentRefs": [ { "nodeId": "a1", "agentId": "agent_x", "name": "分类", "version": 3, "configHash": "..." } ],
  "resources": {
    "tools": [ { "id": "tool_x", "name": "检索", "alias": "kb", "fingerprint": "...", "updatedAt": "..." } ],
    "mcp": [ { "id": "mcp_x", "name": "filesystem", "tools": ["read_file"], "fingerprint": "..." } ],
    "knowledge": [ { "id": "kb_x", "name": "售后", "docCount": 3, "chunkCount": 41, "fingerprint": "..." } ]
  }
}
```

---

## 5. 运行时与清单

- Flow / Agent 运行仍读当前草稿，行为与 R5 一致；
- 创建 run 时计算 `run_manifest`：
  - Flow：自身 `configHash` vs `publishedHash`，任一 Agent 节点当前指纹与发布指纹不一致，则整条 run `versionMode=draft`；
  - 每个 Agent 节点记录 `publishedVersion / publishedHash / currentHash / mode`；
  - Agent 运行记录自身版本与资源指纹；
- `runs` 写 `target_version / version_mode / manifest_json`，`run_started` 事件带 `flowVersion` / `agentVersion` / `versionMode`；
- 回放页与运行历史展示 `Flow vN / Agent vN`，草稿运行有「草稿」标签；R6 统计默认只取 `version_mode=published`。

---

## 6. 回滚

`POST /api/agents/{id}/rollback`、`POST /api/flows/{id}/rollback`，body `{version}`。

- 校验目标版本存在；指针与草稿都已指向该版本时返回 409 `VERSION_ALREADY_CURRENT`；
- 把快照写回草稿行，`draft_hash = published_hash = 目标 configHash`，`published_version = 目标版本`；
- Flow 的 `version` 列同步回目标版本，`dsl_json.version` 也改成目标版本；
- Flow 回滚**不动**任何 Agent 行与 `agent_versions`；
- 历史版本全部保留，后续发布 `MAX+1`，例如 v1/v2/v3 回滚到 v2 后再发布得到 v4。

为什么同时改草稿：运行使用草稿，只改指针不会影响后续运行；回滚必须让「当前保存内容」也回到目标版本。

---

## 7. API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agents/{id}/publish` | body `{name, note?}`，`name` 必填；返回更新后的 Agent |
| GET | `/api/agents/{id}/versions` | 版本列表（含 manifest，不含 snapshot） |
| GET | `/api/agents/{id}/versions/{version}` | 版本详情（含完整 snapshot） |
| GET | `/api/agents/{id}/publish-state` | 指针 / 草稿指纹 / 是否领先 / 版本数 / 最大版本 |
| POST | `/api/agents/{id}/rollback` | body `{version}` |
| POST | `/api/flows/{id}/publish` | 快照 + Agent 绑定 |
| GET / POST | `/api/flows/{id}/versions`、`/rollback`、`/publish-state` | 同上 |
| GET | `/api/versions` | 版本管理页资源列表 |
| GET | `/api/versions/{kind}/{id}/{version}` | 按类型取版本详情 |

错误码：

| code | HTTP | 场景 |
|---|---|---|
| `VERSION_NAME_REQUIRED` | 422 | 发布时版本名为空 |
| `AGENT_VERSION_MISSING` | 422 | Flow 发布时某节点 Agent 未发布 |
| `VERSION_NOT_FOUND` | 404 | 版本 / 资源不存在 |
| `VERSION_ALREADY_CURRENT` | 409 | 指针与草稿都已在目标版本 |
| `VERSION_KIND_INVALID` | 400 | 统一详情接口 kind 非法 |

---

## 8. 前端

- `/versions`：`Agent 版本 / 流程 版本` 两个 tab；左侧资源列表（指针、草稿领先、已回滚）；右侧版本时间线 + manifest 卡 + 结构化快照 + 恢复确认。
- `/agents/:id`：`vN / 未发布` chip 跳版本页；「有未发布改动」徽标；「发布版本」弹窗填发布说明。
- `/flows/:id`：`vN` chip 跳版本页；发布弹窗；`AGENT_VERSION_MISSING` 的 detail 会按节点列在错误条。
- `/runs`、`/runs/:id`：版本号、草稿标签、manifest 折叠块。

---

## 9. 迁移

- `init.sql` 新建库直接带版本表；老库由 `database._migrate` 补列。
- 启动后 `backfill_baselines()` 一次性登记基线：
  - 存量 Agent → v1（`note=基线导入`）；
  - 存量 `dslVersion=2` Flow → 版本号保持当前 `version`，写 published/draft 指纹；
  - 旧 DSL 不登记；
  - `settings` 写 `versions.baseline_v1` 标记，重启不重复；之后新建未发布资源不会被偷偷发布。
- 老 flow run 的 `target_version` 由 `flow_version` 回填。

真实库副本迁移结果（2026-11-27）：agents 3 / agent_versions 3；flows 2 / flow_versions 2；无未发布 Agent；无缺 published_hash 的 v2 Flow；无 `target_version=0` 的 flow run。

---

## 10. 已知限制

- 无版本 diff；对比靠并排看两份快照。
- 运行清单是「当前草稿 + 发布指针」的组合，不是运行瞬间的完整 DSL 快照；若运行期间有人改草稿，清单反映的是 run 创建时的指纹，事件里的节点配置仍以当时读到的对象为准。
- 发布时工作区脏不阻断，但版本页与 manifest 会标 `dirty`。
- 删除 Agent / Flow 不删版本历史；恢复接口只对仍存在的资源开放。
- 多用户可见性、发布审批暂未实现（当前单用户本地原型）。
