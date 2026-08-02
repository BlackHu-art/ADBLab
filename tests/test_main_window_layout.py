from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from gui.main_frame import MainFrame
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.responsive_layout import reflow_widgets, responsive_column_count
from gui.window_layout import (
    DEFAULT_PANEL_RATIO,
    normalize_panel_ratio,
    normalize_window_size,
    ratio_from_sizes,
    split_sizes_for_ratio,
)


@pytest.mark.parametrize(
    ("width", "height", "available", "expected"),
    [
        (1120, 640, QSize(1920, 1040), QSize(1120, 640)),
        ("bad", None, QSize(1920, 1040), QSize(1120, 640)),
        (-1, 200, QSize(1920, 1040), QSize(860, 500)),
        (4000, 3000, QSize(1366, 728), QSize(1366, 728)),
    ],
)
def test_normalize_window_size_handles_invalid_and_offscreen_values(
    width, height, available, expected
):
    assert normalize_window_size(width, height, available_size=available) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.4, 0.4), ("0.55", 0.55), (-1, DEFAULT_PANEL_RATIO), (2, DEFAULT_PANEL_RATIO)],
)
def test_normalize_panel_ratio(value, expected):
    assert normalize_panel_ratio(value) == pytest.approx(expected)


def test_panel_ratio_round_trip_uses_actual_splitter_sizes():
    sizes = split_sizes_for_ratio(1000, 0.37)
    assert sizes == (370, 630)
    assert ratio_from_sizes(*sizes) == pytest.approx(0.37)
    assert ratio_from_sizes("bad", None) == pytest.approx(DEFAULT_PANEL_RATIO)


@pytest.mark.parametrize(
    ("width", "expected"),
    [(300, 1), (419, 1), (420, 2), (559, 2), (560, 4)],
)
def test_responsive_column_count_uses_stable_breakpoints(width, expected):
    assert responsive_column_count(width) == expected


def test_reflow_widgets_preserves_declared_column_weights(qt_application):
    parent = QWidget()
    layout = QGridLayout(parent)
    widgets = tuple(QPushButton(str(index)) for index in range(3))

    reflow_widgets(layout, widgets, 3, widget_stretches=(2, 1, 1))
    assert [layout.columnStretch(index) for index in range(3)] == [2, 1, 1]

    reflow_widgets(layout, widgets, 2, widget_stretches=(2, 1, 1))
    assert [layout.columnStretch(index) for index in range(3)] == [2, 1, 0]
    assert tuple(layout.itemAt(index).widget() for index in range(3)) == widgets


def test_frameless_resize_controller_builds_eight_invisible_edge_zones(qt_application):
    window = QWidget()
    window.resize(800, 600)
    controller = FramelessResizeController(window, edge_width=8, corner_size=14)

    assert len(controller.zones) == 8
    assert controller._zones["left"].geometry().getRect() == (0, 14, 8, 572)
    assert controller._zones["right"].geometry().getRect() == (792, 14, 8, 572)
    assert controller._zones["top_left"].geometry().getRect() == (0, 0, 14, 14)
    assert controller._zones["bottom_right"].geometry().getRect() == (786, 586, 14, 14)
    assert controller._zones["left"]._edges == Qt.Edge.LeftEdge
    assert controller._zones["top_right"]._edges == (Qt.Edge.TopEdge | Qt.Edge.RightEdge)


def test_frameless_resize_zones_follow_maximized_state(qt_application):
    class Window(QWidget):
        maximized = False

        def isMaximized(self):
            return self.maximized

    window = Window()
    window.resize(800, 600)
    controller = FramelessResizeController(window)
    assert all(not zone.isHidden() for zone in controller.zones)

    window.maximized = True
    controller.update_geometry()
    assert all(zone.isHidden() for zone in controller.zones)

    window.maximized = False
    controller.update_geometry()
    assert all(not zone.isHidden() for zone in controller.zones)


def test_main_frame_settings_update_prefers_batch_api():
    calls = []

    class BatchSettings:
        def set_many(self, values):
            calls.append(dict(values))

    MainFrame._update_settings(BatchSettings(), {"a": 1, "b": 2})
    assert calls == [{"a": 1, "b": 2}]


