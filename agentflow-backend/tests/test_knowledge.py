"""R5：知识库切块、检索与 knowledge 节点。"""
from helpers import create_flow, edge, node, wait_for_status

REFUND_DOC = (
    "退款政策：订单支付后 7 天内可以申请退款，退款多久到账取决于支付渠道。"
    "微信支付通常 1 到 3 个工作日到账，银行卡原路退回最长 7 个工作日。"
    "超过 7 天的订单需要联系人工客服审核，跨境订单不适用无理由退款。"
)
INVOICE_DOC = (
    "发票说明：电子发票在订单完成后 24 小时内开具，可在订单详情页下载。"
    "如果需要增值税专用发票，请在下单时填写抬头与税号，开具后不支持修改。"
)


async def _create_kb(client, name="售后知识库", chunk_size=120, overlap=20) -> dict:
    response = await client.post(
        "/api/knowledge",
        json={"name": name, "chunkSize": chunk_size, "overlap": overlap},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_kb_chunks_documents_and_search_ranks_relevant_chunk(client):
    kb = await _create_kb(client)

    refund = await client.post(
        f"/api/knowledge/{kb['id']}/documents",
        json={"title": "退款政策", "content": REFUND_DOC},
    )
    assert refund.status_code == 201, refund.text
    assert refund.json()["chunkCount"] >= 1

    invoice = await client.post(
        f"/api/knowledge/{kb['id']}/documents",
        json={"title": "发票说明", "content": INVOICE_DOC},
    )
    assert invoice.status_code == 201

    kb_after = (await client.get(f"/api/knowledge/{kb['id']}")).json()
    assert kb_after["docCount"] == 2
    assert kb_after["chunkCount"] >= 2

    search = await client.post(
        f"/api/knowledge/{kb['id']}/search",
        json={"query": "退款多久到账", "topK": 2, "rerank": False},
    )
    body = search.json()
    assert body["hits"], body
    assert body["hits"][0]["title"] == "退款政策"
    assert "退款" in body["hits"][0]["text"]
    assert body["totalChunks"] >= 2
    assert body["extra"]["engine"] == "bm25"

    reranked = (
        await client.post(
            f"/api/knowledge/{kb['id']}/search",
            json={"query": "退款多久到账", "topK": 2, "rerank": True},
        )
    ).json()
    assert reranked["extra"]["engine"] == "bm25+mmr"
    assert reranked["hits"][0]["title"] == "退款政策"


async def test_empty_kb_search_gives_actionable_hint(client):
    kb = await _create_kb(client, name="空知识库")
    body = (
        await client.post(
            f"/api/knowledge/{kb['id']}/search",
            json={"query": "随便问点什么", "topK": 3},
        )
    ).json()
    assert body["hits"] == []
    assert "还没有文档" in (body["hint"] or "")


async def test_knowledge_node_injects_context_into_variables(client):
    kb = await _create_kb(client, name="节点检索库")
    await client.post(
        f"/api/knowledge/{kb['id']}/documents",
        json={"title": "退款政策", "content": REFUND_DOC},
    )
    await client.post(
        f"/api/knowledge/{kb['id']}/documents",
        json={"title": "发票说明", "content": INVOICE_DOC},
    )

    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("kb_1", "knowledge", 200, kb_id=kb["id"], top_k=2, query_template="{{query}}"),
            node("output_1", "output", 400, fields=["context", "citations"]),
        ],
        [edge("e_1", "input_1", "kb_1"), edge("e_2", "kb_1", "output_1")],
        name="知识库检索",
    )

    run = (
        await client.post(
            f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "退款多久到账"}}
        )
    ).json()
    await wait_for_status(client, run["id"], {"succeeded"})
    final = (await client.get(f"/api/runs/{run['id']}")).json()

    context = final["outputs"]["context"]
    assert "退款政策" in context and "退款" in context
    assert final["outputs"]["citations"][0]["title"] == "退款政策"

    from app.services.event_bus import event_bus
    import orjson

    history = await event_bus.history(run["id"])
    dumped = orjson.dumps(
        [{"type": event.type, "nodeId": event.node_id, "payload": event.payload} for event in history]
    ).decode()
    assert '"knowledge_retrieved"' in dumped
    assert '"hits":' in dumped


async def test_delete_document_recounts_kb(client):
    kb = await _create_kb(client, name="删文档")
    doc = (
        await client.post(
            f"/api/knowledge/{kb['id']}/documents",
            json={"title": "临时", "content": REFUND_DOC},
        )
    ).json()

    removed = await client.delete(f"/api/knowledge/{kb['id']}/documents/{doc['id']}")
    assert removed.status_code == 204

    kb_after = (await client.get(f"/api/knowledge/{kb['id']}")).json()
    assert kb_after["docCount"] == 0
    assert kb_after["chunkCount"] == 0
