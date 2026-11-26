"""节点类型 Schema 导出：前端配置面板与后端校验共用同一份定义。"""
from fastapi import APIRouter, HTTPException

from app.engine.executor import VALID_RUNNERS, runner_name
from app.nodes.registry import all_specs, categories, get_spec
from app.services.settings_repo import get_llm_config
from app.services.tool_repo import list_tools

router = APIRouter(prefix="/node-types", tags=["node-types"])


@router.get("")
async def list_node_types():
    llm = await get_llm_config()
    return {
        "types": [spec.to_api() for spec in all_specs()],
        "categories": categories(),
        "llmConfigured": llm.configured,
        # 前端用它判断「工具下拉有没有东西可选」：0 个时直接引导去工具管理新建
        "toolsCount": len(await list_tools(only_enabled=True)),
        # R4：前端顶栏显示「引擎」，也让用户知道 condition/loop 是真执行而不是占位
        "engine": runner_name(),
        "engines": sorted(VALID_RUNNERS),
    }


@router.get("/{node_type}")
async def get_node_type(node_type: str):
    spec = get_spec(node_type)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"未知节点类型: {node_type}")
    return spec.to_api()
