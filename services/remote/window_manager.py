"""提供尽力而为的 scrcpy 外部窗口聚焦能力。"""

from __future__ import annotations

import ctypes
import sys
import time

SW_RESTORE = 9


class RemoteWindowManager:
    """按窗口标题查找并聚焦外部 scrcpy 窗口。"""

    def __init__(self, poll_interval_seconds: float = 0.1):
        self.poll_interval_seconds = poll_interval_seconds

    def focus(self, title: str, timeout_seconds: float = 2.5) -> bool:
        """在 Windows 上轮询标题并尝试聚焦，其他平台安全返回 False。"""
        if not title or sys.platform != "win32":
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            hwnd = self._find_window(title)
            if hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, SW_RESTORE)
                if user32.GetForegroundWindow() == hwnd:
                    return True
                user32.SetForegroundWindow(hwnd)
                while time.monotonic() < deadline:
                    if user32.GetForegroundWindow() == hwnd:
                        return True
                    time.sleep(self.poll_interval_seconds)
                return False
            time.sleep(self.poll_interval_seconds)
        return False

    @staticmethod
    def _find_window(title: str) -> int:
        user32 = ctypes.windll.user32
        matches: list[int] = []

        def _callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value == title:
                matches.append(hwnd)
                return False
            return True

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(enum_proc(_callback), 0)
        return matches[0] if matches else 0