def test_main_frame_settings_update_falls_back_to_individual_keys():
    settings = SimpleNamespace(values={})
    settings.set = lambda key, value: settings.values.__setitem__(key, value)

    MainFrame._update_settings(settings, {"a": 1, "b": 2})
    assert settings.values == {"a": 1, "b": 2}


def test_programmatic_panel_ratio_triggers_responsive_reflow():
    splitter = Mock()
    splitter.sizes.return_value = [400, 600]
    frame = SimpleNamespace(
        _panel_splitter=splitter,
        _pending_panel_sizes=None,
        _responsive_layout_timer=Mock(),
    )

    MainFrame.apply_panel_ratio(frame, 0.35)

    splitter.setSizes.assert_called_once_with([350, 650])
    assert frame._pending_panel_sizes == (350, 650)
    frame._responsive_layout_timer.start.assert_called_once_with(0)


def test_restore_default_window_size_leaves_maximized_state():
    frame = SimpleNamespace(
        isMaximized=lambda: True,
        isMinimized=lambda: False,
        isFullScreen=lambda: False,
        showNormal=Mock(),
        apply_window_size=Mock(),
        size=lambda: QSize(1120, 640),
        _schedule_window_size_save=Mock(),
    )

    MainFrame.restore_default_window_size(frame)

    frame.showNormal.assert_called_once_with()
    frame.apply_window_size.assert_called_once_with(1120, 640)
    frame._schedule_window_size_save.assert_called_once_with(QSize(1120, 640))


def test_settings_dialog_close_refreshes_toolbar_save_path():
    dialog = Mock()
    dialog.exec_.return_value = 1
    frame = SimpleNamespace(
        set_continuous_scan=Mock(),
        _refresh_save_path=Mock(),
    )

    with patch("gui.main_frame.SettingsDialog", return_value=dialog):
        MainFrame._show_settings(frame)

    dialog.installEventFilter.assert_called_once_with(frame)
    dialog.continuous_scan_toggled.connect.assert_called_once_with(frame.set_continuous_scan)
    frame._refresh_save_path.assert_called_once_with()


