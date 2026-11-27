"""手写 Agent Loop：拓扑执行 + 真实模型流式 + 步数守卫。

旧 DSL 的对照执行器：事件协议、state 快照格式与 LangGraph 执行器保持一致，
这样前端不需要区分是旧回放还是正常 v2 运行。

MAX_STEPS 的语义：一次 LLM 调用算一步。它防的是「模型被工具喂了结果之后无限自我循环」，
不是「节点数量上限」——线性的 10 个节点流程不该因为 MAX_STEPS=8 就被拦。
"""
import asyncio
import copy
from typing import Any

import orjson

from app.config import settings
from app.engine import extra_nodes
from app.engine.common import (
    DEFAULT_STATE,
    dump_state,
    finish_cancelled,
    node_summary,
    pause,
    topological_order,
    write_state,
)
from app.models.flow import Flow, FlowNode
from app.models.run import RunStatus
from app.services import tool_repo, tool_runner
from app.services.event_bus import event_bus, utc_now
from app.services.llm import LLMConfig, LLMError, stream_completion
from app.services.run_repo import load_run, update_run

# 手写 loop 只支持线性拓扑：condition / loop 的语义在图引擎里，这里仍按直通占位。
# mcp / skill / knowledge 在 R5 已实装，两个引擎共用 extra_nodes 里的实现。
PLACEHOLDER_NODES = {"condition", "loop"}


class StepLimitExceeded(RuntimeError):
    code = "STEP_LIMIT_EXCEEDED"


