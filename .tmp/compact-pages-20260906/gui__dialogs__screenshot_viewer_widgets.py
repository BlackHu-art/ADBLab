"""提供截图查看器专用的图形视图与底栏控件。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QWheelEvent
from PySide6.QtWidgets import QFrame, QGraphicsView

if TYPE_CHECKING:
    from gui.features.media import ScreenshotPage


class ScreenshotGraphicsView(QGraphicsView):
    """把滚轮和双击缩放操作委托给所属截图查看器。"""

    def __init__(self, owner: ScreenshotPage):
        super().__init__()
        self._owner = owner
        self.setObjectName("imageView")
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._owner._zoom_from_wheel(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner.toggle_fit_actual()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ScreenshotBottomBar(QFrame):
    """在实际可用宽度变化后请求所属查看器重排既有工具控件。"""

    def __init__(self, owner: ScreenshotPage):
        super().__init__()
        self._owner = owner

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self._owner, "_bottom_bar_layout"):
            self._owner._schedule_bottom_bar_reflow()
