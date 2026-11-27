"""LangGraph 执行器（R4）：把 DSL 编译成 StateGraph，用 checkpointer 真中断/续跑。

为什么换掉手写循环：R2 的 loop 只能线性跑拓扑序，
- `condition` 没法「只走一条分支」——拓扑序会把两条分支都跑一遍；
- `loop` 没法回到上游——线性游标不往回走；
- `human` 的续跑靠「把 cursor 写进 state 再重放」，中间状态是咱们自己拼的，
  节点重入、并发写、断点恢复都得自己保证。

换成 StateGraph 之后这三件事都由图引擎负责：条件边做路由、环由 superstep 驱动、
`interrupt()` + checkpointer 把暂停点落在真实的执行位置上。

state 结构仍然是 R1–R3 的 `data` 字典（variables/tokens/steps/tool_calls…），
这样事件协议、运行面板、回放、评测采集全都不用改；图里每个节点读改写同一个 dict。

已知取舍：
- 同一节点多条普通出边会 fan-out（并行执行），两条分支共享同一个 `data` 字典，
  互相覆盖的风险由使用方承担；条件分支走的是互斥条件边，不存在这个问题。
- mcp / skill / knowledge 仍是直通占位（R5）。
"""
import asyncio
import copy
from collections import defaultdict
from typing import Any, TypedDict

import orjson
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.engine.agent_runner import AgentRunError, run_agent
from app.engine import expr
from app.engine.common import (
    DEFAULT_STATE,
    dump_state,
    finish_cancelled,
    node_summary,
    pause,
    write_state,
)
from app.engine.loop import StepLimitExceeded
from app.models.agent import AgentVariable
from app.models.flow import Flow, FlowNode
from app.models.run import RunStatus
from app.services import agent_service, flow_vars
from app.services.agent_repo import AgentNotFound, get_agent
from app.services.event_bus import event_bus, utc_now
from app.services.llm import LLMConfig, LLMError
from app.services.run_repo import load_run, update_run

ENGINE_NAME = "langgraph"
# R5 起三类外部资源节点都已实装；这里保留一个空集合，是为了让「占位语义」的扩展点不消失
PLACEHOLDER_NODES: set[str] = set()
_CONDITIONAL_TYPES = {"condition", "loop"}


class GraphState(TypedDict, total=False):
    """只有一个字段：我们的运行状态字典。没有 reducer = 每步整体覆盖。"""

    data: dict


class GraphCancelled(RuntimeError):
    """取消令牌被置位时从节点里抛出，交给外层统一收尾。"""


class HumanPause(Exception):
    """human 节点停在这里等审批。

    为什么不用官方的 `interrupt()`：它内部走 `get_config()` 读 contextvar，而
    langchain-core 在 Python < 3.11 上没有 `asyncio.create_task(context=...)`，
    异步节点的 config 上下文根本进不去，调用直接 RuntimeError（langgraph 0.2/0.3
    在 3.10 上都能复现）。这里改成「抛异常暂停 + aupdate_state 后 ainvoke(None) 续跑」，
    checkpoint 仍在，语义一样是真中断，只是把「暂停点」显式表达成一次异常。
    """

    def __init__(self, node_id: str) -> None:
        super().__init__(f"等待人工审批: {node_id}")
        self.node_id = node_id


def _db_path() -> str:
    """LangGraph checkpoint 独立一个库：和业务表共用会互相抢 SQLite 写锁。"""
    from pathlib import Path

    path = Path(settings.DATABASE_PATH)
    return str(path.with_name(f"{path.stem}_checkpoints{path.suffix}"))


def _recursion_limit(flow: Flow) -> int:
    """superstep 上限。环要算进去：每轮循环体节点数 * 最大轮次。"""
    base = 25 + 2 * len(flow.nodes)
    for node in flow.nodes:
        if node.type == "loop":
            rounds = int(node.config.get("max_rounds") or 3)
            base += rounds * max(1, len(flow.nodes))
    return min(base, 500)


