from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QGridLayout, QPushButton, QToolButton, QWidget

from core.settings_manager import AppSettings
from gui import window_layout
from gui.main_frame import MainFrame
from gui.styles import BaseStyles
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.responsive_controller import ReflowReason
from gui.widgets.responsive_layout import reflow_widgets, responsive_column_count
from gui.window_layout import (
    DEFAULT_PANEL_RATIO,
    normalize_panel_ratio,
    normalize_window_size,
    ratio_from_sizes,
    split_sizes_for_ratio,
)
from tests.ui_geometry_helpers import wait_until


@dataclass
class _FakeScreen:
    name: str
    available_size: QSize
    logical_dpi: float = 96.0


class _FakeScreenAdapter:
    """为 MainFrame 屏幕生命周期测试提供确定性 token 和信号。"""

    def __init__(self, screen: _FakeScreen):
        self.screen = screen
        self._next_token = 0
        self._callbacks = {}
        self.disconnected = []

    def window_screen(self, _window):
        return self.screen

    def available_size(self, screen):
        return QSize(screen.available_size)

    def logical_dpi(self, screen):
        return float(screen.logical_dpi)

    def connect_window_screen_changed(self, _window, callback):
        return self._connect("window", None, callback)

    def connect_available_geometry_changed(self, screen, callback):
        return self._connect("available", screen, callback)

    def connect_logical_dpi_changed(self, screen, callback):
        return self._connect("dpi", screen, callback)

    def disconnect(self, token):
        self.disconnected.append(token)
        self._callbacks.pop(token, None)

    def _connect(self, kind, screen, callback):
        self._next_token += 1
        token = (kind, self._next_token)
        self._callbacks[token] = (kind, screen, callback)
        return token

    def emit_screen_changed(self, screen):
        self.screen = screen
        self._emit("window", None, screen)

    def emit_available_geometry_changed(self, screen):
        self._emit("available", screen, screen)

    def emit_logical_dpi_changed(self, screen):
        self._emit("dpi", screen, screen.logical_dpi)

    def _emit(self, kind, screen, value):
        callbacks = tuple(self._callbacks.values())
        for registered_kind, registered_screen, callback in callbacks:
            if registered_kind == kind and registered_screen is screen:
                callback(value)

    def token_count(self, kind=None):
        return sum(
            1
            for registered_kind, _screen, _callback in self._callbacks.values()
            if kind is None or registered_kind == kind
        )


class _MainFrameSettings:
    save_directory = "."

    def __init__(self):
        self.values = {
            "window_width": 1120,
            "window_height": 640,
            "left_panel_width": 400,
            "right_panel_width": 600,
            "panel_split_ratio": 0.4,
            "device_log_split_ratio": 0.6,
            "always_on_top": False,
            "log_max_lines": 2000,
        }
        self.writes = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.writes.append({key: value})

    def set_many(self, values):
        values = dict(values)
        self.values.update(values)
        self.writes.append(values)


class _FakeMouseButtons:
    def __init__(self):
        self._buttons = Qt.MouseButton.NoButton

    def __call__(self):
        return self._buttons

    def press_left(self):
        self._buttons = Qt.MouseButton.LeftButton

    def release_left(self):
        self._buttons = Qt.MouseButton.NoButton


def build_main_frame(*, screen_adapter=None, settings=None, mouse_buttons_provider=None):
    """用本地依赖替身构造 MainFrame，不访问 ADB 或外部 helper。"""

    settings = settings or _MainFrameSettings()
    controller = Mock()
    controller.signals = Mock()
    with (
        patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
        patch("gui.main_frame.ADBController", lambda _log_service: controller),
        patch.object(MainFrame, "_bootstrap_adb_async", lambda _self: None),
    ):
        return MainFrame(
            screen_adapter=screen_adapter,
            mouse_buttons_provider=mouse_buttons_provider,
        )


