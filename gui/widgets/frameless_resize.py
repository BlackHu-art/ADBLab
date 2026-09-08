"""为无边框顶层窗口提供不可见的原生缩放热区。"""

from __future__ import annotations

from collections.abc import Callable
from weakref import WeakSet

from PySide6.QtCore import QChildEvent, QEvent, QObject, QPoint, QRect, Qt, Signal, Slot
from PySide6.QtGui import QMouseEvent, QRegion
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ScrollBar
from shiboken6 import isValid


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
        if (
            event.button() != Qt.MouseButton.LeftButton
            or self._window.isMaximized()
            or self._window.isFullScreen()
        ):
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


class FramelessResizeController(QObject):
    """管理八个缩放热区，并为本窗口可见的 Fluent 滚动条保留输入区域。"""

    _mask_refresh_requested = Signal()

    def __init__(
        self,
        window: QWidget,
        *,
        edge_width: int = 8,
        corner_size: int = 14,
        on_user_resize_started: Callable[[], None] | None = None,
        on_user_resize_cancelled: Callable[[], None] | None = None,
    ):
        super().__init__(window)
        self._window = window
        self._edge_width = max(4, int(edge_width))
        self._corner_size = max(self._edge_width, int(corner_size))
        self._watched_widgets: WeakSet[QWidget] = WeakSet()
        self._scrollbars: WeakSet[ScrollBar] = WeakSet()
        self._scrollbar_parents: WeakSet[QWidget] = WeakSet()
        self._mask_refresh_pending = False
        self._mask_refresh_requested.connect(
            self._refresh_after_child_removal, Qt.ConnectionType.QueuedConnection,
        )
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
        self._watch_subtree(window)
        self.update_geometry()

    def _watch_subtree(self, widget: QWidget) -> None:
        """仅首次遍历已有控件，后续通过子控件事件增量观察动态页面。"""

        if widget in self._watched_widgets or isinstance(widget, _ResizeZone):
            return
        self._watched_widgets.add(widget)
        widget.installEventFilter(self)
        if isinstance(widget, ScrollBar):
            self._scrollbars.add(widget)
        for child in widget.children():
            if isinstance(child, QWidget):
                self._watch_subtree(child)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """按显隐和几何事件同步输入遮罩，不在运行中重复扫描整棵控件树。"""

        if not isValid(self._window):
            return False
        event_type = event.type()
        if event_type == QEvent.Type.ChildRemoved:
            # 移除事件可能来自半销毁子树；合并到下一事件边界后才读取存活控件几何。
            if not self._mask_refresh_pending:
                self._mask_refresh_pending = True
                self._mask_refresh_requested.emit()
        elif isinstance(event, QChildEvent) and event_type in (
            QEvent.Type.ChildAdded,
            QEvent.Type.ChildPolished,
        ):
            child = event.child()
            if isinstance(child, QWidget):
                self._watch_subtree(child)
        elif event_type in (
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.ParentChange,
            QEvent.Type.WindowStateChange,
        ):
            # ChildAdded 可能早于 Python 子类构造完成；首次显示时补登记实际类型。
            if isinstance(watched, ScrollBar):
                self._scrollbars.add(watched)
                self._refresh_hit_masks()
            elif watched is self._window:
                self.update_geometry()
            elif watched in self._scrollbar_parents:
                self._refresh_hit_masks()
        return False

    @Slot()
    def _refresh_after_child_removal(self) -> None:
        """销毁完成后收回轨道空洞；窗口删除会一并取消此 QObject 的排队调用。"""

        self._mask_refresh_pending = False
        if isValid(self._window):
            self._refresh_hit_masks()

    def _refresh_hit_masks(self) -> None:
        """从热区扣除完整可见轨道；外沿和未重叠角区继续负责原生缩放。"""

        if self._mask_refresh_pending:
            return
        occupied = QRegion()
        parents: WeakSet[QWidget] = WeakSet()
        for bar in tuple(self._scrollbars):
            if not isValid(bar) or bar.window() is not self._window:
                continue
            rect = QRect(bar.mapTo(self._window, QPoint()), bar.size())
            ancestor = bar.parentWidget()
            while ancestor is not None and ancestor is not self._window:
                parents.add(ancestor)
                rect = rect.intersected(
                    QRect(ancestor.mapTo(self._window, QPoint()), ancestor.size())
                )
                ancestor = ancestor.parentWidget()
            if bar.isVisibleTo(self._window):
                occupied |= QRegion(rect)
        self._scrollbar_parents = parents
        enabled = not self._window.isMaximized() and not self._window.isFullScreen()
        for zone in self._zones.values():
            if not isValid(zone):
                continue
            available = QRegion(zone.geometry()).subtracted(occupied)
            available.translate(-zone.pos())
            # Qt 把空 mask 解释为未设置遮罩，因此无剩余面积时必须隐藏热区。
            zone.setMask(available)
            zone.setVisible(enabled and not available.isEmpty())

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
            if not isValid(zone):
                continue
            zone.setGeometry(geometries[name])
            zone.setVisible(enabled)
            if enabled:
                zone.raise_()
        self._refresh_hit_masks()
