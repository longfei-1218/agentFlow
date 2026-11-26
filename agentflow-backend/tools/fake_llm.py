"""本地假模型服务：OpenAI 兼容的 /v1/models 与 /v1/chat/completions（仅开发验收用）。

用途：没有真实 API Key 时，也能把「真流式 → token 事件 → 用量校准 → 成本」这条链路跑通。
它不参与产品逻辑，也不会自动启用——必须手动起服务并在设置里把 Base URL 指过来。

启动：
    .venv\\Scripts\\python.exe -m uvicorn tools.fake_llm:app --port 8899
然后在「模型设置」里填：
    Base URL = http://127.0.0.1:8899/v1
    API Key  = 任意非空（如 sk-fake）
    Model    = fake-model
"""
import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Fake LLM (dev only)", version="0.1")

MODEL_ID = "fake-model"


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    requested = body.get("model") or MODEL_ID
    if requested != MODEL_ID:
        # 故意模仿真实网关的报错：用来验证「节点里写死了别的模型名」时前端能给出可读提示
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": f"The supported API model names are {MODEL_ID}, but you passed {requested}.",
                    "type": "invalid_request_error",
                }
            },
        )

    messages = body.get("messages") or []
    user = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            user = str(message.get("content") or "")
            break

    reply = (
        f"本地假模型收到：「{user[:60]}」。"
        "这段回答由 tools/fake_llm.py 逐字流式返回，"
        "用来验证 token 事件、用量校准与成本统计是否贯通。"
    )
    pieces = [reply[index:index + 6] for index in range(0, len(reply), 6)]
    prompt_tokens = max(1, sum(len(str(m.get("content") or "")) for m in messages) // 3)
    completion_tokens = max(1, len(reply) // 3)

    async def event_stream():
        chunk_id = f"chatcmpl-fake-{int(time.time())}"
        created = int(time.time())
        for index, piece in enumerate(pieces):
            if await request.is_disconnected():
                return
            payload = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": body.get("model") or MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": piece},
                        "finish_reason": "stop" if index == len(pieces) - 1 else None,
                    }
                ],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.06)

        # 最后一帧带 usage：真 provider 可能不给，执行器会退回字符估算
        usage_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.get("model") or MODEL_ID,
            "choices": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        yield f"data: {json.dumps(usage_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
