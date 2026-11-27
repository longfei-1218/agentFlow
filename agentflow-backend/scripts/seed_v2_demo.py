"""写入 2 个演示 Agent + 2 条 Flow v2，并用真实网关做一次冒烟。

用法：
    .venv\\Scripts\\python.exe scripts\\seed_v2_demo.py           # 只写数据
    .venv\\Scripts\\python.exe scripts\\seed_v2_demo.py --smoke   # 写数据并真实运行
"""
import argparse
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
KB_ID = "kb_20261126_154242d719"   # 售后知识库
KB_ALIAS = "售后知识库"

AGENT_CHAT = "演示-通用对话"
AGENT_KB = "演示-售后知识库问答"
FLOW_CHAIN = "演示-两 Agent 串联"
FLOW_CONTROL = "演示-循环条件审批"

CHAT_AGENT = {
    "name": AGENT_CHAT,
    "description": "通用对话：带历史变量，可在流程节点或 Agent 库直接对话",
    "variables": [
        {"key": "query", "label": "问题", "type": "string", "required": True},
        {"key": "history", "label": "历史", "type": "string", "required": False, "default": ""},
    ],
    "prompt": {
        "system": "你是简洁的中文客服助手，回答控制在三句话内。",
        "template": "历史：{{history}}\n用户：{{query}}",
    },
    "resources": [],
    "model": {"name": "", "temperature": 0.2, "maxTokens": 1024, "maxToolRounds": 2},
    "output": {"description": "纯文本", "schema": None},
}

KB_AGENT = {
    "name": AGENT_KB,
    "description": "售后知识库问答：只依据检索到的制度回答",
    "variables": [
        {"key": "query", "label": "问题", "type": "string", "required": True},
        {"key": "history", "label": "历史", "type": "string", "required": False, "default": ""},
    ],
    "prompt": {
        "system": "你是售后政策客服。只依据检索资料回答；资料没有就说不知道。",
        "template": "{{query}} @kb[售后知识库]",
    },
    "resources": [
        {"kind": "knowledge", "id": KB_ID, "alias": KB_ALIAS, "queryVar": "query", "topK": 2}
    ],
    "model": {"name": "", "temperature": 0, "maxTokens": 1024, "maxToolRounds": 2},
    "output": {"description": "纯文本", "schema": None},
}


def node(node_id: str, node_type: str, x: int = 0, **config):
    return {"id": node_id, "type": node_type, "position": {"x": x, "y": 0}, "config": config}


def edge(edge_id: str, source: str, target: str, handle: str | None = None):
    return {"id": edge_id, "source": source, "target": target, "sourceHandle": handle}


def ensure_agent(client: httpx.Client, payload: dict) -> dict:
    for item in client.get("/api/agents").json():
        if item["name"] == payload["name"]:
            response = client.put(f"/api/agents/{item['id']}", json=payload)
            response.raise_for_status()
            return response.json()
    response = client.post("/api/agents", json=payload)
    response.raise_for_status()
    return response.json()


def ensure_flow(client: httpx.Client, name: str, nodes: list, edges: list) -> dict:
    for item in client.get("/api/flows").json():
        if item["name"] == name:
            return item
    response = client.post("/api/flows", json={"name": name, "nodes": nodes, "edges": edges})
    response.raise_for_status()
    return response.json()


def wait_run(client: httpx.Client, run_id: str, expected: set[str], timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/runs/{run_id}").json()
        if last["status"] in expected:
            return last
        time.sleep(0.2)
    raise RuntimeError(f"run {run_id} 停在 {last.get('status')}：{last.get('error')}")


def seed(client: httpx.Client) -> tuple[dict, dict, dict, dict]:
    chat = ensure_agent(client, CHAT_AGENT)
    kb = ensure_agent(client, KB_AGENT)

    chain = ensure_flow(
        client,
        FLOW_CHAIN,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("chat_1", "agent", agentId=chat["id"], inputMap={"query": "{{start.query}}"}),
            node("kb_1", "agent", agentId=kb["id"], inputMap={"query": "{{chat_1.output.text}}"}),
            node("end_1", "end", outputs={"reply": "{{kb_1.output.text}}"}),
        ],
        [
            edge("e1", "start_1", "chat_1"),
            edge("e2", "chat_1", "kb_1"),
            edge("e3", "kb_1", "end_1"),
        ],
    )
    control = ensure_flow(
        client,
        FLOW_CONTROL,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("loop_1", "loop", maxRounds=1),
            node("chat_1", "agent", agentId=chat["id"], inputMap={"query": "{{start.query}}"}),
            node("cond_1", "condition", expression='{{chat_1.output.text}} != ""'),
            node("human_1", "human", message="确认继续结束本次演示？"),
            node("end_1", "end", outputs=["chat_1.output.text"]),
        ],
        [
            edge("e1", "start_1", "loop_1"),
            edge("e2", "loop_1", "chat_1", "body"),
            edge("e3", "chat_1", "loop_1"),
            edge("e4", "loop_1", "cond_1", "done"),
            edge("e5", "cond_1", "human_1", "true"),
            edge("e6", "cond_1", "end_1", "false"),
            edge("e7", "human_1", "end_1"),
        ],
    )
    return chat, kb, chain, control


