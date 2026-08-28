"""主窗口屏幕查询与信号连接的适配层。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QSize
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


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
    def _is_valid_qobject(obj) -> bool:
        """判断 PySide 包装器及其底层 C++ 对象是否仍然有效。"""

        if obj is None:
            return False
        try:
            return bool(isValid(obj))
        except (RuntimeError, TypeError):
            return False

    @classmethod
    def is_valid_screen(cls, screen) -> bool:
        """QScreen 的 Python 包装器非空不代表底层对象仍存活。"""

        return cls._is_valid_qobject(screen)

    @classmethod
    def window_screen(cls, window: QWidget):
        try:
            handle = window.windowHandle()
        except (AttributeError, RuntimeError, TypeError):
            handle = None
        if handle is not None and cls._is_valid_qobject(handle):
            try:
                screen = handle.screen()
            except (AttributeError, RuntimeError, TypeError):
                screen = None
            if cls.is_valid_screen(screen):
                return screen
        try:
            screen = window.screen()
        except (AttributeError, RuntimeError, TypeError):
            screen = None
        if cls.is_valid_screen(screen):
            return screen
        try:
            screen = QApplication.primaryScreen()
        except (AttributeError, RuntimeError, TypeError):
            screen = None
        return screen if cls.is_valid_screen(screen) else None

    @classmethod
    def available_size(cls, screen) -> QSize:
        if not cls.is_valid_screen(screen):
            return QSize()
        try:
            return screen.availableGeometry().size()
        except (AttributeError, RuntimeError, TypeError):
            return QSize()

    @classmethod
    def logical_dpi(cls, screen) -> float:
        if not cls.is_valid_screen(screen):
            return 96.0
        try:
            return float(screen.logicalDotsPerInch())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return 96.0

    @staticmethod
    def _connect(signal, callback: Callable):
        try:
            # QMetaObject.Connection 不依赖已销毁 sender 的 bound signal，
            # 因而可在屏幕热插拔或 Qt 重建 QScreen 后无警告解绑。
            return signal.connect(callback)
        except (AttributeError, RuntimeError, TypeError):
            return None

    def connect_window_screen_changed(self, window: QWidget, callback: Callable):
        try:
            handle = window.windowHandle()
        except (AttributeError, RuntimeError, TypeError):
            handle = None
        if handle is None or not self._is_valid_qobject(handle):
            return None
        return self._connect(handle.screenChanged, callback)

    def connect_available_geometry_changed(self, screen, callback: Callable):
        if not self.is_valid_screen(screen):
            return None
        return self._connect(screen.availableGeometryChanged, callback)

    def connect_logical_dpi_changed(self, screen, callback: Callable):
        if not self.is_valid_screen(screen):
            return None
        return self._connect(screen.logicalDotsPerInchChanged, callback)

    @staticmethod
    def disconnect(token) -> None:
        if token is None:
            return
        try:
            QObject.disconnect(token)
        except (AttributeError, RuntimeError, TypeError):
            pass
