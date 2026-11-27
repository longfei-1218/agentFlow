"""版本持久化：语义指纹、不可变快照、发布指针与回滚。

边界：
- 这里只负责「发布层」，不参与运行；运行期清单见 services/run_manifest.py；
- 不引入 diff：版本详情直接给完整快照，前端按字段分组展示；
- 回滚只把发布指针指回历史版本，并把该版本快照写回草稿，
  不回退、不重排任何资源版本号，也不产生新版本行。
"""
import hashlib
from typing import Any

import orjson

from app.database import db
from app.models.agent import Agent, AgentCreate
from app.models.flow import Flow
from app.models.version import PublishState, ResourceVersionState, VersionDetail
from app.services import knowledge_repo, mcp_repo, tool_repo
from app.services.code_meta import git_meta
from app.services.event_bus import utc_now

# 语义指纹排除的字段：改名、改描述、拖动画布都不应该产生「新版本」
_AGENT_KEEP = ("variables", "prompt", "resources", "model", "output")
_FLOW_META = ("draftHash", "publishedHash")


class VersionNotFound(LookupError):
    pass


class VersionAlreadyCurrent(ValueError):
    pass


class AgentVersionMissing(ValueError):
    def __init__(self, missing: list[dict[str, str]]) -> None:
        super().__init__("有 Agent 节点还没有发布版本")
        self.missing = missing


def canonical_hash(value: Any) -> str:
    data = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(data).hexdigest()[:12]


def agent_snapshot(agent: Agent | AgentCreate) -> dict[str, Any]:
    """AgentCreate 的 camelCase 载荷：直接可回填成发布快照。"""
    data = agent.model_dump(by_alias=True)
    for key in ("id", "createdAt", "updatedAt", "version", "draftHash", "publishedHash"):
        data.pop(key, None)
    return data


def flow_snapshot(flow: Flow, *, version: int | None = None) -> dict[str, Any]:
    data = flow.model_dump(by_alias=True)
    for key in _FLOW_META:
        data.pop(key, None)
    if version is not None:
        data["version"] = version
    return data


def agent_config_hash(agent: Agent | AgentCreate) -> str:
    payload = agent.model_dump(by_alias=True)
    return canonical_hash({key: payload.get(key) for key in _AGENT_KEEP})


def flow_config_hash(flow: Flow) -> str:
    return canonical_hash(
        {
            "dslVersion": flow.dsl_version,
            "nodes": [
                {"id": node.id, "type": node.type, "config": node.config}
                for node in flow.nodes
            ],
            "edges": [
                {
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "sourceHandle": edge.source_handle,
                }
                for edge in flow.edges
            ],
        }
    )


async def resource_entries(agents: list[AgentCreate]) -> dict[str, list[dict[str, Any]]]:
    """资源指纹只记身份与内容 hash，不落 definition_json（里面可能有 header / env 密钥）。"""
    tools: dict[str, dict[str, Any]] = {}
    servers: dict[str, dict[str, Any]] = {}
    kbs: dict[str, dict[str, Any]] = {}

    for agent in agents:
        for resource in agent.resources:
            if resource.kind == "tool" and resource.id not in tools:
                try:
                    tool = await tool_repo.get_tool(resource.id)
                except tool_repo.ToolNotFound:
                    tools[resource.id] = {"id": resource.id, "alias": resource.alias, "missing": True}
                    continue
                payload = tool.model_dump(by_alias=True)
                payload.pop("createdAt", None)
                payload.pop("updatedAt", None)
                tools[resource.id] = {
                    "id": tool.id,
                    "name": tool.name,
                    "alias": resource.alias,
                    "fingerprint": canonical_hash(payload),
                    "updatedAt": tool.updated_at,
                }
            elif resource.kind == "mcp" and resource.id not in servers:
                try:
                    server = await mcp_repo.get_server(resource.id)
                except mcp_repo.MCPServerNotFound:
                    servers[resource.id] = {"id": resource.id, "alias": resource.alias, "missing": True}
                    continue
                payload = server.model_dump(by_alias=True)
                payload.pop("createdAt", None)
                payload.pop("updatedAt", None)
                servers[resource.id] = {
                    "id": server.id,
                    "name": server.name,
                    "alias": resource.alias,
                    "tools": list(resource.tools),
                    "fingerprint": canonical_hash({**payload, "importedTools": resource.tools}),
                    "updatedAt": server.updated_at,
                }
            elif resource.kind == "knowledge" and resource.id not in kbs:
                try:
                    kb = await knowledge_repo.get_kb(resource.id)
                except knowledge_repo.KBNotFound:
                    kbs[resource.id] = {"id": resource.id, "alias": resource.alias, "missing": True}
                    continue
                kbs[resource.id] = {
                    "id": kb.id,
                    "name": kb.name,
                    "alias": resource.alias,
                    "fingerprint": canonical_hash(
                        {
                            "name": kb.name,
                            "chunkSize": kb.chunk_size,
                            "overlap": kb.overlap,
                            "embeddingModel": kb.embedding_model,
                            "docCount": kb.doc_count,
                            "chunkCount": kb.chunk_count,
                        }
                    ),
                    "docCount": kb.doc_count,
                    "chunkCount": kb.chunk_count,
                }

    return {
        "tools": sorted(tools.values(), key=lambda item: item["id"]),
        "mcp": sorted(servers.values(), key=lambda item: item["id"]),
        "knowledge": sorted(kbs.values(), key=lambda item: item["id"]),
    }


