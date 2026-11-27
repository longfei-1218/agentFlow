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

