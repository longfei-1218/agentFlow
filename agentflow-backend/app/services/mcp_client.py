"""极简 MCP 客户端：stdio + 换行分隔 JSON-RPC（R5）。

为什么用「同步子进程 + 线程」而不是 `asyncio.create_subprocess_exec`：
Windows 上 uvicorn 用的是 SelectorEventLoop，它不支持子进程
（`NotImplementedError` 从 `base_events._make_subprocess_transport` 抛出来，实测踩到）。
把阻塞的 Popen 读写丢进 `asyncio.to_thread`，任何事件循环都能跑，代价只是每次调用多一个线程。

不做常驻连接：原型阶段「命令配错导致进程挂住」比「冷启动几百毫秒」更耗人；
超时由 watchdog 定时器 kill 进程兜底，stderr 会收集最后几行拼进错误信息。
"""
import asyncio
import json
import os
import subprocess
import threading
import time
from collections import deque
from typing import Any

from app.models.mcp import MCPToolInfo, MCPServerDef


class MCPError(RuntimeError):
    """带错误码的运行期异常，执行器据此翻译成 run_failed 的 code。"""

    def __init__(self, message: str, code: str = "MCP_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _content_text(result: dict[str, Any]) -> str:
    """把 tools/call 的 content 数组拼成一段文本：text 片段直接连，其余按 JSON 展示。"""
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        if item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
        elif item.get("type") == "resource":
            resource = item.get("resource") or {}
            parts.append(str(resource.get("text") or json.dumps(resource, ensure_ascii=False)))
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    return "\n".join(part for part in parts if part)


class MCPSession:
    def __init__(self, server: MCPServerDef) -> None:
        self.server = server
        self.proc: subprocess.Popen | None = None
        self._next_id = 0
        self._stderr: deque[str] = deque(maxlen=10)
        self._stderr_thread: threading.Thread | None = None
        self._timeout_hit = False

    @property
    def timeout(self) -> float:
        return float(self.server.timeout_s or 15)

    def __enter__(self) -> "MCPSession":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def start(self) -> None:
        if self.server.transport != "stdio":
            raise MCPError(
                f"暂不支持 {self.server.transport} 传输，这一轮只实现 stdio",
                code="MCP_TRANSPORT_UNSUPPORTED",
            )
        if not (self.server.command or "").strip():
            raise MCPError(
                f"MCP Server「{self.server.name}」没有配置启动命令", code="MCP_NOT_CONFIGURED"
            )

        env = {**os.environ, **(self.server.env or {})}
        try:
            self.proc = subprocess.Popen(
                [self.server.command, *[str(arg) for arg in (self.server.args or [])]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.server.cwd or None,
                env=env,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise MCPError(
                f"MCP Server 启动失败：找不到命令 {self.server.command}（检查命令是否在 PATH 里）",
                code="MCP_SPAWN_FAILED",
            ) from exc
        except OSError as exc:
            raise MCPError(f"MCP Server 启动失败：{exc}", code="MCP_SPAWN_FAILED") from exc

        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        try:
            for line in self.proc.stderr:
                text = line.strip()
                if text:
                    self._stderr.append(text)
        except Exception:  # noqa: BLE001 - stderr 诊断失败不能影响主流程
            return

    def _stderr_hint(self) -> str:
        lines = [line for line in self._stderr if line]
        if not lines:
            return ""
        return "；server stderr：" + " | ".join(lines[-3:])

    def close(self) -> None:
        if self.proc is None:
            return
        proc, self.proc = self.proc, None
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        except Exception:  # noqa: BLE001 - 关闭失败不该盖住业务错误
            return

    def _write(self, message: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _kill_on_timeout(self) -> None:
        self._timeout_hit = True
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                return

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdout is not None
        limit = timeout if timeout is not None else self.timeout
        self._next_id += 1
        request_id = self._next_id
        self._timeout_hit = False

        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        watchdog = threading.Timer(limit, self._kill_on_timeout)
        watchdog.daemon = True
        watchdog.start()
        started = time.monotonic()

        try:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    if self._timeout_hit:
                        raise MCPError(
                            f"MCP 调用超时（{method}，{limit:.0f}s）：server 没有在规定时间内回应{self._stderr_hint()}",
                            code="MCP_TIMEOUT",
                        )
                    returncode = self.proc.poll()
                    raise MCPError(
                        f"MCP Server 提前退出（{method}，exit={returncode}）{self._stderr_hint()}",
                        code="MCP_SERVER_EXITED",
                    )
                text = line.strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    # 有的 server 会往 stdout 打日志；不能因此判定协议失败
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message["error"] or {}
                    raise MCPError(
                        f"MCP Server 返回错误（{method}）：{error.get('message') or error}",
                        code="MCP_RPC_ERROR",
                    )
                return message.get("result") or {}
        finally:
            watchdog.cancel()
            elapsed = time.monotonic() - started
            if elapsed >= limit:
                self._kill_on_timeout()

    def initialize(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agentflow-studio", "version": "1.2"},
            },
        )
        self.notify("notifications/initialized")


def _probe_sync(server: MCPServerDef) -> tuple[list[MCPToolInfo], int]:
    started = time.perf_counter()
    with MCPSession(server) as session:
        session.initialize()
        result = session.request("tools/list", {})
        tools = [
            MCPToolInfo(
                name=str(item.get("name") or ""),
                description=str(item.get("description") or ""),
                input_schema=item.get("inputSchema") or {},
            )
            for item in (result.get("tools") or [])
            if isinstance(item, dict) and item.get("name")
        ]
    return tools, int((time.perf_counter() - started) * 1000)


def _call_sync(server: MCPServerDef, tool_name: str, args: dict[str, Any]) -> tuple[str, Any, int]:
    started = time.perf_counter()
    with MCPSession(server) as session:
        session.initialize()
        result = session.request("tools/call", {"name": tool_name, "arguments": args})
        latency = int((time.perf_counter() - started) * 1000)

    if result.get("isError"):
        text = _content_text(result) or "MCP 工具返回 isError=true"
        raise MCPError(f"MCP 工具 {tool_name} 执行失败：{text}", code="MCP_TOOL_ERROR")
    return _content_text(result), result, latency


async def probe_tools(server: MCPServerDef) -> tuple[list[MCPToolInfo], int]:
    """异步包装：握手并拉取工具清单。阻塞部分在线程里跑，不占事件循环。"""
    return await asyncio.to_thread(_probe_sync, server)


async def call_tool(server: MCPServerDef, tool_name: str, args: dict[str, Any]) -> tuple[str, Any, int]:
    """异步包装：调用一个 MCP 工具，返回 (文本结果, 原始 result, latency_ms)。"""
    if not (tool_name or "").strip():
        raise MCPError("没有指定要调用的 MCP 工具名", code="MCP_NOT_CONFIGURED")
    return await asyncio.to_thread(_call_sync, server, tool_name, args)
