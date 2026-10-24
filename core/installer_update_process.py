"""升级交接使用的 Windows 进程身份、文件共享和有界管道原语。"""

from __future__ import annotations

import ctypes
import os
import stat
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from threading import Event
from typing import IO


def _api():
    """延迟加载原生 API，显式声明指针宽度，非 Windows 不接触 WinDLL。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)],
                            wintypes.BOOL),
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "GetFinalPathNameByHandleW": ([wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                       wintypes.DWORD], wintypes.DWORD),
        "PeekNamedPipe": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                           ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p],
                          wintypes.BOOL),
    }
    for name, (args, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


class ParentProcess:
    """持有同一个进程对象；创建时间仅用于首次握手，不反复按 PID 查询。"""

    def __init__(self, pid: int, created: int | None = None):
        self._kernel = _api()
        self._handle = self._kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            values = [wintypes.FILETIME() for _ in range(4)]
            if not self._kernel.GetProcessTimes(self._handle, *map(ctypes.byref, values)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.created = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
            if created is not None and created != self.created:
                raise ValueError("parent identity mismatch")
        except BaseException:
            self.close()
            raise

    def wait(self, timeout: float) -> bool:
        """有界等待本进程对象终止，不终止或恢复任何进程。"""
        result = self._kernel.WaitForSingleObject(self._handle, max(0, int(timeout * 1000)))
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    @property
    def exit_code(self) -> int:
        result = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value

    def close(self) -> None:
        """只释放本对象所有的句柄；重复调用不产生副作用。"""
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def check_plain_path(path: Path) -> None:
    """不 resolve 掩盖重解析点；同时拒绝目录、设备和非规范文件路径。"""
    if not path.is_absolute() or ".." in path.parts or ":" in str(path)[2:]:
        raise ValueError("invalid file path")
    for item in (path, *path.parents):
        metadata = item.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("reparse path")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("not a regular file")


@contextmanager
def locked_file(path: Path):
    """拒绝写入和删除共享，并核对打开的实际路径；锁覆盖验证到启动。"""
    import msvcrt

    path = Path(path)
    check_plain_path(path)
    kernel = _api()
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        name = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, name, len(name), 0)
        if not 0 < length < len(name):
            raise OSError("cannot resolve opened file")
        actual = name.value.removeprefix("\\\\?\\")
        if os.path.normcase(actual) != os.path.normcase(str(path)):
            raise ValueError("opened file identity mismatch")
        check_plain_path(path)
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        with os.fdopen(descriptor, "rb") as stream:
            yield stream
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


def read_pipe_line(stream: IO[bytes], *, timeout: float, cancel: Event | None = None) -> bytes:
    """用原始管道避免缓冲预读；取消、EOF、超长和期限分别失败，不阻塞退出。"""
    import msvcrt

    descriptor = stream.fileno()
    handle = msvcrt.get_osfhandle(descriptor)
    kernel = _api()
    deadline = time.monotonic() + timeout
    result = bytearray()
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            raise InterruptedError("handoff cancelled")
        available = wintypes.DWORD()
        if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            if ctypes.get_last_error() in {109, 232}:
                raise EOFError("handoff channel closed")
            raise ctypes.WinError(ctypes.get_last_error())
        if available.value:
            char = os.read(descriptor, 1)
            if char == b"\n":
                return bytes(result).removesuffix(b"\r")
            if not char:
                raise EOFError("handoff channel closed")
            result.extend(char)
            if len(result) > 8192:
                raise ValueError("handoff message too large")
        else:
            time.sleep(0.01)
    raise TimeoutError("handoff deadline")
