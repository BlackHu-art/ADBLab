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
_SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class ReleaseInfo:
    """经过版本和链接校验的正式发布；日期保留服务端时区。"""

    version: str
    url: str
    published_at: datetime


@dataclass(frozen=True)
class InstallerAsset:
    """固定官方发布响应中的安装资产；摘要只提供 GitHub/TLS 信任模型下的完整性。"""

    release_id: int
    asset_id: int
    tag: str
    version: str
    name: str
    download_url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class UpdateSnapshot:
    """本次检查状态；重试失败仍保留上次确认的发布，状态明确标记为失败。"""

    status: UpdateStatus = "idle"
    release: ReleaseInfo | None = None
    checked_at: datetime | None = None
    error: UpdateError = ""
    can_check: bool = True
    installer_asset: InstallerAsset | None = None


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


def validate_installer_asset(asset: InstallerAsset) -> None:
    """重新验证跨组件传递的资产，不能把 dataclass 或缓存字段本身当作信任凭据。"""

    if not isinstance(asset, InstallerAsset):
        raise ValueError("Invalid installer asset")
    version = ".".join(str(part) for part in _version_parts(asset.version))
    if asset.version != version or asset.tag not in (version, f"v{version}"):
        raise ValueError("Installer version mismatch")
    if any(type(value) is not int or value <= 0 for value in (asset.release_id, asset.asset_id)):
        raise ValueError("Invalid installer identity")
    if type(asset.size) is not int or not 0 < asset.size <= MAX_INSTALLER_BYTES:
        raise ValueError("Invalid installer size")
    name = f"ADBLab-win-x64-v{version}-setup.exe"
    expected_url = f"{APP_RELEASES_URL}/download/{asset.tag}/{name}"
    if asset.name != name or asset.download_url != expected_url:
        raise ValueError("Invalid installer download URL")
    if not isinstance(asset.sha256, str) or _SHA256.fullmatch(asset.sha256) is None:
        raise ValueError("Invalid installer digest")


def parse_installer_asset(payload: object, release: ReleaseInfo) -> InstallerAsset:
    """只接受与当前发布同一次响应绑定的唯一安装资产；失败不改变浏览器发布契约。"""

    if not isinstance(payload, dict) or parse_release(payload) != release:
        raise ValueError("Installer release mismatch")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Missing installer assets")
    name = f"ADBLab-win-x64-v{release.version}-setup.exe"
    candidates = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
    if len(candidates) != 1:
        raise ValueError("Missing or ambiguous installer")
    candidate = candidates[0]
    digest = candidate.get("digest")
    if candidate.get("state") != "uploaded" or not isinstance(digest, str):
        raise ValueError("Installer is not ready")
    if not digest.startswith("sha256:"):
        raise ValueError("Missing SHA256 installer digest")
    release_id, asset_id = payload.get("id"), candidate.get("id")
    tag, download_url = payload.get("tag_name"), candidate.get("browser_download_url")
    size = candidate.get("size")
    if (
        type(release_id) is not int or type(asset_id) is not int or type(size) is not int
        or not isinstance(tag, str) or not isinstance(download_url, str)
    ):
        raise ValueError("Invalid installer metadata fields")
    asset = InstallerAsset(
        release_id=release_id, asset_id=asset_id, tag=tag, version=release.version, name=name,
        download_url=download_url, size=size, sha256=digest[7:].lower(),
    )
    validate_installer_asset(asset)
    return asset
