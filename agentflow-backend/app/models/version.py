"""版本契约：不可变发布快照 + 运行上下文清单。

设计口径（R6.0）：
- 草稿层（agents / flows 表）可编辑、自动保存；
- 发布层（agent_versions / flow_versions）只追加，版本号按资源独立递增；
- 运行时使用「当前保存的版本」，版本清单只做溯源与评测定位，不反向限制运行。
"""
from typing import Any, Literal

from pydantic import Field

from app.models.flow import CamelModel

VersionKind = Literal["agent", "flow"]


class VersionSummary(CamelModel):
    id: str
    kind: VersionKind
    resource_id: str
    version: int
    config_hash: str
    bundle_hash: str
    code_commit: str | None = None
    code_dirty: bool = False
    name: str = ""
    note: str = ""
    restored_from: int | None = None
    created_at: str
    manifest: dict[str, Any] = Field(default_factory=dict)


class VersionDetail(VersionSummary):
    """snapshot 是该版本的完整配置快照，前端直接展示，不做 diff。"""

    snapshot: dict[str, Any]


class PublishRequest(CamelModel):
    # 版本名必填（接口层校验，空串返回 VERSION_NAME_REQUIRED）；说明可留空
    name: str = ""
    note: str = ""


class RollbackRequest(CamelModel):
    version: int


class PublishState(CamelModel):
    published_version: int = 0
    published_hash: str | None = None
    draft_hash: str | None = None
    ahead: bool = False
    unpublished: bool = False
    version_count: int = 0
    # 历史最大版本号：指针可能因回滚小于它，用于页面提示「已回滚 · 最高 vN」
    latest_version: int = 0
    last_published_at: str | None = None


class ResourceVersionState(CamelModel):
    """版本管理页左侧列表的一行。"""

    kind: VersionKind
    id: str
    name: str
    publish: PublishState
