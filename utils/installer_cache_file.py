"""用 Windows 文件对象句柄锁住缓存校验、无覆盖发布和归属删除的完整窗口。"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO


def _api():
    """延迟加载 API，使非 Windows 仍可导入纯校验服务。"""

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetFinalPathNameByHandleW": ([wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                       wintypes.DWORD], wintypes.DWORD),
        "SetFileInformationByHandle": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD], wintypes.BOOL),
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _plain_path(path: Path) -> None:
    """拒绝所有祖先重解析点，不能用 resolve 隐藏 junction 或链接。"""

    if not path.is_absolute() or ".." in path.parts or ":" in str(path)[2:]:
        raise ValueError("Invalid installer cache path")
    for component in (path, *path.parents):
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("Installer cache path contains a reparse point")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Installer cache is not a regular file")


def _normal_windows_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    else:
        value = value.removeprefix("\\\\?\\")
    return os.path.normcase(os.path.abspath(value))


class _RenameInfo(ctypes.Structure):
    _fields_ = [
        ("ReplaceIfExists", ctypes.c_ubyte),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
        ("FileName", wintypes.WCHAR * 1),
    ]


class LockedCacheFile:
    """只打开身份匹配的普通文件；READ/DELETE 权限与仅共享 READ 同时约束所有修改者。

    文件与祖先目录无法在句柄存活时被替换或重命名。删除和重命名均作用于该对象，
    不重新用路径查找源；调用方必须先完成校验，且关闭句柄后才向外发布成功。
    """

    def __init__(self, path: Path, identity: tuple[int, int]) -> None:
        if sys.platform != "win32":
            raise OSError(errno.ENOTSUP, "Windows installer cache operations are unavailable")
        import msvcrt

        self.path = Path(os.path.abspath(path))
        self._stream: BinaryIO | None = None
        _plain_path(self.path)
        self._kernel = _api()
        # 申请读取及删除权限，仅共享读取；打开现有对象并拒绝跟随末级重解析点。
        handle = self._kernel.CreateFileW(
            str(self.path), 0x80010000, 1, None, 3, 0x00200000, None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            actual = ctypes.create_unicode_buffer(32768)
            count = self._kernel.GetFinalPathNameByHandleW(handle, actual, len(actual), 0)
            if not 0 < count < len(actual):
                raise OSError("Cannot resolve opened installer cache file")
            if _normal_windows_path(actual.value) != _normal_windows_path(str(self.path)):
                raise ValueError("Installer cache path changed")
            _plain_path(self.path)
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None
            try:
                self._stream = os.fdopen(descriptor, "rb", buffering=0)
            except BaseException:
                os.close(descriptor)
                raise
            metadata = os.fstat(self._stream.fileno())
            if (
                (metadata.st_dev, metadata.st_ino) != identity
                or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or getattr(metadata, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("Installer cache file identity changed")
        except BaseException:
            self.close()
            raise
        finally:
            if handle is not None:
                self._kernel.CloseHandle(handle)

    @property
    def stream(self) -> BinaryIO:
        """返回受同一共享限制保护的只读流；已关闭对象不可重用。"""

        if self._stream is None:
            raise ValueError("Installer cache handle is closed")
        return self._stream

    def _set_information(self, kind: int, buffer, size: int) -> None:
        import msvcrt

        handle = msvcrt.get_osfhandle(self.stream.fileno())
        if not self._kernel.SetFileInformationByHandle(handle, kind, buffer, size):
            raise ctypes.WinError(ctypes.get_last_error())

    def rename(self, target: Path) -> None:
        """同目录无覆盖发布；目标竞争由系统原子拒绝，不先 exists 再替换。"""

        target = Path(os.path.abspath(target))
        if target.parent != self.path.parent or ":" in target.name:
            raise ValueError("Installer cache publication must stay in the same directory")
        encoded = str(target).encode("utf-16-le")
        # API 要求结尾 NUL；长度字段只计 UTF-16 内容字节，不能计 Python 字符数。
        size = _RenameInfo.FileName.offset + len(encoded) + 2
        buffer = ctypes.create_string_buffer(size)
        info = ctypes.cast(buffer, ctypes.POINTER(_RenameInfo)).contents
        info.ReplaceIfExists = False
        info.RootDirectory = None
        info.FileNameLength = len(encoded)
        ctypes.memmove(
            ctypes.addressof(buffer) + _RenameInfo.FileName.offset, encoded, len(encoded),
        )
        self._set_information(3, buffer, size)
        self.path = target

    def delete(self) -> None:
        """对已核对身份的对象设置删除状态；最后句柄关闭时完成，不按路径 unlink。"""

        disposition = ctypes.c_ubyte(True)
        self._set_information(4, ctypes.byref(disposition), ctypes.sizeof(disposition))

    def close(self) -> None:
        """关闭唯一拥有的流及原生句柄；成功发布必须等待该调用完成。"""

        if self._stream is not None:
            stream, self._stream = self._stream, None
            stream.close()

    def __enter__(self) -> LockedCacheFile:
        return self

    def __exit__(self, *_args) -> None:
        self.close()
