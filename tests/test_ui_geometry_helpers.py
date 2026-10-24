"""真实 Qt 几何断言和测试状态隔离的契约。"""

from __future__ import annotations

import gc
import subprocess
import sys
import textwrap
import threading
import weakref
from builtins import ExceptionGroup
from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget
from shiboken6 import delete, isValid

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.conftest import isolated_ui_state
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_elided_accessible_text,
    assert_non_overlapping,
    assert_positive_geometry,
    assert_scroll_target_reachable,
    assert_square,
    assert_text_fits,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)


def test_geometry_helpers_detect_real_overlap_and_ancestor_clipping(qt_application):
    host = QWidget()
    host.resize(180, 90)
    first = QPushButton("First", host)
    second = QPushButton("Second", host)
    first.setGeometry(10, 10, 90, 30)
    second.setGeometry(70, 10, 90, 30)
    with pytest.raises(AssertionError, match="overlap"):
        assert_non_overlapping([first, second], host)
    second.setGeometry(100, 10, 70, 30)
    assert_non_overlapping([first, second], host)
    assert_contained(second, host)
    second.setGeometry(150, 10, 70, 30)
    with pytest.raises(AssertionError, match="contained"):
        assert_contained(second, host)

    unrelated = QWidget()
    with pytest.raises(ValueError, match="ancestor"):
        mapped_rect(first, unrelated)


def test_geometry_helpers_report_timeout_and_wait_for_stable_geometry(qt_application):
    with pytest.raises(AssertionError, match="deadline"):
        wait_until(qt_application, lambda: False, timeout_ms=1)

    host = QWidget()
    host.resize(120, 60)
    wait_for_stable_geometry(qt_application, host, timeout_ms=100)


def test_geometry_helpers_detect_text_overflow_and_require_elided_accessibility(qt_application):
    label = QLabel("A label whose content cannot fit in this narrow control")
    label.resize(40, 24)
    with pytest.raises(AssertionError, match="text fits"):
        assert_text_fits(label)

    label.setToolTip(label.text())
    assert_elided_accessible_text(label)


def test_geometry_helpers_reach_targets_from_scrollbar_endpoints(qt_application):
    scroll = QScrollArea()
    scroll.resize(100, 100)
    content = QWidget()
    content.resize(100, 420)
    target = QPushButton("Target", content)
    target.setGeometry(10, 360, 80, 30)
    scroll.setWidget(content)
    scroll.show()
    qt_application.processEvents()

    assert scroll.verticalScrollBar().maximum() > 0
    assert_scroll_target_reachable(scroll, target)


def test_geometry_helpers_reach_both_edges_of_oversized_target(qt_application):
    scroll = QScrollArea()
    scroll.resize(120, 100)
    content = QWidget()
    content.resize(360, 100)
    target = QPushButton("Oversized target", content)
    target.setGeometry(10, 20, 320, 30)
    scroll.setWidget(content)
    scroll.show()
    qt_application.processEvents()

    assert scroll.horizontalScrollBar().maximum() > 0
    assert_scroll_target_reachable(scroll, target)


def test_geometry_helpers_validate_positive_and_square_dimensions(qt_application):
    widget = QWidget()
    widget.resize(32, 32)
    assert_positive_geometry(widget)
    assert_square(widget)
    widget.resize(32, 24)
    with pytest.raises(AssertionError, match="square"):
        assert_square(widget)


def test_isolated_ui_state_restores_state_and_stops_hidden_window_timer(
    qt_application,
    isolated_ui_state_probe,
):
    previous_theme = BaseStyles.current_theme()
    previous_font = QApplication.font().toString()
    previous_font_size = BaseStyles.DEFAULT_FONT_SIZE
    previous_font_config = BaseStyles.current_font_config()
    hidden_window = QWidget()
    hidden_window.setObjectName("hidden-isolation-probe")
    hidden_timer = QTimer(hidden_window)
    visible_window = QWidget()
    visible_window.setObjectName("visible-isolation-probe")
    visible_timer = QTimer(visible_window)
    visible_timer_destroyed = []
    visible_window_destroyed = []
    visible_timer.destroyed.connect(lambda: visible_timer_destroyed.append(True))
    visible_window.destroyed.connect(lambda: visible_window_destroyed.append(True))
    timed_out = []
    hidden_timer.timeout.connect(lambda: timed_out.append(True))
    hidden_timer.start(0)
    visible_timer.start(1000)
    BaseStyles.switch_theme("Dark" if previous_theme == "Light" else "Light")
    BaseStyles.DEFAULT_FONT_SIZE = 19
    typography_manager.apply(replace(previous_font_config, ui_size=20))
    qt_application.setFont(QFont("Arial", 19))
    hidden_window.hide()
    visible_window.show()

    def assert_after_isolation(probe):
        hidden_cleanup = probe["cleanup"][id(hidden_window)]
        visible_cleanup = probe["cleanup"][id(visible_window)]
        assert hidden_cleanup["timer_was_active"]
        assert hidden_cleanup["timer_stopped"]
        assert visible_cleanup["timer_was_active"]
        assert visible_cleanup["timer_stopped"]
        assert not isValid(hidden_window)
        QCoreApplication.processEvents()
        assert timed_out == []
        assert not isValid(visible_window)
        assert visible_timer_destroyed == [True]
        assert visible_window_destroyed == [True]
        assert BaseStyles.current_theme() == previous_theme
        assert QApplication.font().toString() == previous_font
        assert BaseStyles.DEFAULT_FONT_SIZE == previous_font_size
        assert BaseStyles.current_font_config() == previous_font_config

    isolated_ui_state_probe["assertions"].append(assert_after_isolation)