def build_graph(
    flow: Flow,
    *,
    run_id: str,
    stop: asyncio.Event,
    llm_config: LLMConfig | None,
    limit: int,
    resume_node: str | None = None,
    emit_events: bool = True,
    persist_state: bool = True,
) -> StateGraph:
    """emit_events / persist_state 默认都开；子流程内联执行时两个都关（见 engine/subflow.py）。"""
    graph = StateGraph(GraphState)
    nodes = {node.id: node for node in flow.nodes}

    out_edges: dict[str, list] = defaultdict(list)
    indegree: dict[str, int] = {node.id: 0 for node in flow.nodes}
    for edge in flow.edges:
        if edge.source in nodes and edge.target in nodes:
            out_edges[edge.source].append(edge)
            indegree[edge.target] += 1

    for node in flow.nodes:
        graph.add_node(
            node.id,
            _make_node_action(
                node,
                run_id=run_id,
                stop=stop,
                llm_config=llm_config,
                limit=limit,
                resume_node=resume_node,
                emit_events=emit_events,
                persist_state=persist_state,
            ),
        )

    # 入口固定走 start（校验保证有且仅有一个）
    starts = [node.id for node in flow.nodes if node.type == "start"]
    entries = starts or [flow.nodes[0].id]
    for entry in entries:
        graph.add_edge(START, entry)

    for node in flow.nodes:
        edges = out_edges.get(node.id, [])

        if node.type == "condition":
            mapping = {"true": _handle_target(edges, "true"), "false": _handle_target(edges, "false")}
            graph.add_conditional_edges(
                node.id,
                lambda state, node_id=node.id: _route_branch(state, node_id, "false"),
                mapping,
            )
            continue

        if node.type == "loop":
            mapping = {"body": _handle_target(edges, "body"), "done": _handle_target(edges, "done")}
            graph.add_conditional_edges(
                node.id,
                lambda state, node_id=node.id: _route_branch(state, node_id, "done"),
                mapping,
            )
            continue

        if not edges:
            graph.add_edge(node.id, END)
            continue

        for edge in edges:
            # 回边（目标本身是 loop 节点）照样连：有界循环靠 loop 的条件边决定要不要回来
            graph.add_edge(node.id, edge.target)

    return graph


def _cfg(config: dict, snake: str, camel: str | None = None, default=None):
    if snake in config:
        return config.get(snake)
    if camel and camel in config:
        return config.get(camel)
    return default


def _handle_target(edges: list, handle: str) -> str:
    for edge in edges:
        if (edge.source_handle or "") == handle:
            return edge.target
    return END


def _route_branch(state: GraphState, node_id: str, fallback: str) -> str:
    branch = (state.get("data") or {}).get("branch", {}).get(node_id)
    return branch or fallback