def render_template(template: str, variables: dict[str, Any]) -> str:
    """{{var}} 插值。缺失变量保留原样，方便用户看出自己拼错了。"""
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def build_messages(node: FlowNode, variables: dict[str, Any]) -> list[dict]:
    system = str(node.config.get("system") or "你是一个有帮助的助手。")
    user = variables.get("text") or variables.get("query") or ""
    if not isinstance(user, str):
        user = str(user)
    if not user.strip():
        user = "用户没有提供输入，请说明你可以做什么。"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def run_loop(
    run_id: str,
    flow: Flow,
    inputs: dict,
    *,
    stop: asyncio.Event,
    resume_from: dict | None = None,
    llm_config: LLMConfig | None = None,
) -> None:
    # deepcopy：DEFAULT_STATE 里的 tool_calls/tool_errors 是 list，
    # 浅拷贝会让两次 run 共享同一个列表（第一次的调用记录泄漏进第二次的 state）
    state = copy.deepcopy(DEFAULT_STATE)
    state.update(copy.deepcopy(resume_from or {}))
    state["variables"] = dict(state.get("variables") or {})
    state["flow_id"] = flow.id
    order = topological_order(flow)
    node_map = {node.id: node for node in flow.nodes}
    delay = max(settings.DEMO_STEP_DELAY, 0.0)
    outputs: dict[str, Any] = dict(state.get("outputs") or {})

    if llm_config is None:
        from app.services.settings_repo import get_llm_config

        llm_config = await get_llm_config()

    limit = settings.MAX_STEPS

    try:
        if state["cursor"] == 0:
            state["variables"] = {**state["variables"], **inputs}
            await update_run(
                run_id,
                status=RunStatus.RUNNING.value,
                started_at=utc_now(),
                state_json=dump_state(state),
            )
            await event_bus.emit(run_id, "run_started", payload={"inputs": inputs})

        for index in range(state["cursor"], len(order)):
            if stop.is_set():
                await finish_cancelled(run_id, state)
                return

            node = node_map.get(order[index])
            if node is None:
                state["cursor"] = index + 1
                continue

            resuming_human = node.type == "human" and state.get("human_pending") == node.id
            if not resuming_human:
                await event_bus.emit(
                    run_id, "node_started", node.id, node_summary(node.type, node.config)
                )
                state["current_node"] = node.id
                await write_state(run_id, state)
                await pause(stop, delay)
                if stop.is_set():
                    await finish_cancelled(run_id, state)
                    return

            completed_payload: dict[str, Any] = {"ok": True}

            if node.type == "input":
                name = str(node.config.get("name") or "query")
                state["variables"].setdefault(name, node.config.get("default", ""))

            elif node.type == "prompt":
                template = str(node.config.get("template") or "")
                state["variables"]["text"] = render_template(template, state["variables"])

            elif node.type == "llm":
                # 步数守卫搬进 _run_llm_node：一次模型调用算一步，
                # Function Calling 的多轮也是多次调用，必须逐轮计数而不是只算一次
                await _run_llm_node(
                    run_id, node, state, llm_config, stop, completed_payload, limit
                )
                if stop.is_set():
                    await finish_cancelled(run_id, state)
                    return

            elif node.type == "output":
                fields = node.config.get("fields") or ["text"]
                if not isinstance(fields, list):
                    fields = [fields]
                outputs = {
                    str(field): state["variables"].get(str(field))
                    for field in fields
                    if str(field) in state["variables"]
                }

            elif node.type == "human":
                if not resuming_human:
                    state["cursor"] = index
                    state["human_pending"] = node.id
                    await write_state(run_id, state)
                    await update_run(run_id, status=RunStatus.WAITING_HUMAN.value)
                    await event_bus.emit(
                        run_id,
                        "human_required",
                        node.id,
                        {
                            "message": node.config.get("message", "是否继续执行？"),
                            "timeout_s": node.config.get("timeout", 300),
                        },
                    )
                    return
                state["human_pending"] = None
                state["variables"]["approved"] = True

            elif node.type == "tool":
                result = await _run_tool_node(run_id, node, state)
                state["variables"]["result"] = result
                completed_payload = {"ok": True, "result": result}

            elif node.type == "mcp":
                emit = extra_nodes.make_emitter(run_id)
                result = await extra_nodes.run_mcp_node(node, state, emit=emit)
                state["variables"]["result"] = result
                completed_payload = {"ok": True, "result": result}

            elif node.type == "knowledge":
                emit = extra_nodes.make_emitter(run_id)
                completed_payload = {
                    "ok": True,
                    **await extra_nodes.run_knowledge_node(node, state, emit=emit),
                }

            elif node.type == "skill":
                completed_payload = {
                    "ok": True,
                    **await extra_nodes.run_skill_node(
                        node, state, stop=stop, llm_config=llm_config
                    ),
                }

            elif node.type in PLACEHOLDER_NODES:
                completed_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": f"{node.type} 节点的执行语义将在后续轮次实装，本轮直通",
                }

            state["cursor"] = index + 1
            state["current_node"] = None
            state["outputs"] = outputs
            await write_state(run_id, state)
            await event_bus.emit(run_id, "node_completed", node.id, completed_payload)

        if stop.is_set():
            await finish_cancelled(run_id, state)
            return

        final_outputs = outputs or {
            "answer": state["variables"].get("text") or state["variables"].get("query") or ""
        }
        await event_bus.emit(
            run_id,
            "run_completed",
            payload={
                "outputs": final_outputs,
                "tokens": state["tokens"],
                "cost": round(state["cost"], 6),
                "steps": state["steps"],
                "maxSteps": limit,
                "model": state["model"],
            },
        )
        await update_run(
            run_id,
            status=RunStatus.SUCCEEDED.value,
            outputs_json=orjson.dumps(final_outputs).decode(),
            state_json=dump_state(state),
            token_usage=state["tokens"],
            cost=round(state["cost"], 6),
            finished_at=utc_now(),
        )

    except StepLimitExceeded as exc:
        message = str(exc)
        await event_bus.emit(
            run_id, "run_failed", payload={"error": message, "code": exc.code}
        )
        await update_run(
            run_id,
            status=RunStatus.FAILED.value,
            error=message,
            state_json=dump_state(state),
            finished_at=utc_now(),
        )
    except LLMError as exc:
        # 把「实际请求了哪个模型 / 是哪个节点 / 怎么改」写进错误里：
        # 节点级 model 会覆盖系统默认，这条规则不写出来，用户只能猜
        model = state.get("model")
        node_id = state.get("current_node")
        override = state.get("model_override")
        if override:
            hint = (
                f"节点 {node_id} 的配置里写死了模型 {override}，节点级模型优先于系统默认；"
                "把它清空就跟随「模型设置」里的默认模型"
            )
        else:
            hint = "本次用的是「模型设置」里的默认模型，请确认它是该网关支持的名称"
        message = f"{exc}（{hint}）"
        await event_bus.emit(
            run_id,
            "run_failed",
            payload={
                "error": message,
                "code": exc.code,
                "model": model,
                "nodeId": node_id,
                "modelFromNode": bool(override),
                "hint": hint,
            },
        )
        await update_run(
            run_id,
            status=RunStatus.FAILED.value,
            error=message,
            state_json=dump_state(state),
            finished_at=utc_now(),
        )
    except tool_runner.ToolError as exc:
        node_id = state.get("current_node")
        message = (
            f"{exc}（节点 {node_id} 的工具调用失败，详见「工具管理」的调用记录；"
            "可先在工具管理里试跑该工具确认参数与超时设置）"
        )
        await event_bus.emit(
            run_id,
            "run_failed",
            payload={"error": message, "code": exc.code, "nodeId": node_id, "toolError": True},
        )
        await update_run(
            run_id,
            status=RunStatus.FAILED.value,
            error=message,
            state_json=dump_state(state),
            finished_at=utc_now(),
        )
    except extra_nodes.NodeError as exc:
        node_id = state.get("current_node")
        await event_bus.emit(
            run_id,
            "run_failed",
            payload={"error": str(exc), "code": exc.code, "nodeId": node_id},
        )
        await update_run(
            run_id,
            status=RunStatus.FAILED.value,
            error=str(exc),
            state_json=dump_state(state),
            finished_at=utc_now(),
        )
    except asyncio.CancelledError:
        await finish_cancelled(run_id, state)
        raise
    except Exception as exc:  # noqa: BLE001 - 引擎异常必须落成事件与终态
        message = f"{type(exc).__name__}: {exc}"
        await event_bus.emit(run_id, "run_failed", payload={"error": message})
        await update_run(
            run_id,
            status=RunStatus.FAILED.value,
            error=message,
            state_json=dump_state(state),
            finished_at=utc_now(),
        )


