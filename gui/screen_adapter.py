"""主窗口屏幕查询与信号连接的适配层。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget


class ScreenAdapter(Protocol):
    """隔离 MainFrame 所需的 Qt 屏幕查询和信号连接。"""

    def window_screen(self, window: QWidget): ...

    def available_size(self, screen) -> QSize: ...

    def logical_dpi(self, screen) -> float: ...

    def connect_window_screen_changed(self, window: QWidget, callback: Callable): ...

    def connect_available_geometry_changed(self, screen, callback: Callable): ...

    def connect_logical_dpi_changed(self, screen, callback: Callable): ...

    def disconnect(self, token) -> None: ...


class QtScreenAdapter:
    """把真实 QWindow/QScreen 信号包装为可统一断开的 token。"""

    @staticmethod
    def window_screen(window: QWidget):
        handle = window.windowHandle()
        if handle is not None and handle.screen() is not None:
            return handle.screen()
        return window.screen() or QApplication.primaryScreen()

    @staticmethod
    def available_size(screen) -> QSize:
        return screen.availableGeometry().size() if screen is not None else QSize()

    @staticmethod
    def logical_dpi(screen) -> float:
        return float(screen.logicalDotsPerInch()) if screen is not None else 96.0

    @staticmethod
    def _connect(signal, callback: Callable):
        signal.connect(callback)
        return signal, callback

    def connect_window_screen_changed(self, window: QWidget, callback: Callable):
        handle = window.windowHandle()
        if handle is None:
            return None
        return self._connect(handle.screenChanged, callback)

    def connect_available_geometry_changed(self, screen, callback: Callable):
        if screen is None:
            return None
        return self._connect(screen.availableGeometryChanged, callback)

    def connect_logical_dpi_changed(self, screen, callback: Callable):
        if screen is None:
            return None
        return self._connect(screen.logicalDotsPerInchChanged, callback)

    @staticmethod
    def disconnect(token) -> None:
        if token is None:
            return
        signal, callback = token
        try:
            signal.disconnect(callback)
        except (AttributeError, RuntimeError, TypeError):
            pass
