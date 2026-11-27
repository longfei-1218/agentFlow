"""单 Agent Run：把 AgentRunner 接进现有 runs/SSE 体系。"""
import asyncio
import uuid

import orjson

from app.database import db
from app.engine.agent_runner import AgentRunError, run_agent
from app.models.agent import Agent, AgentCreate
from app.models.run import Run, RunStatus
from app.services.agent_service import normalize_variables
from app.services.event_bus import event_bus, utc_now
from app.services.run_manager import run_manager
from app.services.run_repo import update_run


async def create_agent_run(
    agent: Agent,
    variables: dict,
    *,
    conversation_id: str | None = None,
) -> Run:
    run = Run(
        id=f"run_{uuid.uuid4().hex[:8]}",
        target_type="agent",
        target_id=agent.id,
        status=RunStatus.PENDING,
        inputs=variables,
        started_at=utc_now(),
        conversation_id=conversation_id,
    )
    await db.execute(
        "INSERT INTO runs (id, target_type, target_id, flow_version, status, inputs_json, "
        "state_json, token_usage, cost, started_at, conversation_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.id,
            run.target_type,
            run.target_id,
            1,
            run.status.value,
            orjson.dumps(variables).decode(),
            "{}",
            0,
            0.0,
            run.started_at,
            conversation_id,
        ),
    )
    return run


async def start_agent_run(run_id: str, agent: Agent, variables: dict) -> None:
    await update_run(
        run_id, status=RunStatus.RUNNING.value, started_at=utc_now()
    )
    await event_bus.emit(
        run_id,
        "run_started",
        payload={"agentId": agent.id, "inputs": variables, "engine": "agent"},
    )

    async def emit(event_type: str, payload: dict) -> None:
        await event_bus.emit(run_id, event_type, "agent", {**payload, "agentId": agent.id})

    try:
        await event_bus.emit(
            run_id, "node_started", "agent", {"agentId": agent.id, "name": agent.name}
        )
        result = await run_agent(
            agent,
            variables,
            emit=emit,
            stop=lambda: run_manager.is_cancelled(run_id),
        )
    except AgentRunError as exc:
        await event_bus.emit(
            run_id,
            "run_failed",
            "agent",
            {"error": str(exc), "code": exc.code, "agentId": agent.id},
        )
        cancelled = exc.code == "RUN_CANCELLED"
        await update_run(
            run_id,
            status=(RunStatus.CANCELLED.value if cancelled else RunStatus.FAILED.value),
            error=str(exc),
            finished_at=utc_now(),
        )
        return
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        await event_bus.emit(
            run_id, "run_failed", "agent", {"error": message, "agentId": agent.id}
        )
        await update_run(
            run_id, status=RunStatus.FAILED.value, error=message, finished_at=utc_now()
        )
        return

    await event_bus.emit(
        run_id,
        "node_completed",
        "agent",
        {
            "agentId": agent.id,
            "output": result.outputs,
            "text": result.text,
            "tokens": result.tokens,
            "cost": result.cost,
        },
    )
    await event_bus.emit(
        run_id,
        "run_completed",
        payload={
            "agentId": agent.id,
            "outputs": result.outputs,
            "text": result.text,
            "tokens": result.tokens,
            "cost": round(result.cost, 6),
            "steps": result.steps,
            "model": result.model,
            "engine": "agent",
        },
    )
    await update_run(
        run_id,
        status=RunStatus.SUCCEEDED.value,
        outputs_json=orjson.dumps(result.outputs).decode(),
        token_usage=result.tokens,
        cost=round(result.cost, 6),
        finished_at=utc_now(),
    )