async def _run_llm_node(
    run_id: str,
    node: FlowNode,
    state: dict,
    llm_config: LLMConfig,
    stop: asyncio.Event,
    completed_payload: dict,
    limit: int,
) -> None:
    """一轮或多轮模型调用。绑了工具时模型自己决定调用，我们把结果回填后再问一次。

    MAX_STEPS 在这里逐轮递增：不用 FC 时只有一次递增（行为和 R2 一致）；
    用了 FC，模型每追问一次就记一步，避免「工具喂结果 → 模型继续要 → 无限循环」。
    """
    model = str(node.config.get("model") or "") or llm_config.model
    # 先记到 state：请求失败时也要能回答「这次到底用了哪个模型、是不是节点覆盖来的」
    state["model"] = model
    state["model_override"] = str(node.config.get("model") or "") or None
    temperature = node.config.get("temperature")
    max_tokens = node.config.get("max_tokens")

    tool_ids = [str(item) for item in (node.config.get("tool_ids") or [])]
    tools = await tool_runner.fc_schemas(tool_ids) if tool_ids else []
    bound_tools = await tool_repo.get_tools_by_ids(tool_ids) if tool_ids else []

    messages = build_messages(node, state["variables"])
    rounds = 0
    answer = ""
    usage: dict | None = None
    reasoning_chars = 0
    finish_reason: str | None = None

    while True:
        if state["steps"] >= limit:
            raise StepLimitExceeded(
                f"超过单次运行的最大步数 MAX_STEPS={limit}，已拦截本次模型调用"
                + (f"（已进行 {rounds} 轮工具调用）" if rounds else "")
            )
        state["steps"] += 1
        rounds += 1

        text, tool_calls, call_usage, round_reasoning_chars, finish_reason_from_round = await _stream_once(
            run_id,
            node,
            state,
            llm_config,
            stop,
            messages,
            model=model or None,
            temperature=float(temperature) if temperature is not None else None,
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            tools=tools or None,
        )
        if call_usage:
            usage = call_usage
        reasoning_chars += round_reasoning_chars
        finish_reason = finish_reason or finish_reason_from_round
        if stop.is_set():
            return

        if not tool_calls:
            answer = text
            break

        # 把「模型想调工具」这件事写进消息历史：OpenAI 协议要求 assistant.tool_calls 与 tool 消息成对
        messages.append(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in tool_calls
                ],
            }
        )
        for call in tool_calls:
            messages.append(
                await _exec_fc_tool(run_id, node, state, call, bound_tools)
            )

    state["variables"]["text"] = answer
    completed_payload.update(
        {
            "model": model,
            "usage": usage
            or {
                "promptTokens": state["prompt_tokens"],
                "completionTokens": state["completion_tokens"],
                "estimated": True,
            },
            "chars": len(answer),
            "reasoningChars": reasoning_chars,
            "finishReason": finish_reason,
            "modelCalls": rounds,
            "toolCalls": rounds - 1 if rounds > 1 else 0,
            "boundTools": [tool.name for tool in bound_tools],
        }
    )
    if not answer.strip() and reasoning_chars:
        # 推理模型把预算花在思维链上时，正文会是空的：别让用户以为是工具/网络坏了
        completed_payload["emptyAnswer"] = True
        completed_payload["hint"] = (
            f"模型把输出预算用在了推理内容上（{reasoning_chars} 字思维链），正文为空；"
            "把 Max tokens 调大，或换一个非推理模型"
        )
    elif not answer.strip() and finish_reason == "length":
        completed_payload["emptyAnswer"] = True
        completed_payload["hint"] = (
            f"模型输出撞到 Max tokens 上限（{max_tokens}）后被截断，正文为空；把 Max tokens 调大再跑"
        )


