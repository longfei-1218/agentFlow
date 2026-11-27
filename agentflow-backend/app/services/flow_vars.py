"""Flow v2 变量寻址：`{{start.x}}` / `{{nodeId.output.field}}`。

模板里如果整段只是一个路径，保留原始类型（数字/布尔/对象）；
混合在文本里才转字符串。缺失路径抛 LookupError，由校验/执行翻译成用户能懂的错。
"""
import json
import re
from typing import Any

PATH_RE = re.compile(r"{{([a-zA-Z_][\w.]*)}}")


def extract_paths(template: str) -> list[str]:
    if not isinstance(template, str):
        return []
    return PATH_RE.findall(template)


def resolve_path(context: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    value: Any = context
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            raise LookupError(path)
        value = value[part]
    return value


def render_value(template: Any, context: dict[str, Any]) -> Any:
    """整段一个路径返回原值；否则做文本插值。"""
    if not isinstance(template, str):
        return template
    matches = list(PATH_RE.finditer(template))
    if len(matches) == 1 and matches[0].span() == (0, len(template)):
        return resolve_path(context, matches[0].group(1))

    def replace(match: re.Match) -> str:
        value = resolve_path(context, match.group(1))
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return PATH_RE.sub(replace, template)


def flow_context(data: dict[str, Any]) -> dict[str, Any]:
    nodes = dict(data.get("nodes") or {})
    return {
        **dict(data.get("variables") or {}),
        "start": dict(data.get("start") or {}),
        "nodes": nodes,
        # 同时暴露 nodeId 短路径：{{a1.output.text}} / {{nodes.a1.output.text}}
        **nodes,
    }