def _make_node_action(
    node: FlowNode,
    *,
    run_id: str,
    stop: asyncio.Event,
    llm_config: LLMConfig | None,
    limit: int,
    resume_node: str | None = None,
    emit_events: bool = True,
    persist_state: bool = True,
):
    """把一类节点包成「发事件 → 执行 → 写 state → 发事件」的图节点。

    事件协议与 loop 完全一致，前端不需要知道这次是谁在跑。

    `resume_node` 由外层从 run.state 里读出来传进来（而不是信 checkpoint 里的
    human_pending）：续跑时 LangGraph 会**从头重跑**被 interrupt 的那个节点，
    不显式传这个标记就会重复发一次 node_started。
    """

    async def action(state: GraphState) -> dict:
        data = state["data"]
        resuming_human = node.type == "human" and node.id == resume_node

        if stop.is_set():
            raise GraphCancelled()

        if not resuming_human:
            if emit_events:
                await event_bus.emit(
                    run_id, "node_started", node.id, node_summary(node.type, node.config)
                )
            data["current_node"] = node.id
            if persist_state:
                await write_state(run_id, data)
            await pause(stop, max(settings.DEMO_STEP_DELAY, 0.0))
            if stop.is_set():
                raise GraphCancelled()

        completed: dict[str, Any] = {"ok": True, "engine": ENGINE_NAME}

        if node.type == "start":
            start_values: dict[str, Any] = {}
            for index, raw in enumerate(_cfg(node.config, "variables", "variables", []) or []):
                try:
                    var = raw if isinstance(raw, AgentVariable) else AgentVariable.model_validate(raw)
                except Exception as exc:  # noqa: BLE001
                    raise AgentRunError(
                        f"start 变量 {index} 不合法: {exc}", code="FLOW_VAR_INVALID"
                    ) from exc
                if var.key in data["variables"]:
                    value = data["variables"][var.key]
                elif var.required:
                    raise AgentRunError(
                        f"流程必选输入 {var.key} 没有提供", code="FLOW_VAR_UNBOUND"
                    )
                else:
                    value = var.default if var.default is not None else ""
                try:
                    start_values[var.key] = agent_service.coerce_value(value, var.type, var.key)
                except ValueError as exc:
                    raise AgentRunError(str(exc), code="FLOW_VAR_INVALID") from exc
            data["start"] = start_values
            data["variables"].update(start_values)
            completed["variables"] = start_values

        elif node.type == "agent":
            agent_id = str(_cfg(node.config, "agent_id", "agentId", "") or "")
            try:
                agent = await get_agent(agent_id)
            except AgentNotFound as exc:
                raise AgentRunError(f"Agent 不存在: {agent_id}", code="AGENT_NOT_FOUND") from exc
            input_map = _cfg(node.config, "input_map", "inputMap", {}) or {}
            context = flow_vars.flow_context(data)
            mapped: dict[str, Any] = {}
            for key, template in input_map.items():
                try:
                    mapped[key] = flow_vars.render_value(template, context)
                except LookupError as exc:
                    raise AgentRunError(
                        f"inputMap.{key} 引用的变量不存在: {template}",
                        code="FLOW_VAR_UNBOUND",
                    ) from exc

            async def on_agent_event(event_type: str, payload: dict) -> None:
                if emit_events:
                    await event_bus.emit(
                        run_id, event_type, node.id, {**payload, "agentId": agent.id}
                    )

            try:
                result = await run_agent(
                    agent,
                    mapped,
                    llm_config=llm_config,
                    emit=on_agent_event,
                    stop=lambda: stop.is_set(),
                )
            except AgentRunError as exc:
                if exc.code == "RUN_CANCELLED":
                    raise GraphCancelled() from exc
                raise
            data.setdefault("nodes", {})[node.id] = {
                "agentId": agent.id,
                "output": result.outputs,
                "text": result.text,
            }
            data["tokens"] += result.tokens
            data["cost"] += result.cost
            data["steps"] += result.steps
            data["model"] = result.model
            data["tool_calls"].extend(result.tool_calls)
            completed.update(
                {
                    "agentId": agent.id,
                    "output": result.outputs,
                    "text": result.text,
                    "tokens": result.tokens,
                    "cost": result.cost,
                    "steps": result.steps,
                }
            )

        elif node.type == "end":
            raw_outputs = _cfg(node.config, "outputs", "outputs", []) or []
            context = flow_vars.flow_context(data)
            outputs: dict[str, Any] = {}
            if isinstance(raw_outputs, dict):
                for key, template in raw_outputs.items():
                    try:
                        outputs[key] = flow_vars.render_value(template, context)
                    except LookupError as exc:
                        raise AgentRunError(
                            f"end.outputs.{key} 引用的变量不存在: {template}",
                            code="FLOW_VAR_UNBOUND",
                        ) from exc
            elif isinstance(raw_outputs, list):
                for address in raw_outputs:
                    try:
                        value = flow_vars.render_value("{{" + str(address) + "}}", context)
                    except LookupError as exc:
                        raise AgentRunError(
                            f"end.outputs 引用的变量不存在: {address}",
                            code="FLOW_VAR_UNBOUND",
                        ) from exc
                    key = str(address).split(".")[-1]
                    outputs[key] = value
            if not outputs:
                last_text = ""
                for item in reversed(list(data.get("nodes", {}).values())):
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        last_text = item["text"]
                        break
                outputs = {"text": last_text}
            data["outputs"] = outputs
            completed["outputs"] = outputs

        elif node.type == "condition":
            try:
                passed, rendered = expr.evaluate_condition(
                    str(_cfg(node.config, "expression", "expression", "") or ""),
                    flow_vars.flow_context(data),
                )
            except expr.ConditionError as exc:
                raise expr.ConditionError(f"{node.id}: {exc}") from exc
            data.setdefault("branch", {})[node.id] = "true" if passed else "false"
            data["variables"]["condition_result"] = passed
            completed.update({"branch": "true" if passed else "false", "expression": rendered})

        elif node.type == "loop":
            rounds = int(data.setdefault("loop_rounds", {}).get(node.id, 0))
            max_rounds = int(_cfg(node.config, "max_rounds", "maxRounds", 3) or 3)

            should_exit = rounds >= max_rounds
            exit_expression = str(
                _cfg(node.config, "exit_condition", "exitCondition", "") or ""
            ).strip()
            if not should_exit and exit_expression:
                try:
                    should_exit, rendered_exit = expr.evaluate_condition(
                        exit_expression, flow_vars.flow_context(data)
                    )
                    completed["exitExpression"] = rendered_exit
                except expr.ConditionError as exc:
                    raise expr.ConditionError(f"{node.id}: {exc}") from exc

            if not should_exit:
                rounds += 1
                data["loop_rounds"][node.id] = rounds
            data["variables"]["loop_round"] = rounds

            branch = "done" if should_exit else "body"
            data.setdefault("branch", {})[node.id] = branch
            completed.update({"round": rounds, "maxRounds": max_rounds, "branch": branch})

        elif node.type == "human":
            message = str(_cfg(node.config, "message", "message", "是否继续执行？") or "")
            timeout = _cfg(node.config, "timeout", "timeout", 300)
            if not resuming_human:
                data["human_pending"] = node.id
                if persist_state:
                    await write_state(run_id, data)
                    await update_run(run_id, status=RunStatus.WAITING_HUMAN.value)
                if emit_events:
                    await event_bus.emit(
                        run_id,
                        "human_required",
                        node.id,
                        {"message": message, "timeout_s": timeout, "engine": ENGINE_NAME},
                    )
                raise HumanPause(node.id)

            approved = bool(data.get("human_approved", True))
            data["human_pending"] = None
            data["variables"]["approved"] = approved
            completed["approved"] = approved

        data["current_node"] = None
        if persist_state:
            await write_state(run_id, data)
        if emit_events:
            await event_bus.emit(run_id, "node_completed", node.id, completed)
        return {"data": data}

    return action