async def _stream_once(
    run_id: str,
    node: FlowNode,
    state: dict,
    llm_config: LLMConfig,
    stop: asyncio.Event,
    messages: list[dict],
    *,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    tools: list[dict] | None,
) -> tuple[str, list[dict], dict | None, int, str | None]:
    """调一次模型并把 token 帧写进事件流。

    返回 (文本, 工具调用, usage, 思维链字符数, finish_reason)。
    """
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    usage: dict | None = None
    reasoning_chars = 0
    finish_reason: str | None = None

    async for delta in stream_completion(
        llm_config,
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
    ):
        if stop.is_set():
            break
        if delta.text:
            text_parts.append(delta.text)
        if delta.reasoning:
            reasoning_chars += len(delta.reasoning)
        if delta.tool_calls:
            tool_calls = delta.tool_calls
        if delta.finish_reason:
            finish_reason = delta.finish_reason
        if delta.text or delta.reasoning or delta.delta_tokens or delta.cost:
            # 只带用量的校准帧也要进事件流：否则「运行卡片的总 token」与节点统计会对不上
            # reasoning 单独放在 payload.reasoning 里，不计入可见正文
            await event_bus.emit(
                run_id, "token", node.id,
                {
                    "text": delta.text,
                    "reasoning": delta.reasoning or None,
                    "deltaTokens": delta.delta_tokens,
                    "cost": round(delta.cost, 6),
                },
            )
        state["tokens"] += delta.delta_tokens
        state["prompt_tokens"] += delta.delta_prompt_tokens
        state["completion_tokens"] += delta.delta_completion_tokens
        state["cost"] += delta.cost
        if delta.usage:
            usage = delta.usage

    return "".join(text_parts), tool_calls, usage, reasoning_chars, finish_reason


