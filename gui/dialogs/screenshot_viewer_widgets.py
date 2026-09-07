"""适配官方图片翻页、圆点分页与截图信息栏，保留图片比例和会话资源边界。"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem
from qfluentwidgets import (
    FlipImageDelegate,
    HorizontalFlipView,
    HorizontalPipsPager,
    PipsScrollButtonDisplayMode,
)
from shiboken6 import isValid

from gui.i18n import tr

if TYPE_CHECKING:
    from gui.features.media import ScreenshotPage


class ScreenshotImageDelegate(FlipImageDelegate):
    """沿用官方翻页项，按原图比例绘制，放大时直接裁剪绘图而不分配巨幅位图。"""

    def itemSize(self, index: int) -> QSize:
        """返回实际图片绘制尺寸；分页项本身始终使用完整视口大小。"""

        view = cast("ScreenshotFlipView", self.parent())
        image = view.image_for_index(index)
        if image.isNull():
            return QSize()
        owner = view.owner()
        if owner is not None and index == owner._current_idx:
            scale = owner._zoom_factor
        else:
            available = view.image_area_size()
            scale = min(available.width() / image.width(), available.height() / image.height(), 1.0)
        return QSize(max(1, round(image.width() * scale)), max(1, round(image.height() * scale)))

    def paint(self, painter, option, index):
        view = cast("ScreenshotFlipView", self.parent())
        image = view.image_for_index(index.row())
        if image.isNull():
            return
        slot = QRectF(view.visualRect(index)).adjusted(8, 8, -8, -8)
        size = self.itemSize(index.row())
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(slot.center())
        if index.row() == view.currentIndex():
            target.translate(view.pan_offset)
        painter.save()
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setClipRect(slot)
        painter.drawImage(target, image)
        painter.restore()


class ScreenshotFlipView(HorizontalFlipView):
    """以官方 FlipView 承载整页截图，并管理缩放拖动与有限数量的解码缓存。

    文件列表和当前变换归截图页面；本控件只保留页面弱引用。路径仍写在官方
    DisplayRole 中，清除远处图片的解码缓存后仍可按需重新读取。
    """

    def __init__(self, owner: ScreenshotPage):
        self._ready = False
        self._owner_ref = weakref.ref(owner)
        self.pan_offset = QPointF()
        self._drag_position: QPointF | None = None
        super().__init__(owner)
        self.setObjectName("imageView")
        self.setMinimumSize(0, 0)
        self.setSpacing(0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setAccessibleName(tr("Screenshot Viewer"))
        self.delegate = ScreenshotImageDelegate(self)
        self.setItemDelegate(self.delegate)
        # 跨多页动画会短暂绘制沿途图片；动画结束后再次回收，保留当前及邻页即可。
        self.scrollBar.ani.finished.connect(self.release_distant_images)
        for button, text in (
            (self.preButton, tr("Previous screenshot (Left)")),
            (self.nextButton, tr("Next screenshot (Right)")),
        ):
            button.setToolTip(text)
            button.setAccessibleName(text)
        self._ready = True

    def owner(self) -> ScreenshotPage | None:
        """仅返回尚未释放的页面，避免原生控件销毁期间调用失效包装对象。"""

        owner = self._owner_ref()
        return owner if owner is not None and isValid(owner) else None

    def image_area_size(self) -> QSize:
        """返回主图的可用区域，四边各留八像素防止适应模式贴住边界。"""

        size = self.viewport().size()
        return QSize(max(1, size.width() - 16), max(1, size.height() - 16))

    def image_for_index(self, index: int) -> QImage:
        """当前页使用页面提供的旋转结果，其他图片按官方路径机制懒加载。"""

        if not 0 <= index < self.count():
            return QImage()
        owner = self.owner()
        if owner is not None and index == owner._current_idx:
            pixmap = owner._display_pixmap
            if pixmap is not None and not pixmap.isNull():
                return pixmap.toImage()
        image = self.itemImage(index)
        if image is None:
            return QImage()
        # 官方 delegate 负责回存懒加载结果；替换绘制后在此接续该职责，
        # 避免相邻动画帧每次重绘都重新读取文件，源路径仍保留在 DisplayRole。
        item = self.item(index)
        cached = item.data(Qt.ItemDataRole.UserRole)
        if not image.isNull() and (cached is None or cached.isNull()):
            item.setData(Qt.ItemDataRole.UserRole, image)
        return image

    def _adjustItemSize(self, item: QListWidgetItem):
        """每张图片独占一个视口，原图横竖比例只影响绘制，不影响分页距离。"""

        item.setSizeHint(self.viewport().size().expandedTo(QSize(1, 1)))

    def reset_pan(self) -> None:
        """切图、旋转或重置缩放时撤销拖动偏移，不修改原始文件。"""

        self.pan_offset = QPointF()
        self._drag_position = None
        self.unsetCursor()
        self.viewport().update()

    def _pan_limits(self) -> QPointF:
        size = self.delegate.itemSize(self.currentIndex())
        available = self.image_area_size()
        return QPointF(
            max(0.0, (size.width() - available.width()) / 2),
            max(0.0, (size.height() - available.height()) / 2),
        )

    def _clamp_pan(self) -> None:
        limits = self._pan_limits()
        self.pan_offset = QPointF(
            max(-limits.x(), min(limits.x(), self.pan_offset.x())),
            max(-limits.y(), min(limits.y(), self.pan_offset.y())),
        )

    def stop_animations(self) -> None:
        """离页时同步停住动画并对齐当前页，避免再次激活时留下半页画面。"""

        self.scrollBar.ani.stop()
        self.preButton.opacityAni.stop()
        self.nextButton.opacityAni.stop()
        self._drag_position = None
        self.unsetCursor()
        if 0 <= self.currentIndex() < self.count():
            item = self.item(self.currentIndex())
            target = self.scrollBar.value() + self.visualItemRect(item).left()
            self.scrollBar.scrollTo(target, useAni=False)

    def release_distant_images(self) -> None:
        """仅保留当前及相邻图的解码缓存，保留路径供返回时重新加载。"""

        current = self.currentIndex()
        for index in range(self.count()):
            item = self.item(index)
            if abs(index - current) > 1 and item.data(Qt.ItemDataRole.DisplayRole):
                item.setData(Qt.ItemDataRole.UserRole, QImage())

    def clear(self):
        """重建批次前停止旧动画、释放图片并复位官方当前索引。"""

        if self._ready:
            self.stop_animations()
        super().clear()
        self._currentIndex = -1
        self.reset_pan()

    def resizeEvent(self, event):
        """按新视口重新分页并保留当前图片，适应模式交由页面统一重算。"""

        if not self._ready:
            QListWidget.resizeEvent(self, event)
            return
        super().resizeEvent(event)
        self.scrollBar.ani.stop()
        self.setItemSize(self.viewport().size().expandedTo(QSize(1, 1)))
        self.doItemsLayout()
        self.scrollToIndex(self.currentIndex())
        self._clamp_pan()
        owner = self.owner()
        if owner is not None and owner._fit_to_window:
            owner._schedule_fit()

    def wheelEvent(self, event: QWheelEvent):
        owner = self.owner()
        if owner is not None and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            owner._zoom_from_wheel(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        owner = self.owner()
        if owner is not None and event.button() == Qt.MouseButton.LeftButton:
            owner.toggle_fit_actual()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        limits = self._pan_limits()
        if event.button() == Qt.MouseButton.LeftButton and (limits.x() or limits.y()):
            self._drag_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_position is not None:
            self.pan_offset += event.position() - self._drag_position
            self._drag_position = event.position()
            self._clamp_pan()
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_position is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        target = _navigation_target(event.key(), self.currentIndex(), self.count())
        if target is not None:
            self.setCurrentIndex(target)
            event.accept()
            return
        super().keyPressEvent(event)


class ScreenshotPipsPager(HorizontalPipsPager):
    """保留官方圆点外观与滚动按钮，补充键盘导航和尺寸变化后的定位。"""

    def __init__(self, parent=None):
        self._ready = False
        super().__init__(parent)
        self.setObjectName("screenshotPager")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr("Number of loaded screenshots"))
        self.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        for button, text in (
            (self.preButton, tr("Previous screenshot (Left)")),
            (self.nextButton, tr("Next screenshot (Right)")),
        ):
            button.setToolTip(text)
            button.setAccessibleName(text)
        self._ready = True

    def stop_animations(self) -> None:
        """停止圆点动画并立即定位当前项，防止旧索引动画落到新模型。"""

        self.scrollBar.ani.stop()
        if self.currentItem() is not None:
            target = (
                self.scrollBar.value()
                + self.visualItemRect(self.currentItem()).center().x()
                - self.viewport().rect().center().x()
            )
            self.scrollBar.scrollTo(target, useAni=False)

    def resizeEvent(self, event):
        if not self._ready:
            QListWidget.resizeEvent(self, event)
            return
        super().resizeEvent(event)
        self.stop_animations()
        self.doItemsLayout()
        with QSignalBlocker(self):
            self.setCurrentIndex(self.currentIndex())

    def keyPressEvent(self, event):
        target = _navigation_target(event.key(), self.currentIndex(), self.count())
        if target is not None:
            self.setCurrentIndex(target)
            event.accept()
            return
        super().keyPressEvent(event)


def _navigation_target(key: int, current: int, count: int) -> int | None:
    targets: dict[int, int] = {
        Qt.Key.Key_Left: current - 1,
        Qt.Key.Key_Right: current + 1,
        Qt.Key.Key_Home: 0,
        Qt.Key.Key_End: count - 1,
    }
    return targets.get(key)


class ScreenshotDetailsBar(QFrame):
    """信息栏随宽度变化请求页面重排，控件不拥有额外定时器或会话状态。"""

    def __init__(self, owner: ScreenshotPage):
        super().__init__(owner)
        self._owner_ref = weakref.ref(owner)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        owner = self._owner_ref()
        if owner is not None and isValid(owner):
            owner._schedule_metadata_reflow()
