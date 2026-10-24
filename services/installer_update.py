"""管理本次安装包的有界缓存与完整性校验，不联网、不授权关闭或执行安装器。"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from services.app_update import InstallerAsset, validate_installer_asset
from utils.installer_cache_file import LockedCacheFile
from utils.user_data import user_data_root

CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class VerifiedInstaller:
    """本次校验结果；执行前必须重新校验，路径不是可持久化的执行授权。"""

    path: Path
    asset: InstallerAsset


def _checked_path(path: Path, *, missing: bool = False) -> Path:
    """检查全部现存祖先及目标，拒绝 symlink、junction 和其他重解析点。"""

    path = Path(os.path.abspath(path))
    for component in (*reversed(path.parents), path):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("Installer path contains a reparse point")
        if component != path and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("Installer ancestor is not a directory")
    return path


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _regular(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        raise ValueError("Installer must be an unlinked regular file")


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise InterruptedError("Installer verification cancelled")


def _verify_stream(
    stream: BinaryIO, asset: InstallerAsset, cancelled: Callable[[], bool] | None,
) -> None:
    """在调用方拥有的文件句柄内校验内容，不为发布而重新打开路径。"""

    before = os.fstat(stream.fileno())
    _regular(before)
    if before.st_size != asset.size:
        raise ValueError("Installer size mismatch")
    digest = hashlib.sha256()
    received = 0
    while True:
        _check_cancelled(cancelled)
        block = stream.read(CHUNK_BYTES)
        if not block:
            break
        received += len(block)
        if received > asset.size:
            raise ValueError("Installer size exceeded")
        digest.update(block)
    after = os.fstat(stream.fileno())
    if (
        before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ValueError("Installer changed during verification")
    if received != asset.size or digest.hexdigest() != asset.sha256:
        raise ValueError("Installer digest mismatch")


def verify_download(
    path: Path, asset: InstallerAsset, *, cancelled: Callable[[], bool] | None = None,
) -> VerifiedInstaller:
    """逐块重读普通文件，绑定同一文件身份、精确大小与摘要；磁盘失败原样传播。

    调用方须在后台线程执行。取消每块检查；此函数不取代交接端覆盖校验到执行窗口的文件锁。
    """

    validate_installer_asset(asset)
    _check_cancelled(cancelled)
    path = _checked_path(path)
    before = path.lstat()
    _regular(before)
    if before.st_size != asset.size:
        raise ValueError("Installer size mismatch")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb", buffering=0) as stream:
        opened = os.fstat(stream.fileno())
        _regular(opened)
        if _identity(opened) != _identity(before):
            raise ValueError("Installer file was replaced")
        _verify_stream(stream, asset, cancelled)
        _checked_path(path)
        current = path.lstat()
        _regular(current)
        if (
            _identity(current) != _identity(opened)
            or before.st_size != current.st_size or before.st_mtime_ns != current.st_mtime_ns
            or before.st_ctime_ns != current.st_ctime_ns
        ):
            raise ValueError("Installer changed during verification")
    return VerifiedInstaller(path, asset)


def _cache_root(root: Path | None) -> Path:
    return _checked_path(user_data_root() / "updates" if root is None else root, missing=True)


class DownloadWriter:
    """单次下载独占随机目录；仅成功校验后发布，失败调用 cancel 释放自己的临时文件。

    所有方法由同一后台 owner 串行调用；不递归清缓存，不清除历史 ready 或未知替换文件。
    """

    def __init__(self, asset: InstallerAsset, cache_root: Path | None = None) -> None:
        validate_installer_asset(asset)
        self.asset = asset
        root = _cache_root(cache_root)
        root.mkdir(parents=True, exist_ok=True)
        _checked_path(root)
        self._directory = Path(tempfile.mkdtemp(prefix="download-", dir=root))
        _checked_path(self._directory)
        self._part = self._directory / "installer.part"
        self._stream: BinaryIO | None = self._part.open("xb", buffering=0)
        self._file_identity = _identity(os.fstat(self._stream.fileno()))
        self._received = 0
        self._finished = False
        self._cancelled = False

    def write(self, block: bytes) -> None:
        """最多接收一块，拒绝超出发布大小；写入失败不能推进已接收计数。"""

        if self._stream is None or self._finished or self._cancelled:
            raise ValueError("Installer download is no longer writable")
        if not isinstance(block, bytes) or len(block) > CHUNK_BYTES:
            raise ValueError("Invalid installer chunk")
        if self._received + len(block) > self.asset.size:
            raise ValueError("Installer size exceeded")
        _checked_path(self._part)
        if _identity(self._part.lstat()) != self._file_identity:
            raise ValueError("Installer temporary file was replaced")
        if self._stream.write(block) != len(block):
            raise OSError("Incomplete installer write")
        self._received += len(block)

    def finish(self, *, cancelled: Callable[[], bool] | None = None) -> VerifiedInstaller:
        """落盘后在 Windows 同一对象句柄内校验并发布；其他平台保留 part 并拒绝发布。"""

        if self._stream is None or self._finished or self._cancelled:
            raise ValueError("Installer download is not active")
        if self._received != self.asset.size:
            raise ValueError("Installer download is incomplete")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        self._stream = None
        if sys.platform != "win32":
            verify_download(self._part, self.asset, cancelled=cancelled)
            raise OSError(errno.ENOTSUP, "Windows installer cache publication is unavailable")
        ready = self._directory / self.asset.name
        _checked_path(ready, missing=True)
        with LockedCacheFile(self._part, self._file_identity) as locked:
            _verify_stream(locked.stream, self.asset, cancelled)
            _check_cancelled(cancelled)
            locked.rename(ready)
        self._finished = True
        return VerifiedInstaller(ready, self.asset)

    def cancel(self) -> None:
        """幂等关闭句柄；Windows 只按匹配身份删除对象，其他平台保留 part，均保留 ready。"""

        if self._cancelled or self._finished:
            return
        self._cancelled = True
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        if sys.platform != "win32":
            # 不支持的平台没有按对象删除协议；保留 part，不能用路径删除冒充归属保证。
            return
        try:
            _checked_path(self._part)
            with LockedCacheFile(self._part, self._file_identity) as locked:
                locked.delete()
        except (FileNotFoundError, ValueError):
            # 路径已消失或归属无法证明时，不通过该路径删除任何文件。
            return


def find_cached(
    asset: InstallerAsset, cache_root: Path | None = None,
    *, cancelled: Callable[[], bool] | None = None,
) -> VerifiedInstaller | None:
    """按调用方刚确认的资产重新校验旧缓存；不读取缓存元数据来授予下载或安装资格。"""

    validate_installer_asset(asset)
    root = _cache_root(cache_root)
    if not root.exists():
        return None
    for directory in root.iterdir():
        _check_cancelled(cancelled)
        if not directory.name.startswith("download-"):
            continue
        try:
            return verify_download(directory / asset.name, asset, cancelled=cancelled)
        except InterruptedError:
            raise
        except (ValueError, OSError):
            # 单个旧目录损坏、被替换或不可访问不妨碍启动新的独立下载。
            continue
    return None
