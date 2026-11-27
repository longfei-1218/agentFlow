"""Flow v2 CRUD / 版本语义 / 校验规则。"""
import orjson

from app.database import db
from app.models.flow import Flow
from helpers import create_flow, edge, node


async def _insert_legacy_flow() -> str:
    flow = Flow(
        id="flow_legacy",
        name="旧流程",
        dsl_version=1,
        nodes=[],
        edges=[],
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    await db.execute(
        "INSERT INTO flows (id, name, version, dsl_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            flow.id,
            flow.name,
            flow.version,
            orjson.dumps(flow.model_dump()).decode(),
            flow.created_at,
            flow.updated_at,
        ),
    )
    return flow.id


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_create_generates_default_flow_when_structure_omitted(client):
    response = await client.post("/api/flows", json={"name": "演示"})
    assert response.status_code == 201
    flow = response.json()
    assert [n["type"] for n in flow["nodes"]] == ["start", "end"]
    assert flow["dslVersion"] == 2
    assert flow["version"] == 1


async def test_explicit_empty_nodes_is_respected(client):
    flow = await create_flow(client, [], [], name="空白画布")
    assert flow["nodes"] == []
    assert flow["edges"] == []


async def test_put_keeps_version_and_publish_bumps_it(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [edge("e_1", "start_1", "end_1")],
    )

    for _ in range(3):
        response = await client.put(
            f"/api/flows/{flow['id']}", json={"name": "改名", "nodes": flow["nodes"], "edges": flow["edges"]}
        )
        assert response.status_code == 200
        assert response.json()["version"] == 1, "自动保存（PUT）不应递增 version"

    published = await client.post(f"/api/flows/{flow['id']}/publish")
    assert published.status_code == 200
    assert published.json()["version"] == 2


async def test_put_with_stale_base_updated_at_is_rejected(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [edge("e_1", "start_1", "end_1")],
        name="并发保存",
    )
    base = flow["updatedAt"]
    assert base

    first = await client.put(
        f"/api/flows/{flow['id']}",
        json={"name": "标签页A", "nodes": flow["nodes"], "edges": flow["edges"], "baseUpdatedAt": base},
    )
    assert first.status_code == 200

    stale = await client.put(
        f"/api/flows/{flow['id']}",
        json={"name": "标签页B", "nodes": flow["nodes"], "edges": flow["edges"], "baseUpdatedAt": base},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "FLOW_STALE"

    current = (await client.get(f"/api/flows/{flow['id']}")).json()
    assert current["name"] == "标签页A", "过期写入不能覆盖服务端内容"

    legacy = await client.put(
        f"/api/flows/{flow['id']}", json={"name": "脚本", "nodes": flow["nodes"], "edges": flow["edges"]}
    )
    assert legacy.status_code == 200


async def test_publish_rejects_invalid_flow(client):
    flow = await create_flow(client, [], [], name="空白")
    response = await client.post(f"/api/flows/{flow['id']}/publish")
    assert response.status_code == 422
    assert response.json()["code"] == "FLOW_INVALID"


async def test_validate_detects_cycle(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("cond_1", "condition", expression="{{start.query}} == 'x'"),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [
            edge("e_1", "start_1", "cond_1"),
            edge("e_2", "cond_1", "start_1", "true"),
            edge("e_3", "cond_1", "end_1", "false"),
        ],
    )
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()
    assert result["valid"] is False
    assert any("环" in issue["message"] for issue in result["errors"])


async def test_validate_requires_entry_exit_and_condition_branches(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("cond_1", "condition", expression="{{start.query}} == 'x'"),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [edge("e_1", "start_1", "cond_1"), edge("e_2", "cond_1", "end_1", "true")],
    )
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()
    assert result["valid"] is False
    messages = " ".join(issue["message"] for issue in result["errors"])
    assert "true/false" in messages


async def test_run_is_blocked_by_validation(client):
    flow = await create_flow(client, [], [], name="空白")
    response = await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})
    assert response.status_code == 422
    assert response.json()["code"] == "FLOW_INVALID"


async def test_legacy_flow_uses_dedicated_error_code(client):
    flow_id = await _insert_legacy_flow()
    for method, path in (
        ("post", f"/api/flows/{flow_id}/validate"),
        ("post", f"/api/flows/{flow_id}/publish"),
        ("post", f"/api/flows/{flow_id}/run"),
        ("put", f"/api/flows/{flow_id}"),
    ):
        response = await client.request(
            method, path, json={"name": "改", "nodes": [], "edges": []}
        )
        assert response.status_code == 422, (path, response.text)
        assert response.json()["code"] == "FLOW_DSL_LEGACY", path
        assert "旧 DSL" in response.json()["message"]
