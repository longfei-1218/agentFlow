"""R6.0 版本管理：发布快照、版本绑定、发布指针回滚、运行清单。"""
import pytest

from helpers import create_flow, edge, node
from app.services.version_repo import backfill_baselines


AGENT_BASE = {
    "name": "版本测试 Agent",
    "description": "",
    "variables": [{"key": "query", "label": "问题", "type": "string", "required": True}],
    "prompt": {"system": "你是测试助手。", "template": "回答：{{query}}"},
    "resources": [],
    "model": {"name": "fake", "temperature": 0, "maxTokens": 128},
    "output": {"description": "", "schema": None},
}


async def _create_agent(client, **overrides):
    payload = {**AGENT_BASE, **overrides}
    response = await client.post("/api/agents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _publish_agent(client, agent_id: str, name: str = "测试版本", note: str = ""):
    response = await client.post(
        f"/api/agents/{agent_id}/publish", json={"name": name, "note": note}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_agent_publish_creates_version_even_without_changes(client):
    agent = await _create_agent(client)
    assert agent["version"] == 0 and agent["publishedHash"] is None

    published = await _publish_agent(client, agent["id"], name="首个版本", note="首个版本说明")
    assert published["version"] == 1
    assert published["draftHash"] == published["publishedHash"]

    # 不检查是否有改动：同配置再发也生成新版本，版本名区分场景
    duplicate = await _publish_agent(client, agent["id"], name="同配置补发")
    assert duplicate["version"] == 2

    versions = await client.get(f"/api/agents/{agent['id']}/versions")
    assert versions.status_code == 200
    rows = versions.json()
    assert [row["version"] for row in rows] == [2, 1]
    assert rows[0]["name"] == "同配置补发"
    assert rows[0]["note"] == ""
    assert rows[1]["name"] == "首个版本"
    assert rows[1]["note"] == "首个版本说明"
    assert rows[0]["configHash"] == rows[1]["configHash"]
    assert rows[0]["manifest"]["configHash"] == rows[0]["configHash"]
    assert "code" in rows[0]["manifest"]


@pytest.mark.asyncio
async def test_publish_requires_version_name(client):
    agent = await _create_agent(client)
    response = await client.post(f"/api/agents/{agent['id']}/publish", json={"note": "只有说明"})
    assert response.status_code == 422
    assert response.json()["code"] == "VERSION_NAME_REQUIRED"

    flow = await create_flow(
        client,
        [node("start_1", "start", variables=[]), node("end_1", "end", outputs=[])],
        [edge("e1", "start_1", "end_1")],
    )
    response = await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "   "})
    assert response.status_code == 422
    assert response.json()["code"] == "VERSION_NAME_REQUIRED"


@pytest.mark.asyncio
async def test_agent_draft_ahead_and_version_snapshot(client):
    agent = await _create_agent(client)
    await _publish_agent(client, agent["id"])
    v1 = (await client.get(f"/api/agents/{agent['id']}/versions/1")).json()

    changed = {**AGENT_BASE, "prompt": {"system": "你是测试助手。", "template": "新模板：{{query}}"}}
    updated = await client.put(f"/api/agents/{agent['id']}", json=changed)
    assert updated.status_code == 200
    assert updated.json()["version"] == 1

    state = (await client.get(f"/api/agents/{agent['id']}/publish-state")).json()
    assert state["ahead"] is True

    v2 = await _publish_agent(client, agent["id"])
    assert v2["version"] == 2

    # 历史版本快照不被草稿覆盖
    again = (await client.get(f"/api/agents/{agent['id']}/versions/1")).json()
    assert again["snapshot"]["prompt"]["template"] == v1["snapshot"]["prompt"]["template"]
    assert again["configHash"] != v2["publishedHash"]


