"""条件表达式求值：给 condition / loop 节点用，禁止 eval 任意代码。

约定：表达式里用 {{变量}}，求值时把变量替换成 **Python 字面量**（字符串带引号、
数字原样、布尔 True/False），所以 `{{score}} > 0.8` → `0.95 > 0.8`，
`{{name}} == "张三"` → `'张三' == "张三"`。这样用户不用操心引号。

白名单 AST：比较、布尔、四则、取反、常量、字面量列表/元组/字典、下标取值。
不允许函数调用、属性访问、推导式、lambda、赋值——表达式只能算值，不能执行动作。
"""
import ast
import re

_TEMPLATE = re.compile(r"\{\{([\w.]+)\}\}")
_KEYWORD_LITERALS = {"true": "True", "false": "False", "null": "None"}


def _lookup(variables: dict, path: str):
    value = variables
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value

_ALLOWED = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare,
    ast.Constant, ast.Name, ast.Load, ast.And, ast.Or, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice,
)


class ConditionError(ValueError):
    """表达式写错时抛这个：文案要能让人照着改，而不是一串 traceback。"""

    code = "CONDITION_INVALID"


def render_expression(expression: str, variables: dict) -> str:
    """把 {{var}} 换成 Python 字面量；缺失变量直接报错（否则 silently 变成奇怪的表达式）。"""
    missing: list[str] = []

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        try:
            value = _lookup(variables, key)
        except KeyError:
            missing.append(key)
            return match.group(0)
        return repr(value)

    rendered = _TEMPLATE.sub(_replace, expression or "")
    if missing:
        raise ConditionError(
            "表达式引用了不存在的变量: " + ", ".join(missing)
            + "（可用的："
            + ", ".join(sorted(str(key) for key in variables)) + "）"
        )
    # 小写字面量按人写习惯放宽：true / false / null
    rendered = re.sub(
        r"\b(true|false|null)\b",
        lambda m: _KEYWORD_LITERALS[m.group(1)],
        rendered,
    )
    return rendered.strip()


def evaluate_condition(expression: str, variables: dict) -> tuple[bool, str]:
    """返回 (真假, 实际求值的表达式)。表达式非法抛 ConditionError。"""
    rendered = render_expression(expression, variables)
    if not rendered:
        raise ConditionError("条件表达式为空")

    try:
        tree = ast.parse(rendered, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"表达式语法错误（渲染后为 `{rendered}`）：{exc.msg}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ConditionError(
                f"表达式里不允许 {type(node).__name__}（渲染后为 `{rendered}`）；"
                "只支持比较、布尔与四则运算"
            )

    try:
        value = eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, {})  # noqa: S307
    except Exception as exc:  # noqa: BLE001 - 用户表达式，任何异常都要转成可读文案
        raise ConditionError(f"表达式求值失败（渲染后为 `{rendered}`）：{exc}") from exc

    if isinstance(value, bool):
        return value, rendered
    if isinstance(value, (int, float)):
        return value != 0, rendered
    if isinstance(value, str):
        return bool(value), rendered
    return bool(value), rendered
