"""验证启动阶段调度、首帧交接与失败资源收口。"""

from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget


class _Splash(QWidget):
    first_painted = Signal()
    cancelled = Signal()

    def __init__(self, events):
        super().__init__()
        self.events = events
        self.progress = []

    def set_progress(self, value, *, animate=True):
        self.progress.append(value)

    def finish(self):
        self.events.append("splash-finished")
        self.hide()


class _Window(QWidget):
    startup_aborted = Signal()

    def __init__(self, events):
        super().__init__()
        self.events = events
        self.abort_count = 0

    def paintEvent(self, event):
        self.events.append("window-painted")
        super().paintEvent(event)

    def abort_startup(self):
        self.abort_count += 1


def _drain_until(predicate):
    for _ in range(100):
        QCoreApplication.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    assert predicate(), "启动事件没有完成"


@pytest.mark.parametrize("cancel", [False, True])
def test_background_gate_keeps_qt_responsive_and_waits_for_exit(qt_application, cancel):
    """慢磁盘门禁期间不建窗口；取消等待真实退出，晚到完成不能重启阶段。"""
    from gui.startup import StartupController
    from gui.startup_task import StartupTask

    entered, release = threading.Event(), threading.Event()
    events = []
    splash = _Splash(events)
    startup = StartupController(splash)
    window = _Window(events)
    cancelled = []
    startup.cancelled.connect(lambda: cancelled.append(True))

    def work(stop):
        assert threading.current_thread() is not threading.main_thread()
        entered.set()
        assert release.wait(3)
        events.append("worker-exit")

    task = StartupTask("history", work)

    def stages():
        try:
            yield task
            events.append("window-created")
            startup.set_window(window)
            yield "window", 95
        finally:
            events.append("generator-closed")

    startup.start(stages())
    splash.first_painted.emit()
    try:
        _drain_until(entered.is_set)
        assert "window-created" not in events
        if cancel:
            startup.cancel()
            startup.cancel()
            assert not startup.is_settled
            assert "generator-closed" not in events
        QTimer.singleShot(0, lambda: (events.append("tick"), release.set()))
        _drain_until(lambda: startup.is_settled)
        assert events.index("tick") < events.index("worker-exit")
        assert not task.isRunning()
        if cancel:
            assert cancelled == [True]
            assert "window-created" not in events
            assert events.index("worker-exit") < events.index("generator-closed")
        else:
            assert events.index("worker-exit") < events.index("window-created")
    finally:
        release.set()
        task.wait(3000)
        startup.deleteLater()


def test_background_failure_resumes_generator_for_explicit_fallback(qt_application):
    from gui.startup import StartupController
    from gui.startup_task import StartupTask

    failure = OSError("synthetic read failure")

    def work(_stop):
        raise failure

    events = []
    splash = _Splash(events)
    startup = StartupController(splash)
    task = StartupTask("history", work)

    def stages():
        yield task
        assert task.error is failure
        raise task.error

    errors = []
    startup.failed.connect(errors.append)
    startup.start(stages())
    splash.first_painted.emit()
    _drain_until(lambda: startup.is_settled)
    assert errors == [failure]
    assert not task.isRunning()
    startup.deleteLater()


def test_stages_wait_for_splash_paint_and_yield_before_window_handoff(qt_application):
    from gui.startup import StartupController

    events = []
    splash = _Splash(events)
    window = _Window(events)
    startup = StartupController(splash)
    ready = []
    startup.ready.connect(ready.append)

    def stages():
        events.append("first-stage")
        QTimer.singleShot(0, lambda: events.append("between-stages"))
        yield "components", 25
        events.append("second-stage")
        startup.set_window(window)
        yield "window", 95

    startup.start(stages())
    qt_application.processEvents()
    assert "first-stage" not in events
    splash.first_painted.emit()
    splash.first_painted.emit()
    _drain_until(lambda: bool(ready))

    assert (
        events.index("first-stage") < events.index("between-stages") < events.index("second-stage")
    )
    assert events.index("window-painted") < events.index("splash-finished")
    assert events.count("first-stage") == 1
    assert ready == [window]
    assert splash.progress[-1] == 100
    assert not splash.isVisible()
    window.close()
    startup.deleteLater()


def test_failure_waits_for_owned_window_cleanup_and_keeps_original_error(qt_application):
    from gui.startup import StartupController

    events = []
    splash = _Splash(events)
    window = _Window(events)
    startup = StartupController(splash)
    failure = ValueError("synthetic startup failure")
    errors = []
    startup.failed.connect(errors.append)

    def stages():
        try:
            startup.set_window(window)
            yield "base", 40
            raise failure
        finally:
            events.append("generator-closed")

    startup.start(stages())
    splash.first_painted.emit()
    _drain_until(lambda: window.abort_count == 1)
    assert not errors
    assert "generator-closed" in events
    assert 100 not in splash.progress
    window.startup_aborted.emit()
    _drain_until(lambda: bool(errors))
    assert errors == [failure]
    assert startup.error is failure
    window.startup_aborted.emit()
    qt_application.processEvents()
    assert len(errors) == 1
    startup.deleteLater()