@pytest.mark.asyncio
async def test_flow_publish_binds_agent_version(client):
    agent = await _create_agent(client)
    missing = await client.post(f"/api/flows/fv_missing/publish", json={"name": "不存在"})
    assert missing.status_code == 404

    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("a1", "agent", agentId=agent["id"], inputMap={"query": "{{start.query}}"}),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
    )

    # Agent 未发布：流程发布被拦截，并定位到节点
    blocked = await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "首次"})
    assert blocked.status_code == 422
    body = blocked.json()
    assert body["code"] == "AGENT_VERSION_MISSING"
    assert body["detail"][0]["nodeId"] == "a1"

    published_agent = await _publish_agent(client, agent["id"])
    assert published_agent["version"] == 1

    published_flow = await client.post(
        f"/api/flows/{flow['id']}/publish", json={"name": "首发", "note": "首发"}
    )
    assert published_flow.status_code == 200, published_flow.text
    assert published_flow.json()["version"] == 2

    versions = (await client.get(f"/api/flows/{flow['id']}/versions")).json()
    assert len(versions) == 1
    refs = versions[0]["manifest"]["agentRefs"]
    assert len(refs) == 1
    assert refs[0]["nodeId"] == "a1"
    assert refs[0]["agentId"] == agent["id"]
    assert refs[0]["version"] == 1
    assert refs[0]["configHash"] == published_agent["publishedHash"]


@pytest.mark.asyncio
async def test_flow_publish_validates_against_bound_agent_snapshot(client):
    """草稿 Agent 加了必填变量、流程也映射了，但该变量还没发布：
    发布必须按已绑定的 v1 校验，拦住「发布出去跑不动」的流程。"""
    agent = await _create_agent(client)
    await _publish_agent(client, agent["id"])

    draft = {
        **AGENT_BASE,
        "variables": [
            {"key": "query", "type": "string", "required": True},
            {"key": "intent", "type": "string", "required": True},
        ],
        "prompt": {"system": "你是测试助手。", "template": "{{intent}} / {{query}}"},
    }
    updated = await client.put(f"/api/agents/{agent['id']}", json=draft)
    assert updated.status_code == 200

    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node(
                "a1",
                "agent",
                agentId=agent["id"],
                inputMap={"query": "{{start.query}}", "intent": "{{start.query}}"},
            ),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
    )

    response = await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "发布草稿"})
    assert response.status_code == 422
    messages = " ".join(item["message"] for item in response.json()["detail"])
    assert "intent" in messages

    # 发布 Agent 新版本后即可发布流程，并绑定 v2
    await _publish_agent(client, agent["id"])
    response = await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "绑定 v2"})
    assert response.status_code == 200
    manifest = (await client.get(f"/api/flows/{flow['id']}/versions")).json()[0]["manifest"]
    assert manifest["agentRefs"][0]["version"] == 2


@pytest.mark.asyncio
async def test_rollback_moves_pointer_without_touching_versions(client):
    agent = await _create_agent(client)
    await _publish_agent(client, agent["id"])

    changed = {**AGENT_BASE, "prompt": {"system": "你是测试助手。", "template": "v2 模板：{{query}}"}}
    await client.put(f"/api/agents/{agent['id']}", json=changed)
    v2 = await _publish_agent(client, agent["id"])
    assert v2["version"] == 2

    rolled = await client.post(f"/api/agents/{agent['id']}/rollback", json={"version": 1})
    assert rolled.status_code == 200, rolled.text
    body = rolled.json()
    assert body["version"] == 1
    assert body["prompt"]["template"] == "回答：{{query}}"
    assert body["draftHash"] == body["publishedHash"]

    # 历史版本一个都没少，v2 仍然可查
    rows = (await client.get(f"/api/agents/{agent['id']}/versions")).json()
    assert [item["version"] for item in rows] == [2, 1]

    # 再发布按 MAX+1 继续，不会撞号
    v3 = await _publish_agent(client, agent["id"])
    assert v3["version"] == 3


