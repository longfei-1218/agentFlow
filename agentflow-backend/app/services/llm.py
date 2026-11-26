"""OpenAI 兼容 LLM provider：流式对话 + 用量/成本折算。

要点：
- 只依赖 httpx，不引入 openai SDK：一套 SSE 解析同时兼容 OpenAI / DeepSeek / 通义 / 本地 vLLM / 自建网关；
- 成本优先用 provider 返回的 usage 精确算，拿不到就按字符估算（中文 1 字≈1 token，英文 4 字符≈1 token），
  并在结束时用估算与真实用量的差额做一次校准，保证界面上的 token 数不会两套口径打架；
- 网络异常统一抛 LLMError，由执行器转成 run_failed 事件，绝不把异常冒到协程外静默丢事件。
"""
import json
import math
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

# 单价：元 / 1K tokens（输入价, 输出价）。仅用于估算展示，真实计费以 provider 为准。
PRICING_CNY_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.0011, 0.0043),
    "gpt-4o": (0.0036, 0.0144),
    "deepseek-chat": (0.001, 0.002),
    "qwen-plus": (0.0008, 0.002),
}
DEFAULT_PRICE = (0.002, 0.006)

CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F),
    (0xFF00, 0xFFEF), (0xAC00, 0xD7AF), (0x3040, 0x30FF),
)


class LLMError(RuntimeError):
    def __init__(self, message: str, code: str = "LLM_ERROR", status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 1024
    source: str = "none"  # db | env | none

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip() and self.model.strip())

    def masked_key(self) -> str | None:
        key = self.api_key.strip()
        if not key:
            return None
        if len(key) <= 8:
            return "****"
        return f"{key[:4]}…{key[-4:]}"


@dataclass
class LLMDelta:
    """一段流式增量。text 为空表示「只带用量/成本的校准帧」。"""

    text: str = ""
    delta_tokens: int = 0          # 增量 token（含输入，用于界面实时计数）
    delta_prompt_tokens: int = 0
    delta_completion_tokens: int = 0
    cost: float = 0.0              # 增量成本（元）
    finish_reason: str | None = None
    usage: dict | None = None
    # 一轮结束后组装好的工具调用：{id, name, arguments(JSON 字符串)}
    tool_calls: list[dict] | None = None


def price_for(model: str) -> tuple[float, float]:
    return PRICING_CNY_PER_1K.get(model, DEFAULT_PRICE)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """粗估 token 数：CJK 字符按 1，其他按 4 字符 1 个。"""
    if not text:
        return 0
    cjk = sum(1 for char in text if _is_cjk(char))
    other = len(text) - cjk
    return max(1, cjk + math.ceil(other / 4))


def _cost(prompt_tokens: int, completion_tokens: int, price: tuple[float, float]) -> float:
    return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1000.0


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


