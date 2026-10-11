"""局部动画的独立采样时钟、重入边界和宿主生命周期。"""

import math
import weakref

import pytest
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from shiboken6 import delete, isValid

from gui.widgets.frame_animation import FrameAnimation

pytestmark = pytest.mark.ui


class _Clock:
    def __init__(self):
        self.now = 0
        self.starts = 0

    def start(self):
        self.now = 0
        self.starts += 1

    def restart(self):
        self.start()

    def elapsed(self):
        return self.now


class _Screen(QObject):
    refreshRateChanged = Signal(float)

    def __init__(self, rate):
        super().__init__()
        self.rate = rate

    def refreshRate(self):
        return self.rate


@pytest.fixture
def animation(qt_application):
    owner = QWidget()
    owner.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    owner.show()
    animation = FrameAnimation(owner)
    animation.setStartValue(0.0)
    animation.setEndValue(100.0)
    animation.setDuration(100)
    animation._clock = _Clock()
    yield animation, owner
    if isValid(owner):
        owner.close()


def _tick(animation, elapsed):
    animation._clock.now = elapsed
    animation._tick()


def test_interpolator_never_runs_and_completion_order_is_exact(animation):
    item, _owner = animation
    observed = []
    item.valueChanged.connect(lambda value: observed.append(("value", value)))
    item.stateChanged.connect(lambda new, old: observed.append(("state", new)))
    item.finished.connect(lambda: observed.append(("finished", None)))
    item.start()
    assert item._timer.timerType() == Qt.TimerType.PreciseTimer
    assert item._timer.isActive()
    _tick(item, 35)
    assert item.currentTime() == 35
    assert item._interpolator.state() == QAbstractAnimation.State.Stopped
    _tick(item, 145)
    assert observed[-3:] == [
        ("value", 100.0), ("state", QAbstractAnimation.State.Stopped), ("finished", None),
    ]
    _tick(item, 190)
    assert observed.count(("finished", None)) == 1
    assert not item._timer.isActive()


def test_running_retarget_keeps_clock_and_stopped_seek_does_not_finish(animation):
    item, _owner = animation
    finished = []
    item.finished.connect(lambda: finished.append(True))
    item.start()
    _tick(item, 40)
    starts = item._clock.starts
    item.setDuration(200)
    item.setEndValue(200.0)
    assert item.currentTime() == 40
    assert item._clock.starts == starts
    _tick(item, 75)
    assert item.currentTime() == 75
    assert item.currentValue() == pytest.approx(75)
    item.stop()
    item.setCurrentTime(200)
    assert item.currentValue() == 200.0
    assert not finished
    assert not item._timer.isActive()


def test_seek_pause_and_resume_rebase_elapsed_time(animation):
    item, _owner = animation
    item.start()
    _tick(item, 30)
    item.setCurrentTime(55)
    _tick(item, 7)
    assert item.currentTime() == 62
    item.pause()
    assert item.state() == QAbstractAnimation.State.Paused
    assert not item._timer.isActive()
    _tick(item, 500)
    assert item.currentTime() == 62
    item.resume()
    _tick(item, 8)
    assert item.currentTime() == 70


def test_repeated_start_does_not_restart_a_running_clock(animation):
    item, _owner = animation
    item.start()
    _tick(item, 35)
    starts = item._clock.starts
    item.start()
    assert item.currentTime() == 35
    assert item._clock.starts == starts
    _tick(item, 50)
    assert item.currentTime() == 50


def test_pause_keeps_last_presented_frame_until_resume(animation):
    item, _owner = animation
    item.start()
    _tick(item, 20)
    item._clock.now = 25
    item.pause()
    assert item.currentTime() == 20
    assert item.currentValue() == 20.0
    item.resume()
    _tick(item, 7)
    assert item.currentTime() == 27


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_terminal_value_callback_cannot_finish_or_stop_a_new_generation(animation, action):
    item, _owner = animation
    finished = []
    handled = []
    item.finished.connect(lambda: finished.append(True))

    def react(value):
        if value != 100.0 or handled:
            return
        handled.append(True)
        item.stop()
        if action == "restart":
            item.setEndValue(200.0)
            item.start()

    item.valueChanged.connect(react)
    item.start()
    _tick(item, 100)
    assert not finished
    if action == "restart":
        assert item.state() == QAbstractAnimation.State.Running
        assert item._timer.isActive()
        _tick(item, 20)
        assert item.currentValue() == pytest.approx(40)
    else:
        assert item.state() == QAbstractAnimation.State.Stopped
        assert not item._timer.isActive()