@pytest.mark.asyncio
async def test_flow_rollback_keeps_agent_versions(client, monkeypatch):
    from app.engine import agent_runner
    from app.services.llm import LLMDelta

    async def fake_stream(config, messages, **kwargs):
        yield LLMDelta(text="ok", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", fake_stream)

    agent = await _create_agent(client)
    await _publish_agent(client, agent["id"])

    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("a1", "agent", agentId=agent["id"], inputMap={"query": "{{start.query}}"}),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
        name="回滚流程",
    )
    await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "回滚流程 v1"})

    changed = {
        **flow,
        "name": "回滚流程 v2",
        "nodes": [
            {**item, "config": {**item["config"], "outputs": []}} if item["id"] == "end_1" else item
            for item in flow["nodes"]
        ],
        "edges": flow["edges"],
    }
    await client.put(f"/api/flows/{flow['id']}", json=changed)
    published = await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "v2 改输出"})
    assert published.json()["version"] == 3

    rolled = await client.post(f"/api/flows/{flow['id']}/rollback", json={"version": 2})
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["version"] == 2
    assert rolled.json()["name"] == "回滚流程"

    # 回滚流程不动 Agent 版本：指针仍是 v1，历史只有 1 条
    agent_after = (await client.get(f"/api/agents/{agent['id']}")).json()
    assert agent_after["version"] == 1
    assert len((await client.get(f"/api/agents/{agent['id']}/versions")).json()) == 1

    # 流程历史仍有 3 和 2
    flow_versions = (await client.get(f"/api/flows/{flow['id']}/versions")).json()
    assert [item["version"] for item in flow_versions] == [3, 2]


@pytest.mark.asyncio
async def test_run_manifest_records_current_and_published(client, monkeypatch):
    from app.engine import agent_runner
    from app.services.llm import LLMDelta

    async def fake_stream(config, messages, **kwargs):
        yield LLMDelta(text="好的", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", fake_stream)

    agent = await _create_agent(client)
    await _publish_agent(client, agent["id"])
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("a1", "agent", agentId=agent["id"], inputMap={"query": "{{start.query}}"}),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
    )
    await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "草稿运行"})

    # 发布后改 Agent 草稿：运行用当前保存版本，清单必须标 draft
    changed = {**AGENT_BASE, "prompt": {"system": "你是测试助手。", "template": "草稿：{{query}}"}}
    await client.put(f"/api/agents/{agent['id']}", json=changed)

    run = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "hi"}})
    ).json()
    assert run["targetVersion"] == 2
    assert run["versionMode"] == "draft"
    ref = run["manifest"]["agentRefs"][0]
    assert ref["publishedVersion"] == 1
    assert ref["mode"] == "draft"
    assert ref["currentHash"] != ref["publishedHash"]


@pytest.mark.asyncio
async def test_backfill_baseline_is_idempotent(client):
    agent = await _create_agent(client)
    assert agent["version"] == 0

    created = await backfill_baselines()
    assert created >= 1

    reloaded = (await client.get(f"/api/agents/{agent['id']}")).json()
    assert reloaded["version"] == 1
    assert len((await client.get(f"/api/agents/{agent['id']}/versions")).json()) == 1

    # 第二次启动不再重复登记
    assert await backfill_baselines() == 0


@pytest.mark.asyncio
async def test_backfill_flow_baseline(client):
    """存量 v2 流程也要有基线版本：否则版本页是空的，也没法按版本回溯。"""
    flow = await create_flow(
        client,
        [node("start_1", "start", variables=[]), node("end_1", "end", outputs=[])],
        [edge("e1", "start_1", "end_1")],
        name="存量流程",
    )
    created = await backfill_baselines()
    assert created >= 1

    reloaded = (await client.get(f"/api/flows/{flow['id']}")).json()
    assert reloaded["version"] == 1
    assert reloaded["publishedHash"]

    rows = (await client.get(f"/api/flows/{flow['id']}/versions")).json()
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert "基线导入" in rows[0]["note"]


@pytest.mark.asyncio
async def test_unified_version_list(client):
    agent = await _create_agent(client)
    await _publish_agent(client, agent["id"])
    flow = await create_flow(
        client,
        [node("start_1", "start", variables=[]), node("end_1", "end", outputs=[])],
        [edge("e1", "start_1", "end_1")],
        name="无 Agent 流程",
    )
    await client.post(f"/api/flows/{flow['id']}/publish", json={"name": "统一列表流程"})

    rows = (await client.get("/api/versions")).json()
    kinds = {(row["kind"], row["id"]) for row in rows}
    assert ("agent", agent["id"]) in kinds
    assert ("flow", flow["id"]) in kinds
    state = next(row for row in rows if row["kind"] == "flow")
    assert state["publish"]["publishedVersion"] == 2
    assert state["publish"]["ahead"] is False

    detail = (await client.get(f"/api/versions/flow/{flow['id']}/2")).json()
    assert detail["snapshot"]["dslVersion"] == 2
    assert len(detail["snapshot"]["nodes"]) == 2
