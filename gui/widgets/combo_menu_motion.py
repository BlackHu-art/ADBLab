"""下拉菜单的局部弹出和候选指示动效，不接管选项提交或材质准备。"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QStyle, QWidget
from qfluentwidgets import RoundMenu
from qfluentwidgets.common.style_sheet import themeColor
from qfluentwidgets.components.widgets.menu import (
    IndicatorMenuItemDelegate,
    MenuAnimationManager,
    MenuAnimationType,
    MenuItemDelegate,
)

from gui.widgets.frame_animation import FrameAnimation


class _CandidateDelegate(MenuItemDelegate):
    """保留原菜单文字与选中背景，蓝条由视口中唯一的指示器绘制。"""


class _CandidateIndicator(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("adblabComboIndicator")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(themeColor())
        painter.drawRoundedRect(QRectF(self.rect()), 1.5, 1.5)


class ComboMenuMotion(QObject):
    """每个弹层独占两个时钟；关闭、离开和滚动不保留旧的候选几何。"""

    def __init__(self, menu: RoundMenu) -> None:
        super().__init__(menu)
        self._menu = menu
        self._manager: MenuAnimationManager | None = None
        self._candidate = QPersistentModelIndex()
        self._waiting_for_paint = False
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.timeout.connect(self._resume_popup)
        self.popup_animation = FrameAnimation(self, owner=menu)
        self.popup_animation.setObjectName("adblabComboPopupAnimation")
        self.popup_animation.valueChanged.connect(self._apply_popup)
        self.popup_animation.finished.connect(menu.clearMask)
        self.indicator_animation = FrameAnimation(self, owner=menu)
        self.indicator_animation.setObjectName("adblabComboIndicatorAnimation")
        self.indicator_animation.setDuration(180)
        self.indicator_animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.indicator_animation.valueChanged.connect(self._apply_indicator)
        self.indicator: _CandidateIndicator | None = None
        view = menu.view
        # 特殊工厂若提供自己的 delegate，不能覆盖其绘制或数据语义。
        if type(view.itemDelegate()) is IndicatorMenuItemDelegate:
            view.setItemDelegate(_CandidateDelegate(view))
            self.indicator = _CandidateIndicator(view.viewport())
            view.selectionModel().currentChanged.connect(self._current_changed)
            view.itemEntered.connect(self._item_entered)
            view.verticalScrollBar().valueChanged.connect(self._scrolled)
            view.horizontalScrollBar().valueChanged.connect(self._scrolled)
        menu.installEventFilter(self)
        view.viewport().installEventFilter(self)
        host = menu.parentWidget()
        window = host.window() if host is not None else None
        if window is not None:
            window.installEventFilter(self)

    def exec(
        self, original: Callable, pos: QPoint, ani: bool, ani_type: MenuAnimationType,
    ) -> None:
        """原工厂先完成材质和定位，返回同一事件栈后接管尚未绘制的原动画。"""
        self.cancel()
        original(pos, ani, ani_type)
        manager = cast(MenuAnimationManager | None, self._menu.aniManager)
        if manager is None:
            return
        native = manager.ani
        native.stop()
        end = native.endValue()
        start = native.startValue()
        self._manager = manager
        animation = self.popup_animation
        animation.setDuration(native.duration())
        animation.setEasingCurve(native.easingCurve())
        animation.setStartValue(start if isinstance(start, QPoint) else self._menu.pos())
        animation.setEndValue(end if isinstance(end, QPoint) else self._menu.pos())
        setattr(manager, "ani", animation)
        native.deleteLater()
        self._move_indicator(self._menu.view.currentIndex(), animated=False)
        if (
            not ani or ani_type == MenuAnimationType.NONE
            or not self._menu.isVisible()
            or not self._animations_enabled()
        ):
            animation.setCurrentTime(animation.duration())
            self._menu.clearMask()
            return
        animation.start()
        animation.pause()
        self._waiting_for_paint = animation.state() == QAbstractAnimation.State.Paused

    def cancel(self) -> None:
        """撤销首帧回调和两个时钟，不提交选项，也不触发业务信号。"""
        self._waiting_for_paint = False
        self._resume_timer.stop()
        self.popup_animation.stop()
        self.indicator_animation.stop()

    def _apply_popup(self, value: object) -> None:
        if self._manager is None or not isinstance(value, QPoint):
            return
        self._menu.move(value)
        self._manager._onValueChanged()
        self._manager._updateMenuViewport()

    def _animations_enabled(self) -> bool:
        # RoundMenu 独占 Fusion style 的原生指针不宜再次查询；设置沿用所属控件。
        host = self._menu.parentWidget()
        window = host.window() if host is not None else None
        style = host.style() if host is not None else QApplication.style()
        return bool(style.styleHint(QStyle.StyleHint.SH_Widget_Animate)) and not (
            window is not None and window.isMinimized()
        )

    def _resume_popup(self) -> None:
        if self._menu.isVisible():
            self.popup_animation.resume()

    def _apply_indicator(self, value: object) -> None:
        if self.indicator is not None and isinstance(value, QRectF):
            self.indicator.setGeometry(value.toRect())

    def _move_indicator(self, index: QModelIndex, *, animated: bool = True) -> None:
        if self.indicator is None:
            return
        if not index.isValid():
            # 无默认项时离开悬停区域，应撤销候选，不能留下已失去归属的蓝条。
            self.indicator_animation.stop()
            self._candidate = QPersistentModelIndex()
            self.indicator.hide()
            return
        if not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self._candidate = QPersistentModelIndex(index)
        rect = self._menu.view.visualRect(index)
        target = QRect(6, rect.top() + 11, 3, 15)
        animation = self.indicator_animation
        animation.stop()
        if (
            not animated or self.indicator.isHidden() or not self._menu.isVisible()
            or not self._animations_enabled()
        ):
            self.indicator.setGeometry(target)
        else:
            animation.setStartValue(QRectF(self.indicator.geometry()))
            animation.setEndValue(QRectF(target))
            animation.start()
        self.indicator.show()
        self.indicator.raise_()

    def _current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._move_indicator(current)

    def _item_entered(self, item) -> None:
        self._move_indicator(self._menu.view.indexFromItem(item))

    def _scrolled(self, _value: int) -> None:
        # 候选跟随内容坐标，不能把滚动位移再变成蓝条追赶页面的第二段动画。
        model = self._candidate.model()
        if model is not None:
            self._move_indicator(model.index(
                self._candidate.row(), self._candidate.column(), self._candidate.parent(),
            ), animated=False)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if isinstance(watched, QWidget) and (watched is self._menu or watched.isWindow()):
            if kind in (QEvent.Type.Hide, QEvent.Type.Close):
                self.cancel()
            elif kind == QEvent.Type.WindowStateChange and watched.isMinimized():
                self.cancel()
        elif kind == QEvent.Type.Leave:
            self._move_indicator(self._menu.view.currentIndex())
        if (
            kind == QEvent.Type.Paint and self._waiting_for_paint
            and watched in (self._menu, self._menu.view.viewport())
        ):
            self._waiting_for_paint = False
            self._resume_timer.start(0)
        return False


def configure_combo_menu_motion(menu: RoundMenu) -> None:
    """幂等适配现有菜单实例；保留自定义工厂类型、动作与材质 exec 边界。"""
    if menu.findChild(ComboMenuMotion) is not None:
        return
    motion = ComboMenuMotion(menu)
    original = menu.exec

    def exec_menu(pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):  # noqa: N803
        motion.exec(original, pos, ani, aniType)

    menu.exec = exec_menu
