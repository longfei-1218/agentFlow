"""R5：MCP Server 探测与工具调用（stdio 真进程，不 mock 协议）。"""
import json
import pathlib
import sys

import pytest

from helpers import create_flow, edge, node, wait_for_status

MCP_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "resources" / "mcp" / "demo" / "server.py"
PARSE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "resources" / "mcp" / "parse_document" / "server.py"


async def _create_server(client, name="演示 MCP", env=None) -> dict:
    response = await client.post(
        "/api/mcp-servers",
        json={
            "name": name,
            "command": sys.executable,
            "args": [str(MCP_SCRIPT)],
            "env": env or {},
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


async def _create_parse_server(client, *, env: dict[str, str], name="parse-document") -> dict:
    response = await client.post(
        "/api/mcp-servers",
        json={
            "name": name,
            "command": sys.executable,
            "args": [str(PARSE_SCRIPT)],
            "env": env,
            "timeoutS": 20,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_parse_document_mcp_reads_txt_and_enforces_root(client, tmp_path, monkeypatch):
    doc = tmp_path / "resume.txt"
    doc.write_text("张三\n五年 React 经验\n" + "x" * 5000, encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_TEST_DOC_ROOT", str(tmp_path))
    server = await _create_parse_server(
        client,
        env={
            "AGENTFLOW_DOC_ROOTS": "${AGENTFLOW_TEST_DOC_ROOT}",
            "AGENTFLOW_DOC_MAX_CHARS": "1200",
        },
    )

    probe = (await client.get(f"/api/mcp-servers/{server['id']}/tools")).json()
    assert probe["ok"] is True, probe
    assert [tool["name"] for tool in probe["tools"]] == ["parse_document"]

    call = (
        await client.post(
            f"/api/mcp-servers/{server['id']}/call",
            json={"toolName": "parse_document", "args": {"path": "resume.txt"}},
        )
    ).json()
    assert call["ok"] is True, call
    parsed = json.loads(call["result"])
    assert parsed["ok"] is True
    assert parsed["fileName"] == "resume.txt"
    assert parsed["text"].startswith("张三\n五年 React 经验")
    assert parsed["truncated"] is True
    assert parsed["returnedChars"] == 1200

    outside = (
        await client.post(
            f"/api/mcp-servers/{server['id']}/call",
            json={"toolName": "parse_document", "args": {"path": str(PARSE_SCRIPT)}},
        )
    ).json()
    assert outside["ok"] is False
    assert "DOC_PATH_NOT_ALLOWED" in outside["error"]


async def test_mcp_reports_missing_env_before_spawn(client, monkeypatch):
    monkeypatch.delenv("AGENTFLOW_MISSING_ROOT", raising=False)
    server = await _create_parse_server(
        client,
        env={"AGENTFLOW_DOC_ROOTS": "${AGENTFLOW_MISSING_ROOT}"},
        name="parse-document-missing-env",
    )

    probe = (await client.get(f"/api/mcp-servers/{server['id']}/tools")).json()
    assert probe["ok"] is False
    assert probe["code"] == "MCP_ENV_MISSING"
    assert "AGENTFLOW_MISSING_ROOT" in probe["error"]