async def _exec_fc_tool(
    run_id: str,
    node: FlowNode,
    state: dict,
    call: dict,
    bound_tools: list,
) -> dict:
    """执行模型要的那次工具调用，返回要回填给模型的 tool 消息。

    工具失败**不**让整个 run 挂掉：把错误作为 tool 结果回给模型，
    它才有机会改参数重试——这正是 Agent 该有的行为。失败细节另外落调用记录。
    """
    name = str(call.get("name") or "")
    raw_args = call.get("arguments") or "{}"
    try:
        args = orjson.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        if not isinstance(args, dict):
            raise tool_runner.ToolArgsError("模型给的 arguments 不是 JSON 对象")
    except orjson.JSONDecodeError as exc:
        args = {}
        error_text = f"参数不是合法 JSON：{exc}"
        await event_bus.emit(
            run_id, "tool_call", node.id,
            {"tool": name, "args": raw_args, "callId": call.get("id"), "source": "llm"},
        )
        await event_bus.emit(
            run_id, "tool_result", node.id,
            {"tool": name, "ok": False, "error": error_text, "callId": call.get("id")},
        )
        return {"role": "tool", "tool_call_id": call.get("id"), "content": f"ERROR: {error_text}"}

    await event_bus.emit(
        run_id, "tool_call", node.id,
        {"tool": name, "args": args, "callId": call.get("id"), "source": "llm"},
    )
    try:
        tool = await tool_runner.resolve_by_name(bound_tools, name)
        invocation = await tool_runner.invoke(
            tool, args, run_id=run_id, node_id=node.id
        )
    except tool_runner.ToolError as exc:
        await event_bus.emit(
            run_id, "tool_result", node.id,
            {"tool": name, "ok": False, "error": str(exc), "code": exc.code, "callId": call.get("id")},
        )
        state.setdefault("tool_errors", []).append({"tool": name, "error": str(exc)})
        return {"role": "tool", "tool_call_id": call.get("id"), "content": f"ERROR: {exc}"}

    content = (
        invocation.result
        if isinstance(invocation.result, str)
        else orjson.dumps(invocation.result).decode()
    )
    await event_bus.emit(
        run_id, "tool_result", node.id,
        {
            "tool": name,
            "ok": True,
            "result": invocation.result,
            "latencyMs": invocation.latency_ms,
            "attempts": invocation.attempts,
            "idemHit": invocation.idem_hit,
            "callId": call.get("id"),
        },
    )
    state.setdefault("tool_calls", []).append(
        {
            "tool": name,
            "args": args,
            "status": invocation.status,
            "attempts": invocation.attempts,
            "latencyMs": invocation.latency_ms,
            "idemHit": invocation.idem_hit,
        }
    )
    return {"role": "tool", "tool_call_id": call.get("id"), "content": content}


async def _run_tool_node(run_id: str, node: FlowNode, state: dict) -> str:
    """tool 节点：参数模板插值 → 强校验 → 带超时重试幂等地执行。

    和 FC 的差别：这里是用户写死的固定调用，失败了就让 run 失败（错误要显眼），
    而不是悄悄回给模型——用户没有模型可以替他重试。
    """
    tool_id = str(node.config.get("tool_id") or "")
    if not tool_id:
        raise tool_runner.ToolError("tool 节点未选择工具", code="TOOL_NOT_CONFIGURED")

    tool = await _load_tool_or_fail(tool_id)
    args = _parse_args_template(str(node.config.get("args_template") or "{}"), state["variables"])

    await event_bus.emit(
        run_id, "tool_call", node.id,
        {"tool": tool.name, "toolId": tool.id, "args": args, "source": "node"},
    )
    invocation = await tool_runner.invoke(tool, args, run_id=run_id, node_id=node.id)
    await event_bus.emit(
        run_id, "tool_result", node.id,
        {
            "tool": tool.name,
            "ok": True,
            "result": invocation.result,
            "latencyMs": invocation.latency_ms,
            "attempts": invocation.attempts,
            "idemHit": invocation.idem_hit,
        },
    )
    state.setdefault("tool_calls", []).append(
        {
            "tool": tool.name,
            "args": args,
            "status": invocation.status,
            "attempts": invocation.attempts,
            "latencyMs": invocation.latency_ms,
            "idemHit": invocation.idem_hit,
        }
    )
    return (
        invocation.result
        if isinstance(invocation.result, str)
        else orjson.dumps(invocation.result).decode()
    )


async def _load_tool_or_fail(tool_id: str):
    try:
        return await tool_repo.get_tool(tool_id)
    except tool_repo.ToolNotFound as exc:
        raise tool_runner.ToolError(str(exc), code="TOOL_NOT_FOUND") from exc


def _parse_args_template(template: str, variables: dict) -> dict:
    rendered = render_template(template, variables)
    try:
        parsed = orjson.loads(rendered or "{}")
    except orjson.JSONDecodeError as exc:
        raise tool_runner.ToolArgsError(
            f"参数模板不是合法 JSON（插值后为 {rendered[:120]}）：{exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise tool_runner.ToolArgsError("参数模板必须是一个 JSON 对象")
    return parsed


async def resume_loop(run_id: str, flow: Flow, stop: asyncio.Event) -> None:
    run = await load_run(run_id)
    await run_loop(run_id, flow, {}, stop=stop, resume_from=run.state)
