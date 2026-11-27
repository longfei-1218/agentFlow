"""parse_document MCP Server（stdio JSON-RPC）。

用途：把简历 / JD / 面试材料解析成纯文本，交给 Agent 继续处理。
协议与 resources/mcp/demo/server.py 一致：一行一个 JSON-RPC，实现
initialize、tools/list、tools/call、ping。

安全边界（全部走环境变量，不把隐私路径写进 MCP 配置）：
- AGENTFLOW_DOC_ROOTS：允许读取的根目录，多个用系统路径分隔符（Windows 用 `;`）。
  不设置时退化为「MCP 进程当前目录」。
- AGENTFLOW_DOC_MAX_BYTES：单文件大小上限，默认 20 MiB。
- AGENTFLOW_DOC_MAX_CHARS：返回文本最大字符数，默认 50000。

支持格式：
- .txt / .md / .markdown / .csv / .json / .log：直接按文本读；
- .html / .htm：去标签；
- .docx：读取 word/document.xml（标准库 zipfile，无需 python-docx）；
- .pdf：需要安装 pypdf（requirements.txt 已声明）。
"""
import json
import os
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

PROTOCOL_VERSION = "2024-11-05"
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".yaml", ".yml"}
HTML_SUFFIXES = {".html", ".htm"}

DOC_TOOL = {
    "name": "parse_document",
    "description": (
        "把本地简历 / JD / 面试材料解析成纯文本。支持 txt/md/csv/json/html/docx/pdf；"
        "路径必须在 AGENTFLOW_DOC_ROOTS 允许的目录内。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文档路径；绝对路径，或相对 AGENTFLOW_DOC_ROOTS 的路径",
            },
            "maxChars": {
                "type": "integer",
                "description": "返回文本最大字符数，默认取 AGENTFLOW_DOC_MAX_CHARS（50000）",
            },
        },
        "required": ["path"],
    },
}


class ParseError(RuntimeError):
    def __init__(self, message: str, code: str = "DOC_PARSE_FAILED") -> None:
        super().__init__(message)
        self.code = code


class _HTMLText(HTMLParser):
    BLOCK_TAGS = {
        "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "table", "ul", "ol", "blockquote", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _text_content(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _error(message: str, code: str) -> dict[str, Any]:
    return _text_content(json.dumps({"ok": False, "code": code, "error": message}, ensure_ascii=False), True)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _allowed_roots() -> list[Path]:
    raw = os.environ.get("AGENTFLOW_DOC_ROOTS", "")
    raw = raw.replace(";", os.pathsep)
    parts = [item.strip() for item in raw.split(os.pathsep) if item.strip()]
    roots = [Path(item).expanduser().resolve() for item in parts]
    return roots or [Path.cwd().resolve()]


def _resolve_path(raw_path: str) -> Path:
    if not raw_path.strip():
        raise ParseError("path 不能为空", "DOC_PATH_INVALID")
    candidate = Path(raw_path).expanduser()
    roots = _allowed_roots()

    if not candidate.is_absolute():
        candidates = [root / candidate for root in roots]
        candidate = next((item for item in candidates if item.exists()), candidates[0])

    target = candidate.resolve()
    for root in roots:
        if target == root or root in target.parents:
            return target
    raise ParseError(
        f"路径不在 AGENTFLOW_DOC_ROOTS 允许范围内: {target}；允许根目录: "
        + ", ".join(str(root) for root in roots),
        "DOC_PATH_NOT_ALLOWED",
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(encoding).lstrip("\ufeff")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").lstrip("\ufeff")


def _extract_html(data: bytes) -> str:
    parser = _HTMLText()
    parser.feed(_decode_text(data))
    parser.close()
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", text)


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ParseError(f"不是有效的 docx 文件: {exc}", "DOC_PARSE_FAILED") from exc

    # WordprocessingML 命名空间；只取 w:t 文本节点，按 w:p 分段
    paragraphs = re.findall(r"<w:p(?:\s[^>]*)?>.*?</w:p>", xml, flags=re.S)
    if not paragraphs:
        paragraphs = [xml]
    lines: list[str] = []
    for paragraph in paragraphs:
        texts = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", paragraph, flags=re.S)
        if texts:
            lines.append("".join(texts))
        else:
            lines.append("")
    text = "\n".join(lines)
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ParseError(
            "解析 PDF 需要 pypdf：在 agentflow-backend 执行 "
            ".venv\\Scripts\\python.exe -m pip install pypdf（requirements.txt 已声明）",
            "DOC_DEPENDENCY_MISSING",
        ) from exc

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ParseError("PDF 已加密，无法解析", "DOC_PARSE_FAILED")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf 的异常类型很杂，统一转成可读错误
        raise ParseError(f"PDF 解析失败: {exc}", "DOC_PARSE_FAILED") from exc

    return "\n\n".join(f"[第 {index} 页]\n{text}" for index, text in enumerate(pages, 1) if text)


_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    **{suffix: (lambda path: _decode_text(path.read_bytes())) for suffix in TEXT_SUFFIXES},
    **{suffix: (lambda path: _extract_html(path.read_bytes())) for suffix in HTML_SUFFIXES},
    ".docx": _extract_docx,
    ".pdf": _extract_pdf,
}


def parse_document(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_path(str(arguments.get("path") or ""))
    if not path.is_file():
        raise ParseError(f"文件不存在: {path}", "DOC_NOT_FOUND")

    size = path.stat().st_size
    max_bytes = _env_int("AGENTFLOW_DOC_MAX_BYTES", 20 * 1024 * 1024, 1024, 100 * 1024 * 1024)
    if size > max_bytes:
        raise ParseError(
            f"文件过大: {size} bytes，超过 AGENTFLOW_DOC_MAX_BYTES={max_bytes}",
            "DOC_TOO_LARGE",
        )

    suffix = path.suffix.lower()
    extractor = _EXTRACTORS.get(suffix)
    if extractor is None:
        raise ParseError(
            f"不支持的格式: {suffix or '(无后缀)'}；支持 {', '.join(sorted(_EXTRACTORS))}",
            "DOC_UNSUPPORTED",
        )

    try:
        full_text = extractor(path)
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"解析失败: {exc}", "DOC_PARSE_FAILED") from exc

    max_chars_env = _env_int("AGENTFLOW_DOC_MAX_CHARS", 50000, 1000, 1000000)
    requested = arguments.get("maxChars")
    max_chars = max_chars_env
    if isinstance(requested, int) and not isinstance(requested, bool):
        max_chars = max(1000, min(1000000, requested))
    # 统一换行，避免 Windows 文本的 \r\n 让下游 prompt / 分段逻辑多一个字符
    full_text = full_text.replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(full_text) > max_chars
    text = full_text[:max_chars]

    return {
        "ok": True,
        "path": str(path),
        "fileName": path.name,
        "suffix": suffix,
        "sizeBytes": size,
        "chars": len(full_text),
        "returnedChars": len(text),
        "truncated": truncated,
        "maxChars": max_chars,
        "text": text,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "parse_document":
        return _error(f"未知工具: {name}", "DOC_TOOL_UNKNOWN")
    try:
        result = parse_document(arguments)
    except ParseError as exc:
        return _error(str(exc), exc.code)
    return _text_content(json.dumps(result, ensure_ascii=False))


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agentflow-parse-document", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [DOC_TOOL]}}
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
            continue
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
