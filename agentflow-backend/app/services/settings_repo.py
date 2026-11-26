"""设置持久化：数据库优先于 .env。

为什么要有这一层：用户要求「LLM key 在系统配置里填」，而不是让他去改 .env 再重启。
优先级 db > env > 空；API Key 只写不读返（返回时只给脱敏预览）。
"""
import orjson

from app.config import settings
from app.database import db
from app.services.event_bus import utc_now
from app.services.llm import LLMConfig

LLM_SETTING_KEY = "llm"


async def get_setting(key: str) -> tuple[dict, str] | None:
    row = await db.fetchone(
        "SELECT value_json, updated_at FROM settings WHERE key = ?", (key,)
    )
    if row is None:
        return None
    try:
        value = orjson.loads(row["value_json"])
    except orjson.JSONDecodeError:
        value = {}
    return value, row["updated_at"]


async def put_setting(key: str, value: dict) -> str:
    now = utc_now()
    await db.execute(
        "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        (key, orjson.dumps(value).decode(), now),
    )
    return now


def _env_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_DEFAULT_MODEL,
        temperature=0.7,
        max_tokens=1024,
        source="env" if settings.LLM_API_KEY.strip() else "none",
    )


async def get_llm_config() -> LLMConfig:
    """运行期取配置：库里填过就用库里的，否则回落 .env。"""
    stored = await get_setting(LLM_SETTING_KEY)
    if stored is None:
        return _env_llm_config()

    value, _updated_at = stored
    fallback = _env_llm_config()
    return LLMConfig(
        base_url=str(value.get("baseUrl") or fallback.base_url),
        api_key=str(value.get("apiKey") or ""),
        model=str(value.get("model") or fallback.model),
        temperature=float(value.get("temperature", fallback.temperature)),
        max_tokens=int(value.get("maxTokens", fallback.max_tokens)),
        source="db" if value.get("apiKey") else ("env" if settings.LLM_API_KEY.strip() else "none"),
    )


async def save_llm_config(patch: dict) -> tuple[LLMConfig, str]:
    """合并写库。patch 里 apiKey 省略=保持不变，传空串=清空。"""
    stored = await get_setting(LLM_SETTING_KEY)
    value = dict(stored[0]) if stored else {}
    if not value:
        env = _env_llm_config()
        value = {
            "baseUrl": env.base_url,
            "apiKey": env.api_key,
            "model": env.model,
            "temperature": env.temperature,
            "maxTokens": env.max_tokens,
        }

    if patch.get("baseUrl") is not None:
        value["baseUrl"] = str(patch["baseUrl"]).strip()
    if patch.get("model") is not None:
        value["model"] = str(patch["model"]).strip()
    if patch.get("temperature") is not None:
        value["temperature"] = float(patch["temperature"])
    if patch.get("maxTokens") is not None:
        value["maxTokens"] = int(patch["maxTokens"])
    if "apiKey" in patch and patch["apiKey"] is not None:
        value["apiKey"] = str(patch["apiKey"]).strip()

    updated_at = await put_setting(LLM_SETTING_KEY, value)
    return await get_llm_config(), updated_at


def public_llm_view(config: LLMConfig, *, updated_at: str | None) -> dict:
    """给前端的视图：密钥只回脱敏预览。"""
    return {
        "baseUrl": config.base_url,
        "model": config.model,
        "temperature": config.temperature,
        "maxTokens": config.max_tokens,
        "hasApiKey": bool(config.api_key.strip()),
        "apiKeyPreview": config.masked_key(),
        "configured": config.configured,
        "source": config.source,
        "updatedAt": updated_at,
    }