async def llm_meta(agent: Agent | AgentCreate | None) -> dict[str, Any]:
    try:
        from app.services.settings_repo import get_llm_config

        config = await get_llm_config()
        model = (agent.model.name if agent and agent.model.name else config.model) or ""
    except Exception:  # noqa: BLE001 - 模型配置读不到不该阻断发布
        model = agent.model.name if agent else ""
    return {
        "model": model,
        "temperature": agent.model.temperature if agent else None,
    }


async def build_manifest(
    kind: str,
    resource_id: str,
    version: int,
    config_hash: str,
    agents: list[AgentCreate],
    *,
    agent_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resources = await resource_entries(agents)
    code = git_meta()
    llm = await llm_meta(agents[0] if kind == "agent" and agents else None)
    bundle_hash = canonical_hash(
        {
            "configHash": config_hash,
            "resources": [
                {"id": item.get("id"), "fingerprint": item.get("fingerprint")}
                for group in resources.values()
                for item in group
            ],
            "code": code.get("commit"),
        }
    )
    return {
        "schemaVersion": 1,
        "kind": kind,
        "resourceId": resource_id,
        "version": version,
        "publishedAt": utc_now(),
        "configHash": config_hash,
        "bundleHash": bundle_hash,
        "code": code,
        "llm": llm,
        "agentRefs": agent_refs or [],
        "resources": resources,
    }


# ---------- 发布 ----------


async def _latest_version(kind: str, resource_id: str) -> dict[str, Any] | None:
    table, column = (
        ("agent_versions", "agent_id") if kind == "agent" else ("flow_versions", "flow_id")
    )
    row = await db.fetchone(
        f"SELECT * FROM {table} WHERE {column} = ? ORDER BY version DESC LIMIT 1",
        (resource_id,),
    )
    return None if row is None else dict(row)


async def publish_agent(agent: Agent, *, name: str, note: str = "") -> VersionDetail:
    """发布不检查内容是否有改动：允许对同一配置再发一版（版本名用于区分场景）。"""
    config_hash = agent_config_hash(agent)
    latest = await _latest_version("agent", agent.id)
    version = (int(latest["version"]) + 1) if latest else 1
    manifest = await build_manifest("agent", agent.id, version, config_hash, [agent])
    snapshot = agent_snapshot(agent)
    now = utc_now()
    version_id = f"av_{agent.id}_{version}"

    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO agent_versions (id, agent_id, version, config_hash, bundle_hash, "
            "snapshot_json, manifest_json, code_commit, code_dirty, name, note, restored_from, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                agent.id,
                version,
                config_hash,
                manifest["bundleHash"],
                orjson.dumps(snapshot).decode(),
                orjson.dumps(manifest).decode(),
                manifest["code"].get("commit"),
                int(bool(manifest["code"].get("dirty"))),
                name,
                note,
                None,
                now,
            ),
        )
        await conn.execute(
            "UPDATE agents SET published_version = ?, published_hash = ?, draft_hash = ?, updated_at = ? "
            "WHERE id = ?",
            (version, config_hash, config_hash, now, agent.id),
        )

    return await get_version("agent", agent.id, version)


