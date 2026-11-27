"""render_interview_repo 内置工具实现（独立资源包）。

主程序只通过 manifest 调用 `run(args, context)`；模板、转义、文件命名都在这里，
主 Agent 代码不再包含具体报告实现。
"""
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
import html
import re
import uuid

import orjson


def run(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return _render_interview_report(args, context)
def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return orjson.dumps(value, option=orjson.OPT_INDENT_2).decode()
    return str(value)


def _esc(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score(value: Any) -> tuple[float | None, str]:
    number = _num(value)
    if number is None:
        return None, ""
    number = max(0.0, min(100.0, number))
    return number, (str(int(number)) if number.is_integer() else f"{number:.1f}")


def _paragraphs(value: Any) -> str:
    lines = [line.strip() for line in _text(value).splitlines() if line.strip()]
    return "".join(f"<p>{_esc(line)}</p>" for line in lines)


def _bullets(value: Any) -> str:
    items = value if isinstance(value, list) else []
    rows = [f"<li>{_esc(item)}</li>" for item in items if _text(item).strip()]
    return "<ul>" + "".join(rows) + "</ul>" if rows else ""


def _section(title: str, body: str, extra_class: str = "") -> str:
    if not body.strip():
        return ""
    return (
        f'<section class="section {extra_class}">'
        f'<h2>{_esc(title)}</h2>{body}</section>'
    )


def _meta_chip(label: str, value: Any) -> str:
    text = _text(value).strip()
    if not text:
        return ""
    return f'<span class="chip"><b>{_esc(label)}</b>{_esc(text)}</span>'


INTERVIEW_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 16px;
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  background: #eef1f5; color: #1f2937; line-height: 1.65;
}
.page {
  width: 100%; max-width: 920px; margin: 0 auto; background: #fff;
  border: 1px solid #e5e7eb; border-radius: 10px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, .08); padding: 44px 52px 36px;
}
.toolbar { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.toolbar button {
  border: 1px solid #d1d5db; background: #fff; color: #374151;
  border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer;
}
.header { border-bottom: 3px solid #1d4ed8; padding-bottom: 18px; }
.eyebrow { color: #1d4ed8; font-size: 12px; letter-spacing: .18em; font-weight: 700; }
h1 { margin: 8px 0 10px; font-size: 28px; line-height: 1.3; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-flex; gap: 6px; align-items: center;
  border: 1px solid #e5e7eb; background: #f8fafc;
  border-radius: 999px; padding: 4px 10px; font-size: 12px; color: #4b5563;
}
.chip b { color: #111827; font-weight: 600; }
.hero {
  display: flex; gap: 22px; align-items: center;
  margin: 24px 0 6px; padding: 18px 22px;
  border-radius: 10px; background: linear-gradient(135deg, #eff6ff, #f8fafc);
  border: 1px solid #dbeafe;
}
.score { font-size: 38px; font-weight: 800; color: #1d4ed8; line-height: 1; white-space: nowrap; }
.score small { font-size: 13px; color: #64748b; font-weight: 500; }
.verdict { font-size: 16px; font-weight: 700; color: #0f172a; }
.hero p { margin: 4px 0 0; color: #64748b; font-size: 12px; }
.section { margin-top: 26px; }
h2 {
  margin: 0 0 12px; padding-left: 10px; border-left: 4px solid #1d4ed8;
  font-size: 16px; line-height: 1.4;
}
p { margin: 0 0 8px; font-size: 13px; color: #374151; }
ul { margin: 0; padding-left: 20px; }
li { margin-bottom: 6px; font-size: 13px; color: #374151; }
.dim { margin-bottom: 12px; }
.dim-head { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.dim-head b { font-weight: 600; }
.dim-head span { color: #1d4ed8; font-weight: 700; white-space: nowrap; }
.bar { height: 7px; margin-top: 5px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #60a5fa, #1d4ed8); border-radius: 999px; }
.dim-comment { margin-top: 5px; font-size: 12px; color: #6b7280; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.box { border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; background: #fcfcfd; }
.box h3 { margin: 0 0 8px; font-size: 13px; color: #166534; }
.box.risk h3 { color: #b45309; }
.qa { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
.q { font-size: 13px; font-weight: 700; color: #111827; }
.a { margin-top: 5px; font-size: 13px; color: #374151; }
.a em { font-style: normal; color: #64748b; font-size: 11px; margin-right: 6px; }
.note { margin-top: 6px; font-size: 12px; color: #6b7280; border-left: 2px solid #e5e7eb; padding-left: 8px; }
.transcript { max-height: 420px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
.turn { padding: 9px 12px; border-bottom: 1px solid #f1f5f9; font-size: 12px; }
.turn:last-child { border-bottom: 0; }
.turn b { display: inline-block; min-width: 62px; color: #1d4ed8; }
.turn.candidate b { color: #047857; }
.turn.system b { color: #9a3412; }
footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #e5e7eb; color: #94a3b8; font-size: 11px; }
@media (max-width: 680px) {
  .page { padding: 26px 20px; }
  .grid { grid-template-columns: 1fr; }
  .hero { flex-direction: column; align-items: flex-start; }
}
@media print {
  body { background: #fff; padding: 0; }
  .page { max-width: none; border: 0; box-shadow: none; padding: 0; }
  .toolbar { display: none; }
  .transcript { max-height: none; overflow: visible; }
}
"""


def _render_interview_report(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """用固定模板把结构化面试结果渲染成 HTML，并落到产物目录。

    不让模型自己写 HTML：模板、转义和布局都由代码控制，模型只负责提供结构化字段。
    """
    title = _text(args.get("title")).strip() or "面试评估报告"
    candidate = _text(args.get("candidate")).strip()
    position = _text(args.get("position")).strip()
    interviewer = _text(args.get("interviewer")).strip()
    date_text = _text(args.get("date")).strip() or datetime.now().strftime("%Y-%m-%d")
    verdict = _text(args.get("verdict")).strip()
    summary = _text(args.get("summary")).strip()

    dimensions = args.get("dimensions") if isinstance(args.get("dimensions"), list) else []
    dim_rows: list[str] = []
    dim_scores: list[float] = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name")).strip() or "未命名维度"
        score, score_text = _score(item.get("score"))
        if score is not None:
            dim_scores.append(score)
        bar = (
            f'<div class="bar"><i style="width:{score:.1f}%"></i></div>' if score is not None else ""
        )
        comment = _text(item.get("comment")).strip()
        dim_rows.append(
            '<div class="dim">'
            f'<div class="dim-head"><b>{_esc(name)}</b><span>{_esc(score_text) if score_text else "—"}</span></div>'
            f"{bar}"
            + (f'<div class="dim-comment">{_esc(comment)}</div>' if comment else "")
            + "</div>"
        )

    overall, overall_text = _score(args.get("overall_score"))
    if overall is None and dim_scores:
        overall = sum(dim_scores) / len(dim_scores)
        overall_text = str(int(overall)) if overall.is_integer() else f"{overall:.1f}"

    strengths = _bullets(args.get("strengths"))
    risks = _bullets(args.get("risks"))
    grid = ""
    if strengths or risks:
        grid = (
            '<div class="grid">'
            + (f'<div class="box"><h3>亮点与优势</h3>{strengths}</div>' if strengths else "")
            + (f'<div class="box risk"><h3>风险与待确认</h3>{risks}</div>' if risks else "")
            + "</div>"
        )

    qa_rows: list[str] = []
    qa_items = args.get("qa") if isinstance(args.get("qa"), list) else []
    for index, item in enumerate(qa_items, start=1):
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question")).strip()
        answer = _text(item.get("answer")).strip()
        comment = _text(item.get("comment")).strip()
        qa_rows.append(
            '<div class="qa">'
            f'<div class="q">Q{index}. {_esc(question)}</div>'
            + (f'<div class="a"><em>回答</em>{_esc(answer)}</div>' if answer else "")
            + (f'<div class="note">{_esc(comment)}</div>' if comment else "")
            + "</div>"
        )

    turns: list[str] = []
    transcript = args.get("transcript") if isinstance(args.get("transcript"), list) else []
    for item in transcript:
        if not isinstance(item, dict):
            continue
        role = _text(item.get("role")).strip() or "system"
        role_cls = "candidate" if role in ("candidate", "候选人") else ("interviewer" if role in ("interviewer", "面试官") else "system")
        role_label = {"candidate": "候选人", "interviewer": "面试官"}.get(role_cls, "系统")
        turns.append(
            f'<div class="turn {role_cls}"><b>{_esc(role_label)}</b>{_esc(item.get("content"))}</div>'
        )

    hero = ""
    if overall is not None or verdict:
        hero = (
            '<div class="hero">'
            + (
                f'<div class="score">{_esc(overall_text)}<small> / 100</small></div>'
                if overall is not None
                else ""
            )
            + "<div>"
            + (f'<div class="verdict">{_esc(verdict)}</div>' if verdict else "")
            + "<p>综合评分由各维度取平均或调用方直接给出</p></div></div>"
        )

    meta = "".join(
        [
            _meta_chip("候选人", candidate),
            _meta_chip("岗位", position),
            _meta_chip("面试官", interviewer),
            _meta_chip("日期", date_text),
        ]
    )

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_esc(title)}</title>
<style>{INTERVIEW_CSS}</style>
</head>
<body>
<div class="page">
  <div class="toolbar"><button type="button" onclick="window.print()">打印 / 另存为 PDF</button></div>
  <header class="header">
    <div class="eyebrow">INTERVIEW REPORT</div>
    <h1>{_esc(title)}</h1>
    <div class="meta">{meta}</div>
  </header>
  {hero}
  {_section("总体评价", _paragraphs(summary))}
  {_section("能力维度", "".join(dim_rows))}
  {_section("亮点与风险", grid)}
  {_section("关键问答", "".join(qa_rows))}
  {_section("面试记录", f'<div class="transcript">{"".join(turns)}</div>' if turns else "")}
  <footer>本报告由 AgentFlow Studio 的 render_interview_repo 内置工具自动生成 · {_esc(datetime.now().strftime("%Y-%m-%d %H:%M"))}</footer>
</div>
</body>
</html>
"""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _text(args.get("output_name")).strip()
    if stem.lower().endswith(".html"):
        stem = stem[:-5]
    stem = re.sub(r"[^0-9A-Za-z_-]+", "_", stem).strip("_")[:48] or "interview_report"
    file_name = f"{stem}_{stamp}_{uuid.uuid4().hex[:6]}.html"

    artifact_dir = Path(context.get("artifact_dir") or "data/artifacts").expanduser().resolve()
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        target = artifact_dir / file_name
        target.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"面试报告落盘失败: {exc}") from exc

    return {
        "ok": True,
        "title": title,
        "path": str(target),
        "fileName": file_name,
        "downloadUrl": f"/api/artifacts/{quote(file_name)}",
        "bytes": target.stat().st_size,
        "overallScore": overall_text or None,
    }


