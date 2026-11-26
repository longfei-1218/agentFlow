"""测试辅助：构造 DSL 与轮询 run 状态。"""
import asyncio


def node(node_id: str, node_type: str, x: int = 0, **config):
    return {"id": node_id, "type": node_type, "position": {"x": x, "y": 0}, "config": config}


def edge(edge_id: str, source: str, target: str, source_handle: str | None = None):
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
    }


async def create_flow(client, nodes, edges, name="测试流程"):
    response = await client.post(
        "/api/flows", json={"name": name, "nodes": nodes, "edges": edges}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def wait_for_status(client, run_id: str, expected: set[str], timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/runs/{run_id}")
        last = response.json()
        if last["status"] in expected:
            return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} 状态停留于 {last.get('status')}，期望 {expected}")
