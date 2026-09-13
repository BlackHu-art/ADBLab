"""按内置工具、显式环境变量、Android SDK 和系统 PATH 的顺序解析 ADB 路径。"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from utils import adb_debug
from utils.resource_path import resource_path
from utils.runtime_tools import WINDOWS_TOOL_BUNDLE, bundled_tool_path

_adb_path: str | None = None
_resolved: bool = False

# 用户选定的客户端："auto" 表示按候选顺序自动选择，其余为命名来源或绝对路径。
CLIENT_PREFERENCE_AUTO = "auto"
CLIENT_SOURCE_TOKENS = frozenset({
    CLIENT_PREFERENCE_AUTO, "bundled", "runtime_cache", "env", "sdk_home", "sdk_root",
    "sdk_local", "PATH",
})
SDK_SOURCE_TOKENS = frozenset({"sdk_home", "sdk_root", "sdk_local"})
_client_preference = CLIENT_PREFERENCE_AUTO


@dataclass(frozen=True)
class AdbCandidate:
    """一个候选 ADB 客户端；不存在的候选也保留，供界面解释"为什么没识别到"。"""

    source: str
    path: str

    @property
    def exists(self) -> bool:
        """PATH 来源由 shutil.which 保证存在，其余按文件系统判断。"""

        if self.source in _PRE_VALIDATED_SOURCES:
            return True
        return bool(self.path) and os.path.isfile(self.path)


def set_client_preference(value: object) -> str:
    """注入用户选定的客户端来源或绝对路径，并让下一次解析重新开始。"""

    global _client_preference
    text = str(value).strip() if value is not None else ""
    _client_preference = text or CLIENT_PREFERENCE_AUTO
    invalidate_adb_path_cache()
    return _client_preference


def client_preference() -> str:
    """返回当前注入的客户端选择；默认自动。"""

    return _client_preference


# Windows 下复用无控制台窗口标志，避免每次执行 ADB 时弹出命令行窗口。
CF = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def invalidate_adb_path_cache() -> None:
    """清除解析缓存，使下一次解析重新扫描全部候选。

    显式「重新检测」或切换客户端路径后必须调用：否则进程内会一直复用首次解析
    结果，启动时未安装的 platform-tools 在用户安装后也不会被识别。
    """

    global _adb_path, _resolved
    _adb_path = None
    _resolved = False


def _adb_executable_name() -> str:
    """返回当前平台使用的 ADB 可执行文件名。"""

    return "adb.exe" if sys.platform == "win32" else "adb"


def _bundled_candidate() -> tuple[str, str]:
    """返回 Windows 内置候选；来源区分随包资源与 onefile 运行时缓存副本。"""

    bundled = bundled_tool_path(WINDOWS_TOOL_BUNDLE, "adb.exe")
    source_path = resource_path(os.path.join(WINDOWS_TOOL_BUNDLE, "adb.exe"))
    source = (
        "bundled" if os.path.normcase(os.path.abspath(bundled)) == os.path.normcase(
            os.path.abspath(source_path)
        ) else "runtime_cache"
    )
    return source, bundled


def _environment_candidate() -> tuple[str, str] | None:
    """读取显式 ADB_PATH 环境变量；Windows 上它排在内置客户端之后。"""

    value = os.environ.get("ADB_PATH", "").strip()
    return ("env", value) if value else None


def _sdk_candidates() -> list[tuple[str, str]]:
    """按 Android SDK 环境变量推导 platform-tools 下的候选，只读环境变量不扫盘。"""

    roots = [
        ("sdk_home", os.environ.get("ANDROID_HOME", "")),
        ("sdk_root", os.environ.get("ANDROID_SDK_ROOT", "")),
    ]
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            roots.append(("sdk_local", os.path.join(local_app_data, "Android", "Sdk")))
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source, root in roots:
        text = str(root).strip()
        if not text:
            continue
        path = os.path.join(text, "platform-tools", _adb_executable_name())
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        candidates.append((source, path))
    return candidates


# shutil.which 只返回已存在的可执行文件，不需要再次查询文件系统。
_PRE_VALIDATED_SOURCES = frozenset({"PATH"})


def _candidates() -> list[tuple[str, str]]:
    """返回有序候选：Windows 内置 → ADB_PATH → Android SDK → 系统 PATH。"""

    candidates: list[tuple[str, str]] = []
    if sys.platform == "win32":
        candidates.append(_bundled_candidate())
    environment = _environment_candidate()
    if environment is not None:
        candidates.append(environment)
    candidates.extend(_sdk_candidates())
    found = shutil.which("adb")
    if found:
        candidates.append(("PATH", found))
    return candidates


def list_adb_candidates() -> list[AdbCandidate]:
    """返回设置界面展示并可探测的候选（含不可用项）。

    只包含应用内置、环境变量 ADB_PATH 与系统 PATH：Android SDK 位置仍留在
    自动解析链里做兜底，但不参与界面展示与版本探测，避免冷启动时逐个启动
    多个 adb 客户端拖慢识别。
    """

    return [
        AdbCandidate(source, path)
        for source, path in _candidates()
        if source not in SDK_SOURCE_TOKENS
    ]


def _preferred_candidates(
    candidates: list[tuple[str, str]], preferred: str,
) -> list[tuple[str, str]]:
    """按用户选择过滤候选；绝对路径只保留该文件，缺失时不静默换用其它 adb。"""

    if os.path.isabs(preferred):
        return [("custom", preferred)]
    return [item for item in candidates if item[0] == preferred]


def resolve_adb_path() -> str | None:
    """查找可用的 ADB 可执行文件，并在首次解析后缓存结果。

    Windows 先看内置 adb.exe，再按显式 ADB_PATH、Android SDK platform-tools、系统
    PATH 的顺序兜底；非 Windows 直接使用环境中的 adb，避免把仓库内 Windows 二进制
    当成 adb 执行。需要重新扫描时先调用 invalidate_adb_path_cache()。
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
    selected: str | None = None
    source = "missing"
    candidates = _candidates()
    if _client_preference != CLIENT_PREFERENCE_AUTO:
        candidates = _preferred_candidates(candidates, _client_preference)
    for name, candidate in candidates:
        exists = name in _PRE_VALIDATED_SOURCES or bool(candidate) and os.path.isfile(candidate)
        adb_debug.event("resolve_candidate", source=name, candidate=candidate, exists=exists)
        if exists:
            selected, source = candidate, name
            break
    _adb_path = selected
    _resolved = True
    adb_debug.event("resolve_result", selected_adb=selected, source=source, cached=False)
    return _adb_path


def adb_path() -> str:
    """返回已解析的 ADB 路径；不可用时回退为命令名 adb。"""

    path = resolve_adb_path()
    return path if path else "adb"
