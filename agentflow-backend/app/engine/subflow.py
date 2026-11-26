"""子流程内联执行（R5）：把另一个 Flow 当成一次「大号函数调用」跑完。

为什么内联而不是再开一个 run：
- 子流程的中间事件不该混进父 run 的事件流，否则时间轴会乱；
- 父流程要拿到的是「子流程 outputs + 花了多少 token」，这本来就是调用方的账；
- 所以这里用 MemorySaver 单独编译一张图，不落 runs 表、不发事件。

代价：子流程不可在「运行历史」里单独回放。等需要单独回放时，再给它开 run 记录。
"""
import copy
import uuid

from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.engine.common import DEFAULT_STATE


async def run_subflow(
    flow,
    inputs: dict,
    *,
    stop,
    llm_config,
    parent_chain: list[str] | None = None,
) -> dict:
    """同步跑完子流程，返回 outputs 与用量统计。"""
    # 延迟导入：graph_runner 依赖 loop，loop 又依赖 extra_nodes，顶层导入会成环
    from app.engine.graph_runner import _recursion_limit, build_graph

    data = copy.deepcopy(DEFAULT_STATE)
    data["variables"] = {**data["variables"], **inputs}
    data["flow_id"] = flow.id
    data["skill_chain"] = list(parent_chain or [])

    builder = build_graph(
        flow,
        run_id="",
        stop=stop,
        llm_config=llm_config,
        limit=settings.MAX_STEPS,
        emit_events=False,
        persist_state=False,
    )
    compiled = builder.compile(checkpointer=MemorySaver())
    config = {
        "configurable": {"thread_id": f"subflow-{flow.id}-{uuid.uuid4().hex[:8]}"},
        "recursion_limit": _recursion_limit(flow),
    }

    result = await compiled.ainvoke({"data": data}, config)
    final = dict((result or {}).get("data") or data)
    variables = final.get("variables") or {}
    outputs = final.get("outputs") or {
        "text": variables.get("text"),
        "result": variables.get("result"),
    }
    outputs = {key: value for key, value in outputs.items() if value is not None}

    return {
        "outputs": outputs,
        "variables": variables,
        "steps": int(final.get("steps") or 0),
        "tokens": int(final.get("tokens") or 0),
        "prompt_tokens": int(final.get("prompt_tokens") or 0),
        "completion_tokens": int(final.get("completion_tokens") or 0),
        "cost": float(final.get("cost") or 0.0),
    }
