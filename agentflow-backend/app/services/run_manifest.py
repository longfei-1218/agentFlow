"""运行期版本清单：记录这次运行实际用的配置指纹与 Agent 发布版本。

口径（按 R6.0 确认）：
- 运行时用「当前保存的版本」（草稿），不强制走发布快照；
- 清单同时记录发布指针与该次运行的当前指纹：两者一致标 published，
  不一致标 draft —— 评测默认只认 published。
"""
from typing import Any

from app.models.agent import Agent, AgentCreate
from app.models.flow import Flow
from app.services import agent_repo, version_repo
from app.services.code_meta import git_meta


def _mode(current: str | None, published: str | None) -> str:
    return "published" if current and published and current == published else "draft"


async def resolve_flow_pins(
    flow: Flow,
) -> tuple[list[dict[str, Any]], dict[str, AgentCreate], list[dict[str, str]]]:
    """解析每个 Agent 节点应当绑定的发布版本（发布与运行共用）。

    绑定的是 Agent 的「发布指针」，不是最大版本号：回滚过 Agent 后，
    流程再发布也应该钉住指针指向的那一版，而不是已经被回滚掉的最高版。
    """
    pins: list[dict[str, Any]] = []
    pinned: dict[str, AgentCreate] = {}
    missing: list[dict[str, str]] = []

    for node in flow.nodes:
        if node.type != "agent":
            continue
        agent_id = str(node.config.get("agentId") or node.config.get("agent_id") or "")
        try:
            agent = await agent_repo.get_agent(agent_id)
        except agent_repo.AgentNotFound:
            missing.append({"nodeId": node.id, "agentId": agent_id, "reason": "Agent 不存在"})
            continue
        if agent.version <= 0 or not agent.published_hash:
            missing.append({"nodeId": node.id, "agentId": agent_id, "reason": "Agent 还没有发布版本"})
            continue
        snapshot = await version_repo.published_agent_snapshot(agent_id, agent.version)
        if snapshot is None:
            missing.append(
                {
                    "nodeId": node.id,
                    "agentId": agent_id,
                    "reason": f"发布版本 v{agent.version} 的快照缺失",
                }
            )
            continue
        pinned[node.id] = snapshot
        pins.append(
            {
                "nodeId": node.id,
                "agentId": agent.id,
                "name": agent.name,
                "version": agent.version,
                "configHash": agent.published_hash,
            }
        )

    return pins, pinned, missing


async def build_flow_run_manifest(flow: Flow) -> dict[str, Any]:
    config_hash = version_repo.flow_config_hash(flow)
    published_hash = flow.published_hash
    agent_refs: list[dict[str, Any]] = []
    agents: list[AgentCreate] = []

    for node in flow.nodes:
        if node.type != "agent":
            continue
        agent_id = str(node.config.get("agentId") or node.config.get("agent_id") or "")
        try:
            agent = await agent_repo.get_agent(agent_id)
        except agent_repo.AgentNotFound:
            agent_refs.append(
                {"nodeId": node.id, "agentId": agent_id, "missing": True, "mode": "missing"}
            )
            continue
        current_hash = version_repo.agent_config_hash(agent)
        agents.append(agent)
        agent_refs.append(
            {
                "nodeId": node.id,
                "agentId": agent.id,
                "name": agent.name,
                "publishedVersion": agent.version,
                "publishedHash": agent.published_hash,
                "currentHash": current_hash,
                "mode": _mode(current_hash, agent.published_hash),
            }
        )

    resources = await version_repo.resource_entries(agents)
    flow_mode = _mode(config_hash, published_hash)
    # 流程自身没变、但某个节点 Agent 用了未发布草稿，也算 draft 运行
    if flow_mode == "published" and any(
        ref.get("mode") not in ("published",) for ref in agent_refs
    ):
        flow_mode = "draft"
    return {
        "schemaVersion": 1,
        "kind": "flow",
        "resourceId": flow.id,
        "targetVersion": flow.version,
        "versionMode": flow_mode,
        "configHash": config_hash,
        "publishedHash": published_hash,
        "code": git_meta(),
        "agentRefs": agent_refs,
        "resources": resources,
    }


async def build_agent_run_manifest(agent: Agent) -> dict[str, Any]:
    config_hash = version_repo.agent_config_hash(agent)
    resources = await version_repo.resource_entries([agent])
    llm = await version_repo.llm_meta(agent)

    return {
        "schemaVersion": 1,
        "kind": "agent",
        "resourceId": agent.id,
        "targetVersion": agent.version,
        "versionMode": _mode(config_hash, agent.published_hash),
        "configHash": config_hash,
        "publishedHash": agent.published_hash,
        "code": git_meta(),
        "llm": llm,
        "resources": resources,
    }
