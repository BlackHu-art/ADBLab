"""按本次进程归属跟踪 scrcpy 窗口，并提供无焦点的原生侧栏定位。"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

_LOGGER = logging.getLogger(__name__)
PhysicalRect = tuple[int, int, int, int]


@dataclass(frozen=True)
class NativeWindowSnapshot:
    """窗口状态；矩形统一为桌面物理像素的 x、y、宽、高。"""

    hwnd: int
    pid: int
    rect: PhysicalRect
    work_area: PhysicalRect
    visible: bool
    minimized: bool
    foreground: bool
    topmost: bool
    dpi: int = 96
    foreground_hwnd: int = 0


class _WindowApi(Protocol):
    """隔离原生读取和定位，使身份决策不依赖 GUI 或外部命令。"""

    def process_parents(self) -> dict[int, int]: ...
    def window_handles(self) -> list[int]: ...
    def identity(self, hwnd: int) -> tuple[int, str] | None: ...
    def snapshot(self, hwnd: int) -> NativeWindowSnapshot | None: ...
    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect
    ) -> bool: ...


class WindowsWindowTracker:
    """复用原生 API 绑定启动进程及其后代窗口；失效后永久结束，调用方负责关闭。"""

    def __init__(
        self,
        root_pid: int,
        title: str,
        *,
        api: _WindowApi | None = None,
        clock: Callable[[], float] = time.monotonic,
        discovery_interval_seconds: float = 0.25,
    ):
        self._root_pid = root_pid
        self._title = title
        self._api = api
        if api is None and sys.platform == "win32":
            self._api = _Win32WindowApi()
        self._clock = clock
        self._discovery_interval = max(0.05, discovery_interval_seconds)
        self._next_discovery = float("-inf")
        self._bound: tuple[int, int] | None = None
        self._lost = False

    @property
    def supported(self) -> bool:
        """当前平台是否具有原生窗口能力。"""
        return self._api is not None

    @property
    def lost(self) -> bool:
        """已绑定身份是否失效；首次窗口尚未出现不属于失效。"""
        return self._lost

    def close(self) -> None:
        """会话结束时撤销绑定并释放自有原生连接；重复关闭不重复释放。"""
        api, self._api = self._api, None
        self._bound = None
        self._lost = True
        close = getattr(api, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                _LOGGER.debug("关闭投屏窗口连接失败", exc_info=True)

    def snapshot(self) -> NativeWindowSnapshot | None:
        """同步读取一次状态，不等待窗口出现；初始发现节流且不启动外部命令。"""
        api = self._api
        if api is None or self._lost or self._root_pid <= 0 or not self._title:
            return None
        try:
            if self._bound is None:
                now = self._clock()
                if now < self._next_discovery:
                    return None
                self._next_discovery = now + self._discovery_interval
                parents = api.process_parents()
                for hwnd in api.window_handles():
                    identity = api.identity(hwnd)
                    if identity is None or identity[1] != self._title:
                        continue
                    if not self._belongs_to_session(identity[0], parents):
                        continue
                    snapshot = api.snapshot(hwnd)
                    if snapshot is not None and snapshot.pid == identity[0]:
                        if api.identity(hwnd) == identity:
                            self._bound = (hwnd, identity[0])
                            return snapshot
                return None
            hwnd, pid = self._bound
            if api.identity(hwnd) != (pid, self._title):
                self._lost = True
                return None
            snapshot = api.snapshot(hwnd)
            # 几何查询可能短暂失败；仅身份变化才终止，避免把最小化当成退出。
            if api.identity(hwnd) != (pid, self._title):
                self._lost = True
                return None
            if snapshot is None or snapshot.pid != pid:
                return None
            return snapshot
        except OSError:
            _LOGGER.debug("读取投屏窗口状态失败", exc_info=True)
            return None

    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect
    ) -> bool:
        """仅定位本跟踪实例的侧栏；不显示、激活或改变 scrcpy 本身的位置。"""
        api = self._api
        if api is None or self._lost or self._bound != (owner.hwnd, owner.pid):
            return False
        if tool_hwnd <= 0 or rect[2] <= 0 or rect[3] <= 0:
            return False
        current = self.snapshot()
        if current is None or not current.visible or current.minimized:
            return False
        try:
            return api.position_tool(tool_hwnd, current, rect)
        except OSError:
            _LOGGER.debug("定位投屏侧栏失败", exc_info=True)
            return False

    def _belongs_to_session(self, pid: int, parents: dict[int, int]) -> bool:
        """沿一次进程快照回溯，兼容冻结入口和 venv 的多级启动进程。"""
        visited: set[int] = set()
        while pid > 0 and pid not in visited:
            if pid == self._root_pid:
                return True
            visited.add(pid)
            pid = parents.get(pid, 0)
        return False


def create_window_tracker(
    root_pid: int, title: str, *, platform_name: str,
) -> WindowsWindowTracker:
    """仅为能定位工具窗及镜像的后端创建跟踪器；其余交给便携工具栏。

    GUI 提供已经创建的 Qt 后端名称，不能仅凭 Wayland 会话中也存在 DISPLAY 就使用
    X11 句柄。显式 SDL 非 x11 选择保留，原生连接由返回的跟踪器负责关闭。
    """
    api = None
    if sys.platform == "linux" and platform_name == "xcb":
        from utils.gui_platform import sdl_allows_x11

        if sdl_allows_x11(os.environ) and ";" not in os.environ.get("QT_QPA_PLATFORM", ""):
            from services.remote.x11_window_tracking import X11WindowApi

            try:
                api = X11WindowApi()
            except OSError:
                _LOGGER.debug("X11 窗口跟随不可用，使用便携工具栏", exc_info=True)
    return WindowsWindowTracker(root_pid, title, api=api)


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _Win32WindowApi:
    """显式声明指针宽度；所有 HWND 操作都在调用方 GUI 线程短时完成。"""

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user = self._user32
        user.EnumWindows.argtypes = [self._enum_callback, wintypes.LPARAM]
        user.EnumWindows.restype = wintypes.BOOL
        user.IsWindow.argtypes = [wintypes.HWND]
        user.IsWindow.restype = wintypes.BOOL
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.IsWindowVisible.restype = wintypes.BOOL
        user.IsIconic.argtypes = [wintypes.HWND]
        user.IsIconic.restype = wintypes.BOOL
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowThreadProcessId.restype = wintypes.DWORD
        user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user.GetWindowTextLengthW.restype = ctypes.c_int
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.GetWindowTextW.restype = ctypes.c_int
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetWindowRect.restype = wintypes.BOOL
        user.GetForegroundWindow.argtypes = []
        user.GetForegroundWindow.restype = wintypes.HWND
        user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.MonitorFromWindow.restype = wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
        user.GetMonitorInfoW.restype = wintypes.BOOL
        user.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user.SetWindowPos.restype = wintypes.BOOL
        suffix = "PtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "W"
        self._get_window_long = getattr(user, f"GetWindowLong{suffix}")
        self._get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
        self._get_window_long.restype = ctypes.c_ssize_t
        self._set_window_long = getattr(user, f"SetWindowLong{suffix}")
        self._set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_window_long.restype = ctypes.c_ssize_t
        self._get_dpi = getattr(user, "GetDpiForWindow", None)
        if self._get_dpi is not None:
            self._get_dpi.argtypes = [wintypes.HWND]
            self._get_dpi.restype = wintypes.UINT
        self._set_dpi_context = getattr(user, "SetThreadDpiAwarenessContext", None)
        if self._set_dpi_context is not None:
            self._set_dpi_context.argtypes = [wintypes.HANDLE]
            self._set_dpi_context.restype = wintypes.HANDLE
        kernel = self._kernel32
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        kernel.Process32FirstW.restype = wintypes.BOOL
        kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        kernel.Process32NextW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL

    def process_parents(self) -> dict[int, int]:
        """一次 Toolhelp32 快照只读取父 PID，句柄始终在本调用内释放。"""
        handle = self._kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            parents: dict[int, int] = {}
            valid = self._kernel32.Process32FirstW(handle, ctypes.byref(entry))
            while valid:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                valid = self._kernel32.Process32NextW(handle, ctypes.byref(entry))
            return parents
        finally:
            self._kernel32.CloseHandle(handle)

    def window_handles(self) -> list[int]:
        handles: list[int] = []

        def collect(hwnd: int, _lparam: int) -> bool:
            handles.append(int(hwnd))
            return True

        if not self._user32.EnumWindows(self._enum_callback(collect), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return handles

    def identity(self, hwnd: int) -> tuple[int, str] | None:
        if not self._user32.IsWindow(hwnd):
            return None
        pid = wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        length = self._user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, length + 1)
        return int(pid.value), buffer.value

    @contextmanager
    def _physical_coordinates(self) -> Iterator[None]:
        # GetWindowRect 会被 DPI 虚拟化；临时切换并还原线程上下文，不改全局配置。
        previous = self._set_dpi_context(-4) if self._set_dpi_context is not None else None
        try:
            yield
        finally:
            if previous is not None and self._set_dpi_context is not None:
                self._set_dpi_context(previous)

    def snapshot(self, hwnd: int) -> NativeWindowSnapshot | None:
        identity = self.identity(hwnd)
        if identity is None:
            return None
        with self._physical_coordinates():
            rect = wintypes.RECT()
            if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            monitor = self._user32.MonitorFromWindow(hwnd, 2)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if not monitor or not self._user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return None
            foreground_hwnd = int(self._user32.GetForegroundWindow() or 0)
            return NativeWindowSnapshot(
                hwnd=hwnd,
                pid=identity[0],
                rect=self._rect(rect),
                work_area=self._rect(info.rcWork),
                visible=bool(self._user32.IsWindowVisible(hwnd)),
                minimized=bool(self._user32.IsIconic(hwnd)),
                foreground=foreground_hwnd == hwnd,
                topmost=bool(self._get_window_long(hwnd, -20) & 0x00000008),
                dpi=int(self._get_dpi(hwnd) or 96) if self._get_dpi is not None else 96,
                foreground_hwnd=foreground_hwnd,
            )

    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect
    ) -> bool:
        """只修改本进程侧栏，以原生 owner 保持相对层级，普通移动不改变 Z 序。"""
        tool_identity = self.identity(tool_hwnd)
        owner_identity = self.identity(owner.hwnd)
        if tool_identity is None or tool_identity[0] != os.getpid():
            return False
        if owner_identity is None or owner_identity[0] != owner.pid:
            return False
        if self._get_window_long(tool_hwnd, -8) != owner.hwnd:
            ctypes.set_last_error(0)
            result = self._set_window_long(tool_hwnd, -8, owner.hwnd)
            if not result and ctypes.get_last_error():
                return False
        tool_topmost = bool(self._get_window_long(tool_hwnd, -20) & 0x00000008)
        flags = 0x0010 | 0x0200  # 不激活侧栏，也不提升投屏窗口的 Z 序。
        insert_after = 0
        if tool_topmost == owner.topmost:
            flags |= 0x0004
        else:
            insert_after = -1 if owner.topmost else -2
        with self._physical_coordinates():
            return bool(self._user32.SetWindowPos(tool_hwnd, insert_after, *rect, flags))

    @staticmethod
    def _rect(rect: wintypes.RECT) -> PhysicalRect:
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
