"""像素滚动视图的连续阻尼过渡，不改变原生控件和触控板的输入处理。"""

from __future__ import annotations

from math import exp

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QSignalBlocker,
    Qt,
)
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QApplication
from qfluentwidgets import SmoothScrollBar

from gui.widgets.frame_animation import FrameAnimation


class SettingsWheelScroll(QObject):
    """沿用设置页入口的局部滚动控制器；外部定位、离页或禁用立即取消旧目标。"""

    def __init__(
        self, area: QAbstractScrollArea, overlay_bar: SmoothScrollBar | None = None,
    ) -> None:
        super().__init__(area)
        self.setObjectName("adblabWheelScroll")
        self._area = area
        self._viewport = area.viewport()
        self._bar = area.verticalScrollBar()
        self._target: int | None = None
        self._direction = 0
        self._writing = False
        self._shutdown = False
        self._position = float(self._bar.value())
        self._velocity = 0.0
        self._start_position = self._position
        self._start_velocity = 0.0
        self._segment_start_ms = 0
        self._animation = FrameAnimation(self, owner=area)
        self._animation.setDuration(420)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(420.0)
        self._animation.setEasingCurve(QEasingCurve.Type.Linear)
        self._animation.valueChanged.connect(self._apply_value)
        self._animation.finished.connect(self.cancel)
        self._bar.valueChanged.connect(self._on_external_value)
        self._bar.rangeChanged.connect(self.cancel)
        self._bar.actionTriggered.connect(self.cancel)
        self._bar.sliderPressed.connect(self.cancel)
        # Fluent 显示的是覆盖式滚动条；按下但尚未移动时也要先归还滚动控制权。
        if overlay_bar is not None:
            overlay_bar.sliderPressed.connect(self.cancel)
            overlay_bar.installEventFilter(self)
        self._viewport.installEventFilter(self)
        area.installEventFilter(self)

    def cancel(self, *_args: object) -> None:
        """停止待执行帧且丢弃旧目标，不回写滚动值，允许在隐藏和关闭边界重复调用。"""
        self._animation.stop()
        self._target = None
        self._direction = 0
        self._velocity = 0.0

    def prepare_shutdown(self) -> None:
        """异步关闭开始即停止过渡，并拒绝窗口尚可见期间晚到的滚轮输入。"""
        self._shutdown = True
        self.cancel()

    def _on_external_value(self, _value: int) -> None:
        if not self._writing:
            self.cancel()

    def _apply_value(self, elapsed_ms: float) -> None:
        if self._target is None:
            return
        # 临界阻尼保留位置与速度；按实际经过时间求值，帧间隔变化也不累积积分误差。
        # 28/s 使单刻度约 100ms 到达四分之三，余程柔和收尾，且不会越过目标回弹。
        rate = 28.0
        elapsed = max(0.0, elapsed_ms - self._segment_start_ms) / 1000.0
        error = self._start_position - self._target
        impulse = self._start_velocity + rate * error
        decay = exp(-rate * elapsed)
        self._position = self._target + (error + impulse * elapsed) * decay
        self._velocity = (self._start_velocity - rate * impulse * elapsed) * decay
        settled = (
            abs(self._position - self._target) < 0.25 and abs(self._velocity) < 8.0
        ) or elapsed_ms >= self._animation.duration()
        self._writing = True
        try:
            self._bar.setValue(self._target if settled else round(self._position))
        finally:
            self._writing = False
        if settled:
            self.cancel()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind in (
            QEvent.Type.Hide, QEvent.Type.Close,
            QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
        ):
            self.cancel()
        elif kind == QEvent.Type.EnabledChange and not self._area.isEnabled():
            self.cancel()
        if watched is self._viewport and isinstance(event, QWheelEvent):
            if self._shutdown or not self._area.isEnabled():
                event.accept()
                return True
            delta = event.angleDelta()
            # 这些事件已有原生语义，尤其像素滚动不应再被第二段缓动叠加。
            if (
                not self._area.isVisible() or not event.pixelDelta().isNull()
                or delta.x() != 0 or delta.y() == 0 or delta.y() % 120 != 0
                or event.modifiers() != Qt.KeyboardModifier.NoModifier
                or event.buttons() != Qt.MouseButton.NoButton
                or event.phase() != Qt.ScrollPhase.NoScrollPhase or event.inverted()
            ):
                self.cancel()
                return False
            if self._scroll_notches(delta.y() // 120):
                event.accept()
                return True
        return False

    def _scroll_notches(self, notches: int) -> bool:
        page_step = self._bar.pageStep()
        offset = -notches * self._bar.singleStep() * QApplication.wheelScrollLines()
        offset = max(-page_step, min(page_step, offset))
        if offset == 0:
            self.cancel()
            return False
        current = self._bar.value()
        direction = 1 if offset > 0 else -1
        continuing = self._target is not None and direction == self._direction
        base = self._target if continuing and self._target is not None else current
        # 同向保留连续滚动距离，但待执行距离最多一页；反向直接从可见位置起算。
        target = max(
            self._bar.minimum(), current - page_step,
            min(self._bar.maximum(), current + page_step, base + offset),
        )
        if target == current:
            self.cancel()
            return False
        if target == self._target:
            return True
        # 同向只改变目标，续接当前浮点位置与速度；反向丢弃余速，首个运动帧就换向。
        self._start_position = self._position if continuing else float(current)
        self._start_velocity = self._velocity if continuing else 0.0
        # 一帧之间可能收到多个刻度；不能依赖 valueChanged(0) 初始化本段状态。
        self._position = self._start_position
        self._velocity = self._start_velocity
        self._target = target
        self._direction = direction
        state = self._animation.state()
        self._segment_start_ms = (
            0 if state == QAbstractAnimation.State.Stopped else self._animation.currentTime()
        )
        # 连续输入只延长截止时间，不能反复重启时钟而丢掉尚未绘制的帧时间。
        # duration 与 endValue 相等，线性动画的值始终就是经过的毫秒数。
        deadline = self._segment_start_ms + 420
        with QSignalBlocker(self._animation):
            if state == QAbstractAnimation.State.Stopped:
                self._animation.setCurrentTime(0)
            self._animation.setDuration(deadline)
            self._animation.setEndValue(float(deadline))
        if state == QAbstractAnimation.State.Stopped:
            self._animation.start()
        elif state == QAbstractAnimation.State.Paused:
            self._animation.resume()
        return self._animation.state() != QAbstractAnimation.State.Stopped
