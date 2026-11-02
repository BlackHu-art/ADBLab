"""以辅助功能接口读取会话窗口，仅用 AppKit 定位本进程的投屏侧栏。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Any

import psutil

from services.remote.windowing.contracts import (
    NativeWindowSnapshot,
    PhysicalRect,
    _WindowSubscription,
)


def _load_macos() -> tuple[Any, Any, Any, Any]:
    """仅在 cocoa 后端实例化时加载现有 PyObjC 依赖，不在导入时打开原生资源。"""
    import AppKit
    import ApplicationServices
    import objc
    import Quartz

    return AppKit, ApplicationServices, Quartz, objc


def _physical_rect(rect: tuple[float, float, float, float], scale: float) -> PhysicalRect:
    x, y, width, height = rect
    return round(x * scale), round(y * scale), round(width * scale), round(height * scale)


def _cg_rect(info: Any) -> tuple[float, float, float, float] | None:
    if info is None:
        return None
    bounds = info.get("kCGWindowBounds", {})
    x, y, width, height = (float(bounds.get(name, float("inf"))) for name in (
        "X", "Y", "Width", "Height",
    ))
    rect = (x, y, width, height)
    return rect if all(map(isfinite, rect)) and width > 0 and height > 0 else None


@dataclass
class _Window:
    pid: int
    application: Any
    element: Any
    number: int = 0
    level: int = 0
    focused: bool = False
    needs_verification: bool = False


class MacOSWindowApi:
    """GUI 线程拥有 AX 引用；只读取本次进程树，关闭时释放全部窗口和应用引用。

    不请求或更改系统权限。缺少辅助功能授权时由工厂使用便携侧栏；短时 AX 超时
    抛出 OSError 保留已绑定身份，只有原生对象失效才允许跟踪器结束会话绑定。
    """

    def __init__(self, root_pid: int) -> None:
        self._appkit, self._ax, self._quartz, self._objc = _load_macos()
        if not self._appkit.NSThread.isMainThread():
            raise OSError("macOS 窗口跟随必须在 GUI 主线程初始化")
        if not self._ax.AXIsProcessTrusted():
            raise OSError("macOS 窗口跟随需要在系统设置中授予启动程序辅助功能权限")
        self._root_pid = root_pid
        self._parents: dict[int, int] = {}
        self._applications: dict[int, Any] = {}
        self._windows: dict[int, _Window] = {}
        self._next_handle = 1
        self._closed = False

    def process_parents(self) -> dict[int, int]:
        """只读取 PID 与父 PID，不读取命令行、路径或设备标识。"""
        self._parents = {
            process.info["pid"]: process.info["ppid"]
            for process in psutil.process_iter(["pid", "ppid"])
            if process.info["pid"] and process.info["ppid"] is not None
        }
        return self._parents

    def _belongs(self, pid: int) -> bool:
        visited: set[int] = set()
        while pid > 0 and pid not in visited:
            if pid == self._root_pid:
                return True
            visited.add(pid)
            pid = self._parents.get(pid, 0)
        return False

    def _attribute(self, element: Any, name: str) -> Any:
        error, value = self._ax.AXUIElementCopyAttributeValue(element, name, None)
        if error == self._ax.kAXErrorSuccess:
            return value
        if error in (
            self._ax.kAXErrorInvalidUIElement, self._ax.kAXErrorNoValue,
            self._ax.kAXErrorAttributeUnsupported,
        ):
            return None
        # 无响应或授权被撤销不等于窗口身份失效，避免永久丢失可恢复的镜像。
        raise OSError("macOS 镜像窗口暂时不可读取")

    def _set_timeout(self, element: Any) -> None:
        """AX 超时只属于当前引用；每个将被查询的应用和窗口引用必须分别设置。"""
        if self._ax.AXUIElementSetMessagingTimeout(element, 0.025) != self._ax.kAXErrorSuccess:
            raise OSError("无法限制 macOS 镜像窗口查询时间")

    def window_handles(self) -> list[int]:
        """只枚举本次进程树中已注册 GUI 应用的 AX 窗口，保留稳定的不透明身份。"""
        if self._closed:
            return []
        handles = []
        workspace = self._appkit.NSWorkspace.sharedWorkspace()
        for running in workspace.runningApplications():
            pid = int(running.processIdentifier())
            if not self._belongs(pid):
                continue
            application = self._applications.get(pid)
            if application is None:
                application = self._ax.AXUIElementCreateApplication(pid)
                # AX 消息跨进程同步调用；目标无响应时必须有界返回 GUI 事件循环。
                self._set_timeout(application)
                self._applications[pid] = application
            try:
                windows = self._attribute(application, "AXWindows") or ()
            except OSError:
                continue
            for element in windows:
                handle = next((
                    key for key, window in self._windows.items()
                    if window.pid == pid and window.element == element
                ), None)
                if handle is None:
                    self._set_timeout(element)
                    handle = self._next_handle
                    self._next_handle += 1
                    self._windows[handle] = _Window(pid, application, element)
                handles.append(handle)
        return handles

    def identity(self, hwnd: int) -> tuple[int, str] | None:
        """精确标题由 AX 读取，不需要屏幕录制权限，也不以无标题窗口猜测身份。"""
        window = self._windows.get(hwnd)
        if self._closed or window is None:
            return None
        title = self._attribute(window.element, "AXTitle")
        return (window.pid, title) if isinstance(title, str) else None

    def subscribe_changes(
        self, hwnd: int, pid: int, callback: Callable[[], None],
    ) -> _WindowSubscription | None:
        """仅为已发现且身份仍有效的会话窗口注册通知，调用方拥有并负责关闭订阅。"""
        window = self._windows.get(hwnd)
        if self._closed or window is None or window.pid != pid or self.identity(hwnd) is None:
            return None
        from services.remote.windowing.macos_events import MacOSWindowSubscription

        return MacOSWindowSubscription(
            self._ax, pid, window.application, window.element, callback,
            state_changed=lambda: setattr(window, "needs_verification", True),
        )

    def _rect(self, window: _Window) -> tuple[float, float, float, float] | None:
        position = self._attribute(window.element, "AXPosition")
        size = self._attribute(window.element, "AXSize")
        if position is None or size is None:
            return None
        valid_position, point = self._ax.AXValueGetValue(
            position, self._ax.kAXValueCGPointType, None,
        )
        valid_size, extent = self._ax.AXValueGetValue(size, self._ax.kAXValueCGSizeType, None)
        if not valid_position or not valid_size:
            return None
        rect = (float(point.x), float(point.y), float(extent.width), float(extent.height))
        return rect if all(map(isfinite, rect)) and rect[2] > 0 and rect[3] > 0 else None

    def _screen(self, rect: tuple[float, float, float, float]) -> tuple[Any, float]:
        screens = self._appkit.NSScreen.screens()
        if not screens:
            raise OSError("macOS 显示器工作区暂时不可用")
        primary_top = float(screens[0].frame().size.height)
        x, y, width, height = rect

        def rank(screen: Any) -> tuple[float, float]:
            frame = screen.frame()
            left = float(frame.origin.x)
            top = primary_top - float(frame.origin.y + frame.size.height)
            right, bottom = left + frame.size.width, top + frame.size.height
            area = max(0, min(x + width, right) - max(x, left)) * max(
                0, min(y + height, bottom) - max(y, top),
            )
            distance = (x + width / 2 - (left + right) / 2) ** 2 + (
                y + height / 2 - (top + bottom) / 2
            ) ** 2
            return area, -distance

        return max(screens, key=rank), primary_top

    def _window_info(self, window: _Window, rect: tuple[float, float, float, float]) -> Any:
        """首次按 AX 几何匹配 CG 编号，移动期间只查该编号，避免逐帧枚举整个桌面。"""
        cg = self._quartz
        if window.number:
            infos = cg.CGWindowListCopyWindowInfo(
                cg.kCGWindowListOptionIncludingWindow, window.number,
            )
            for info in infos or ():
                if (info.get("kCGWindowOwnerPID") == window.pid
                        and info.get("kCGWindowNumber") == window.number):
                    window.level = int(info.get("kCGWindowLayer", 0))
                    return info
            # 编号失效或被别的进程复用时，不得继续据此排列侧栏层级。
            window.number = window.level = 0
            return None
        infos = cg.CGWindowListCopyWindowInfo(cg.kCGWindowListOptionAll, cg.kCGNullWindowID)
        for info in infos or ():
            if info.get("kCGWindowOwnerPID") != window.pid:
                continue
            bounds = info.get("kCGWindowBounds", {})
            values = tuple(float(bounds.get(name, float("inf"))) for name in (
                "X", "Y", "Width", "Height",
            ))
            if all(abs(a - b) <= 1 for a, b in zip(values, rect)):
                window.number = int(info["kCGWindowNumber"])
                window.level = int(info.get("kCGWindowLayer", 0))
                return info
        return None

    def snapshot(self, hwnd: int) -> NativeWindowSnapshot | None:
        """读取完整状态；跟踪器在调用前后验证 AX 身份，已绑定几何由 CG 提供。"""
        window = self._windows.get(hwnd)
        if self._closed or window is None:
            return None
        info = self._window_info(window, (0, 0, 0, 0)) if window.number else None
        rect = _cg_rect(info) or self._rect(window)
        if rect is None:
            return None
        if info is None:
            info = self._window_info(window, rect)
        onscreen = info is not None and bool(info.get("kCGWindowIsOnscreen"))
        # 可见窗口不可能最小化；仅不可见时再问 AX，避免拖动中多次同步跨进程消息。
        minimized = not onscreen and bool(self._attribute(window.element, "AXMinimized"))
        hidden = not onscreen if info is not None else bool(
            self._attribute(window.application, "AXHidden"),
        )
        screen, primary_top = self._screen(rect)
        scale = float(screen.backingScaleFactor())
        work = screen.visibleFrame()
        work_rect = (work.origin.x, primary_top - work.origin.y - work.size.height,
                     work.size.width, work.size.height)
        front = self._appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        front_pid = int(front.processIdentifier()) if front is not None else 0
        foreground = front_pid == window.pid and (
            self._attribute(window.application, "AXFocusedWindow") == window.element
        )
        window.focused = foreground
        window.needs_verification = False
        return NativeWindowSnapshot(
            hwnd=hwnd, pid=window.pid,
            rect=_physical_rect(rect, scale),
            work_area=_physical_rect(work_rect, scale),
            visible=not hidden and (info is None or bool(info.get("kCGWindowIsOnscreen"))),
            minimized=minimized, foreground=foreground, topmost=window.level > 0,
            dpi=round(96 * scale), foreground_hwnd=hwnd if foreground else -front_pid,
        )

    def motion_snapshot(self, hwnd: int, pid: int) -> NativeWindowSnapshot | None:
        """移动只查已绑定 CG 编号；状态通知或编号失效交还完整 AX 核验，不授权输入。"""
        window = self._windows.get(hwnd)
        if (self._closed or window is None or window.pid != pid
                or not window.number or window.needs_verification):
            return None
        info = self._window_info(window, (0, 0, 0, 0))
        if info is None:
            return None
        rect = _cg_rect(info)
        if rect is None:
            return None
        screen, primary_top = self._screen(rect)
        scale = float(screen.backingScaleFactor())
        work = screen.visibleFrame()
        work_rect = (work.origin.x, primary_top - work.origin.y - work.size.height,
                     work.size.width, work.size.height)
        front = self._appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        front_pid = int(front.processIdentifier()) if front is not None else 0
        foreground = front_pid == pid and window.focused
        return NativeWindowSnapshot(
            hwnd=hwnd, pid=pid, rect=_physical_rect(rect, scale),
            work_area=_physical_rect(work_rect, scale),
            visible=bool(info.get("kCGWindowIsOnscreen")), minimized=False,
            foreground=foreground, topmost=window.level > 0, dpi=round(96 * scale),
            foreground_hwnd=hwnd if foreground else -front_pid,
        )

    def _tool_window(self, tool_hwnd: int) -> Any:
        # Qt 的 macOS winId 是 NSView 指针。只遍历本应用持有的视图，不解引用任意外部地址。
        for window in self._appkit.NSApplication.sharedApplication().windows():
            views = [window.contentView()]
            while views:
                view = views.pop()
                if view is not None:
                    if int(self._objc.pyobjc_id(view)) == tool_hwnd:
                        return window
                    views.extend(view.subviews())
        return None

    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect,
    ) -> bool:
        """仅定位本进程侧栏，不设置 AX 属性、不激活应用或调整镜像窗口。"""
        window = self._windows.get(owner.hwnd)
        if self._closed or window is None or window.pid != owner.pid or tool_hwnd <= 0:
            return False
        tool = self._tool_window(tool_hwnd)
        if tool is None or rect[2] <= 0 or rect[3] <= 0:
            return False
        screens = self._appkit.NSScreen.screens()
        if not screens:
            return False
        scale = owner.dpi / 96
        x, y, width, height = (value / scale for value in rect)
        y = screens[0].frame().size.height - y - height
        tool.setFrame_display_(self._appkit.NSMakeRect(x, y, width, height), True)
        if hasattr(tool, "setHidesOnDeactivate_"):
            # 镜像属于外部应用，激活镜像不应使 Qt 的 NSPanel 自动隐藏。
            tool.setHidesOnDeactivate_(False)
        tool.setLevel_(window.level)
        if window.number or owner.foreground:
            tool.orderWindow_relativeTo_(self._appkit.NSWindowAbove, window.number)
        return True

    def close(self) -> None:
        """幂等释放会话 AX 引用；调用方应先关闭其拥有的事件订阅。"""
        self._closed = True
        self._windows.clear()
        self._applications.clear()
        self._parents.clear()
