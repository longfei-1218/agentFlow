"""一个可跑的最小 MCP stdio server（演示 / 测试用）。

它实现 MCP 的三个关键方法：initialize、tools/list、tools/call，
传输是「一行一条 JSON-RPC」。用它可以在没有任何外网依赖的情况下，
把「注册 MCP Server → 探测工具 → 画布 mcp 节点调用」整条链路走通。

用法（在 AgentFlow 的「MCP 服务」页填）：
    command = python 的绝对路径
    args    = ["<仓库路径>/agentflow-backend/scripts/mcp_demo_server.py"]

也可以手工验证：
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python scripts/mcp_demo_server.py
"""
import json
import sys
import time

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "echo",
        "description": "原样返回文本，用来验证 MCP 调用链路",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "两个数字相加",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "now",
        "description": "返回当前时间（ISO 字符串 + 时间戳）",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text_content(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name: str, arguments: dict) -> dict:
    if name == "echo":
        text = str(arguments.get("text", ""))
        return _text_content(f"echo: {text}")
    if name == "add":
        try:
            total = float(arguments.get("a", 0)) + float(arguments.get("b", 0))
        except (TypeError, ValueError) as exc:
            return _text_content(f"参数不是数字: {exc}", is_error=True)
        return _text_content(str(int(total) if total.is_integer() else total))
    if name == "now":
        stamp = time.time()
        return _text_content(
            json.dumps(
                {"iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "timestamp": round(stamp, 3)},
                ensure_ascii=False,
            )
        )
    return _text_content(f"未知工具: {name}", is_error=True)


def handle(message: dict) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agentflow-demo-mcp", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None  # 通知没有 id，不回
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": call_tool(str(params.get("name") or ""), params.get("arguments") or {}),
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"方法不存在: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            # 非 JSON 的输入直接忽略，保持协议健壮（真实 server 会打日志到 stderr）
            continue
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