async def publish_flow(
    flow: Flow,
    *,
    agent_refs: list[dict[str, Any]],
    pinned_agents: list[AgentCreate],
    name: str,
    note: str = "",
) -> VersionDetail:
    """发布不检查内容是否有改动，按 MAX(version)+1 追加。"""
    config_hash = flow_config_hash(flow)
    latest = await _latest_version("flow", flow.id)

    # 回滚过的资源：指针可能小于历史最大版本，发布必须接着 MAX+1 走，避免撞号；
    # 从未发布过的流程初始 version=1，第一次发布推进到 2（与 R1 的既有口径一致）
    base = max(int(latest["version"]), flow.version) if latest else flow.version
    version = base + 1
    manifest = await build_manifest(
        "flow", flow.id, version, config_hash, pinned_agents, agent_refs=agent_refs
    )
    snapshot = flow_snapshot(flow, version=version)
    now = utc_now()
    # dsl_json 里的时间戳要和发布行一致，否则乐观锁会拿旧 updatedAt 去比对
    snapshot["updatedAt"] = now

    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO flow_versions (id, flow_id, version, config_hash, bundle_hash, "
            "snapshot_json, manifest_json, code_commit, code_dirty, name, note, restored_from, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"fv_{flow.id}_{version}",
                flow.id,
                version,
                config_hash,
                manifest["bundleHash"],
                orjson.dumps(snapshot).decode(),
                orjson.dumps(manifest).decode(),
                manifest["code"].get("commit"),
                int(bool(manifest["code"].get("dirty"))),
                name,
                note,
                None,
                now,
            ),
        )
        await conn.execute(
            "UPDATE flows SET name = ?, version = ?, published_hash = ?, draft_hash = ?, "
            "dsl_json = ?, updated_at = ? WHERE id = ?",
            (
                snapshot["name"],
                version,
                config_hash,
                config_hash,
                orjson.dumps(snapshot).decode(),
                now,
                flow.id,
            ),
        )

    return await get_version("flow", flow.id, version)


# ---------- 读取 ----------


def _row_to_version(row, kind: str) -> VersionDetail:
    return VersionDetail(
        id=row["id"],
        kind=kind,
        resource_id=row["agent_id"] if kind == "agent" else row["flow_id"],
        version=int(row["version"]),
        config_hash=row["config_hash"],
        bundle_hash=row["bundle_hash"],
        code_commit=row["code_commit"],
        code_dirty=bool(row["code_dirty"]),
        name=row["name"] or "",
        note=row["note"] or "",
        restored_from=row["restored_from"],
        created_at=row["created_at"],
        manifest=orjson.loads(row["manifest_json"] or "{}"),
        snapshot=orjson.loads(row["snapshot_json"] or "{}"),
    )


async def list_versions(kind: str, resource_id: str) -> list[VersionDetail]:
    table, column = (
        ("agent_versions", "agent_id") if kind == "agent" else ("flow_versions", "flow_id")
    )
    rows = await db.fetchall(
        f"SELECT * FROM {table} WHERE {column} = ? ORDER BY version DESC",
        (resource_id,),
    )
    return [_row_to_version(row, kind) for row in rows]


async def get_version(kind: str, resource_id: str, version: int) -> VersionDetail:
    table, column = (
        ("agent_versions", "agent_id") if kind == "agent" else ("flow_versions", "flow_id")
    )
    row = await db.fetchone(
        f"SELECT * FROM {table} WHERE {column} = ? AND version = ?",
        (resource_id, version),
    )
    if row is None:
        raise VersionNotFound(f"版本不存在: {kind} {resource_id} v{version}")
    return _row_to_version(row, kind)


async def published_agent_snapshot(agent_id: str, version: int) -> AgentCreate | None:
    try:
        detail = await get_version("agent", agent_id, version)
    except VersionNotFound:
        return None
    return AgentCreate.model_validate(detail.snapshot)


