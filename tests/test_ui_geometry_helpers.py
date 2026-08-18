"""真实 Qt 几何断言和测试状态隔离的契约。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
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
        assert not hidden_window.isVisible()
        QCoreApplication.processEvents()
        assert timed_out == []
        QCoreApplication.sendPostedEvents(visible_window, QEvent.Type.DeferredDelete)
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
