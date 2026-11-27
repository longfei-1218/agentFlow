"""产物下载（render_interview_repo 生成的 HTML）。

只暴露 `ARTIFACT_DIR` 下的一层 `.html` 文件：
- 文件名必须是纯文件名，不允许 `..` 或子目录，避免路径穿越；
- 下载时用 inline，浏览器可以直接预览，也可以另存为 PDF。
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _root() -> Path:
    return Path(settings.ARTIFACT_DIR).expanduser().resolve()


def _safe_file(filename: str) -> Path:
    name = Path(filename).name
    if name != filename or not name.lower().endswith(".html"):
        raise HTTPException(status_code=404, detail=f"产物不存在: {filename}")
    root = _root()
    target = (root / name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"产物不存在: {filename}") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"产物不存在: {filename}")
    return target


@router.get("")
async def list_artifacts():
    root = _root()
    if not root.is_dir():
        return []
    files = sorted(
        (path for path in root.glob("*.html") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "fileName": path.name,
            "bytes": path.stat().st_size,
            "downloadUrl": f"/api/artifacts/{quote(path.name)}",
            "createdAt": datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        }
        for path in files
    ]


@router.get("/{filename}")
async def download_artifact(filename: str):
    target = _safe_file(filename)
    return FileResponse(
        target,
        media_type="text/html; charset=utf-8",
        filename=target.name,
        content_disposition_type="inline",
    )