async def run_graph(
    run_id: str,
    flow: Flow,
    inputs: dict,
    *,
    stop: asyncio.Event,
    llm_config: LLMConfig | None = None,
) -> None:
    data = copy.deepcopy(DEFAULT_STATE)
    data["variables"] = {**(data.get("variables") or {}), **inputs}
    data["start"] = dict(inputs)
    data["nodes"] = {}
    data["flow_id"] = flow.id

    await update_run(
        run_id,
        status=RunStatus.RUNNING.value,
        started_at=utc_now(),
        state_json=dump_state(data),
    )
    await event_bus.emit(
        run_id,
        "run_started",
        payload={
            "inputs": inputs,
            "engine": ENGINE_NAME,
            "versionMode": (
                "published"
                if flow.published_hash and flow.draft_hash == flow.published_hash
                else "draft"
            ),
        },
    )

    if llm_config is None:
        from app.services.settings_repo import get_llm_config

        llm_config = await get_llm_config()

    try:
        await _drive(run_id, flow, data, stop=stop, llm_config=llm_config, resume=False)
    except GraphCancelled:
        await finish_cancelled(run_id, data)
    except Exception as exc:  # noqa: BLE001
        await _fail(run_id, data, exc)


async def resume_graph(run_id: str, flow: Flow, *, stop: asyncio.Event) -> None:
    run = await load_run(run_id)
    data = copy.deepcopy(run.state or copy.deepcopy(DEFAULT_STATE))
    data.setdefault("variables", {})
    data.setdefault("start", {})
    data.setdefault("nodes", {})
    data.setdefault("outputs", {})
    data["flow_id"] = flow.id
    # API 只在 approved=True 时才会走到这里（拒绝走 cancel），这里显式记一笔给 human 节点读
    data["human_approved"] = True

    try:
        await _drive(run_id, flow, data, stop=stop, llm_config=None, resume=True)
    except GraphCancelled:
        await finish_cancelled(run_id, data)
    except Exception as exc:  # noqa: BLE001
        await _fail(run_id, data, exc)


