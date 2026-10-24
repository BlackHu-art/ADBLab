"""提供 Win32 窗口查询、物理坐标定位及可选事件订阅。"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes

from services.remote.windowing.contracts import (
    NativeWindowSnapshot,
    PhysicalRect,
    _WindowSubscription,
)


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

    def subscribe_changes(
        self, hwnd: int, pid: int, callback: Callable[[], None],
    ) -> _WindowSubscription | None:
        """只为已验证窗口安装可释放的事件通知；缺少 API 时保留周期轮询。"""
        if not all(
            callable(getattr(self._user32, name, None))
            for name in ("SetWinEventHook", "UnhookWinEvent")
        ):
            return None
        from services.remote.windowing.events import WinEventSubscription

        return WinEventSubscription(self._user32, hwnd, pid, callback)

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
