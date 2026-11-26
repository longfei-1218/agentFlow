"""手写 Agent Loop：拓扑执行 + 真实模型流式 + 步数守卫。

与 demo_runner 的区别只有一个：llm 节点真的调模型。其余（取消、审批中断、续跑、
事件协议、state 快照格式）保持一致，这样前端不需要区分是演示还是真实运行。

MAX_STEPS 的语义：一次 LLM 调用算一步。它防的是「模型被工具喂了结果之后无限自我循环」，
不是「节点数量上限」——线性的 10 个节点流程不该因为 MAX_STEPS=8 就被拦。
"""
import asyncio
from typing import Any

import orjson

from app.config import settings
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
from app.services.event_bus import event_bus, utc_now
from app.services.llm import LLMConfig, LLMError, stream_completion
from app.services.run_repo import load_run, update_run

# R2 只把拓扑里的「线性可执行」部分跑通；这几类节点的执行语义留到 R3/R4/R5，
# 先按直通占位处理，既不假装成功，也不让用户以为它们已经生效。
PLACEHOLDER_NODES = {"condition", "loop", "mcp", "skill", "knowledge"}


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
    state = {**DEFAULT_STATE, **(resume_from or {})}
    state["variables"] = dict(state.get("variables") or {})
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
                if state["steps"] >= limit:
                    raise StepLimitExceeded(
                        f"超过单次运行的最大步数 MAX_STEPS={limit}，已拦截本次模型调用"
                    )
                state["steps"] += 1
                await _run_llm_node(
                    run_id, node, state, llm_config, stop, completed_payload
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
                # R3 接管工具执行；这一版只把「调用点」出现在事件流里，结果标明是占位
                tool_id = str(node.config.get("tool_id") or "unspecified_tool")
                await event_bus.emit(
                    run_id, "tool_call", node.id,
                    {"name": tool_id, "args": state["variables"]},
                )
                result = f"工具 {tool_id} 尚未注册（R3 工具层实装后可执行）"
                await event_bus.emit(run_id, "tool_result", node.id, {"result": result, "stub": True})
                state["variables"]["result"] = result
                completed_payload = {"ok": True, "stub": True}

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
) -> None:
    """流式调用并逐帧写事件；tokens/cost 以 provider 的校准帧为准。"""
    model = str(node.config.get("model") or "") or llm_config.model
    # 先记到 state：请求失败时也要能回答「这次到底用了哪个模型、是不是节点覆盖来的」
    state["model"] = model
    state["model_override"] = str(node.config.get("model") or "") or None
    temperature = node.config.get("temperature")
    max_tokens = node.config.get("max_tokens")
    messages = build_messages(node, state["variables"])

    text_parts: list[str] = []
    usage: dict | None = None

    async for delta in stream_completion(
        llm_config,
        messages,
        model=model or None,
        temperature=float(temperature) if temperature is not None else None,
        max_tokens=int(max_tokens) if max_tokens is not None else None,
    ):
        if stop.is_set():
            break
        if delta.text:
            text_parts.append(delta.text)
        if delta.text or delta.delta_tokens or delta.cost:
            # 只带用量的校准帧也要进事件流：否则「运行卡片的总 token」与节点统计会对不上
            await event_bus.emit(
                run_id, "token", node.id,
                {
                    "text": delta.text,
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

    answer = "".join(text_parts)
    state["variables"]["text"] = answer
    state["model"] = model
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
        }
    )


async def resume_loop(run_id: str, flow: Flow, stop: asyncio.Event) -> None:
    run = await load_run(run_id)
    await run_loop(run_id, flow, {}, stop=stop, resume_from=run.state)
