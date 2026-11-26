"""执行器选择：一处决定「这次运行走演示桩还是真模型」。

RUNNER=demo -> 确定性演示（不联网、可离线回归）
RUNNER=loop -> 手写 Agent Loop（llm 节点真调模型）
"""
import asyncio

from app.config import settings
from app.engine.demo_runner import resume_demo_flow, run_demo_flow
from app.engine.loop import resume_loop, run_loop
from app.models.flow import Flow
from app.services.run_repo import load_run

VALID_RUNNERS = {"demo", "loop"}


def runner_name() -> str:
    name = (settings.RUNNER or "loop").strip().lower()
    return name if name in VALID_RUNNERS else "loop"


async def start(run_id: str, flow: Flow, inputs: dict, *, stop: asyncio.Event) -> None:
    if runner_name() == "demo":
        await run_demo_flow(run_id, flow, inputs, stop=stop)
        return
    await run_loop(run_id, flow, inputs, stop=stop)


async def resume(run_id: str, flow: Flow, *, stop: asyncio.Event) -> None:
    if runner_name() == "demo":
        await resume_demo_flow(run_id, flow, stop=stop)
        return
    run = await load_run(run_id)
    await run_loop(run_id, flow, {}, stop=stop, resume_from=run.state)
