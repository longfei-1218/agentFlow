"""AgentRunner：单 Agent 的唯一执行入口。

流程节点、单 Agent 对话、Agent 调试都走这里，避免出现两套 prompt/工具/知识库语义。
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import orjson

from app.models.agent import (
    Agent,
    AgentResource,
    AgentRunResult,
    parse_resource_tokens,
)
from app.services import knowledge_repo, llm, mcp_client, mcp_repo, tool_runner, tool_repo
from app.services.agent_service import normalize_variables

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]
VAR_RE = re.compile(r"{{(\w+)}}")
FUNC_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


class AgentRunError(RuntimeError):
    def __init__(self, message: str, code: str = "AGENT_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class BoundTool:
    fc_name: str
    display_name: str
    kind: str  # tool | mcp
    description: str
    parameters: dict[str, Any]
    tool: Any = None
    server: Any = None
    mcp_tool: str = ""
    alias: str = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.fc_name,
                "description": self.description or f"调用 {self.display_name}",
                "parameters": self.parameters,
            },
        }


@dataclass
class AgentUsage:
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    usage: dict | None = None
    steps: int = 0
    model: str = ""


@dataclass
class RoundResult:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None
    reasoning: str = ""


def _safe_func_name(raw: str, prefix: str, used: set[str]) -> str:
    base = f"{prefix}{FUNC_NAME_RE.sub('_', raw).strip('_')}"[:56]
    if not base or base == prefix:
        base = f"{prefix}tool"
    name = base
    index = 2
    while name in used:
        name = f"{base}_{index}"[:64]
        index += 1
    used.add(name)
    return name


def _render_vars(template: str, variables: dict[str, Any]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        value = variables[key]
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    return VAR_RE.sub(repl, template)


def _coerce_json_text(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise


def _validate_schema(data: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """够用即可的 JSON Schema 校验：type/properties/required/items/enum。"""
    problems: list[str] = []
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(data, dict):
            return [f"{path} 应为 object"]
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in data:
                problems.append(f"{path}.{key} 缺失")
        for key, child in properties.items():
            if key in data and isinstance(child, dict):
                problems.extend(_validate_schema(data[key], child, f"{path}.{key}"))
    elif expected == "array":
        if not isinstance(data, list):
            return [f"{path} 应为 array"]
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(data):
                problems.extend(_validate_schema(item, item_schema, f"{path}[{index}]"))
    elif expected == "string":
        if not isinstance(data, str):
            problems.append(f"{path} 应为 string")
    elif expected == "number":
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            problems.append(f"{path} 应为 number")
    elif expected == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            problems.append(f"{path} 应为 integer")
    elif expected == "boolean":
        if not isinstance(data, bool):
            problems.append(f"{path} 应为 boolean")
    if "enum" in schema and data not in schema["enum"]:
        problems.append(f"{path} 不在 enum 里")
    return problems


async def _build_prompt_and_resources(
    agent: Agent,
    variables: dict[str, Any],
    *,
    emit: EmitFn | None,
) -> tuple[str, list[BoundTool], set[str], list[dict]]:
    """展开 @kb、收集工具候选、返回渲染后的用户提示词。"""
    resources_by_alias = {res.alias: res for res in agent.resources}
    bound: list[BoundTool] = []
    used_names: set[str] = set()
    force_names: set[str] = set()
    knowledge_calls: list[dict] = []

    # Tool 资源：无论是否 @，都作为 FC 候选
    for res in agent.resources:
        if res.kind != "tool":
            continue
        try:
            tool = await tool_repo.get_tool(res.id)
        except tool_repo.ToolNotFound as exc:
            raise AgentRunError(str(exc), code="AGENT_RESOURCE_MISSING") from exc
        if not tool.enabled:
            raise AgentRunError(f"工具「{tool.name}」已停用", code="AGENT_RESOURCE_MISSING")
        fc_name = _safe_func_name(tool.name, "tool_", used_names)
        bound.append(
            BoundTool(
                fc_name=fc_name,
                display_name=tool.name,
                kind="tool",
                description=tool.description,
                parameters=tool.params_schema,
                tool=tool,
                alias=res.alias,
            )
        )

    # MCP 资源：探测一次工具清单，把选中工具也作为 FC 候选
    for res in agent.resources:
        if res.kind != "mcp":
            continue
        try:
            server = await mcp_repo.get_server(res.id)
        except mcp_repo.MCPServerNotFound as exc:
            raise AgentRunError(str(exc), code="AGENT_RESOURCE_MISSING") from exc
        if not server.enabled:
            raise AgentRunError(f"MCP Server「{server.name}」已停用", code="AGENT_RESOURCE_MISSING")
        try:
            tools, _ = await mcp_client.probe_tools(server)
        except mcp_client.MCPError as exc:
            raise AgentRunError(str(exc), code=exc.code) from exc
        by_name = {item.name: item for item in tools}
        missing = [name for name in res.tools if name not in by_name]
        if missing:
            raise AgentRunError(
                f"MCP Server「{server.name}」缺少导入的工具: {missing}",
                code="AGENT_RESOURCE_MISSING",
            )
        for name in res.tools:
            info = by_name[name]
            fc_name = _safe_func_name(f"{res.alias}_{name}", "mcp_", used_names)
            bound.append(
                BoundTool(
                    fc_name=fc_name,
                    display_name=f"{server.name}.{name}",
                    kind="mcp",
                    description=info.description,
                    parameters=info.input_schema or {"type": "object", "properties": {}},
                    server=server,
                    mcp_tool=name,
                    alias=res.alias,
                )
            )

    prompt = agent.prompt.template
    try:
        tokens = parse_resource_tokens(prompt)
    except ValueError as exc:
        raise AgentRunError(str(exc), code="AGENT_PROMPT_RESOURCE_UNKNOWN") from exc
    for token in tokens:
        if token.kind == "kb":
            res = resources_by_alias.get(token.alias)
            if res is None or res.kind != "knowledge":
                raise AgentRunError(
                    f"@kb[{token.alias}] 没有对应的知识库资源",
                    code="AGENT_PROMPT_RESOURCE_UNKNOWN",
                )
            query = str(variables.get(res.query_var) or "").strip()
            if not query:
                raise AgentRunError(
                    f"知识库「{token.alias}」的检索变量 {res.query_var} 为空",
                    code="AGENT_INPUT_MISSING",
                )
            try:
                result = await knowledge_repo.search(
                    res.id, query, top_k=res.top_k, rerank=res.rerank
                )
            except knowledge_repo.KBNotFound as exc:
                raise AgentRunError(str(exc), code="AGENT_RESOURCE_MISSING") from exc
            context = "\n\n".join(
                f"[{index + 1}] {hit.title} #chunk{hit.seq}（score {hit.score}）\n{hit.text}"
                for index, hit in enumerate(result.hits)
            )
            if not context:
                context = f"（知识库「{token.alias}」未命中任何片段）"
            prompt = prompt.replace(f"@kb[{token.alias}]", context)
            record = {
                "alias": token.alias,
                "kbId": res.id,
                "query": query,
                "hits": len(result.hits),
                "topScore": result.hits[0].score if result.hits else 0,
                "totalChunks": result.total_chunks,
                "tookMs": result.took_ms,
            }
            knowledge_calls.append(record)
            if emit:
                await emit("knowledge_retrieved", record)

        elif token.kind == "tool":
            matches = [item for item in bound if item.kind == "tool" and item.alias == token.alias]
            if not matches:
                raise AgentRunError(
                    f"@tool[{token.alias}] 没有对应的工具资源",
                    code="AGENT_PROMPT_RESOURCE_UNKNOWN",
                )
            force_names.add(matches[0].fc_name)
            prompt = prompt.replace(f"@tool[{token.alias}]", "")

        else:
            matches = [
                item
                for item in bound
                if item.kind == "mcp"
                and item.alias == token.alias
                and item.mcp_tool == token.tool
            ]
            if not matches:
                raise AgentRunError(
                    f"@mcp[{token.alias}.{token.tool}] 没有对应的 MCP 工具",
                    code="AGENT_PROMPT_RESOURCE_UNKNOWN",
                )
            force_names.add(matches[0].fc_name)
            prompt = prompt.replace(f"@mcp[{token.alias}.{token.tool}]", "")

    return _render_vars(prompt, variables).strip(), bound, force_names, knowledge_calls


async def _stream_round(
    config: llm.LLMConfig,
    messages: list[dict],
    *,
    tools: list[dict] | None,
    tool_choice: str | dict | None,
    model: str,
    temperature: float,
    max_tokens: int,
    usage: AgentUsage,
    emit: EmitFn | None = None,
    stop: Callable[[], bool] | None = None,
) -> RoundResult:
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    reasoning_parts: list[str] = []
    finish: str | None = None
    if stop and stop():
        raise AgentRunError("用户取消", code="RUN_CANCELLED")
    try:
        async for delta in llm.stream_completion(
            config,
            messages,
            model=model or None,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        ):
            if stop and stop():
                raise AgentRunError("用户取消", code="RUN_CANCELLED")
            if delta.text:
                text_parts.append(delta.text)
                if emit:
                    await emit(
                        "token",
                        {
                            "text": delta.text,
                            "deltaTokens": delta.delta_tokens,
                            "cost": delta.cost,
                        },
                    )
            if delta.reasoning:
                reasoning_parts.append(delta.reasoning)
            if delta.tool_calls:
                tool_calls = delta.tool_calls
            if delta.finish_reason:
                finish = delta.finish_reason
            usage.tokens += delta.delta_tokens
            usage.prompt_tokens += delta.delta_prompt_tokens
            usage.completion_tokens += delta.delta_completion_tokens
            usage.cost += delta.cost
            if delta.usage:
                usage.usage = delta.usage
    except llm.LLMError as exc:
        raise AgentRunError(str(exc), code=exc.code) from exc
    usage.steps += 1
    return RoundResult(
        text="".join(text_parts),
        tool_calls=tool_calls,
        finish_reason=finish,
        reasoning="".join(reasoning_parts),
    )


async def _execute_call(
    call: dict,
    bound: list[BoundTool],
    *,
    emit: EmitFn | None,
    trace: list[dict],
) -> dict:
    name = str(call.get("name") or "")
    match = next((item for item in bound if item.fc_name == name), None)
    if match is None:
        error = f"模型调用了未导入的工具: {name}"
        trace.append({"tool": name, "ok": False, "error": error})
        return {"role": "tool", "tool_call_id": call.get("id"), "content": f"ERROR: {error}"}

    raw_args = call.get("arguments") or "{}"
    try:
        args = orjson.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        if not isinstance(args, dict):
            raise ValueError("arguments 不是 JSON 对象")
    except (orjson.JSONDecodeError, ValueError, TypeError) as exc:
        error = f"参数不是合法 JSON: {exc}"
        if emit:
            await emit(
                "tool_call",
                {"tool": match.display_name, "args": raw_args, "source": match.kind, "alias": match.alias},
            )
            await emit("tool_result", {"tool": match.display_name, "ok": False, "error": error})
        trace.append({"tool": match.display_name, "ok": False, "error": error})
        return {"role": "tool", "tool_call_id": call.get("id"), "content": f"ERROR: {error}"}

    if emit:
        await emit(
            "tool_call",
            {"tool": match.display_name, "args": args, "source": match.kind, "alias": match.alias},
        )
    try:
        if match.kind == "tool":
            invocation = await tool_runner.invoke(match.tool, args, node_id="agent")
            content = (
                invocation.result
                if isinstance(invocation.result, str)
                else orjson.dumps(invocation.result).decode()
            )
            result_payload = {
                "tool": match.display_name,
                "ok": True,
                "result": invocation.result,
                "latencyMs": invocation.latency_ms,
                "source": "tool",
            }
            trace.append(
                {
                    "tool": match.display_name,
                    "source": "tool",
                    "args": args,
                    "ok": True,
                    "latencyMs": invocation.latency_ms,
                }
            )
        else:
            text, _, latency = await mcp_client.call_tool(match.server, match.mcp_tool, args)
            content = text
            result_payload = {
                "tool": match.display_name,
                "ok": True,
                "result": text,
                "latencyMs": latency,
                "source": "mcp",
            }
            trace.append(
                {
                    "tool": match.display_name,
                    "source": "mcp",
                    "args": args,
                    "ok": True,
                    "latencyMs": latency,
                }
            )
    except (tool_runner.ToolError, mcp_client.MCPError) as exc:
        error = str(exc)
        if emit:
            await emit(
                "tool_result",
                {"tool": match.display_name, "ok": False, "error": error, "source": match.kind},
            )
        trace.append({"tool": match.display_name, "ok": False, "error": error, "source": match.kind})
        return {"role": "tool", "tool_call_id": call.get("id"), "content": f"ERROR: {error}"}

    if emit:
        await emit("tool_result", result_payload)
    return {"role": "tool", "tool_call_id": call.get("id"), "content": content}


async def run_agent(
    agent: Agent,
    variables: dict[str, Any],
    *,
    llm_config: llm.LLMConfig | None = None,
    emit: EmitFn | None = None,
    stop: Callable[[], bool] | None = None,
    chat_text: str | None = None,
) -> AgentRunResult:
    try:
        values = normalize_variables(agent, variables)
    except ValueError as exc:
        raise AgentRunError(str(exc), code="AGENT_INPUT_MISSING") from exc

    if llm_config is None:
        from app.services.settings_repo import get_llm_config

        llm_config = await get_llm_config()
    if not llm_config.configured:
        raise AgentRunError("尚未配置 LLM API Key", code="LLM_NOT_CONFIGURED")

    model = agent.model.name or llm_config.model
    usage = AgentUsage(model=model)
    prompt, bound, force_names, knowledge_calls = await _build_prompt_and_resources(
        agent, values, emit=emit
    )
    # 零变量 Agent 的对话：消息没有可填的变量，直接追加到模板末尾，
    # 否则固定提示词 Agent 在对话里会把用户这句话静默丢掉
    if chat_text and chat_text.strip():
        prompt = f"{prompt.rstrip()}\n\n用户消息：\n{chat_text.strip()}"

    messages: list[dict] = []
    if agent.prompt.system.strip():
        messages.append({"role": "system", "content": agent.prompt.system})
    messages.append({"role": "user", "content": prompt})

    tools = [item.schema() for item in bound] if bound else None
    trace: list[dict] = []
    called: set[str] = set()
    forced_retry = 0
    rounds = 0
    answer = ""
    force_tool_choice: str | dict | None = "auto" if tools else None
    if force_names:
        if len(force_names) == 1:
            only = next(iter(force_names))
            force_tool_choice = {"type": "function", "function": {"name": only}}
        else:
            force_tool_choice = "required"

    while True:
        if stop and stop():
            raise AgentRunError("用户取消", code="RUN_CANCELLED")
        if agent.model.max_tool_rounds and rounds > agent.model.max_tool_rounds:
            raise AgentRunError(
                f"工具调用超过上限 maxToolRounds={agent.model.max_tool_rounds}",
                code="AGENT_TOOL_ROUND_LIMIT",
            )
        current_choice = force_tool_choice
        if force_names and force_names <= called:
            current_choice = "auto"
        result = await _stream_round(
            llm_config,
            messages,
            tools=tools,
            tool_choice=current_choice,
            model=model,
            temperature=agent.model.temperature,
            max_tokens=agent.model.max_tokens,
            usage=usage,
            emit=emit,
            stop=stop,
        )

        if not result.tool_calls:
            answer = result.text
            missing = force_names - called
            if missing and forced_retry < 1:
                forced_retry += 1
                names = ", ".join(item.display_name for item in bound if item.fc_name in missing)
                messages.append({"role": "assistant", "content": result.text or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": f"本轮还没有调用必须使用的工具：{names}。请先调用工具，再给出最终回答。",
                    }
                )
                continue
            if missing:
                raise AgentRunError(
                    f"强制工具未被调用: {missing}",
                    code="AGENT_FORCED_TOOL_NOT_CALLED",
                )
            if not answer.strip():
                if result.finish_reason == "length":
                    hint = f"回答达到 maxTokens={agent.model.max_tokens} 被截断"
                elif result.reasoning:
                    hint = "模型只返回了推理内容，没有最终答案"
                else:
                    hint = "模型没有返回任何文本"
                raise AgentRunError(f"空回答：{hint}", code="AGENT_EMPTY_ANSWER")
            break

        rounds += 1
        if agent.model.max_tool_rounds and rounds > agent.model.max_tool_rounds:
            raise AgentRunError(
                f"工具调用超过上限 maxToolRounds={agent.model.max_tool_rounds}",
                code="AGENT_TOOL_ROUND_LIMIT",
            )
        messages.append(
            {
                "role": "assistant",
                "content": result.text or None,
                "tool_calls": [
                    {
                        "id": call.get("id"),
                        "type": "function",
                        "function": {
                            "name": call.get("name"),
                            "arguments": call.get("arguments") or "{}",
                        },
                    }
                    for call in result.tool_calls
                ],
            }
        )
        for call in result.tool_calls:
            called.add(str(call.get("name") or ""))
            messages.append(await _execute_call(call, bound, emit=emit, trace=trace))

    if agent.output.schema_ is not None:
        try:
            data = _coerce_json_text(answer)
            problems = _validate_schema(data, agent.output.schema_)
            if problems:
                raise ValueError("; ".join(problems))
        except (json.JSONDecodeError, ValueError) as exc:
            # 只重试一次：把错误回给模型，要求纯 JSON
            messages.append({"role": "assistant", "content": answer})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一次输出不符合要求的 JSON schema："
                        f"{exc}。请只输出符合 schema 的 JSON，不要解释、不要代码块。"
                    ),
                }
            )
            retry = await _stream_round(
                llm_config,
                messages,
                tools=None,
                tool_choice=None,
                model=model,
                temperature=agent.model.temperature,
                max_tokens=agent.model.max_tokens,
                usage=usage,
                emit=emit,
                stop=stop,
            )
            answer = retry.text
            try:
                data = _coerce_json_text(answer)
                problems = _validate_schema(data, agent.output.schema_)
                if problems:
                    raise ValueError("; ".join(problems))
            except (json.JSONDecodeError, ValueError) as exc2:
                raise AgentRunError(
                    f"输出不符合 JSON schema: {exc2}", code="AGENT_OUTPUT_INVALID"
                ) from exc2
        if not isinstance(data, dict):
            raise AgentRunError("输出 schema 要求 JSON 对象", code="AGENT_OUTPUT_INVALID")
        outputs = data
        text = data.get("text") if isinstance(data.get("text"), str) else answer
    else:
        outputs = {"text": answer}
        text = answer

    return AgentRunResult(
        agent_id=agent.id,
        outputs=outputs,
        text=text,
        tokens=usage.tokens,
        cost=round(usage.cost, 6),
        steps=usage.steps,
        model=model,
        tool_calls=trace,
        knowledge_calls=knowledge_calls,
    )
