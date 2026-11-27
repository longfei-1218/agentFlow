"""资源包导入：本地 MCP zip、远程 MCP、HTTP 工具、知识库文件存储。"""
import io
import json
import pathlib
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.config import settings

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PARSE_DIR = BACKEND / "resources" / "mcp" / "parse_document"


def _parse_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.write(PARSE_DIR / "manifest.json", "manifest.json")
        archive.write(PARSE_DIR / "server.py", "server.py")
    return buffer.getvalue()


async def test_import_local_mcp_zip_into_owner_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RESOURCE_DATA_DIR", str(tmp_path / "resources"))

    response = await client.post(
        "/api/resources/import",
        data={"kind": "mcp_local"},
        files={"file": ("parse.zip", _parse_zip(), "application/zip")},
    )
    body = response.json()
    assert body["ok"] is True, body
    assert body["status"] == "installed"
    assert [tool["name"] for tool in body["tools"]] == ["parse_document"]
    assert body["targetId"]

    package = pathlib.Path(body["packagePath"])
    assert package.is_dir()
    assert package.name.startswith("parse_document-")
    assert (package / "manifest.json").is_file()
    assert (package / "server.py").is_file()

    server = (await client.get("/api/mcp-servers")).json()
    imported = next(item for item in server if item["id"] == body["targetId"])
    assert imported["source"] == "import"
    assert imported["packagePath"] == str(package)
    assert imported["verifiedAt"]


async def test_import_http_tool_manifest(client):
    manifest = {
        "schemaVersion": 1,
        "kind": "http_tool",
        "name": "lookup_order",
        "description": "按订单号查询",
        "method": "GET",
        "url": "https://example.invalid/orders/{{orderId}}",
        "headers": {"Authorization": "Bearer ${TEST_IMPORT_TOKEN}"},
        "env": {"TEST_IMPORT_TOKEN": "${TEST_IMPORT_SECRET}"},
        "paramsSchema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
    }
    response = await client.post(
        "/api/resources/import",
        data={"kind": "http_tool", "manifest": json.dumps(manifest, ensure_ascii=False)},
    )
    body = response.json()
    assert body["ok"] is True, body
    assert body["targetId"].startswith("tool_")

    tool = next(item for item in (await client.get("/api/tools")).json() if item["id"] == body["targetId"])
    assert tool["source"] == "import"
    assert tool["paramsSchema"]["required"] == ["orderId"]


class _RemoteMCPHandler(BaseHTTPRequestHandler):
    def _send(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "session-test")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        message = json.loads(self.rfile.read(length) or b"{}")
        method = message.get("method")
        request_id = message.get("id")

        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "remote-test", "version": "1.0"},
                    },
                }
            )
            return
        if method == "tools/list":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "ping",
                                "description": "返回 pong",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            )
            return
        if method == "tools/call":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "pong"}], "isError": False},
                }
            )
            return
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown"}}
        )

    def log_message(self, *args):
        return


async def test_import_remote_mcp_http_and_call(client):
    httpd = HTTPServer(("127.0.0.1", 0), _RemoteMCPHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        manifest = {
            "schemaVersion": 1,
            "kind": "mcp",
            "name": "remote-ping",
            "transport": "http",
            "url": f"http://127.0.0.1:{httpd.server_port}/mcp",
            "timeoutS": 10,
        }
        response = await client.post(
            "/api/resources/import",
            data={"kind": "mcp_remote", "manifest": json.dumps(manifest)},
        )
        body = response.json()
        assert body["ok"] is True, body
        assert [tool["name"] for tool in body["tools"]] == ["ping"]

        call = (
            await client.post(
                f"/api/mcp-servers/{body['targetId']}/call",
                json={"toolName": "ping", "args": {}},
            )
        ).json()
        assert call["ok"] is True, call
        assert call["result"] == "pong"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


async def test_knowledge_documents_land_in_resource_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RESOURCE_DATA_DIR", str(tmp_path / "resources"))
    kb = (
        await client.post("/api/knowledge", json={"name": "文件化知识库", "chunkSize": 80, "overlap": 10})
    ).json()
    doc = (
        await client.post(
            f"/api/knowledge/{kb['id']}/documents",
            json={"title": "退款政策", "content": "退款 7 天内可申请，原路退回。"},
        )
    ).json()

    kb_dir = tmp_path / "resources" / "users" / "local" / "knowledge" / kb["id"]
    assert (kb_dir / "manifest.json").is_file()
    content = (kb_dir / "documents" / f"{doc['id']}.md").read_text(encoding="utf-8")
    assert content.startswith("# 退款政策")