def smoke(client: httpx.Client, chat: dict, chain: dict, control: dict) -> None:
    run = client.post(f"/api/flows/{chain['id']}/run", json={"inputs": {"query": "我要退款，多久到账？"}}).json()
    final = wait_run(client, run["id"], {"succeeded", "failed"})
    print("两 Agent 串联:", final["status"], final.get("outputs"), final.get("error"))
    if final["status"] != "succeeded":
        sys.exit(1)

    run = client.post(f"/api/flows/{control['id']}/run", json={"inputs": {"query": "你好，介绍一下你自己"}}).json()
    paused = wait_run(client, run["id"], {"waiting_human", "failed"})
    print("循环/条件/审批 暂停:", paused["status"], paused.get("error"))
    if paused["status"] != "waiting_human":
        sys.exit(1)
    client.post(f"/api/runs/{run['id']}/resume", json={"approved": True}).raise_for_status()
    final = wait_run(client, run["id"], {"succeeded", "failed"})
    print("审批后完成:", final["status"], final.get("outputs"), final.get("error"))
    if final["status"] != "succeeded":
        sys.exit(1)

    scopes = [
        ("库内直聊", {"agentId": chat["id"]}),
        ("流程 A 节点", {"agentId": chat["id"], "flowId": chain["id"], "nodeId": "chat_1"}),
        ("流程 B 节点", {"agentId": chat["id"], "flowId": control["id"], "nodeId": "chat_1"}),
    ]
    conversation_ids = {}
    for label, scope in scopes:
        conv = client.post("/api/chat/conversations", json={**scope, "title": label}).json()
        conversation_ids[label] = conv["id"]
        for suffix in ("第一句", "第二句"):
            turn = client.post(
                f"/api/chat/conversations/{conv['id']}/turns",
                json={"content": f"[{label}] {suffix}，只在这个会话里说"},
            ).json()
            wait_run(client, turn["runId"], {"succeeded", "failed"})
        detail = client.get(f"/api/chat/conversations/{conv['id']}").json()
        assert len(detail["messages"]) == 4, detail
        assert all(label in item["content"] for item in detail["messages"][0::2])
    print("三处同 Agent 会话（各两轮）:", conversation_ids)

    runs = client.get("/api/runs", params={"agent_id": chat["id"]}).json()
    chat_runs = [item for item in runs if item["targetType"] == "agent"]
    checked = 0
    for item in chat_runs:
        content = (item.get("inputs") or {}).get("query", "")
        if "第二句，只在这个会话里说" not in content:
            continue
        checked += 1
        label = content.split("]")[0][1:]
        history = (item.get("inputs") or {}).get("history", "")
        assert f"[{label}] 第一句" in history, f"{label} 第二轮没带自己的历史: {history}"
        others = [name for name, _ in scopes if name != label and f"[{name}]" in history]
        assert not others, f"{label} 的历史串了: {history}"
    assert checked == len(scopes), f"只检查到 {checked} 个会话的第二轮"
    print("历史隔离检查通过：每个作用域只回灌自己的历史；库内 Agent run 数:", len(chat_runs))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    with httpx.Client(base_url=BASE, timeout=200) as client:
        chat, kb, chain, control = seed(client)
        print(json.dumps(
            {"chatAgent": chat["id"], "kbAgent": kb["id"], "chainFlow": chain["id"], "controlFlow": control["id"]},
            ensure_ascii=False,
        ))
        if args.smoke:
            smoke(client, chat, chain, control)


if __name__ == "__main__":
    main()