def test_isolated_ui_state_stops_timers_before_and_after_reentrant_shutdown(
    isolated_ui_state_probe,
):
    class ReentrantShutdownWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.timeouts = []
            self.timer = QTimer(self)
            self.timer.timeout.connect(lambda: self.timeouts.append(True))
            self.timer.start(0)

        def shutdown(self):
            QCoreApplication.processEvents()
            self.timer.start(0)

    window = ReentrantShutdownWindow()
    window.hide()

    def assert_after_isolation(probe):
        cleanup = probe["cleanup"][id(window)]
        assert cleanup["timer_was_active"]
        assert cleanup["post_shutdown_timer_was_active"]
        assert cleanup["timer_stopped"]
        QCoreApplication.processEvents()
        assert window.timeouts == []

    isolated_ui_state_probe["assertions"].append(assert_after_isolation)


def test_isolated_ui_state_releases_already_closed_windows(isolated_ui_state_probe):
    window = QWidget()
    destroyed = []
    window.destroyed.connect(lambda: destroyed.append(True))
    window.show()
    window.close()

    def assert_after_isolation(_probe):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(window)
        assert destroyed == [True]

    isolated_ui_state_probe["assertions"].append(assert_after_isolation)


def test_isolated_ui_state_reports_shutdown_failure_and_still_releases_windows(qt_application):
    isolation = isolated_ui_state.__wrapped__(qt_application, {"cleanup": {}}, None)
    next(isolation)
    failure = RuntimeError("shutdown failed while the Qt window is still alive")

    class FailingShutdownWindow(QWidget):
        def shutdown(self):
            raise failure

    failed_window = FailingShutdownWindow()
    other_window = QWidget()
    try:
        with pytest.raises(ExceptionGroup, match="UI window cleanup failed") as captured:
            next(isolation)
        assert captured.value.exceptions == (failure,)
        assert not isValid(failed_window)
        assert not isValid(other_window)
    finally:
        for window in (failed_window, other_window):
            if isValid(window):
                delete(window)


def test_isolated_ui_state_accepts_window_deleted_by_its_shutdown(qt_application):
    isolation = isolated_ui_state.__wrapped__(qt_application, {"cleanup": {}}, None)
    next(isolation)

    class SelfDeletingWindow(QWidget):
        def shutdown(self):
            delete(self)

    window = SelfDeletingWindow()
    with pytest.raises(StopIteration):
        next(isolation)
    assert not isValid(window)


class _ControlledCleanupThread(QThread):
    """不访问外部资源，清理回归可在 finally 可靠解除阻塞。"""

    def __init__(self, entered, release, parent):
        super().__init__(parent)
        self.entered = entered
        self.release = release

    def run(self):
        self.entered.set()
        self.release.wait(10)


def test_isolated_ui_state_prepares_owner_and_joins_active_child_before_deletion(qt_application):
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    isolation = isolated_ui_state.__wrapped__(qt_application, {"cleanup": {}}, None)
    next(isolation)
    entered, release = threading.Event(), threading.Event()
    prepared = []

    class PreparedWindow(QWidget):
        def _prepare_ui_for_shutdown(self):
            prepared.append(True)
            # 模拟既有异步清理：等待线程时仍须允许 GUI 回调兑现。
            QTimer.singleShot(0, release.set)

    window = PreparedWindow()
    worker = _ControlledCleanupThread(entered, release, window)
    worker.start()
    assert entered.wait(2)
    try:
        with pytest.raises(StopIteration):
            next(isolation)
        assert prepared == [True]
        assert not isValid(window)
        assert not isValid(worker)
    finally:
        release.set()
        if isValid(worker):
            assert worker.wait(2000)
        if isValid(window):
            assert cleanup_ui_windows((window,), cleanup_records={}) == []
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("shutdown_raises", [False, True])
def test_ui_cleanup_timeout_retains_owner_and_continues_other_windows(
    qt_application, shutdown_raises,
):
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    entered, release = threading.Event(), threading.Event()
    failure = RuntimeError("synthetic shutdown failure")

    class BlockedWindow(QWidget):
        def shutdown(self):
            if shutdown_raises:
                raise failure

    window = BlockedWindow()
    other_window = QWidget()
    worker = _ControlledCleanupThread(entered, release, window)
    worker.start()
    assert entered.wait(2)
    owner_ref = weakref.ref(window)
    records = {}
    try:
        errors = cleanup_ui_windows((window, other_window), cleanup_records=records, timeout_ms=5)
        assert len(errors) == 1 + int(shutdown_raises)
        if shutdown_raises:
            assert errors[0] is failure
        assert isinstance(errors[-1], TimeoutError)
        assert records[id(window)]["retained"] is True
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(other_window)
        assert isValid(window)
        del window
        gc.collect()
        assert owner_ref() is not None
        assert worker.isRunning()
    finally:
        release.set()
        assert worker.wait(2000)
        owner = owner_ref()
        if owner is not None and isValid(owner):
            # 复核已退出线程后须移除保留引用，失败的 shutdown 仍如实返回。
            cleanup_ui_windows((owner,), cleanup_records={})
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert owner is not None and not isValid(owner)
        # 预期异常的 traceback 也会持有 self；这里只衡量清理保留表的引用。
        failure.__traceback__ = None
        del owner
        gc.collect()
        assert owner_ref() is None


