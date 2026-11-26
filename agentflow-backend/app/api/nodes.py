"""节点类型 Schema 导出：前端配置面板与后端校验共用同一份定义。"""
from fastapi import APIRouter, HTTPException

from app.nodes.registry import all_specs, categories, get_spec
from app.services.settings_repo import get_llm_config

router = APIRouter(prefix="/node-types", tags=["node-types"])


@router.get("")
async def list_node_types():
    llm = await get_llm_config()
    return {
        "types": [spec.to_api() for spec in all_specs()],
        "categories": categories(),
        "llmConfigured": llm.configured,
    }


@router.get("/{node_type}")
async def get_node_type(node_type: str):
    spec = get_spec(node_type)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"未知节点类型: {node_type}")
    return spec.to_api()