async def stream_completion(
    config: LLMConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
) -> AsyncIterator[LLMDelta]:
    """逐帧吐模型输出；调用方负责把 delta 写进事件流。

    `tools` 就是 OpenAI 的 tools 数组（由 tool_runner.fc_schema 生成）。
    Function Calling 的增量参数（delta.tool_calls[].function.arguments）是**分片**来的，
    这里按 index 累积，整轮结束后一次性交给调用方，避免上层自己做拼装状态机。
    """
    if not config.configured:
        raise LLMError("尚未配置 LLM API Key，请到系统设置里填写", code="LLM_NOT_CONFIGURED", status_code=409)

    payload = {
        "model": model or config.model,
        "messages": messages,
        "stream": True,
        "temperature": config.temperature if temperature is None else temperature,
        "max_tokens": config.max_tokens if max_tokens is None else max_tokens,
        # OpenAI 兼容实现大多支持；不支持的网关会直接忽略这个字段
        "stream_options": {"include_usage": True},
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    price = price_for(payload["model"])
    prompt_text = "".join(str(message.get("content", "")) for message in messages)
    if tools:
        # tools 定义本身也占输入 token：不把它算进去，prompt 估算会明显偏低
        prompt_text += json.dumps(tools, ensure_ascii=False)
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = 0
    accumulated_text = ""
    exact_usage: dict | None = None
    tool_acc: dict[int, dict] = {}

    if prompt_tokens:
        # 先把输入 token 记上，界面上的 token 数从第一帧起就有值
        yield LLMDelta(
            delta_tokens=prompt_tokens,
            delta_prompt_tokens=prompt_tokens,
            cost=_cost(prompt_tokens, 0, price),
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            async with client.stream(
                "POST", _build_url(config.base_url, "chat/completions"),
                json=payload, headers=headers,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise LLMError(
                        f"模型接口返回 {response.status_code}: {body[:300].decode('utf-8', 'ignore')}",
                        code="LLM_HTTP_ERROR",
                        status_code=502,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data in ("[DONE]", "DONE"):
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue

                    usage = chunk.get("usage")
                    if usage:
                        exact_usage = usage

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or ""
                    finish = choice.get("finish_reason")

                    if text:
                        accumulated_text += text
                        chunk_tokens = estimate_tokens(text)
                        completion_tokens += chunk_tokens
                        yield LLMDelta(
                            text=text,
                            delta_tokens=chunk_tokens,
                            delta_completion_tokens=chunk_tokens,
                            cost=_cost(0, chunk_tokens, price),
                        )

                    for partial in delta.get("tool_calls") or []:
                        index = int(partial.get("index") or 0)
                        slot = tool_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if partial.get("id"):
                            slot["id"] = partial["id"]
                        function = partial.get("function") or {}
                        if function.get("name"):
                            slot["name"] += function["name"]
                        fragment = function.get("arguments") or ""
                        if fragment:
                            # 参数分片的 token 也是真花钱的：一并计入 completion，别漏账
                            slot["arguments"] += fragment
                            chunk_tokens = estimate_tokens(fragment)
                            completion_tokens += chunk_tokens
                            yield LLMDelta(
                                delta_tokens=chunk_tokens,
                                delta_completion_tokens=chunk_tokens,
                                cost=_cost(0, chunk_tokens, price),
                            )

                    if finish:
                        yield LLMDelta(finish_reason=finish)
    except LLMError:
        raise
    except httpx.HTTPError as exc:
        raise LLMError(f"模型接口连接失败: {exc}", code="LLM_CONNECT_ERROR") from exc

    if tool_acc:
        yield LLMDelta(
            tool_calls=[
                {
                    "id": slot["id"] or f"call_{index}",
                    "name": slot["name"],
                    "arguments": slot["arguments"] or "{}",
                }
                for index, slot in sorted(tool_acc.items())
            ],
            finish_reason="tool_calls",
        )

    # 收尾校准：provider 给了 usage 就以它为准，差额补一帧（差可以是负的，界面表现为回退到真实值）
    if exact_usage:
        real_prompt = int(exact_usage.get("prompt_tokens") or prompt_tokens)
        real_completion = int(exact_usage.get("completion_tokens") or estimate_tokens(accumulated_text))
        real_total = int(exact_usage.get("total_tokens") or (real_prompt + real_completion))
        real_cost = _cost(real_prompt, real_completion, price)
        estimated_total = prompt_tokens + completion_tokens
        estimated_cost = _cost(prompt_tokens, completion_tokens, price)
        yield LLMDelta(
            delta_tokens=real_total - estimated_total,
            delta_prompt_tokens=real_prompt - prompt_tokens,
            delta_completion_tokens=real_completion - completion_tokens,
            cost=real_cost - estimated_cost,
            usage={
                "promptTokens": real_prompt,
                "completionTokens": real_completion,
                "totalTokens": real_total,
                "estimated": False,
            },
        )
    else:
        yield LLMDelta(
            usage={
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": prompt_tokens + completion_tokens,
                "estimated": True,
            }
        )


async def list_models(config: LLMConfig) -> list[str]:
    """取模型列表用于「测试连接」；部分网关没实现 /models，回退为空列表。"""
    if not config.base_url.strip():
        raise LLMError("Base URL 为空", code="LLM_BAD_CONFIG", status_code=400)
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key.strip() else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            response = await client.get(_build_url(config.base_url, "models"), headers=headers)
            if response.status_code >= 400:
                raise LLMError(
                    f"/models 返回 {response.status_code}",
                    code="LLM_HTTP_ERROR",
                    status_code=502,
                )
            body = response.json()
            data = body.get("data") or []
            return [str(item.get("id")) for item in data if item.get("id")]
    except LLMError:
        raise
    except httpx.HTTPError as exc:
        raise LLMError(f"连接失败: {exc}", code="LLM_CONNECT_ERROR") from exc
    except ValueError as exc:
        raise LLMError(f"返回体不是合法 JSON: {exc}", code="LLM_BAD_RESPONSE") from exc
