"""协调本次 GUI 与投屏进程的显示后端，不持久化或修改系统会话。"""

from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path

_SDL_DRIVER_KEYS = ("SDL_VIDEO_DRIVER", "SDL_VIDEODRIVER")


def sdl_allows_x11(environment: Mapping[str, str]) -> bool:
    """仅未选驱动或明确一致选择 x11 时允许自动跟随；冲突及候选列表保守回退。"""
    return all(key not in environment or environment[key] == "x11" for key in _SDL_DRIVER_KEYS)


def _xcb_plugin_loadable() -> bool:
    """只探测当前 PySide6 的 xcb 插件依赖，避免缺库时强制选择导致 Qt 终止。

    不创建 Qt 应用或连接显示服务器；包路径兼容源码解释器和 PyInstaller 收集布局。
    """
    try:
        specification = importlib.util.find_spec("PySide6")
        if specification is None or specification.origin is None:
            return False
        package = Path(specification.origin).parent
        for relative in ("Qt/plugins/platforms/libqxcb.so", "plugins/platforms/libqxcb.so"):
            plugin = package / relative
            if plugin.is_file():
                ctypes.CDLL(str(plugin))
                return True
    except (ImportError, OSError, ValueError):
        return False
    return False


def configure_gui_platform(
    argv: Sequence[str], environment: MutableMapping[str, str] | None = None,
) -> bool:
    """在 QApplication 创建前选择本进程后端，并让启动图标继承 CLI 的优先选择。

    Linux 未显式选择 Qt/SDL 后端且已有 DISPLAY 和可加载插件时优先 xcb，连接失效
    仍由 Qt 尝试 Wayland。仅自动选择返回 True，调用者须在构造后将实际后端传给子进程；
    显式选择保持原样。此函数不设置全局 SDL 驱动或持久化标记。
    """
    if sys.platform != "linux":
        return False
    target = os.environ if environment is None else environment
    requested = None
    for index, argument in enumerate(argv[1:], start=1):
        if argument in {"-platform", "--platform"} and index + 1 < len(argv):
            requested = argv[index + 1]
    if requested is not None:
        # Qt 的 CLI 优先于环境；子进程没有父进程的 argv，必须继承相同选择。
        target["QT_QPA_PLATFORM"] = requested
        return False
    if "QT_QPA_PLATFORM" in target or not target.get("DISPLAY") or not sdl_allows_x11(target):
        return False
    if _xcb_plugin_loadable():
        target["QT_QPA_PLATFORM"] = "xcb;wayland"
        return True
    return False


def scrcpy_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """冻结投屏环境，仅为确定的 Linux xcb 启动补齐 SDL2/SDL3 的 X11 驱动。

    不修改调用者环境；任何显式非 x11 选择及两代变量冲突都保留，由便携工具栏承接。
    """
    result = dict(environment)
    qpa = result.get("QT_QPA_PLATFORM", "")
    if (
        sys.platform == "linux" and result.get("DISPLAY")
        and ";" not in qpa and qpa.partition(":")[0] == "xcb"
        and sdl_allows_x11(result)
    ):
        for key in _SDL_DRIVER_KEYS:
            result.setdefault(key, "x11")
    return result
