"""按宿主屏幕刷新率近似采样的局部有限动画，不参与 Qt 的全局动画时钟。"""

from __future__ import annotations

import weakref
from math import isfinite

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QObject,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QScreen, QWindow
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


class FrameAnimation(QObject):
    """单次正向动画；隐藏、最小化和关闭只停止，终态提交由业务控件负责。

    定时器只决定采样机会，实际经过时间决定进度，不承诺与屏幕垂直同步。
    内部 QVariantAnimation 从不启动，只复用 Qt 的数值插值和缓动算法。
    """

    valueChanged = Signal(object)
    finished = Signal()
    stateChanged = Signal(object, object)

    def __init__(self, parent: QObject, owner: QWidget | None = None) -> None:
        super().__init__(parent)
        ancestor = parent
        while owner is None and ancestor is not None:
            if isinstance(ancestor, QWidget):
                owner = ancestor
                break
            ancestor = ancestor.parent()
        self._owner = owner
        # 动画只观察祖先，不能保活外层窗口；否则子控件析构中归还最后一个
        # Python 引用会重入祖先的 C++ 析构。
        self._window_ref: weakref.ReferenceType[QWidget] | None = None
        self._handle: QWindow | None = None
        self._screen: QScreen | None = None
        self._disposed = False
        self._generation = 0
        self._state = QAbstractAnimation.State.Stopped
        self._time = 0
        self._anchor_time = 0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(17)
        self._timer.timeout.connect(self._tick)
        self._interpolator = QVariantAnimation(self)
        self._interpolator.valueChanged.connect(self.valueChanged.emit)
        if owner is not None:
            owner.installEventFilter(self)
            owner.destroyed.connect(self._owner_destroyed)
        self._sync_host()

    def state(self) -> QAbstractAnimation.State:
        return self._state

    def currentTime(self) -> int:  # noqa: N802 - 沿用动画调用接口
        return self._time

    def currentValue(self) -> object:  # noqa: N802
        return self._interpolator.currentValue()

    def duration(self) -> int:
        return self._interpolator.duration()

    def setDuration(self, duration: int) -> None:  # noqa: N802
        """修改截止时间而不重置运行时钟；缩短到已采样时间则立即完成。"""
        if duration < 0:
            raise ValueError("动画时长必须是非负毫秒数")
        generation = self._generation
        self._time = min(self._time, duration)
        self._interpolator.setDuration(duration)
        if self._time >= duration:
            self._complete(generation)

    def startValue(self) -> object:  # noqa: N802
        return self._interpolator.startValue()

    def setStartValue(self, value: object) -> None:  # noqa: N802
        self._interpolator.setStartValue(value)

    def endValue(self) -> object:  # noqa: N802
        return self._interpolator.endValue()

    def setEndValue(self, value: object) -> None:  # noqa: N802
        self._interpolator.setEndValue(value)

    def easingCurve(self) -> QEasingCurve:  # noqa: N802
        return self._interpolator.easingCurve()

    def setEasingCurve(self, easing: QEasingCurve | QEasingCurve.Type) -> None:  # noqa: N802
        self._interpolator.setEasingCurve(easing)

    def setCurrentTime(self, time_ms: int) -> None:  # noqa: N802
        """定位同时重设经过时间基准；停止态只求值，不发出完成通知。"""
        self._anchor_time = max(0, min(self.duration(), time_ms))
        if self._state == QAbstractAnimation.State.Running:
            self._clock.restart()
        self._advance(self._anchor_time)

    def start(self) -> None:
        if self._state == QAbstractAnimation.State.Running:
            return
        self.stop()
        if self._disposed:
            return
        self._sync_host()
        window = self._host_window()
        if self._owner is not None and (
            not self._owner.isVisible()
            or window is not None and window.isMinimized()
        ):
            return
        generation = self._generation
        self._anchor_time = 0
        self._clock.start()
        self._set_state(QAbstractAnimation.State.Running)
        if generation != self._generation or self._state != QAbstractAnimation.State.Running:
            return
        self._advance(0)
        if generation == self._generation and self._state == QAbstractAnimation.State.Running:
            self._timer.start()

    def stop(self) -> None:
        """取消后不补终帧、不发 finished；递增代次使旧回调无法结束后续动画。"""
        self._generation += 1
        self._timer.stop()
        self._set_state(QAbstractAnimation.State.Stopped)

    def pause(self) -> None:
        if self._state != QAbstractAnimation.State.Running:
            return
        # 暂停保留已经呈现的那一帧，不把定时器尚未采样的零碎时间再推入控件。
        self._timer.stop()
        self._set_state(QAbstractAnimation.State.Paused)

    def resume(self) -> None:
        if self._disposed or self._state != QAbstractAnimation.State.Paused:
            return
        generation = self._generation
        self._anchor_time = self._time
        self._clock.restart()
        self._set_state(QAbstractAnimation.State.Running)
        if generation == self._generation and self._state == QAbstractAnimation.State.Running:
            self._timer.start()

    def _set_state(self, state: QAbstractAnimation.State) -> None:
        previous = self._state
        if previous != state:
            self._state = state
            self.stateChanged.emit(state, previous)

    def _tick(self) -> None:
        if self._state == QAbstractAnimation.State.Running:
            self._advance(self._anchor_time + self._clock.elapsed())

    def _advance(self, time_ms: int) -> None:
        generation = self._generation
        self._time = max(0, min(self.duration(), time_ms))
        self._interpolator.setCurrentTime(self._time)
        # 终值的消费者可能 stop 或重新 start；旧帧不能再停掉新一代并发出旧 finished。
        if self._time >= self.duration():
            self._complete(generation)

    def _complete(self, generation: int) -> None:
        if generation != self._generation or self._state == QAbstractAnimation.State.Stopped:
            return
        self._timer.stop()
        self._set_state(QAbstractAnimation.State.Stopped)
        if generation == self._generation and self._state == QAbstractAnimation.State.Stopped:
            self.finished.emit()

    def _host_window(self) -> QWidget | None:
        window = self._window_ref() if self._window_ref is not None else None
        return window if window is not None and isValid(window) else None

    def _sync_host(self) -> None:
        if self._disposed or self._owner is None:
            return
        window = self._owner.window() or self._owner
        previous = self._host_window()
        if window is not previous:
            if previous is not None and previous is not self._owner:
                previous.removeEventFilter(self)
            self._window_ref = weakref.ref(window)
            if window is not self._owner:
                window.installEventFilter(self)
        handle = window.windowHandle()
        if handle is not self._handle:
            self._unbind_handle()
            self._handle = handle
            if handle is not None:
                handle.screenChanged.connect(self._bind_screen)
                handle.destroyed.connect(self._handle_destroyed)
        self._bind_screen(handle.screen() if handle is not None else None)

    def _unbind_handle(self) -> None:
        if self._handle is not None and isValid(self._handle):
            self._handle.screenChanged.disconnect(self._bind_screen)
            self._handle.destroyed.disconnect(self._handle_destroyed)
        self._handle = None

    def _handle_destroyed(self) -> None:
        self._handle = None
        self.stop()
        self._bind_screen(None)

    def _bind_screen(self, screen: QScreen | None) -> None:
        if screen is not self._screen:
            if self._screen is not None and isValid(self._screen):
                self._screen.refreshRateChanged.disconnect(self._refresh_sampling)
                self._screen.destroyed.disconnect(self._screen_destroyed)
            self._screen = screen
            if screen is not None:
                screen.refreshRateChanged.connect(self._refresh_sampling)
                screen.destroyed.connect(self._screen_destroyed)
        self._refresh_sampling()

    def _screen_destroyed(self) -> None:
        self._screen = None
        self._refresh_sampling()

    def _refresh_sampling(self, _rate: float | None = None) -> None:
        rate = self._screen.refreshRate() if self._screen is not None else 60.0
        if not isfinite(rate) or rate < 24:
            rate = 60.0
        # 毫秒定时器只做近似采样；最高按 360Hz 取整，避免异常驱动值形成忙循环。
        self._timer.setInterval(max(1, round(1000 / min(360.0, rate))))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Type.Hide, QEvent.Type.Close):
            self.stop()
        elif kind == QEvent.Type.WindowStateChange:
            window = self._host_window()
            if window is not None and window.isMinimized():
                self.stop()
        elif kind in (QEvent.Type.ParentChange, QEvent.Type.Show):
            # 原生表面销毁期间的 WinIdChange 不能安全查询 QWidget；窗口重新显示
            # 或控件重挂时再解析宿主，其余跨屏变化由 QWindow.screenChanged 通知。
            self._sync_host()
        return False

    def _owner_destroyed(self) -> None:
        """显式宿主先销毁时停止采样；不访问其控件树或向销毁中的消费者发信号。"""
        if self._disposed:
            return
        self._disposed = True
        self._generation += 1
        self._timer.stop()
        self._state = QAbstractAnimation.State.Stopped
        self._unbind_handle()
        self._bind_screen(None)
        # 显式 owner 可以是仍存活窗口中的子控件，只撤下外部窗口的观察器，
        # 不触碰当前正在销毁的 owner 本身。
        window = self._host_window()
        if window is not None and window is not self._owner:
            window.removeEventFilter(self)
        self._owner = None
        self._window_ref = None