def begin_native_user_resize(frame, qt_application):
    handle = Mock()
    handle.startSystemResize.return_value = True
    resize_window = SimpleNamespace(
        isMaximized=lambda: False,
        windowHandle=lambda: handle,
    )
    zone = frame._resize_controller._zones["right"]
    original_window = zone._window
    zone._window = resize_window
    try:
        QTest.mouseClick(zone, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
    finally:
        zone._window = original_window
    handle.startSystemResize.assert_called_once_with(Qt.Edge.RightEdge)


def assert_non_overlapping(widgets, parent):
    """断言一组可见工具栏控件均位于父控件内且互不相交。"""

    visible = [widget for widget in widgets if widget.isVisibleTo(parent)]
    for widget in visible:
        assert parent.rect().contains(widget.geometry())
    for index, widget in enumerate(visible):
        assert all(
            not widget.geometry().intersects(other.geometry()) for other in visible[index + 1 :]
        )


class _VisibilityEventCounter(QObject):
    """记录真实 QWidget 的 Show/Hide 事件，不替换被测控件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show_count = 0
        self.hide_count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show:
            self.show_count += 1
        elif event.type() == QEvent.Type.Hide:
            self.hide_count += 1
        return super().eventFilter(watched, event)


_DIRECT_TOOLBAR_ACTION_KEYS = (
    "app_mgr",
    "file_explorer",
    "logcat",
    "performance",
    "settings",
    "cmd",
    "save_path",
    "clear",
    "about",
    "theme",
    "always_on_top",
    "minimize",
    "maximize",
    "exit",
)


@pytest.mark.parametrize("font_size", (8, 12, 22))
def test_supported_minimum_toolbar_keeps_every_action_directly_reachable(
    qt_application,
    monkeypatch,
    font_size,
):
    """860px 下不得出现空 More，原动作按钮必须完整留在工具栏。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, _role, size=None: QFont("Arial", font_size if size is None else size)
        ),
    )
    large = _FakeScreen("large", QSize(1600, 900))
    adapter = _FakeScreenAdapter(large)
    frame = build_main_frame(screen_adapter=adapter)
    try:
        frame.show()
        frame.resize(860, 500)
        wait_until(qt_application, lambda: frame._toolbar.width() == 860)

        assert frame.findChild(QToolButton, "toolbarMoreButton") is None
        assert frame.findChild(QWidget, "toolbarMoreMenu") is None
        assert set(_DIRECT_TOOLBAR_ACTION_KEYS).issubset(frame._toolbar_actions)
        buttons = tuple(frame._toolbar_action_buttons[key] for key in _DIRECT_TOOLBAR_ACTION_KEYS)
        assert all(button.isVisibleTo(frame._toolbar) for button in buttons)
        assert all(frame._toolbar.rect().contains(button.geometry()) for button in buttons)
        assert_non_overlapping(buttons, frame._toolbar)
        assert all(
            button.defaultAction() is frame._toolbar_actions[key]
            and button.isEnabled() == frame._toolbar_actions[key].isEnabled()
            for key, button in zip(_DIRECT_TOOLBAR_ACTION_KEYS, buttons)
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_toolbar_resize_does_not_toggle_stable_action_buttons(qt_application):
    """成员未变化的连续缩放不能产生按钮 Show/Hide 往返。"""

    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    )
    try:
        frame.show()
        frame.resize(1600, 600)
        wait_until(
            qt_application,
            lambda: frame._toolbar.width() == 1600
            and all(
                button.isVisibleTo(frame._toolbar)
                for button in frame._toolbar_action_buttons.values()
            ),
        )
        counters = []
        for button in frame._toolbar_action_buttons.values():
            counter = _VisibilityEventCounter(button)
            button.installEventFilter(counter)
            counters.append(counter)

        for width in (1120, 860) * 50:
            frame.resize(width, 500)
            qt_application.processEvents()

        assert sum(counter.show_count for counter in counters) == 0
        assert sum(counter.hide_count for counter in counters) == 0
        assert all(
            button.isVisibleTo(frame._toolbar) for button in frame._toolbar_action_buttons.values()
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_main_window_resize_batch_settles_side_panel_once_with_final_geometry(
    qt_application,
):
    """一次真实主窗口 resize 只能提交一代，并应用最终 viewport 几何。"""

    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    )
    try:
        frame.show()
        panel = frame.left_panel
        feature_panel = panel._apps_tab
        wait_until(
            qt_application,
            lambda: panel._responsive_coordinator.diagnostics.stable
            and feature_panel.responsive_geometry_is_applied(),
        )
        for _index in range(4):
            qt_application.processEvents()

        before = panel._responsive_coordinator.diagnostics.generation
        settled_spy = QSignalSpy(panel.responsive_layout_settled)
        frame.resize(860, 500)
        wait_until(
            qt_application,
            lambda: panel._responsive_coordinator.diagnostics.stable
            and panel._responsive_coordinator.diagnostics.generation > before
            and feature_panel.responsive_geometry_is_applied(),
        )
        wait_until(qt_application, lambda: settled_spy.count() == 1)

        assert panel._responsive_coordinator.diagnostics.generation == before + 1
        assert settled_spy.count() == 1
        assert all(
            binding.applied_plan is not None
            and binding.applied_plan.available_width == binding.responsive_context().width
            and binding.applied_plan.context_fingerprint == binding.responsive_context().fingerprint
            for binding in feature_panel._responsive_rows
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_device_medium_compact_transition_does_not_collapse_wide_right_panel_rows(
    qt_application,
    monkeypatch,
):
    """Devices 的高度反馈必须独立收敛，不能让宽右栏在相同宽度变成全单列。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 10)),
    )
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 1000)))
    )
    try:
        frame.resize(1400, 900)
        frame.show()
        panel = frame.left_panel
        manager = panel._devices_tab
        apps = panel._apps_tab
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)

        compact_limit, wide_limit = manager._device_layout_limits()
        medium_width = min(wide_limit - 1, compact_limit + 40)
        compact_width = compact_limit - 20
        total_width = sum(frame._panel_splitter.sizes())
        assert total_width - compact_width >= 600

        def apply_left_width(width: int) -> tuple[int, ...]:
            before = panel._responsive_coordinator.diagnostics.generation
            frame._panel_splitter.setSizes([width, total_width - width])
            panel.request_responsive_reflow(ReflowReason.SPLITTER)
            wait_until(
                qt_application,
                lambda: panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before,
            )
            plans = tuple(binding.applied_plan for binding in apps._responsive_rows)
            assert all(plan is not None for plan in plans)
            return tuple(plan.mode.columns for plan in plans if plan is not None)

        apply_left_width(medium_width)
        first_compact = apply_left_width(compact_width)
        apply_left_width(medium_width)
        second_compact = apply_left_width(compact_width)

        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        assert first_compact == second_compact
        assert all(columns > 1 for columns in first_compact)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_toolbar_action_identity_and_single_trigger_survive_resize(qt_application):
    """缩放前后 QAction/QToolButton 身份不变，单击仍只触发一次业务动作。"""

    with patch.object(MainFrame, "_show_settings", autospec=True) as business:
        frame = build_main_frame()
        try:
            frame.show()
            action = frame._toolbar_actions["settings"]
            button = frame.tb_settings
            action_spy = QSignalSpy(action.triggered)
            for width in (860, 1120, 860):
                frame.resize(width, 500)
                qt_application.processEvents()

            assert frame._toolbar_actions["settings"] is action
            assert frame.tb_settings is button
            button.click()
            assert action_spy.count() == 1
            assert business.call_args_list == [((frame,), {})]
        finally:
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()


def test_toolbar_buttons_are_excluded_from_window_drag_target(qt_application):
    frame = build_main_frame()
    try:
        frame.show()
        qt_application.processEvents()

        button_position = frame.tb_settings.mapTo(frame, frame.tb_settings.rect().center())
        title_position = frame._toolbar_title.mapTo(frame, frame._toolbar_title.rect().center())
        assert frame._is_toolbar_drag_target(button_position) is False
        assert frame._is_toolbar_drag_target(title_position) is True
    finally:
        frame._close_ready = True
        frame.close()


def test_small_screen_clamp_does_not_replace_preferred_window_size():
    assert hasattr(window_layout, "compute_workspace_constraints")
    constraints = window_layout.compute_workspace_constraints(
        QSize(720, 420),
        QSize(1120, 640),
    )

    assert constraints.effective_window_size == QSize(720, 420)
    assert constraints.preferred_window_size == QSize(1120, 640)
    assert constraints.restricted is True


def test_show_binds_screen_once_after_window_handle_exists(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    frame = build_main_frame(screen_adapter=adapter)

    try:
        assert adapter.token_count() == 0

        frame.show()
        wait_until(qt_application, lambda: adapter.token_count() == 3)
        coordinator = frame.left_panel._responsive_coordinator
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)

        generation = coordinator.diagnostics.generation
        frame._bind_window_screen()
        qt_application.processEvents()
        assert adapter.token_count() == 3
        assert coordinator.diagnostics.generation == generation
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_initial_small_screen_clamp_is_not_recorded_as_user_resize(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("small", QSize(720, 420)))
    settings = _MainFrameSettings()
    frame = build_main_frame(screen_adapter=adapter, settings=settings)

    try:
        frame.show()
        frame._bind_window_screen()
        wait_until(
            qt_application,
            lambda: frame.left_panel._responsive_coordinator.diagnostics.stable,
        )

        assert frame.size() == QSize(720, 420)
        assert frame._preferred_window_size == QSize(1120, 640)
        assert frame._pending_user_window_size is None
        assert settings.writes == []
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("signal_kind", ["screen", "geometry", "dpi"])
@pytest.mark.parametrize("signal_after_debounce", [False, True], ids=["prompt", "late"])
def test_native_screen_resize_before_signal_does_not_replace_preferred_size(
    qt_application,
    signal_kind,
    signal_after_debounce,
):
    large = _FakeScreen("large", QSize(1600, 900))
    adapter = _FakeScreenAdapter(large)
    settings = _MainFrameSettings()
    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        frame = build_main_frame(screen_adapter=adapter, settings=settings)

        try:
            frame.show()
            wait_until(qt_application, lambda: adapter.token_count() == 3)
            wait_until(
                qt_application,
                lambda: frame.left_panel._responsive_coordinator.diagnostics.stable,
            )

            target_size = QSize(720, 420)
            frame.resize(target_size)
            assert frame.size() == QSize(860, 500)
            if signal_after_debounce:
                QTest.qWait(frame.WINDOW_SIZE_SAVE_DEBOUNCE_MS + 100)

            if signal_kind == "screen":
                target_screen = _FakeScreen("small", target_size, logical_dpi=144.0)
                adapter.emit_screen_changed(target_screen)
            else:
                large.available_size = QSize(target_size)
                if signal_kind == "geometry":
                    adapter.emit_available_geometry_changed(large)
                else:
                    large.logical_dpi = 144.0
                    adapter.emit_logical_dpi_changed(large)

            wait_until(qt_application, lambda: frame._effective_window_size == target_size)
            wait_until(
                qt_application,
                lambda: frame.left_panel._responsive_coordinator.diagnostics.stable,
            )

            assert frame._preferred_window_size == QSize(1120, 640)
            assert not any("window_width" in values for values in settings.writes)
            assert settings.values["window_width"] == 1120
            assert settings.values["window_height"] == 640

            if signal_kind == "screen":
                adapter.emit_screen_changed(large)
            else:
                large.available_size = QSize(1600, 900)
                if signal_kind == "geometry":
                    adapter.emit_available_geometry_changed(large)
                else:
                    large.logical_dpi = 96.0
                    adapter.emit_logical_dpi_changed(large)

            wait_until(qt_application, lambda: frame.size() == QSize(1120, 640))
            assert frame._preferred_window_size == QSize(1120, 640)
            assert not any("window_width" in values for values in settings.writes)
        finally:
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()


def test_marked_user_resize_without_screen_transition_is_saved_after_debounce(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    settings = _MainFrameSettings()
    mouse_buttons = _FakeMouseButtons()
    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        frame = build_main_frame(
            screen_adapter=adapter,
            settings=settings,
            mouse_buttons_provider=mouse_buttons,
        )

        try:
            frame.show()
            wait_until(qt_application, lambda: adapter.token_count() == 3)
            begin_native_user_resize(frame, qt_application)
            frame.resize(1000, 600)
            expected_write = {"window_width": 1000, "window_height": 600}
            wait_until(
                qt_application,
                lambda: expected_write in settings.writes,
            )

            assert frame._preferred_window_size == QSize(1000, 600)
            assert expected_write in settings.writes
            assert frame._user_resize_transaction_active is False
        finally:
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()


def test_user_resize_waits_for_mouse_release_before_accepting_first_resize(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    settings = _MainFrameSettings()
    mouse_buttons = _FakeMouseButtons()
    settings_patch = patch.object(AppSettings, "instance", classmethod(lambda _cls: settings))
    settings_patch.start()
    frame = build_main_frame(
        screen_adapter=adapter,
        settings=settings,
        mouse_buttons_provider=mouse_buttons,
    )

    try:
        frame.show()
        wait_until(qt_application, lambda: adapter.token_count() == 3)
        mouse_buttons.press_left()
        begin_native_user_resize(frame, qt_application)

        QTest.qWait(frame.WINDOW_SIZE_SAVE_DEBOUNCE_MS + 100)
        assert frame._user_resize_transaction_active is True
        assert not any("window_width" in values for values in settings.writes)

        frame.resize(1000, 600)
        wait_until(qt_application, lambda: frame._pending_user_window_size == QSize(1000, 600))
        mouse_buttons.release_left()
        expected_write = {"window_width": 1000, "window_height": 600}
        wait_until(qt_application, lambda: expected_write in settings.writes)

        window_writes = [values for values in settings.writes if "window_width" in values]
        assert window_writes == [expected_write]
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        settings_patch.stop()


def test_user_resize_keeps_only_latest_size_while_mouse_remains_pressed(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    settings = _MainFrameSettings()
    mouse_buttons = _FakeMouseButtons()
    settings_patch = patch.object(AppSettings, "instance", classmethod(lambda _cls: settings))
    settings_patch.start()
    frame = build_main_frame(
        screen_adapter=adapter,
        settings=settings,
        mouse_buttons_provider=mouse_buttons,
    )

    try:
        frame.show()
        wait_until(qt_application, lambda: adapter.token_count() == 3)
        mouse_buttons.press_left()
        begin_native_user_resize(frame, qt_application)
        frame.resize(1000, 600)
        wait_until(qt_application, lambda: frame._pending_user_window_size == QSize(1000, 600))

        QTest.qWait(frame.WINDOW_SIZE_SAVE_DEBOUNCE_MS + 100)
        assert frame._user_resize_transaction_active is True
        assert not any("window_width" in values for values in settings.writes)

        frame.resize(980, 580)
        wait_until(qt_application, lambda: frame._pending_user_window_size == QSize(980, 580))
        mouse_buttons.release_left()
        expected_write = {"window_width": 980, "window_height": 580}
        wait_until(qt_application, lambda: expected_write in settings.writes)

        window_writes = [values for values in settings.writes if "window_width" in values]
        assert window_writes == [expected_write]
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        settings_patch.stop()


def test_unmarked_programmatic_resize_does_not_persist_after_debounce(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    settings = _MainFrameSettings()
    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        frame = build_main_frame(screen_adapter=adapter, settings=settings)

        try:
            frame.show()
            wait_until(qt_application, lambda: adapter.token_count() == 3)
            frame.resize(1000, 600)
            QTest.qWait(frame.WINDOW_SIZE_SAVE_DEBOUNCE_MS + 100)

            assert frame._preferred_window_size == QSize(1120, 640)
            assert not any("window_width" in values for values in settings.writes)
        finally:
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()


@pytest.mark.parametrize(
    ("configured_size", "expected_preferred", "expected_effective"),
    [
        (QSize(0, 0), QSize(860, 500), QSize(720, 420)),
        (QSize(100, 100), QSize(860, 500), QSize(720, 420)),
        (QSize(1400, 800), QSize(1400, 800), QSize(720, 420)),
    ],
)
def test_configured_preferred_size_uses_design_minimum_without_small_screen_cap(
    configured_size,
    expected_preferred,
    expected_effective,
):
    adapter = _FakeScreenAdapter(_FakeScreen("small", QSize(720, 420)))
    settings = _MainFrameSettings()
    settings.values.update(
        window_width=configured_size.width(),
        window_height=configured_size.height(),
    )
    frame = build_main_frame(screen_adapter=adapter, settings=settings)

    try:
        assert frame._preferred_window_size == expected_preferred
        assert frame._effective_window_size == expected_effective
        assert frame.window_layout_snapshot()["width"] == expected_preferred.width()
        assert frame.window_layout_snapshot()["height"] == expected_preferred.height()
    finally:
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize(
    ("requested_size", "expected_preferred"),
    [
        (QSize(0, 0), QSize(860, 500)),
        (QSize(100, 100), QSize(860, 500)),
        (QSize(1400, 800), QSize(1400, 800)),
    ],
)
def test_applied_preferred_size_uses_design_minimum_without_small_screen_cap(
    requested_size,
    expected_preferred,
):
    adapter = _FakeScreenAdapter(_FakeScreen("small", QSize(720, 420)))
    frame = build_main_frame(screen_adapter=adapter)

    try:
        frame.apply_window_size(requested_size.width(), requested_size.height())

        assert frame._preferred_window_size == expected_preferred
        assert frame._effective_window_size == QSize(720, 420)
    finally:
        frame._close_ready = True
        frame.close()


def test_apply_window_size_persists_without_resize_event(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    settings = _MainFrameSettings()
    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        frame = build_main_frame(screen_adapter=adapter, settings=settings)

        try:
            frame.apply_window_size(1000, 600)

            assert frame._preferred_window_size == QSize(1000, 600)
            assert {"window_width": 1000, "window_height": 600} in settings.writes
        finally:
            frame._close_ready = True
            frame.close()


def test_screen_binding_restores_preferred_size_and_disconnects_old_screen(
    qt_application,
):
    large = _FakeScreen("large", QSize(1600, 900))
    small = _FakeScreen("small", QSize(720, 420), logical_dpi=144.0)
    adapter = _FakeScreenAdapter(large)
    settings = _MainFrameSettings()
    mouse_buttons = _FakeMouseButtons()

    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        frame = build_main_frame(
            screen_adapter=adapter,
            settings=settings,
            mouse_buttons_provider=mouse_buttons,
        )
        frame._close_ready = True
        frame.show()
        frame._bind_window_screen()
        wait_until(qt_application, lambda: adapter.token_count() == 3)
        coordinator = frame.left_panel._responsive_coordinator
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)

        begin_native_user_resize(frame, qt_application)
        frame.resize(1000, 600)
        assert frame._pending_user_window_size == QSize(1000, 600)
        wait_until(
            qt_application,
            lambda: {"window_width": 1000, "window_height": 600} in settings.writes,
        )
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)
        before_small_screen = coordinator.diagnostics.generation
        adapter.emit_screen_changed(small)
        wait_until(qt_application, lambda: frame._effective_window_size == QSize(720, 420))
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)

        assert frame._preferred_window_size == QSize(1000, 600)
        assert settings.values["window_width"] == 1000
        assert settings.values["window_height"] == 600
        assert frame.minimumSize() == QSize(720, 420)
        assert frame._left_panel_wrapper.minimumWidth() == 120
        assert frame.left_panel.minimumWidth() == 160
        assert coordinator.diagnostics.generation == before_small_screen + 1
        assert adapter.token_count("window") == 1
        assert adapter.token_count("available") == 1
        assert adapter.token_count("dpi") == 1

        writes_after_user_resize = list(settings.writes)
        before_small_metrics = coordinator.diagnostics.generation
        adapter.emit_available_geometry_changed(small)
        adapter.emit_logical_dpi_changed(small)
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)
        assert settings.writes == writes_after_user_resize
        assert coordinator.diagnostics.generation == before_small_metrics + 1

        adapter.emit_screen_changed(large)
        wait_until(qt_application, lambda: frame._effective_window_size == QSize(1000, 600))
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)
        generation = coordinator.diagnostics.generation
        adapter.emit_available_geometry_changed(small)
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)

        assert frame._preferred_window_size == QSize(1000, 600)
        assert frame.size() == QSize(1000, 600)
        assert frame.minimumSize() == QSize(860, 500)
        assert frame._left_panel_wrapper.minimumWidth() == 280
        assert frame.left_panel.minimumWidth() == 300
        assert coordinator.diagnostics.generation == generation

        frame.close()
        assert adapter.token_count() == 0


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


def test_responsive_column_count_expands_breakpoints_for_large_font():
    assert responsive_column_count(500, font_point_size=12) == 2
    assert responsive_column_count(500, font_point_size=22) == 1
    assert responsive_column_count(620, font_point_size=22) == 2


def test_reflow_widgets_preserves_declared_column_weights(qt_application):
    parent = QWidget()
    layout = QGridLayout(parent)
    widgets = tuple(QPushButton(str(index)) for index in range(3))
    layout.setColumnStretch(3, 9)
    layout.setRowStretch(2, 7)

    reflow_widgets(layout, widgets, 3, widget_stretches=(2, 1, 1))
    assert [layout.columnStretch(index) for index in range(4)] == [2, 1, 1, 0]
    assert [layout.rowStretch(index) for index in range(3)] == [0, 0, 0]

    reflow_widgets(layout, widgets, 2, widget_stretches=(2, 1, 1))
    assert [layout.columnStretch(index) for index in range(4)] == [2, 1, 0, 0]
    assert [layout.rowStretch(index) for index in range(3)] == [0, 0, 0]
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


@pytest.mark.parametrize("started", [True, False], ids=["success", "failure"])
def test_frameless_resize_zone_reports_native_start_result(qt_application, started):
    handle = Mock()
    handle.startSystemResize.return_value = started

    class Window(QWidget):
        def windowHandle(self):
            return handle

    window = Window()
    window.resize(800, 600)
    on_started = Mock()
    on_cancelled = Mock()
    controller = FramelessResizeController(
        window,
        on_user_resize_started=on_started,
        on_user_resize_cancelled=on_cancelled,
    )
    window.show()
    qt_application.processEvents()

    zone = controller._zones["right"]
    QTest.mousePress(zone, Qt.MouseButton.LeftButton)

    handle.startSystemResize.assert_called_once_with(Qt.Edge.RightEdge)
    if started:
        on_started.assert_called_once_with()
        on_cancelled.assert_not_called()
    else:
        on_started.assert_called_once_with()
        on_cancelled.assert_called_once_with()


def test_frameless_resize_zone_cancels_when_window_handle_is_missing(qt_application):
    class Window(QWidget):
        def windowHandle(self):
            return None

    window = Window()
    window.resize(800, 600)
    on_started = Mock()
    on_cancelled = Mock()
    controller = FramelessResizeController(
        window,
        on_user_resize_started=on_started,
        on_user_resize_cancelled=on_cancelled,
    )
    window.show()
    qt_application.processEvents()

    QTest.mouseClick(controller._zones["right"], Qt.MouseButton.LeftButton)

    on_started.assert_called_once_with()
    on_cancelled.assert_called_once_with()


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
    splitter.sizes.side_effect = ([400, 600], [350, 650], [350, 650])
    left_panel = Mock()
    frame = SimpleNamespace(
        _panel_splitter=splitter,
        _pending_panel_sizes=None,
        left_panel=left_panel,
    )

    MainFrame.apply_panel_ratio(frame, 0.35)

    splitter.setSizes.assert_called_once_with([350, 650])
    assert frame._pending_panel_sizes == (350, 650)
    left_panel.request_responsive_reflow.assert_called_once_with(ReflowReason.SPLITTER)


def test_restore_default_window_size_leaves_maximized_state():
    frame = SimpleNamespace(
        isMaximized=lambda: True,
        isMinimized=lambda: False,
        isFullScreen=lambda: False,
        showNormal=Mock(),
        apply_window_size=Mock(),
        size=lambda: QSize(1120, 640),
    )

    MainFrame.restore_default_window_size(frame)

    frame.showNormal.assert_called_once_with()
    frame.apply_window_size.assert_called_once_with(1120, 640)


def test_settings_dialog_opens_as_reusable_non_modal_window():
    dialog = Mock()
    frame = SimpleNamespace(
        set_continuous_scan=Mock(),
        _refresh_save_path=Mock(),
        _refresh_live_settings=Mock(),
        _find_active_dialog=Mock(return_value=None),
        _register_dialog=Mock(side_effect=lambda value, *_args: value),
        log_panel=SimpleNamespace(set_max_lines=Mock()),
    )

    with patch("gui.secondary_windows.SettingsDialog", return_value=dialog):
        MainFrame._show_settings(frame)

    frame._register_dialog.assert_called_once()
    dialog.continuous_scan_toggled.connect.assert_called_once_with(frame.set_continuous_scan)
    dialog.log_max_lines_changed.connect.assert_called_once_with(frame.log_panel.set_max_lines)
    dialog.settings_applied.connect.assert_called_once_with(frame._refresh_live_settings)
    dialog.show.assert_called_once_with()
    dialog.exec_.assert_not_called()


def test_settings_dialog_reuses_existing_window():
    dialog = Mock()
    frame = SimpleNamespace(_find_active_dialog=Mock(return_value=dialog))

    MainFrame._show_settings(frame)

    dialog.show.assert_called_once_with()
    dialog.raise_.assert_called_once_with()
    dialog.activateWindow.assert_called_once_with()


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

            # 路径宽度来自工具栏扣除其余控件后的真实余量，并在 420px 封顶。
            expected_maximum_widths = (288, 347, 348, 420, 420, 420, 420)
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
                    all(state[3].startswith("Globa") for state in path_states),
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

        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy

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
            for _index in range(8):
                app.processEvents()
                QTest.qWait(5)
            device_widget = window.left_panel.device_widget
            log_soft_minimum = max(
                32,
                window.log_panel.text_output.fontMetrics().height()
                + 2 * window.log_panel.text_output.frameWidth(),
            )
            required_height = (
                window._workspace_vertical_chrome_height()
                + device_widget.minimumSizeHint().height()
                + window._device_log_splitter.handleWidth()
                + log_soft_minimum
            )
            passed = all(
                (
                    device_widget.sizePolicy().verticalPolicy() == QSizePolicy.Preferred,
                    not device_widget.findChildren(QScrollArea),
                    window.log_panel.minimumHeight() == log_soft_minimum,
                    window.log_panel.height() >= log_soft_minimum,
                    window.log_panel.isVisible(),
                    window.minimumHeight() == max(500, required_height),
                    window.height() >= window.minimumHeight(),
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
