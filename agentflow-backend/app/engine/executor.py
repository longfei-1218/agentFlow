"""执行器选择：一处决定「这次运行走哪个引擎」。

RUNNER=demo  -> 确定性演示（不联网、可离线回归）
RUNNER=loop  -> R2 手写 Agent Loop（线性拓扑，llm 节点真调模型）
RUNNER=graph -> R4 LangGraph（默认：条件边路由、有界循环、interrupt + checkpointer 续跑）
"""
import asyncio

from app.config import settings
from app.engine.demo_runner import resume_demo_flow, run_demo_flow
from app.engine.loop import run_loop
from app.models.flow import Flow
from app.services.run_repo import load_run

VALID_RUNNERS = {"demo", "loop", "graph"}
DEFAULT_RUNNER = "graph"


def runner_name() -> str:
    name = (settings.RUNNER or DEFAULT_RUNNER).strip().lower()
    return name if name in VALID_RUNNERS else DEFAULT_RUNNER


async def start(run_id: str, flow: Flow, inputs: dict, *, stop: asyncio.Event) -> None:
    name = runner_name()
    if name == "demo":
        await run_demo_flow(run_id, flow, inputs, stop=stop)
        return
    if name == "loop":
        await run_loop(run_id, flow, inputs, stop=stop)
        return

    from app.engine.graph_runner import run_graph

    await run_graph(run_id, flow, inputs, stop=stop)


async def resume(run_id: str, flow: Flow, *, stop: asyncio.Event) -> None:
    name = runner_name()
    if name == "demo":
        await resume_demo_flow(run_id, flow, stop=stop)
        return
    if name == "loop":
        run = await load_run(run_id)
        await run_loop(run_id, flow, {}, stop=stop, resume_from=run.state)
        return

    from app.engine.graph_runner import resume_graph

    await resume_graph(run_id, flow, stop=stop)