def test_toolbar_height_does_not_follow_vertical_window_resize():
    """在隔离 Qt 进程中验证工具栏只响应字体尺寸，不吸收窗口剩余高度。"""

    script = textwrap.dedent("""
        import os
        from unittest.mock import Mock, patch

        from PySide6.QtWidgets import QApplication, QSizePolicy

        from core.settings_manager import AppSettings
        from gui.main_frame import MainFrame
        from gui.styles import BaseStyles


        class Settings:
            save_directory = os.path.join(os.getcwd(), "__missing_default_save_directory__")

            def __init__(self):
                self.values = {
                    "window_width": 1120,
                    "window_height": 640,
                    "left_panel_width": 400,
                    "right_panel_width": 600,
                    "panel_split_ratio": 0.4,
                    "always_on_top": False,
                    "log_max_lines": 2000,
                }

            def get(self, key, default=None):
                return self.values.get(key, default)

            def set(self, key, value):
                self.values[key] = value

            def update(self, values):
                self.values.update(values)

            set_many = update


        app = QApplication([])
        settings = Settings()
        controller = Mock()
        controller.signals = Mock()
        with (
            patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
            patch("gui.main_frame.ADBController", lambda _log_service: controller),
            patch.object(MainFrame, "_bootstrap_adb_async", lambda _self: None),
        ):
            window = MainFrame()
            window.show()
            toolbar_heights = []
            content_heights = []
            for height in (500, 640, 800):
                window.resize(1120, height)
                app.processEvents()
                app.processEvents()
                toolbar_heights.append(window._toolbar.height())
                content_heights.append(window._panel_splitter.height())

            expected_height = BaseStyles.control_height(minimum=32, padding=8)
            layout = window.centralWidget().layout()
            base_size_passed = all(
                (
                    window._toolbar.sizePolicy().verticalPolicy() == QSizePolicy.Fixed,
                    toolbar_heights == [expected_height] * 3,
                    content_heights[-1] - content_heights[0] == 300,
                    layout.stretch(0) == 0,
                    layout.stretch(1) == 1,
                )
            )

            with patch.object(BaseStyles, "control_height", return_value=48):
                window._on_ui_font_changed(None)
                window.resize(1120, 640)
                app.processEvents()
                app.processEvents()
                scaled_height = window._toolbar.height()
                window.resize(1120, 800)
                app.processEvents()
                app.processEvents()
                scaled_resized_height = window._toolbar.height()

            with patch.object(BaseStyles, "control_height", return_value=expected_height):
                window._on_ui_font_changed(None)
                app.processEvents()
                app.processEvents()
                restored_height = window._toolbar.height()

            path_states = []
            for width in (860, 919, 920, 1039, 1040, 1120, 1230):
                window.resize(width, 640)
                app.processEvents()
                app.processEvents()
                path_states.append(
                    (
                        window._save_path_label.isVisible(),
                        window._save_path_label.width(),
                        window._save_path_label.maximumWidth(),
                        window._save_path_label.text(),
                        window._save_path_label.toolTip(),
                    )
                )

            expected_maximum_widths = (100, 159, 160, 160, 180, 260, 370)
            narrow_texts = tuple(state[3] for state in path_states[:4])
            wide_texts = tuple(state[3] for state in path_states[4:])
            settings.save_directory = os.path.join(os.getcwd(), "updated-save-directory")
            window._refresh_save_path()
            app.processEvents()
            updated_path_state = (
                window._save_path_label.width(),
                window._save_path_label.text(),
                window._save_path_label.toolTip(),
            )

            passed = all(
                (
                    base_size_passed,
                    scaled_height == scaled_resized_height == 48,
                    restored_height == expected_height,
                    window._save_path_label.sizePolicy().horizontalPolicy()
                    == QSizePolicy.Preferred,
                    window._toolbar_title.font().bold(),
                    not window._save_path_label.font().bold(),
                    tuple(state[2] for state in path_states) == expected_maximum_widths,
                    all(state[0] and state[1] > 0 and state[3] for state in path_states),
                    all("GlobalSavePath:" not in text for text in narrow_texts),
                    all(text.startswith("Globa") for text in wide_texts),
                    all("__missing_default_save_directory__" in state[4] for state in path_states),
                    updated_path_state[0] > 0,
                    updated_path_state[1].startswith("Globa"),
                    updated_path_state[2] == settings.save_directory,
                )
            )
            if not passed:
                print(
                    "toolbar_heights=",
                    toolbar_heights,
                    "content_heights=",
                    content_heights,
                    "expected_height=",
                    expected_height,
                    "scaled_heights=",
                    (scaled_height, scaled_resized_height),
                    "restored_height=",
                    restored_height,
                    "path_states=",
                    path_states,
                    "updated_path_state=",
                    updated_path_state,
                )
            window._close_ready = True
            window.close()
        raise SystemExit(0 if passed else 2)
        """)
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_minimum_window_keeps_log_panel_visible_with_large_font():
    """在隔离 Qt 进程中验证最小窗口和最大字号组合。"""

    script = textwrap.dedent("""
        from unittest.mock import Mock, patch

        from PySide6.QtWidgets import QApplication, QSizePolicy

        from core.settings_manager import AppSettings
        from gui.main_frame import MainFrame
        from gui.styles import BaseStyles


        class Settings:
            save_directory = "."

            def __init__(self):
                self.values = {
                    "window_width": 860,
                    "window_height": 500,
                    "left_panel_width": 300,
                    "right_panel_width": 560,
                    "panel_split_ratio": 0.35,
                    "always_on_top": False,
                    "log_max_lines": 2000,
                }

            def get(self, key, default=None):
                return self.values.get(key, default)

            def set(self, key, value):
                self.values[key] = value

            def update(self, values):
                self.values.update(values)

            set_many = update


        app = QApplication([])
        settings = Settings()
        controller = Mock()
        controller.signals = Mock()
        BaseStyles.DEFAULT_FONT_SIZE = 22
        with (
            patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
            patch("gui.main_frame.ADBController", lambda _log_service: controller),
            patch.object(MainFrame, "_bootstrap_adb_async", lambda _self: None),
        ):
            window = MainFrame()
            window.resize(860, 500)
            window.show()
            app.processEvents()
            device_widget = window.left_panel.device_widget
            passed = all(
                (
                    device_widget.sizePolicy().verticalPolicy() == QSizePolicy.Preferred,
                    window.log_panel.minimumHeight() == 120,
                    window.log_panel.height() >= 120,
                    window.log_panel.isVisible(),
                )
            )
            window._close_ready = True
            window.close()
        raise SystemExit(0 if passed else 2)
        """)
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