def test_ui_cleanup_close_error_still_joins_stopped_children_and_releases_windows(
    qt_application, monkeypatch,
):
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    window, other_window = QWidget(), QWidget()
    entered, release = threading.Event(), threading.Event()
    worker = _ControlledCleanupThread(entered, release, window)
    worker.start()
    release.set()
    assert worker.wait(2000)
    failure = RuntimeError("synthetic close failure")

    def fail_close():
        raise failure

    monkeypatch.setattr(window, "close", fail_close)
    window.show()
    try:
        errors = cleanup_ui_windows((window, other_window), cleanup_records={})
        assert errors == [failure]
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(window)
        assert not isValid(other_window)
    finally:
        if isValid(window):
            window.hide()
            cleanup_ui_windows((window,), cleanup_records={})
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_ui_cleanup_retries_retained_owner_even_when_no_new_window_is_supplied(qt_application):
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    window = QWidget()
    entered, release = threading.Event(), threading.Event()
    worker = _ControlledCleanupThread(entered, release, window)
    worker.start()
    assert entered.wait(2)
    try:
        errors = cleanup_ui_windows((window,), cleanup_records={}, timeout_ms=0)
        assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
        release.set()
        assert worker.wait(2000)
        assert cleanup_ui_windows((), cleanup_records={}, timeout_ms=0) == []
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(window)
    finally:
        release.set()
        if isValid(worker):
            assert worker.wait(2000)
        if isValid(window):
            cleanup_ui_windows((window,), cleanup_records={})
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("delete_mode", ["automatic", "posted"])
def test_ui_cleanup_retains_live_thread_owner_when_deletion_was_already_requested(delete_mode):
    """危险析构断言在受控子进程中执行，红灯不能杀死父 pytest。"""
    script = textwrap.dedent("""
        import ctypes
        import sys
        import threading
        from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt
        from PySide6.QtWidgets import QApplication, QWidget
        from shiboken6 import isValid
        from tests.ui_lifecycle_helpers import cleanup_ui_windows

        if sys.platform == "win32":
            ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
        app = QApplication([])
        entered, release = threading.Event(), threading.Event()
        class Worker(QThread):
            def run(self):
                entered.set()
                release.wait(5)
        window = QWidget()
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.show()
        worker = Worker(window)
        worker.start()
        assert entered.wait(2)
        if sys.argv[1] == "posted":
            window.deleteLater()
        try:
            errors = cleanup_ui_windows((window,), cleanup_records={}, timeout_ms=0)
            assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert isValid(window) and worker.isRunning()
        finally:
            release.set()
            if isValid(worker):
                assert worker.wait(2000)
            if isValid(window):
                assert cleanup_ui_windows((window,), cleanup_records={}, timeout_ms=0) == []
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not isValid(window)
    """)
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script, delete_mode],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, (
        f"child exit {result.returncode:#x}\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize("advanced_stages", [0, 1, 2])
def test_ui_cleanup_uses_real_abort_boundary_for_incomplete_mainframe(
    qt_application, monkeypatch, advanced_stages,
):
    from tests.test_mainframe_startup import startup
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    startup_scope = startup.__wrapped__(qt_application, monkeypatch)
    create, _bootstrap, _detection, _controllers = next(startup_scope)
    frame = create(deferred_startup=True)
    aborted = []
    frame.startup_aborted.connect(lambda: aborted.append(True))
    try:
        for _ in range(advanced_stages):
            frame.advance_startup()
        assert cleanup_ui_windows((frame,), cleanup_records={}) == []
        assert aborted == [True]
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(frame)
    finally:
        with pytest.raises(StopIteration):
            next(startup_scope)