@pytest.mark.parametrize("rate,interval", [
    (0, 17), (-1, 17), (math.nan, 17), (math.inf, 17), (15, 17),
    (60, 17), (120, 8), (144, 7), (240, 4), (360, 3), (1000, 3),
])
def test_screen_sampling_rate_is_bounded_without_global_clock_changes(animation, rate, interval):
    item, _owner = animation
    item.start()
    screen = _Screen(rate)
    item._bind_screen(screen)
    assert item._timer.interval() == interval
    assert item._interpolator.state() == QAbstractAnimation.State.Stopped


def test_screen_switch_disconnects_old_refresh_signal_without_resetting_time(animation):
    item, _owner = animation
    item.start()
    first, second = _Screen(60), _Screen(120)
    item._bind_screen(first)
    _tick(item, 25)
    starts = item._clock.starts
    item._bind_screen(second)
    first.rate = 30
    first.refreshRateChanged.emit(30)
    assert item._timer.interval() == 8
    second.rate = 144
    second.refreshRateChanged.emit(144)
    assert item._timer.interval() == 7
    assert item.currentTime() == 25
    assert item._clock.starts == starts


@pytest.mark.parametrize("change", ["hide", "minimize", "close"])
def test_visibility_change_stops_at_current_value_without_finishing(animation, change):
    item, owner = animation
    finished = []
    item.finished.connect(lambda: finished.append(True))
    item.start()
    _tick(item, 40)
    before = item.currentValue()
    if change == "hide":
        owner.hide()
    elif change == "minimize":
        owner.showMinimized()
    else:
        owner.close()
    assert item.state() == QAbstractAnimation.State.Stopped
    assert not item._timer.isActive()
    assert item.currentValue() == before
    assert not finished


def test_parent_destruction_stops_timer_and_disconnects_external_screen(animation):
    item, owner = animation
    timer = item._timer
    screen = _Screen(120)
    item.start()
    item._bind_screen(screen)
    delete(owner)
    assert not isValid(item)
    assert not isValid(timer)
    screen.refreshRateChanged.emit(144)


def test_explicit_owner_can_be_destroyed_before_animation_parent(qt_application):
    parent = QObject()
    owner = QWidget()
    owner.show()
    item = FrameAnimation(parent, owner)
    item.setStartValue(0.0)
    item.setEndValue(1.0)
    item.start()
    delete(owner)
    assert isValid(item)
    assert item.state() == QAbstractAnimation.State.Stopped
    assert not item._timer.isActive()
    item.start()
    assert item.state() == QAbstractAnimation.State.Stopped
    delete(parent)


def test_child_owner_destruction_detaches_from_surviving_window(qt_application):
    class ObservedAnimation(FrameAnimation):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.User:
                events.append(watched)
            return super().eventFilter(watched, event)

    events = []
    parent = QObject()
    window = QWidget()
    owner = QWidget(window)
    window.show()
    item = ObservedAnimation(parent, owner)
    item.setStartValue(0.0)
    item.setEndValue(1.0)
    item.start()
    qt_application.sendEvent(window, QEvent(QEvent.Type.User))
    assert events == [window]
    delete(owner)
    events.clear()
    qt_application.sendEvent(window, QEvent(QEvent.Type.User))
    assert events == []
    assert not item._timer.isActive()
    delete(parent)
    delete(window)


def test_reparented_child_animation_does_not_keep_outer_window_alive(qt_application):
    from PySide6.QtWidgets import QScrollArea

    def build():
        panel = QWidget()
        owner = QWidget(panel)
        item = FrameAnimation(owner)
        outer = QScrollArea()
        outer.setWidget(panel)
        outer.show()
        qt_application.processEvents()
        outer.close()
        return weakref.ref(outer), panel, item

    reference, panel, item = build()
    try:
        assert reference() is None, "子动画不能改变外层窗口的 Python 所有权"
        assert not isValid(panel)
        assert not isValid(item)
    finally:
        # RED 阶段保留调用栈的窗口引用，避免断言清理自身触发祖先重入析构。
        outer = reference()
        if outer is not None and isValid(outer):
            delete(outer)


def test_real_timer_uses_elapsed_time_and_becomes_idle(qt_application):
    parent = QObject()
    item = FrameAnimation(parent)
    item.setStartValue(0.0)
    item.setEndValue(1.0)
    item.setDuration(70)
    item.setEasingCurve(QEasingCurve.Type.InOutSine)
    values = []
    item.valueChanged.connect(values.append)
    item.start()
    QTest.qWait(120)
    assert any(0.0 < value < 1.0 for value in values)
    assert values[-1] == 1.0
    assert item.state() == QAbstractAnimation.State.Stopped
    assert not any(timer.isActive() for timer in item.findChildren(QTimer))
    delete(parent)
