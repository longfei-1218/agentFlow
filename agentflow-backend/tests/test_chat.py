"""R5.1：对话模式（会话 → 每轮一个 run，历史回灌）。"""
from helpers import create_flow, edge, node, wait_for_status


async def _chat_flow(client, name="对话测试"):
    return await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("prompt_1", "prompt", 200, template="历史=[{{history}}] 本轮=[{{query}}]"),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "prompt_1"), edge("e_2", "prompt_1", "output_1")],
        name=name,
    )


async def test_chat_two_turns_persist_and_feed_history(client):
    flow = await _chat_flow(client)
    conversation = (
        await client.post("/api/chat/conversations", json={"flowId": flow["id"]})
    ).json()
    assert conversation["title"] == flow["name"]

    first = (
        await client.post(
            f"/api/chat/conversations/{conversation['id']}/turns",
            json={"content": "你好"},
        )
    ).json()
    run1 = await wait_for_status(client, first["runId"], {"succeeded"})
    assert run1["inputs"]["query"] == "你好"
    assert run1["inputs"]["history"] == ""
    assert run1["conversationId"] == conversation["id"]
    assert run1["outputs"]["text"] == "历史=[] 本轮=[你好]"

    second = (
        await client.post(
            f"/api/chat/conversations/{conversation['id']}/turns",
            json={"content": "再说一次"},
        )
    ).json()
    run2 = await wait_for_status(client, second["runId"], {"succeeded"})
    assert "用户：你好" in run2["inputs"]["history"]
    assert "助手：历史=[] 本轮=[你好]" in run2["inputs"]["history"]
    assert run2["inputs"]["query"] == "再说一次"

    detail = (
        await client.get(f"/api/chat/conversations/{conversation['id']}")
    ).json()
    assert len(detail["messages"]) == 4
    assert [m["role"] for m in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert detail["messages"][1]["content"] == "历史=[] 本轮=[你好]"
    assert detail["messages"][3]["content"] == "历史=[用户：你好\n助手：历史=[] 本轮=[你好]] 本轮=[再说一次]"
    assert detail["title"] == "你好"


async def test_chat_rejects_human_flow_and_keeps_turn_clean(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("human_1", "human", 200, message="确认？"),
            node("output_1", "output", 400, fields=["approved"]),
        ],
        [edge("e_1", "input_1", "human_1"), edge("e_2", "human_1", "output_1")],
        name="带审批",
    )
    conversation = (
        await client.post("/api/chat/conversations", json={"flowId": flow["id"]})
    ).json()

    response = await client.post(
        f"/api/chat/conversations/{conversation['id']}/turns",
        json={"content": "能批吗"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CHAT_HUMAN_UNSUPPORTED"

    detail = (
        await client.get(f"/api/chat/conversations/{conversation['id']}")
    ).json()
    assert detail["messages"] == []


async def test_chat_list_is_scoped_to_flow(client):
    flow_a = await _chat_flow(client, name="会话归属 A")
    flow_b = await _chat_flow(client, name="会话归属 B")
    conv_a = (
        await client.post("/api/chat/conversations", json={"flowId": flow_a["id"]})
    ).json()
    conv_b = (
        await client.post("/api/chat/conversations", json={"flowId": flow_b["id"]})
    ).json()

    list_a = (
        await client.get(f"/api/chat/conversations?flow_id={flow_a['id']}")
    ).json()
    list_b = (
        await client.get(f"/api/chat/conversations?flow_id={flow_b['id']}")
    ).json()
    assert [item["id"] for item in list_a] == [conv_a["id"]]
    assert [item["id"] for item in list_b] == [conv_b["id"]]
    assert conv_a["flowId"] == flow_a["id"]
    assert conv_b["flowId"] == flow_b["id"]


async def test_chat_rejects_blank_message(client):
    flow = await _chat_flow(client, name="空消息")
    conversation = (
        await client.post("/api/chat/conversations", json={"flowId": flow["id"]})
    ).json()

    response = await client.post(
        f"/api/chat/conversations/{conversation['id']}/turns",
        json={"content": "   "},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["detail"][0]["ctx"]["error"] == "消息内容不能为空"


async def test_chat_delete_conversation(client):
    flow = await _chat_flow(client, name="删除会话")
    conversation = (
        await client.post("/api/chat/conversations", json={"flowId": flow["id"]})
    ).json()

    deleted = await client.delete(f"/api/chat/conversations/{conversation['id']}")
    assert deleted.status_code == 204

    missing = await client.get(f"/api/chat/conversations/{conversation['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "CONVERSATION_NOT_FOUND"
