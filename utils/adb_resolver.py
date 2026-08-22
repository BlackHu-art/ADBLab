"""按内置工具、系统 PATH、不可用的顺序解析 ADB 路径。"""

import os
import shutil
import subprocess
import sys

from utils.runtime_tools import bundled_tool_path

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
        return _adb_path

    if sys.platform == "win32":
        bundled = bundled_tool_path("scrcpy-win64-v3.3.1", "adb.exe")
        if os.path.isfile(bundled):
            _adb_path = bundled
            _resolved = True
            return _adb_path

    _adb_path = shutil.which("adb")
    _resolved = True
    return _adb_path


def adb_path() -> str:
    """返回已解析的 ADB 路径；不可用时回退为命令名 adb。"""
    path = resolve_adb_path()
    return path if path else "adb"