async def publish_state(kind: str, resource_id: str) -> PublishState:
    table, column = (
        ("agent_versions", "agent_id") if kind == "agent" else ("flow_versions", "flow_id")
    )
    if kind == "agent":
        row = await db.fetchone(
            "SELECT published_version, published_hash, draft_hash FROM agents WHERE id = ?",
            (resource_id,),
        )
        if row is None:
            raise VersionNotFound(f"Agent 不存在: {resource_id}")
        published_version = int(row["published_version"] or 0)
    else:
        row = await db.fetchone(
            "SELECT version, published_hash, draft_hash FROM flows WHERE id = ?",
            (resource_id,),
        )
        if row is None:
            raise VersionNotFound(f"流程不存在: {resource_id}")
        published_version = int(row["version"] or 0)

    published_hash = row["published_hash"]
    draft_hash = row["draft_hash"]
    latest = await db.fetchone(
        f"SELECT COUNT(*) AS n, MAX(version) AS max_version, MAX(created_at) AS ts "
        f"FROM {table} WHERE {column} = ?",
        (resource_id,),
    )
    count = int(latest["n"] or 0) if latest else 0
    return PublishState(
        published_version=published_version,
        published_hash=published_hash,
        draft_hash=draft_hash,
        ahead=bool(draft_hash and published_hash and draft_hash != published_hash),
        unpublished=published_version <= 0 or not published_hash,
        version_count=count,
        latest_version=int(latest["max_version"] or 0) if latest else 0,
        last_published_at=(latest["ts"] if latest else None),
    )


async def list_resource_states() -> list[ResourceVersionState]:
    states: list[ResourceVersionState] = []
    agents = await db.fetchall(
        "SELECT id, name, published_version, published_hash, draft_hash, updated_at FROM agents "
        "ORDER BY updated_at DESC"
    )
    for row in agents:
        states.append(
            ResourceVersionState(
                kind="agent",
                id=row["id"],
                name=row["name"],
                publish=await publish_state("agent", row["id"]),
            )
        )

    flows = await db.fetchall(
        "SELECT id, name, version, published_hash, draft_hash, updated_at FROM flows "
        "ORDER BY updated_at DESC"
    )
    for row in flows:
        states.append(
            ResourceVersionState(
                kind="flow",
                id=row["id"],
                name=row["name"],
                publish=await publish_state("flow", row["id"]),
            )
        )
    return states


# ---------- 回滚 ----------


async def rollback(kind: str, resource_id: str, version: int) -> None:
    """把发布指针指回历史版本，并把该版本快照写回草稿。

    明确不做的事：
    - 不回退资源版本号（Flow 回滚不会改动任何 Agent 的版本）；
    - 不新增版本行，不修改历史版本的 manifest；
    - 后续发布按 MAX(version)+1 继续，不会因为指针回退而撞号。
    """
    detail = await get_version(kind, resource_id, version)
    state = await publish_state(kind, resource_id)
    if (
        state.published_version == version
        and state.draft_hash == detail.config_hash
        and state.published_hash == detail.config_hash
    ):
        raise VersionAlreadyCurrent("当前草稿与发布指针都已指向该版本")

    now = utc_now()
    if kind == "agent":
        snapshot = detail.snapshot
        if not snapshot.get("name"):
            raise VersionNotFound("版本快照损坏：缺少 Agent 定义")
        async with db.transaction() as conn:
            await conn.execute(
                "UPDATE agents SET name = ?, description = ?, definition_json = ?, draft_hash = ?, "
                "published_version = ?, published_hash = ?, updated_at = ? WHERE id = ?",
                (
                    snapshot.get("name", ""),
                    snapshot.get("description", ""),
                    orjson.dumps(snapshot).decode(),
                    detail.config_hash,
                    version,
                    detail.config_hash,
                    now,
                    resource_id,
                ),
            )
        return

    snapshot = {**detail.snapshot, "version": version, "updatedAt": now}
    async with db.transaction() as conn:
        await conn.execute(
            "UPDATE flows SET name = ?, version = ?, published_hash = ?, draft_hash = ?, "
            "dsl_json = ?, updated_at = ? WHERE id = ?",
            (
                snapshot.get("name", "未命名流程"),
                version,
                detail.config_hash,
                detail.config_hash,
                orjson.dumps(snapshot).decode(),
                now,
                resource_id,
            ),
        )


# ---------- 基线回填 ----------


