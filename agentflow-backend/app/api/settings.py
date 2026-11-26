"""/api/settings：LLM 配置的读取、保存、连通性测试。"""
import time

from fastapi import APIRouter
from pydantic import Field

from app.models.flow import CamelModel
from app.services.llm import LLMConfig, LLMError, list_models
from app.services.settings_repo import (
    get_llm_config,
    get_setting,
    LLM_SETTING_KEY,
    public_llm_view,
    save_llm_config,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class LLMSettingsPatch(CamelModel):
    """apiKey 省略=不动；传空串=清空。"""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)


@router.get("/llm")
async def read_llm_settings():
    stored = await get_setting(LLM_SETTING_KEY)
    config = await get_llm_config()
    return public_llm_view(config, updated_at=stored[1] if stored else None)


@router.put("/llm")
async def write_llm_settings(patch: LLMSettingsPatch):
    payload = patch.model_dump(by_alias=True, exclude_unset=True)
    config, updated_at = await save_llm_config(payload)
    return public_llm_view(config, updated_at=updated_at)


@router.get("/llm/models")
async def llm_models():
    """网关支持的模型清单：给前端的模型下拉用。

    故意不缓存：用户换网关/换 Key 后点一下就该看到真实列表；
    这个端点只打一次 /models，频率很低。
    """
    config = await get_llm_config()
    try:
        models = await list_models(config)
    except LLMError as exc:
        return {
            "ok": False,
            "models": [],
            "message": str(exc),
            "current": config.model,
            "supported": False,
        }
    return {
        "ok": True,
        "models": models,
        "message": "" if models else "网关未返回模型列表（仍可尝试运行）",
        "current": config.model,
        "supported": config.model in models if models else True,
    }


@router.post("/llm/test")
async def test_llm_settings(patch: LLMSettingsPatch | None = None):
    """测试连接：拿合并后的配置打一次 /models，返回耗时与可用模型。

    注意这是「测连通」，不是「测推理」：真的跑一次补全会白烧钱。
    """
    config = await get_llm_config()
    if patch is not None:
        overrides = patch.model_dump(by_alias=True, exclude_unset=True, exclude_none=True)
        api_key = overrides.get("apiKey")
        config = LLMConfig(
            base_url=str(overrides.get("baseUrl") or config.base_url),
            api_key=api_key if api_key is not None else config.api_key,
            model=str(overrides.get("model") or config.model),
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            source=config.source,
        )

    started = time.perf_counter()
    try:
        models = await list_models(config)
        return {
            "ok": True,
            "message": "连接正常" + (f"，可用模型 {len(models)} 个" if models else "（/models 未返回列表，仍可尝试运行）"),
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "models": models[:20],
        }
    except LLMError as exc:
        return {
            "ok": False,
            "message": str(exc),
            "code": exc.code,
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "models": [],
        }
