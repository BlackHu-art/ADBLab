"""为无边框顶层窗口提供不可见的原生缩放热区。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget


class _ResizeZone(QWidget):
    """把指定边缘的按压事件交给窗口系统处理。"""

    def __init__(
        self,
        window: QWidget,
        edges: Qt.Edge,
        cursor: Qt.CursorShape,
        *,
        on_user_resize_started: Callable[[], None] | None = None,
        on_user_resize_cancelled: Callable[[], None] | None = None,
    ):
        super().__init__(window)
        self._window = window
        self._edges = edges
        self._on_user_resize_started = on_user_resize_started
        self._on_user_resize_cancelled = on_user_resize_cancelled
        self.setCursor(cursor)
        self.setObjectName("framelessResizeZone")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._window.isMaximized():
            super().mousePressEvent(event)
            return
        handle = self._window.windowHandle()
        # 先开启持久化事务：即使原生缩放未成功启动（无 handle / startSystemResize
        # 返回 False），随后没有实际 resize 的事务也会被 _finish_user_resize_transaction
        # 以 _pending_user_window_size is None 分支回滚。
        if self._on_user_resize_started is not None:
            self._on_user_resize_started()
        if handle is not None and handle.startSystemResize(self._edges):
            event.accept()
            return
        if self._on_user_resize_cancelled is not None:
            self._on_user_resize_cancelled()
        super().mousePressEvent(event)


class FramelessResizeController:
    """管理四边和四角共八个透明缩放热区。"""

    def __init__(
        self,
        window: QWidget,
        *,
        edge_width: int = 8,
        corner_size: int = 14,
        on_user_resize_started: Callable[[], None] | None = None,
        on_user_resize_cancelled: Callable[[], None] | None = None,
    ):
        self._window = window
        self._edge_width = max(4, int(edge_width))
        self._corner_size = max(self._edge_width, int(corner_size))
        edge = Qt.Edge
        cursor = Qt.CursorShape
        callback_options = {
            "on_user_resize_started": on_user_resize_started,
            "on_user_resize_cancelled": on_user_resize_cancelled,
        }
        self._zones = {
            "left": _ResizeZone(window, edge.LeftEdge, cursor.SizeHorCursor, **callback_options),
            "right": _ResizeZone(window, edge.RightEdge, cursor.SizeHorCursor, **callback_options),
            "top": _ResizeZone(window, edge.TopEdge, cursor.SizeVerCursor, **callback_options),
            "bottom": _ResizeZone(
                window, edge.BottomEdge, cursor.SizeVerCursor, **callback_options
            ),
            "top_left": _ResizeZone(
                window,
                edge.TopEdge | edge.LeftEdge,
                cursor.SizeFDiagCursor,
                **callback_options,
            ),
            "top_right": _ResizeZone(
                window,
                edge.TopEdge | edge.RightEdge,
                cursor.SizeBDiagCursor,
                **callback_options,
            ),
            "bottom_left": _ResizeZone(
                window,
                edge.BottomEdge | edge.LeftEdge,
                cursor.SizeBDiagCursor,
                **callback_options,
            ),
            "bottom_right": _ResizeZone(
                window,
                edge.BottomEdge | edge.RightEdge,
                cursor.SizeFDiagCursor,
                **callback_options,
            ),
        }
        self.update_geometry()

    @property
    def zones(self) -> tuple[QWidget, ...]:
        """返回热区集合，供窗口生命周期和自动化测试使用。"""

        return tuple(self._zones.values())

    def update_geometry(self) -> None:
        """根据当前窗口尺寸更新热区并保持在内容控件上方。"""

        width = max(0, self._window.width())
        height = max(0, self._window.height())
        edge = min(self._edge_width, width, height)
        corner = min(self._corner_size, width, height)
        horizontal_length = max(0, width - corner * 2)
        vertical_length = max(0, height - corner * 2)

        geometries = {
            "left": QRect(0, corner, edge, vertical_length),
            "right": QRect(max(0, width - edge), corner, edge, vertical_length),
            "top": QRect(corner, 0, horizontal_length, edge),
            "bottom": QRect(corner, max(0, height - edge), horizontal_length, edge),
            "top_left": QRect(0, 0, corner, corner),
            "top_right": QRect(max(0, width - corner), 0, corner, corner),
            "bottom_left": QRect(0, max(0, height - corner), corner, corner),
            "bottom_right": QRect(max(0, width - corner), max(0, height - corner), corner, corner),
        }
        enabled = not self._window.isMaximized() and not self._window.isFullScreen()
        for name, zone in self._zones.items():
            zone.setGeometry(geometries[name])
            zone.setVisible(enabled)
            if enabled:
                zone.raise_()