async def backfill_baselines() -> int:
    """版本功能上线前的老数据：把当前内容登记成基线版本，避免「未发布不能引用」。

    只跑一次（settings 表留标记）；之后新建但未发布的资源不会在重启时被偷偷发布。
    """
    marker = await db.fetchone("SELECT key FROM settings WHERE key = ?", ("versions.baseline_v1",))
    if marker is not None:
        return 0

    created = 0
    agent_rows = await db.fetchall("SELECT * FROM agents")
    for row in agent_rows:
        if await _latest_version("agent", row["id"]):
            continue
        agent = Agent(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=int(row["published_version"] or 0),
            draft_hash=row["draft_hash"],
            published_hash=row["published_hash"],
            **orjson.loads(row["definition_json"]),
        )
        config_hash = agent_config_hash(agent)
        manifest = await build_manifest("agent", agent.id, 1, config_hash, [agent])
        now = utc_now()
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO agent_versions (id, agent_id, version, config_hash, bundle_hash, "
                "snapshot_json, manifest_json, code_commit, code_dirty, name, note, restored_from, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"av_{agent.id}_1",
                    agent.id,
                    1,
                    config_hash,
                    manifest["bundleHash"],
                    orjson.dumps(agent_snapshot(agent)).decode(),
                    orjson.dumps(manifest).decode(),
                    manifest["code"].get("commit"),
                    int(bool(manifest["code"].get("dirty"))),
                    "基线 v1",
                    "基线导入：版本功能上线前的当前配置",
                    None,
                    now,
                ),
            )
            await conn.execute(
                "UPDATE agents SET published_version = 1, published_hash = ?, draft_hash = ? WHERE id = ?",
                (config_hash, config_hash, agent.id),
            )
        created += 1

    flow_rows = await db.fetchall("SELECT * FROM flows")
    for row in flow_rows:
        if await _latest_version("flow", row["id"]):
            continue
        flow = Flow.model_validate(orjson.loads(row["dsl_json"]))
        if flow.dsl_version != 2:
            continue  # 旧 DSL 只读回放，不登记版本
        version = max(1, int(row["version"] or 1))
        config_hash = flow_config_hash(flow)
        # 基线无法还原「当时引用的 Agent 版本」，按当前发布指针登记，并在 note 里说明
        agent_refs: list[dict[str, Any]] = []
        pinned: list[AgentCreate] = []
        for node in flow.nodes:
            if node.type != "agent":
                continue
            agent_id = str(node.config.get("agentId") or node.config.get("agent_id") or "")
            agent_row = await db.fetchone("SELECT * FROM agents WHERE id = ?", (agent_id,))
            if agent_row is None:
                continue
            agent = Agent(
                id=agent_row["id"],
                created_at=agent_row["created_at"],
                updated_at=agent_row["updated_at"],
                version=int(agent_row["published_version"] or 0),
                draft_hash=agent_row["draft_hash"],
                published_hash=agent_row["published_hash"],
                **orjson.loads(agent_row["definition_json"]),
            )
            pinned.append(agent)
            agent_refs.append(
                {
                    "nodeId": node.id,
                    "agentId": agent.id,
                    "name": agent.name,
                    "version": agent.version,
                    "configHash": agent.published_hash,
                    "baseline": True,
                }
            )
        manifest = await build_manifest(
            "flow", flow.id, version, config_hash, pinned, agent_refs=agent_refs
        )
        snapshot = flow_snapshot(flow, version=version)
        now = utc_now()
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO flow_versions (id, flow_id, version, config_hash, bundle_hash, "
                "snapshot_json, manifest_json, code_commit, code_dirty, name, note, restored_from, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"fv_{flow.id}_{version}",
                    flow.id,
                    version,
                    config_hash,
                    manifest["bundleHash"],
                    orjson.dumps(snapshot).decode(),
                    orjson.dumps(manifest).decode(),
                    manifest["code"].get("commit"),
                    int(bool(manifest["code"].get("dirty"))),
                    f"基线 v{version}",
                    "基线导入：版本功能上线前的当前配置",
                    None,
                    now,
                ),
            )
            await conn.execute(
                "UPDATE flows SET published_hash = ?, draft_hash = ? WHERE id = ?",
                (config_hash, config_hash, flow.id),
            )
        created += 1

    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)",
        ("versions.baseline_v1", orjson.dumps({"created": created}).decode(), utc_now()),
    )
    return created
