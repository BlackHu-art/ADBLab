"""将设备内容写入明确的宿主路径，不让 ADB 递归解释设备提供的文件名。"""

from __future__ import annotations

import os
import posixpath
import re
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from core.exec import CommandRunner
from services.file_explorer import shell_quote


def local_child_path(
    directory: str, name: str, *, windows: bool | None = None, check_existing: bool = False,
) -> str:
    """GUI 仅做词法校验；后台落盘必须开启 check_existing，拒绝链接重定向。"""
    windows = os.name == "nt" if windows is None else windows
    if (not name or name in {".", ".."} or "/" in name or "\\" in name
            or any(char in name for char in "\0\r\n")):
        raise ValueError("文件名不能安全保存到本机，请先重命名。")
    if windows and (
        re.search(r'[<>:"|?*\x00-\x1f]', name)
        or name.endswith((".", " "))
        or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", name.split(".")[0], re.I)
    ):
        raise ValueError("文件名与 Windows 路径规则冲突，请先重命名。")
    root = Path(directory).resolve() if check_existing else Path(os.path.abspath(directory))
    child = root / name
    # 已存在的本地链接或 Windows junction 不能将下载重定向到另一位置。
    if check_existing and (child.is_symlink() or child.resolve() != child):
        raise ValueError("下载目标包含本地链接，请选择其他目录。")
    return str(child)


def default_save_path(directory: str, name: str) -> str:
    """非法设备名称不进入系统文件对话框；仍允许用户显式选择另存名称。"""
    try:
        return local_child_path(directory, name)
    except ValueError:
        return os.path.abspath(directory) + os.sep


class SafeFileDownload:
    """逐层校验目录，按原始字节下载普通文件；取消/失败不发布未完成文件。

    符号链接按目标内容下载，祖先目标循环拒绝；不在本地创建符号链接。目录批次失败时
    保留已完成文件，与既有部分成功语义一致。远端必须支持 find -print0 和 readlink -f。
    """

    def __init__(self, device: str, cancelled: Callable[[], bool], progress: Callable[[str], None]):
        self.device = device
        self.cancelled = cancelled
        self.progress = progress

    def _capture(self, command: str, path: Path, *, timeout: float = 120) -> None:
        if self.cancelled():
            raise InterruptedError("下载已取消")
        marker = f"ADBLAB_PULL_END_{uuid.uuid4().hex}".encode("ascii")
        command = f"({command}) && printf %s {shell_quote(marker.decode())}"
        result = CommandRunner.run_to_file(
            ["adb", "-s", self.device, "shell", "-T", command], str(path),
            timeout=timeout, cancelled=self.cancelled,
        )
        if self.cancelled():
            raise InterruptedError("下载已取消")
        if not result.success:
            raise OSError("设备下载失败，请检查连接和读取权限。")
        # 兼容旧设备不传播 shell 退出码；确认完整尾标记后才允许发布正文。
        with path.open("r+b") as stream:
            size = stream.seek(0, os.SEEK_END)
            if size < len(marker):
                raise OSError("设备未返回完整文件。")
            stream.seek(-len(marker), os.SEEK_END)
            if stream.read() != marker:
                raise OSError("设备未返回完整文件。")
            stream.truncate(size - len(marker))

    def download(self, remote: str, destination: str) -> None:
        """destination 为精确目标路径，既有目录直接合并，不额外附加设备 basename。"""
        if not remote.startswith("/") or any(char in remote for char in "\0\r\n"):
            raise ValueError("设备路径无效，请刷新文件列表。")
        remote = posixpath.normpath("/" + remote.lstrip("/"))
        target = Path(destination).absolute()
        # 单文件另存为可采用用户命名，但现有链接仍不能改变落盘归属。
        target = Path(local_child_path(str(target.parent), target.name, check_existing=True))
        with tempfile.TemporaryDirectory(prefix="adblab-pull-") as temporary:
            self._copy(remote, target, Path(temporary) / "metadata", frozenset())

    def _copy(self, remote: str, target: Path, metadata: Path, ancestors: frozenset[str]) -> None:
        if self.cancelled():
            raise InterruptedError("下载已取消")
        quoted = shell_quote(remote)
        self._capture(
            f"if [ -d {quoted} ]; then readlink -f -- {quoted}; "
            f"elif [ -f {quoted} ]; then printf FILE; else exit 1; fi",
            metadata, timeout=30,
        )
        with metadata.open("rb") as stream:
            kind = stream.read(8193)
        if len(kind) > 8192:
            raise ValueError("设备目录信息过长。")
        if kind != b"FILE":
            canonical = kind.decode("utf-8", errors="strict").removesuffix("\n")
            if (not canonical.startswith("/") or "\n" in canonical or "\r" in canonical
                    or "\0" in canonical or canonical in ancestors or len(ancestors) >= 128):
                raise ValueError("设备目录循环或路径无效，已停止下载。")
            # NUL 分隔避免空白、换行和伪造 ls 行改变子项边界；整层先验证再落盘。
            self._capture(
                f"find {shell_quote(remote.rstrip('/') + '/')} -mindepth 1 -maxdepth 1 -print0",
                metadata, timeout=30,
            )
            with metadata.open("rb") as stream:
                raw = stream.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024 or raw and not raw.endswith(b"\0"):
                raise ValueError("设备目录列表不完整或过大。")
            names = []
            seen: set[str] = set()
            prefix = remote.rstrip("/") + "/"
            for encoded in raw.split(b"\0")[:-1]:
                child = encoded.decode("utf-8", errors="strict")
                if not child.startswith(prefix):
                    raise ValueError("设备目录列表包含越界路径。")
                name = child[len(prefix):]
                local = Path(local_child_path(str(target), name, check_existing=True))
                key = os.path.normcase(str(local))
                if key in seen:
                    raise ValueError("设备目录包含本机无法区分的重名条目。")
                seen.add(key)
                names.append((name, local))
            target.mkdir(exist_ok=True)
            for name, local in names:
                self._copy(posixpath.join(remote, name), local, metadata, ancestors | {canonical})
            return
        descriptor, temporary = tempfile.mkstemp(prefix=".adblab-pull-", dir=target.parent)
        try:
            os.close(descriptor)
            self._capture(f"[ -f {quoted} ] && cat -- {quoted}", Path(temporary), timeout=3600)
            if self.cancelled():
                raise InterruptedError("下载已取消")
            os.replace(temporary, target)
            self.progress("文件下载完成")
        finally:
            Path(temporary).unlink(missing_ok=True)
