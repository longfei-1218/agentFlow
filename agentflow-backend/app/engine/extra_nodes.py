"""R5 三类「外部资源」节点的执行实现：MCP / 知识库 / 子流程。

为什么单独放一个模块：loop 与 graph 两个执行器都要用，逻辑放在任何一边都会让
另一边反向依赖；而且这三类节点都要发「子事件」（tool_call / tool_result），
把「发不发事件」做成参数，子流程内联执行时就能复用同一份代码而不污染父 run 的事件流。
"""
import orjson
from typing import Any, Awaitable, Callable

from app.config import settings
from app.services.event_bus import event_bus


class NodeError(RuntimeError):
    """节点执行错误：带 code，执行器据此落 run_failed。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


EmitFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def _noop_emit(event_type: str, node_id: str, payload: dict[str, Any]) -> None:
    return None


def make_emitter(run_id: str, enabled: bool = True) -> EmitFn:
    if not enabled or not run_id:
        return _noop_emit

    async def emit(event_type: str, node_id: str, payload: dict[str, Any]) -> None:
        await event_bus.emit(run_id, event_type, node_id, payload)

    return emit


def render_template(template: str, variables: dict[str, Any]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def parse_args_template(template: str, variables: dict[str, Any], *, field: str = "参数模板") -> dict:
    rendered = render_template(template or "{}", variables)
    try:
        parsed = orjson.loads(rendered or "{}")
    except orjson.JSONDecodeError as exc:
        raise NodeError(
            f"{field}不是合法 JSON（插值后为 {rendered[:120]}）：{exc}", code="NODE_ARGS_INVALID"
        ) from exc
    if not isinstance(parsed, dict):
        raise NodeError(f"{field}必须是一个 JSON 对象", code="NODE_ARGS_INVALID")
    return parsed


async def run_mcp_node(node, data: dict, *, emit: EmitFn = _noop_emit) -> str:
    """调用 MCP Server 上的一个工具，结果写进 variables.result。"""
    from app.services import mcp_client, mcp_repo

    server_id = str(node.config.get("server_id") or "")
    tool_name = str(node.config.get("tool_name") or "")
    if not server_id:
        raise NodeError(
            f"{node.id}: 没有选择 MCP Server，先在「MCP 服务」页注册一个再选",
            code="MCP_NOT_CONFIGURED",
        )
    if not tool_name:
        raise NodeError(
            f"{node.id}: 没有指定要调用的 MCP 工具名（可先在该 Server 上「探测工具」查看清单）",
            code="MCP_NOT_CONFIGURED",
        )

    try:
        server = await mcp_repo.get_server(server_id)
    except mcp_repo.MCPServerNotFound as exc:
        raise NodeError(f"{node.id}: {exc}", code="MCP_SERVER_NOT_FOUND") from exc
    if not server.enabled:
        raise NodeError(
            f"{node.id}: MCP Server「{server.name}」已停用，先在「MCP 服务」页启用再运行",
            code="MCP_NOT_CONFIGURED",
        )

    args = parse_args_template(str(node.config.get("args_template") or "{}"), data["variables"])
    await emit(
        "tool_call",
        node.id,
        {
            "tool": tool_name,
            "server": server.name,
            "serverId": server.id,
            "args": args,
            "source": "mcp",
        },
    )

    try:
        text, raw, latency = await mcp_client.call_tool(server, tool_name, args)
    except mcp_client.MCPError as exc:
        await emit(
            "tool_result",
            node.id,
            {
                "tool": tool_name,
                "server": server.name,
                "ok": False,
                "error": str(exc),
                "code": exc.code,
            },
        )
        raise NodeError(f"{node.id}: {exc}", code=exc.code) from exc

    await emit(
        "tool_result",
        node.id,
        {
            "tool": tool_name,
            "server": server.name,
            "ok": True,
            "result": text,
            "latencyMs": latency,
        },
    )
    data.setdefault("mcp_calls", []).append(
        {"server": server.name, "tool": tool_name, "args": args, "latencyMs": latency}
    )
    return text


async def run_knowledge_node(node, data: dict, *, emit: EmitFn = _noop_emit) -> dict:
    """检索知识库，把命中片段拼成 context 写进变量（下游 prompt/llm 可直接 {{context}}）。"""
    from app.services import knowledge_repo

    kb_id = str(node.config.get("kb_id") or "")
    if not kb_id:
        raise NodeError(
            f"{node.id}: 没有选择知识库，先在「知识库」页新建并导入文档",
            code="KNOWLEDGE_NOT_CONFIGURED",
        )

    query_template = str(node.config.get("query_template") or "{{query}}")
    query = render_template(query_template, data["variables"]).strip()
    if not query:
        raise NodeError(
            f"{node.id}: 检索 query 是空的（检查 query_template，默认取 {{query}} 变量）",
            code="KNOWLEDGE_QUERY_EMPTY",
        )

    top_k = int(node.config.get("top_k") or 4)
    rerank = bool(node.config.get("rerank") or False)
    try:
        result = await knowledge_repo.search(kb_id, query, top_k=top_k, rerank=rerank)
    except knowledge_repo.KBNotFound as exc:
        raise NodeError(f"{node.id}: {exc}", code="KNOWLEDGE_KB_NOT_FOUND") from exc

    context = "\n\n".join(
        f"[{index + 1}] {hit.title} #chunk{hit.seq}（score {hit.score}）\n{hit.text}"
        for index, hit in enumerate(result.hits)
    )
    data["variables"]["context"] = context
    data["variables"]["citations"] = [
        {"title": hit.title, "docId": hit.doc_id, "seq": hit.seq, "score": hit.score}
        for hit in result.hits
    ]
    data.setdefault("knowledge_calls", []).append(
        {"kbId": kb_id, "query": query, "hits": len(result.hits), "tookMs": result.took_ms}
    )

    payload = {
        "kbId": kb_id,
        "query": query,
        "hits": len(result.hits),
        "topScore": result.hits[0].score if result.hits else 0,
        "totalChunks": result.total_chunks,
        "rerank": rerank,
        "tookMs": result.took_ms,
    }
    if result.hint:
        payload["hint"] = result.hint
    await emit("knowledge_retrieved", node.id, payload)
    return payload


async def run_skill_node(node, data: dict, *, stop, llm_config) -> dict:
    """把另一个流程当子流程同步跑完，输出合并回父流程变量。"""
    from app.engine.subflow import run_subflow
    from app.services.flow_repo import load_flow

    flow_id = str(node.config.get("flow_id") or "")
    if not flow_id:
        raise NodeError(
            f"{node.id}: 没有选择子流程，先在配置面板里选一个已有流程",
            code="SKILL_NOT_CONFIGURED",
        )

    chain = list(data.get("skill_chain") or [])
    parent_flow_id = str(data.get("flow_id") or "")
    if flow_id == parent_flow_id or flow_id in chain:
        raise NodeError(
            f"{node.id}: 子流程形成了递归调用（{flow_id} 已在调用链 {chain + [parent_flow_id]} 中）",
            code="SKILL_RECURSION",
        )
    if len(chain) >= 3:
        raise NodeError(
            f"{node.id}: 子流程嵌套超过 3 层（当前链 {chain}），拒绝继续下钻",
            code="SKILL_DEPTH_EXCEEDED",
        )

    try:
        child_flow = await load_flow(flow_id)
    except Exception as exc:  # noqa: BLE001 - 老实现抛 HTTPException，这里统一翻成节点错误
        raise NodeError(
            f"{node.id}: 读取子流程失败：{exc}（检查 flow_id 是否还存在）",
            code="SKILL_FLOW_NOT_FOUND",
        ) from exc

    human_nodes = [item.id for item in child_flow.nodes if item.type == "human"]
    if human_nodes:
        raise NodeError(
            f"{node.id}: 子流程「{child_flow.name}」含人工审批节点 {human_nodes}，"
            "嵌套审批暂不支持；请把审批放在父流程里，子流程只做纯计算/工具调用",
            code="SKILL_HUMAN_UNSUPPORTED",
        )

    inputs = parse_args_template(
        str(node.config.get("inputs_template") or "{}"), data["variables"], field="子流程入参模板"
    )

    result = await run_subflow(
        child_flow,
        inputs,
        stop=stop,
        llm_config=llm_config,
        parent_chain=chain + ([parent_flow_id] if parent_flow_id else []),
    )

    # 子流程的输出合并回父变量：下游可以直接 {{text}}；同时保留一份结构化 result
    outputs = result["outputs"]
    data["variables"].update({key: value for key, value in outputs.items()})
    data["variables"]["result"] = orjson.dumps(outputs, option=orjson.OPT_NON_STR_KEYS).decode()
    data["skill_chain"] = chain
    data["tokens"] += result["tokens"]
    data["prompt_tokens"] += result["prompt_tokens"]
    data["completion_tokens"] += result["completion_tokens"]
    data["cost"] += result["cost"]
    data.setdefault("skill_calls", []).append(
        {
            "flowId": flow_id,
            "flowName": child_flow.name,
            "inputs": inputs,
            "steps": result["steps"],
            "tokens": result["tokens"],
        }
    )

    return {
        "skillFlow": flow_id,
        "skillFlowName": child_flow.name,
        "inputs": inputs,
        "outputs": outputs,
        "steps": result["steps"],
        "tokens": result["tokens"],
        "cost": round(result["cost"], 6),
        "depth": len(chain) + 1,
    }
