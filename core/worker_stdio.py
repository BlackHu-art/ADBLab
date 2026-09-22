"""为专用 worker 恢复 Windows 输出管道，并统一父子进程的 UTF-8 文本协议。"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import TextIO


def _open_windows_output(name: str) -> TextIO:
    """只拥有不可继承的副本；分阶段失败时由当前所有者释放资源。"""
    if sys.platform != "win32":
        raise OSError("Windows worker output is unavailable on this platform")
    import _winapi
    import msvcrt

    code = _winapi.STD_OUTPUT_HANDLE if name == "stdout" else _winapi.STD_ERROR_HANDLE
    original = _winapi.GetStdHandle(code)
    if original in (None, 0, -1, ctypes.c_void_p(-1).value):
        raise OSError(f"MobilePerf worker {name} pipe is unavailable")
    process = _winapi.GetCurrentProcess()
    duplicate = _winapi.DuplicateHandle(
        process, original, process, 0, False, _winapi.DUPLICATE_SAME_ACCESS,
    )
    try:
        descriptor = msvcrt.open_osfhandle(duplicate, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        _winapi.CloseHandle(duplicate)
        raise
    try:
        # CRT 已拥有副本；文本层再接管描述符，不能再次 CloseHandle。
        return os.fdopen(descriptor, "w", buffering=1, encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise


def prepare_worker_stdio() -> None:
    """在解析参数和导入日志前准备输出，不修改 stdin 或替换已有注入流。

    windowed Windows worker 缺少 Python 流时必须存在真实标准句柄；缺失或
    无法包装时直接失败，避免采集继续运行却丢失输出。成功安装的流由 sys
    持有至解释器退出，使异常和日志收尾仍可输出；重复调用不创建新的句柄。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None and sys.platform == "win32":
            stream = _open_windows_output(name)
            setattr(sys, name, stream)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", line_buffering=True)
