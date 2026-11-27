"""代码版本元信息：发布时记录 git commit / 分支 / 工作区是否干净。

为什么发布时抓：质量归因要能回答「这次指标变化对应哪次代码变更」。
工作区脏不阻断发布，但会写进 manifest，评测报告里必须显著提示「该版本不可复现」。
"""
import subprocess
import time
from pathlib import Path

_CACHE: tuple[float, dict] | None = None
_TTL_S = 10.0


def repo_root() -> Path:
    """从后端目录向上找 .git；找不到就把后端目录当工作区。"""
    start = Path(__file__).resolve().parents[2]
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_meta(*, refresh: bool = False) -> dict:
    global _CACHE
    now = time.monotonic()
    if not refresh and _CACHE and now - _CACHE[0] < _TTL_S:
        return dict(_CACHE[1])

    root = repo_root()
    commit = _git(["rev-parse", "--short", "HEAD"], root)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    status = _git(["status", "--porcelain"], root)
    meta = {
        "commit": commit or None,
        "branch": branch or None,
        "dirty": bool(status) if status is not None else False,
    }
    _CACHE = (now, meta)
    return dict(meta)
