"""按内置工具、系统 PATH、不可用的顺序解析 ADB 路径。"""

import os
import shutil
import subprocess
import sys

from utils import adb_debug
from utils.resource_path import resource_path
from utils.runtime_tools import WINDOWS_TOOL_BUNDLE, bundled_tool_path

_adb_path: str | None = None
_resolved: bool = False

# Windows 下复用无控制台窗口标志，避免每次执行 ADB 时弹出命令行窗口。
CF = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def resolve_adb_path() -> str | None:
    """查找可用的 ADB 可执行文件，并在首次解析后缓存结果。

    Windows 优先内置 adb.exe；非 Windows 直接使用系统 PATH 中的 adb，
    避免把仓库内 Windows 二进制当成 adb 执行。
    """
    global _adb_path, _resolved
    if _resolved:
        adb_debug.event("resolve_result", selected_adb=_adb_path, cached=True)
        return _adb_path

    if adb_debug.enabled():
        adb_debug.event(
            "resolve_start", frozen=bool(getattr(sys, "frozen", False)),
            application=sys.executable, resource_root=resource_path(""),
        )
    if sys.platform == "win32":
        bundled = bundled_tool_path(WINDOWS_TOOL_BUNDLE, "adb.exe")
        exists = os.path.isfile(bundled)
        adb_debug.event("resolve_candidate", candidate=bundled, exists=exists)
        if exists:
            _adb_path = bundled
            _resolved = True
            if adb_debug.enabled():
                source_path = resource_path(os.path.join(WINDOWS_TOOL_BUNDLE, "adb.exe"))
                source = (
                    "bundled" if os.path.normcase(os.path.abspath(bundled)) == os.path.normcase(
                        os.path.abspath(source_path)
                    ) else "runtime_cache"
                )
                adb_debug.event(
                    "resolve_result", selected_adb=_adb_path, source=source, cached=False,
                )
            return _adb_path

    _adb_path = shutil.which("adb")
    _resolved = True
    adb_debug.event(
        "resolve_result", selected_adb=_adb_path, source="PATH" if _adb_path else "missing",
        cached=False,
    )
    return _adb_path


def adb_path() -> str:
    """返回已解析的 ADB 路径；不可用时回退为命令名 adb。"""
    path = resolve_adb_path()
    return path if path else "adb"