def test_cancelling_before_first_paint_never_runs_late_stages(qt_application):
    from gui.startup import StartupController

    events = []
    splash = _Splash(events)
    startup = StartupController(splash)
    cancelled = []
    startup.cancelled.connect(lambda: cancelled.append(True))

    def stages():
        events.append("unexpected-stage")
        yield "unexpected", 25

    startup.start(stages())
    splash.cancelled.emit()
    splash.first_painted.emit()
    startup.cancel()
    _drain_until(lambda: bool(cancelled))
    assert "unexpected-stage" not in events
    assert len(cancelled) == 1
    assert not splash.isVisible()
    startup.deleteLater()


def test_cancelling_after_initialization_before_paint_does_not_report_ready(qt_application):
    from gui.startup import StartupController

    events = []
    splash = _Splash(events)
    window = _Window(events)
    startup = StartupController(splash)
    ready = []
    cancelled = []
    startup.ready.connect(ready.append)
    startup.cancelled.connect(lambda: cancelled.append(True))

    def stages():
        startup.set_window(window)
        yield "window", 95
        startup.cancel()

    startup.start(stages())
    splash.first_painted.emit()
    _drain_until(lambda: window.abort_count == 1)
    window.startup_aborted.emit()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    assert not ready
    assert cancelled == [True]
    assert 100 not in splash.progress
    startup.deleteLater()


def test_generator_close_failure_still_aborts_window_and_reports_failure(qt_application):
    from gui.startup import StartupController

    events = []
    splash = _Splash(events)
    window = _Window(events)
    startup = StartupController(splash)
    failure = RuntimeError("synthetic generator close failure")
    errors = []
    startup.failed.connect(errors.append)

    def stages():
        try:
            startup.set_window(window)
            while True:
                yield "base", 40
        finally:
            raise failure

    startup.start(stages())
    splash.first_painted.emit()
    _drain_until(lambda: bool(splash.progress))
    startup.cancel()
    assert window.abort_count == 1
    assert errors == []
    assert not startup.is_settled
    window.startup_aborted.emit()
    _drain_until(lambda: bool(errors))
    assert errors == [failure]
    assert startup.error is failure
    assert startup.is_settled
    startup.cancel()
    assert window.abort_count == 1
    assert errors == [failure]
    startup.deleteLater()


def test_close_after_first_paint_before_handoff_never_reports_ready(qt_application):
    from gui.startup import StartupController

    class ClosingWindow(_Window):
        def paintEvent(self, event):
            super().paintEvent(event)
            self.close()

    events = []
    splash = _Splash(events)
    window = ClosingWindow(events)
    startup = StartupController(splash)
    ready = []
    cancelled = []
    startup.ready.connect(ready.append)
    startup.cancelled.connect(lambda: cancelled.append(True))

    def stages():
        startup.set_window(window)
        yield "window", 95

    startup.start(stages())
    splash.first_painted.emit()
    _drain_until(lambda: bool(ready) or window.abort_count == 1)
    assert ready == []
    assert window.abort_count == 1
    assert cancelled == []
    window.startup_aborted.emit()
    _drain_until(lambda: bool(cancelled))
    assert cancelled == [True]
    assert ready == []
    assert 100 not in splash.progress
    assert not window.isVisible()
    startup.deleteLater()


def test_window_show_failure_waits_for_abort_then_reports_original_error(
    qt_application, monkeypatch,
):
    from gui.startup import StartupController

    events = []
    splash = _Splash(events)
    window = _Window(events)
    startup = StartupController(splash)
    failure = RuntimeError("synthetic native window show failure")
    errors = []
    ready = []
    startup.failed.connect(errors.append)
    startup.ready.connect(ready.append)

    def fail_show():
        raise failure

    monkeypatch.setattr(window, "show", fail_show)

    def stages():
        startup.set_window(window)
        yield "window", 95

    startup.start(stages())
    splash.first_painted.emit()
    _drain_until(lambda: window.abort_count == 1)
    assert errors == []
    assert ready == []
    window.startup_aborted.emit()
    _drain_until(lambda: bool(errors))
    assert errors == [failure]
    assert startup.error is failure
    assert startup.is_settled
    assert 100 not in splash.progress
    startup.deleteLater()
