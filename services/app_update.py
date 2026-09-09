"""校验公开正式发布信息并比较版本，不执行网络、文件或界面操作。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from utils.app_metadata import APP_RELEASES_URL

ReleaseStatus = Literal["available", "current", "ahead"]
UpdateStatus = Literal["idle", "checking", "available", "current", "ahead", "error"]
UpdateError = Literal[
    "", "network", "tls", "timeout", "rate_limited", "unavailable", "invalid_response",
]
_VERSION = re.compile(r"v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")


@dataclass(frozen=True)
class ReleaseInfo:
    """经过版本和链接校验的正式发布；日期保留服务端时区。"""

    version: str
    url: str
    published_at: datetime


@dataclass(frozen=True)
class UpdateSnapshot:
    """本次检查状态；重试失败仍保留上次确认的发布，状态明确标记为失败。"""

    status: UpdateStatus = "idle"
    release: ReleaseInfo | None = None
    checked_at: datetime | None = None
    error: UpdateError = ""
    can_check: bool = True


def _version_parts(value: object) -> tuple[int, int, int]:
    """只接受现行三段数字版本，拒绝预发布后缀、Unicode 数字及多余字符。"""

    if not isinstance(value, str) or (match := _VERSION.fullmatch(value)) is None:
        raise ValueError("Invalid stable version")
    return int(match[1]), int(match[2]), int(match[3])


def parse_release(payload: object) -> ReleaseInfo:
    """只接受正式发布及同仓库、同标签的 HTTPS 页面，异常信息不能生成可点击链接。"""

    if not isinstance(payload, dict):
        raise ValueError("Invalid release object")
    if payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise ValueError("Not a published stable release")
    tag = payload.get("tag_name")
    parts = _version_parts(tag)
    url = payload.get("html_url")
    if not isinstance(url, str) or url != f"{APP_RELEASES_URL}/tag/{tag}":
        raise ValueError("Invalid release page")
    published = payload.get("published_at")
    if not isinstance(published, str):
        raise ValueError("Invalid publication date")
    published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
    if published_at.tzinfo is None:
        raise ValueError("Publication date must include timezone")
    return ReleaseInfo(".".join(str(part) for part in parts), url, published_at)


def release_status(release: ReleaseInfo, current_version: str) -> ReleaseStatus:
    """比较数值版本；本地领先时单独呈现，避免暗示用户降级。"""

    current = _version_parts(current_version)
    remote = _version_parts(release.version)
    if remote > current:
        return "available"
    return "current" if remote == current else "ahead"
