"""R5：MCP Server 探测与工具调用（stdio 真进程，不 mock 协议）。"""
import pathlib
import sys

import pytest

from helpers import create_flow, edge, node, wait_for_status

MCP_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "mcp_demo_server.py"


async def _create_server(client, name="演示 MCP") -> dict:
    response = await client.post(
        "/api/mcp-servers",
        json={
            "name": name,
            "command": sys.executable,
            "args": [str(MCP_SCRIPT)],
            "timeoutS": 20,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_probe_lists_tools_and_call_returns_text(client):
    server = await _create_server(client)

    probe = await client.get(f"/api/mcp-servers/{server['id']}/tools")
    assert probe.status_code == 200
    payload = probe.json()
    assert payload["ok"] is True, payload
    names = {tool["name"] for tool in payload["tools"]}
    assert {"echo", "add", "now"} <= names
    assert payload["latencyMs"] >= 0

    call = await client.post(
        f"/api/mcp-servers/{server['id']}/call",
        json={"toolName": "add", "args": {"a": 2, "b": 3}},
    )
    body = call.json()
    assert body["ok"] is True, body
    assert body["result"] == "5"


async def test_probe_reports_spawn_failure_instead_of_500(client):
    response = await client.post(
        "/api/mcp-servers",
        json={"name": "不存在的命令", "command": "agentflow-definitely-missing-cmd", "args": []},
    )
    server = response.json()

    probe = await client.get(f"/api/mcp-servers/{server['id']}/tools")
    body = probe.json()
    assert probe.status_code == 200
    assert body["ok"] is False
    assert body["code"] == "MCP_SPAWN_FAILED"
    assert "找不到命令" in body["error"]


async def test_mcp_node_runs_in_flow_and_emits_tool_events(client):
    server = await _create_server(client, name="流程用 MCP")
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node(
                "mcp_1",
                "mcp",
                200,
                server_id=server["id"],
                tool_name="echo",
                args_template='{"text": "{{query}}"}',
            ),
            node("output_1", "output", 400, fields=["result"]),
        ],
        [edge("e_1", "input_1", "mcp_1"), edge("e_2", "mcp_1", "output_1")],
        name="MCP 直连",
    )

    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "画布到 MCP"}})).json()
    await wait_for_status(client, run["id"], {"succeeded"})
    final = (await client.get(f"/api/runs/{run['id']}")).json()
    assert final["outputs"]["result"] == "echo: 画布到 MCP"

    from app.services.event_bus import event_bus
    import orjson

    history = await event_bus.history(run["id"])
    dumped = orjson.dumps(
        [{"type": event.type, "nodeId": event.node_id, "payload": event.payload} for event in history]
    ).decode()
    assert '"source":"mcp"' in dumped
    assert '"server":"流程用 MCP"' in dumped
    assert '"latencyMs"' in dumped


async def test_mcp_node_without_server_fails_run_with_code(client, monkeypatch):
    """没选 Server 时必须在运行期给出可读错误，而不是静默直通。

    注意：配置校验（REQUIRED_NON_EMPTY）会先拦一次，所以这里直接绕开 API 校验，
    改用手工构造的节点跑引擎——目的是守住「即使脏 DSL 漏进来也不会假装成功」。
    """
    from app.engine import extra_nodes

    class FakeNode:
        id = "mcp_1"
        config: dict = {}

    try:
        await extra_nodes.run_mcp_node(FakeNode(), {"variables": {}})
    except extra_nodes.NodeError as exc:
        assert exc.code == "MCP_NOT_CONFIGURED"
    else:
        pytest.fail("空的 MCP 节点必须报 MCP_NOT_CONFIGURED")


async def test_disabled_server_is_rejected_at_run_time(client):
    """停用的 Server 不能被 mcp 节点偷偷调用（否则「停用」开关就是摆设）。"""
    from app.engine import extra_nodes

    server = await _create_server(client, name="停用的 MCP")
    await client.put(
        f"/api/mcp-servers/{server['id']}",
        json={
            "name": "停用的 MCP",
            "command": server["command"],
            "args": server["args"],
            "timeoutS": 20,
            "enabled": False,
        },
    )

    class FakeNode:
        id = "mcp_1"
        config = {"server_id": server["id"], "tool_name": "echo", "args_template": "{}"}

    try:
        await extra_nodes.run_mcp_node(FakeNode(), {"variables": {}})
    except extra_nodes.NodeError as exc:
        assert exc.code == "MCP_NOT_CONFIGURED"
        assert "已停用" in str(exc)
    else:
        pytest.fail("停用的 MCP Server 必须拒绝执行")