async def _drive(
    run_id: str,
    flow: Flow,
    data: dict,
    *,
    stop: asyncio.Event,
    llm_config: LLMConfig | None,
    resume: bool,
) -> None:
    if llm_config is None:
        from app.services.settings_repo import get_llm_config

        llm_config = await get_llm_config()

    limit = settings.MAX_STEPS

    async with AsyncSqliteSaver.from_conn_string(_db_path()) as saver:
        builder = build_graph(
            flow,
            run_id=run_id,
            stop=stop,
            llm_config=llm_config,
            limit=limit,
            resume_node=(data.get("human_pending") if resume else None),
        )
        compiled = builder.compile(checkpointer=saver)
        config = {
            "configurable": {"thread_id": run_id},
            "recursion_limit": _recursion_limit(flow),
        }

        if resume:
            snapshot = await compiled.aget_state(config)
            if not snapshot or not snapshot.next:
                raise RuntimeError(
                    "找不到该运行的图检查点（可能服务重启时数据库被换过），无法用 LangGraph 续跑；"
                    "可在运行历史里重新发起一次"
                )
            # 把自己落库的 state（含 human_pending / 之前节点写的变量）灌回图里
            await compiled.aupdate_state(config, {"data": data})

        payload: dict[str, Any] | None = None if resume else {"data": data}
        try:
            result = await compiled.ainvoke(payload, config)
        except HumanPause:
            # 节点已把 waiting_human、human_required、state 写过了；这里只需要把最新 state 落库
            await write_state(run_id, data)
            return

        final_data = dict((result or {}).get("data") or data)
        data.clear()
        data.update(final_data)

    outputs = data.get("outputs") or {
        "answer": data["variables"].get("text") or data["variables"].get("query") or ""
    }
    await event_bus.emit(
        run_id,
        "run_completed",
        payload={
            "outputs": outputs,
            "tokens": data["tokens"],
            "cost": round(data["cost"], 6),
            "steps": data["steps"],
            "maxSteps": limit,
            "model": data["model"],
            "engine": ENGINE_NAME,
        },
    )
    await update_run(
        run_id,
        status=RunStatus.SUCCEEDED.value,
        outputs_json=orjson.dumps(outputs).decode(),
        state_json=dump_state(data),
        token_usage=data["tokens"],
        cost=round(data["cost"], 6),
        finished_at=utc_now(),
    )


async def _fail(run_id: str, data: dict, exc: Exception) -> None:
    """把各类失败翻译成前端能读懂的事件 + 终态。文案规则与 loop 保持一致。"""
    node_id = data.get("current_node")

    if isinstance(exc, StepLimitExceeded):
        code = exc.code
        message = str(exc)
        extra: dict[str, Any] = {"code": code}
    elif isinstance(exc, expr.ConditionError):
        code = exc.code
        message = f"{exc}（检查「分支/循环」节点的表达式，变量要先由上游节点写入）"
        extra = {"code": code, "nodeId": node_id}
    elif isinstance(exc, GraphRecursionError):
        message = (
            "图执行的 superstep 超过上限：多半是 loop 节点的回边没有在 max_rounds 内退出，"
            "或退出条件永远为假"
        )
        extra = {"code": "GRAPH_RECURSION_LIMIT", "nodeId": node_id}
    elif isinstance(exc, LLMError):
        model = data.get("model")
        override = data.get("model_override")
        if override:
            hint = (
                f"节点 {node_id} 的配置里写死了模型 {override}，节点级模型优先于系统默认；"
                "把它清空就跟随「模型设置」里的默认模型"
            )
        else:
            hint = "本次用的是「模型设置」里的默认模型，请确认它是该网关支持的名称"
        message = f"{exc}（{hint}）"
        extra = {
            "code": exc.code,
            "model": model,
            "nodeId": node_id,
            "modelFromNode": bool(override),
            "hint": hint,
        }
    elif isinstance(exc, AgentRunError):
        message = str(exc)
        extra = {"code": exc.code, "nodeId": node_id, "agentError": True}
    else:
        message = f"{type(exc).__name__}: {exc}"
        extra = {}

    payload = {"error": message, "engine": ENGINE_NAME, **extra}
    await event_bus.emit(run_id, "run_failed", payload=payload)
    await update_run(
        run_id,
        status=RunStatus.FAILED.value,
        error=message,
        state_json=dump_state(data),
        finished_at=utc_now(),
    )
