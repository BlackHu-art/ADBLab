from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget
from qfluentwidgets import CardWidget, NavigationDisplayMode, NavigationPanel
from shiboken6 import invalidate, isValid

from core.settings_manager import DEFAULTS, AppSettings
from gui import window_layout
from gui.main_frame import MainFrame
from gui.screen_adapter import QtScreenAdapter
from gui.styles import BaseStyles
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.responsive_layout import reflow_widgets, responsive_column_count
from gui.window_layout import normalize_window_size
from tests.ui_geometry_helpers import assert_text_fits, wait_until


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

    def reset(self):
        self.values = dict(DEFAULTS)
        self.writes.append({"reset": True})


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


def test_logs_navigation_switches_to_independent_page_and_focuses_output(qt_application):
    page = object()
    text_output = Mock()
    frame = SimpleNamespace(
        _logs_page=page,
        _home_page=None,
        _devices_page=None,
        _apps_page=None,
        _system_page=None,
        _remote_page=None,
        _tasks_page=None,
        _settings_page=None,
        log_panel=SimpleNamespace(text_output=text_output),
        switchTo=Mock(),
    )

    MainFrame._on_nav_requested(frame, "logs")

    frame.switchTo.assert_called_once_with(page)
    text_output.setFocus.assert_called_once_with(Qt.FocusReason.ShortcutFocusReason)
    text_output.ensureCursorVisible.assert_called_once_with()


def test_shutdown_flush_captures_visible_window_size_and_theme_without_resize_transaction(
    qt_application,
):
    """关闭时兜底保存最终 UI 状态，避免原生缩放回调缺失后丢失用户设置。"""

    settings = _MainFrameSettings()
    adapter = _FakeScreenAdapter(_FakeScreen("large", QSize(1600, 1000)))
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    frame.show()
    qt_application.processEvents()
    frame.resize(1000, 600)
    qt_application.processEvents()
    settings.writes.clear()

    try:
        with (
            patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
            patch.object(BaseStyles, "current_theme", return_value="Dark"),
        ):
            frame._flush_pending_layout_state()

        assert {
            "window_width": 1000,
            "window_height": 600,
            "theme": "Dark",
        } in settings.writes
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_shutdown_flush_preserves_preferred_size_when_screen_is_restricted(qt_application):
    """小屏幕只限制本次显示尺寸，关闭时不得覆盖用户保存的大屏首选尺寸。"""

    settings = _MainFrameSettings()
    settings.values.update({"window_width": 1400, "window_height": 800})
    adapter = _FakeScreenAdapter(_FakeScreen("small", QSize(720, 420)))
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    frame.show()
    qt_application.processEvents()
    settings.writes.clear()

    try:
        with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
            frame._flush_pending_layout_state()

        assert frame.size() == QSize(720, 420)
        assert any(
            values.get("window_width") == 1400 and values.get("window_height") == 800
            for values in settings.writes
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


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


@pytest.mark.parametrize("font_size", (8, 12, 22))
def test_supported_minimum_home_keeps_every_action_keyboard_reachable(
    qt_application,
    monkeypatch,
    font_size,
):
    """860px 下 Gallery 流式卡片换行，所有入口仍可键盘访问。"""

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
        frame._on_nav_requested("home")
        cards = tuple(frame._home_page.tool_cards.values())
        wait_until(qt_application, lambda: frame._home_page.viewport().width() > 0)

        assert not hasattr(frame, "_toolbar")
        assert len(cards) == 6
        assert all(card.focusPolicy() & Qt.FocusPolicy.TabFocus for card in cards)
        assert frame._home_page.horizontalScrollBar().maximum() == 0
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_home_resize_does_not_toggle_stable_action_cards(qt_application):
    """连续缩放只触发 FlowLayout 重排，不产生卡片 Show/Hide 往返。"""

    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    )
    try:
        frame.show()
        frame.resize(1600, 600)
        frame._on_nav_requested("home")
        cards = tuple(frame._home_page.tool_cards.values())
        wait_until(qt_application, lambda: all(card.isVisibleTo(frame) for card in cards))
        counters = []
        for card in cards:
            counter = _VisibilityEventCounter(card)
            card.installEventFilter(counter)
            counters.append(counter)

        for width in (1120, 860) * 50:
            frame.resize(width, 500)
            qt_application.processEvents()

        assert sum(counter.show_count for counter in counters) == 0
        assert sum(counter.hide_count for counter in counters) == 0
        assert all(card.isVisibleTo(frame) for card in cards)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_save_path_remains_in_settings_card_after_window_resize(qt_application):
    """保存路径由 SettingCard 承载，窗口缩放后内容不得丢失。"""

    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    )
    try:
        frame.show()
        frame._on_nav_requested("settings")
        expected = frame._refresh_save_path()
        frame.resize(860, 500)
        qt_application.processEvents()

        assert frame._settings_page.save_card.contentLabel.text() == (
            expected or "系统默认目录"
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_main_window_resize_batch_settles_side_panel_once_with_final_geometry(
    qt_application,
    monkeypatch,
):
    """一次真实主窗口 resize 只能提交一代，并应用最终 viewport 几何。"""

    # 关闭异步设备扫描：真实 adb 环境下扫描随时更新设备列表最小宽，会让分栏
    # 在 settle 后漂移，破坏本用例的确定性（P1 NavBar 改变事件时序后更易触发）。
    monkeypatch.setattr(MainFrame, "_start_scan_thread", lambda _self: None)
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
        wait_until(
            qt_application,
            lambda: panel._last_settled_generation
            == panel._responsive_coordinator.diagnostics.generation,
        )

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
        # P1 页面栈/NavBar 引入额外布局层级后，分栏在 settle 信号后还有一次
        # 无新代的宿主布局收尾；改为等待"最终几何与已应用计划一致"这一不变式
        # 成立（wait 超时同样失败，断言强度不变，仅把瞬时时序改为确定性等待）。
        wait_until(
            qt_application,
            lambda: all(
                binding.applied_plan is not None
                and binding.applied_plan.available_width == binding.responsive_context().width
                and binding.applied_plan.context_fingerprint
                == binding.responsive_context().fingerprint
                for binding in feature_panel._responsive_rows
            ),
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_device_medium_compact_transition_does_not_collapse_wide_right_panel_rows(
    qt_application,
    monkeypatch,
):
    """工作台分区共享内容宽度，切换时设备上下文保持可见。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 10)),
    )
    monkeypatch.setattr(MainFrame, "_start_scan_thread", lambda _self: None)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 1000)))
    )
    try:
        frame.resize(1400, 900)
        frame.show()
        frame._on_nav_requested("devices")
        assert frame.stackedWidget.currentWidget() is frame._workspace_page
        assert frame._workspace_page.context_card.isVisibleTo(frame._workspace_page)
        wait_until(qt_application, lambda: frame._devices_page.body.viewport().width() > 1000)
        devices_width = frame._devices_page.body.viewport().width()
        frame._on_nav_requested("apps")
        assert frame.stackedWidget.currentWidget() is frame._workspace_page
        assert frame._workspace_page.stack.currentWidget() is frame._apps_page
        wait_until(qt_application, lambda: frame._apps_page.body.viewport().width() > 1000)
        apps_width = frame._apps_page.body.viewport().width()

        assert abs(devices_width - apps_width) <= 2
        assert not hasattr(frame, "_panel_splitter")
        assert not hasattr(frame, "_device_log_splitter")
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_dark_theme_updates_hidden_workspace_surfaces_before_navigation(qt_application):
    """隐藏分区切换主题后首次打开时，不得露出创建期的浅色宿主。"""

    BaseStyles.switch_theme("Light")
    frame = build_main_frame()
    try:
        frame.show()
        qt_application.processEvents()

        BaseStyles.switch_theme("Dark")
        qt_application.processEvents()
        frame._on_nav_requested("apps")
        qt_application.processEvents()

        expected = BaseStyles.color("WINDOW_BG").lower()
        assert frame._workspace_page.autoFillBackground()
        assert frame._workspace_page.palette().window().color().name() == expected
        assert frame._settings_page.viewport().palette().window().color().name() == expected

        wrapper = frame._apps_page.body.widget()
        filled_surfaces = [
            widget
            for widget in (wrapper, *wrapper.findChildren(QWidget))
            if widget.autoFillBackground()
        ]
        assert filled_surfaces
        assert all(
            widget.palette().window().color().name() == expected
            for widget in filled_surfaces
        )

        cards = frame._apps_page.findChildren(CardWidget)
        assert cards
        assert all(
            card.backgroundColor.rgba() == card._normalBackgroundColor().rgba()
            for card in cards
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_theme_switch_updates_mica_fluent_window_shell(qt_application):
    """Mica 壳层的标题栏和导航区必须与内容区同步切换明暗主题。"""

    original_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Dark")
    frame = build_main_frame()
    try:
        frame.show()
        qt_application.processEvents()

        panels = frame.navigationInterface.findChildren(NavigationPanel)
        assert panels
        shell_surfaces = (
            frame.titleBar,
            frame.navigationInterface,
            *panels,
        )

        for theme in ("Light", "Dark"):
            BaseStyles.switch_theme(theme)
            qt_application.processEvents()
            expected = BaseStyles.color("WINDOW_BG").lower()
            assert all(surface.autoFillBackground() for surface in shell_surfaces)
            assert all(
                surface.palette().window().color().name() == expected
                for surface in shell_surfaces
            )
    finally:
        BaseStyles.switch_theme(original_theme)
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_light_theme_is_applied_after_mica_first_show(qt_application):
    """首次 show 再应用 Mica 后，浅色标题栏和导航壳层不能退回深色。"""

    original_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Light")
    frame = build_main_frame()
    try:
        frame.show()
        qt_application.processEvents()

        expected = BaseStyles.color("WINDOW_BG").lower()
        assert frame.titleBar.palette().window().color().name() == expected
        assert frame.navigationInterface.palette().window().color().name() == expected
    finally:
        BaseStyles.switch_theme(original_theme)
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_and_workspace_selection_feedback_is_immediate(qt_application):
    """顶层与工作台分区点击后，导航选中态和内容必须在过渡动画前一致。"""

    frame = build_main_frame()
    try:
        section_spy = QSignalSpy(frame._workspace_page.sectionChanged)
        frame._on_nav_requested("apps")

        assert frame.navigationInterface.panel.currentItem().property("routeKey") == (
            frame._workspace_page.objectName()
        )
        assert frame._workspace_page.segmented.currentRouteKey() == "apps"
        assert frame._workspace_page.stack.currentWidget() is frame._apps_page
        assert section_spy.count() == 1
        assert "应用与自动化" in frame._workspace_page.header.subtitle_label.text()

        frame._on_nav_requested("settings")
        assert frame.navigationInterface.panel.currentItem().property("routeKey") == (
            frame._settings_page.objectName()
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_route_click_collapses_menu_during_expand_animation(qt_application):
    """窄窗菜单尚在展开时切页，也必须收起覆盖层并保留目标页面。"""

    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 1000)))
    )
    try:
        frame.show()
        qt_application.processEvents()
        frame.resize(860, 640)
        qt_application.processEvents()
        assert frame.width() == 860
        panel = frame.navigationInterface.panel
        assert panel.displayMode == NavigationDisplayMode.COMPACT

        panel.menuButton.click()
        assert panel.displayMode == NavigationDisplayMode.MENU
        assert panel.expandAni.state() == QAbstractAnimation.State.Running

        frame.navigationInterface.widget(frame._logs_page.objectName()).click()

        assert frame.stackedWidget.currentWidget() is frame._logs_page
        assert panel.currentItem().property("routeKey") == frame._logs_page.objectName()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT and panel.width() == 48,
        )
        assert panel.parentWidget() is frame.navigationInterface
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_system_color_scheme_change_reapplies_system_theme(qt_application):
    """运行中系统配色变化时，仅在跟随系统模式下重新解析实际主题。"""

    frame = build_main_frame()
    try:
        with (
            patch.object(BaseStyles, "current_theme", return_value="System"),
            patch.object(BaseStyles, "switch_theme") as switch_theme,
        ):
            frame._on_system_color_scheme_changed(Qt.ColorScheme.Dark)
        switch_theme.assert_called_once_with("System")

        with (
            patch.object(BaseStyles, "current_theme", return_value="Light"),
            patch.object(BaseStyles, "switch_theme") as switch_theme,
        ):
            frame._on_system_color_scheme_changed(Qt.ColorScheme.Dark)
        switch_theme.assert_not_called()
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_home_action_identity_and_single_trigger_survive_resize(qt_application):
    """缩放前后首页 ActionCard 身份不变，激活仍只触发一次业务动作。"""

    with patch.object(MainFrame, "_on_save_path_clicked", autospec=True) as business:
        frame = build_main_frame()
        try:
            frame.show()
            card = frame._home_page.tool_cards["save_path"]
            action_spy = QSignalSpy(card.activated)
            for width in (860, 1120, 860):
                frame.resize(width, 500)
                qt_application.processEvents()

            assert frame._home_page.tool_cards["save_path"] is card
            card.activated.emit()
            assert action_spy.count() == 1
            assert business.call_args_list == [((frame,), {})]
        finally:
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()


def test_narrow_home_wraps_cards_without_horizontal_overflow(
    qt_application,
    monkeypatch,
):
    """极窄大字体下 Gallery 卡片纵向换行，不能复制或丢失动作。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, _role, size=None: QFont("Arial", 22 if size is None else size)
        ),
    )
    screen = _FakeScreen("narrow", QSize(500, 700))
    adapter = _FakeScreenAdapter(screen)
    settings = _MainFrameSettings()
    settings.values.update(window_width=860, window_height=500)
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    try:
        frame.show()
        frame._on_nav_requested("home")
        wait_until(qt_application, lambda: frame._home_page.viewport().width() > 0)
        cards = tuple(frame._home_page.tool_cards.values())

        assert len(cards) == 6
        assert len({id(card) for card in cards}) == 6
        assert frame._home_page.horizontalScrollBar().maximum() == 0
        assert all(card.focusPolicy() & Qt.FocusPolicy.TabFocus for card in cards)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_narrow_settings_long_save_path_stays_in_scrollable_card(
    qt_application,
    monkeypatch,
):
    """完整保存路径留在 SettingCard 中，不能造成横向页面溢出。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, _role, size=None: QFont("Arial", 22 if size is None else size)
        ),
    )
    available = QSize(500, 700)
    settings = _MainFrameSettings()
    settings.save_directory = os.path.join(
        "C:\\",
        *("very-long-save-directory-segment" for _index in range(20)),
    )
    expected_path = os.path.normpath(settings.save_directory)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("narrow", available)),
        settings=settings,
    )
    try:
        frame.show()
        frame._on_nav_requested("settings")
        wait_until(qt_application, lambda: frame._settings_page.viewport().width() > 0)

        assert frame._settings_page.save_card.contentLabel.text() == expected_path
        assert frame._settings_page.horizontalScrollBar().maximum() == 0
        assert frame._settings_page.save_card.width() <= available.width()
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_fluent_title_bar_owns_drag_region_not_page_actions(qt_application):
    frame = build_main_frame()
    try:
        frame.show()
        qt_application.processEvents()

        card = frame._home_page.tool_cards["save_path"]
        assert not hasattr(frame, "_toolbar")
        assert not frame.titleBar.isAncestorOf(card)
        assert frame.titleBar.height() > 0
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


def test_windows_apps_page_responsive_groups_fit_at_supported_widths(
    qt_application,
):
    """独立 Apps 页面在 Windows 支持宽度下保持 Monkey 字段完整。"""

    if qt_application.platformName() != "windows":
        pytest.skip("Exact main-window breakpoint contract targets the Windows platform plugin")

    settings = _MainFrameSettings()
    settings.values.update(
        window_width=1250,
        window_height=700,
        panel_split_ratio=0.5,
    )
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )

    try:
        frame.show()
        app_panel = frame.left_panel._ensure_tab_loaded(0)
        frame._on_nav_requested("apps")
        coordinator = frame.left_panel._responsive_coordinator
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)

        flag_binding = next(
            binding
            for binding in app_panel._responsive_rows
            if app_panel.monkey_chk_crashes in binding.widgets()
        )
        app_panel.monkey_events.setText("1000000")
        app_panel.monkey_throttle.setText("60000 ms")
        for field in app_panel._monkey_pct_combos.values():
            field.setText("100")

        def snapshot(size: QSize):
            frame.resize(size)
            qt_application.processEvents()
            app_panel.apply_responsive_width(0)
            wait_until(qt_application, lambda: coordinator.diagnostics.stable)

            plans = (
                app_panel.monkey_parameter_binding.applied_plan,
                app_panel.monkey_percentage_binding.applied_plan,
                flag_binding.applied_plan,
            )
            assert all(plan is not None and not plan.overflow_required for plan in plans)
            for field in (
                app_panel.monkey_events,
                app_panel.monkey_throttle,
                *app_panel._monkey_pct_combos.values(),
            ):
                assert_text_fits(field)
            parameter_starts = tuple(
                widget.mapTo(
                    app_panel.monkey_parameter_binding._container_ref(),
                    QPoint(0, 0),
                ).x()
                for widget in (
                    app_panel.monkey_events_label,
                    app_panel.monkey_throttle_label,
                    app_panel._pct_total_lbl,
                )
            )
            percentage_starts = tuple(
                app_panel._monkey_pct_labels[key]
                .mapTo(
                    app_panel.monkey_percentage_binding._container_ref(),
                    QPoint(0, 0),
                )
                .x()
                for key in ("touch", "motion", "trackball")
            )
            flag_starts = tuple(
                widget.mapTo(flag_binding._container_ref(), QPoint(0, 0)).x()
                for widget in (
                    app_panel.monkey_chk_crashes,
                    app_panel.monkey_chk_timeouts,
                    app_panel.monkey_chk_security,
                )
            )
            return (
                tuple(plan.mode.name for plan in plans if plan is not None),
                (parameter_starts, percentage_starts, flag_starts),
            )

        default_modes, default_starts = snapshot(QSize(1250, 700))
        minimum_modes, minimum_starts = snapshot(QSize(860, 500))

        def assert_tracks_aligned(track_sets):
            for positions in zip(*track_sets):
                # 同为宽屏多列计划时，各组列起点的像素余数最多相差 2px。
                assert max(positions) - min(positions) <= 2, track_sets

        assert_tracks_aligned(default_starts)
        # 最小窗口下各组按自身内容切换成不同列数；跨组列起点无需强制对齐，
        # 前面的 overflow 与文本测量断言已经保证字段完整可达。
        assert all(position >= 0 for starts in minimum_starts for position in starts)
        modes = {"wide", "three", "medium", "two", "compact", "one"}
        assert all(mode in modes for mode in default_modes)
        assert all(mode in modes for mode in minimum_modes)
        assert not hasattr(frame, "_panel_splitter")
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_default_supported_workspace_keeps_devices_page_horizontally_responsive(qt_application):
    """常规字体的 860x500 工作区由独立 Devices 页面承接滚动。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=860, window_height=500)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900))),
        settings=settings,
    )
    try:
        frame.show()
        frame._on_nav_requested("devices")
        wait_until(qt_application, lambda: frame._device_scroll_area.viewport().width() > 0)
        qt_application.processEvents()

        scroll = frame._device_scroll_area
        assert frame.width() == 860
        assert 500 <= frame.height() <= 900
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.widget() is not None
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("font_size", (12, 22))
def test_short_workspace_scrolls_devices_without_exceeding_available_height(
    qt_application,
    monkeypatch,
    font_size,
):
    """短屏把完整 Devices 内容交给页面纵向滚动，窗口本身不得越出工作区。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, _role, size=None: QFont(
                "Arial",
                font_size if size is None else size,
            )
        ),
    )
    available = QSize(720, 420)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("short", available))
    )
    try:
        frame.show()
        frame._on_nav_requested("devices")
        wait_until(
            qt_application,
            lambda: frame._device_scroll_area.verticalScrollBar().maximum() > 0,
        )

        scroll = frame._device_scroll_area
        manager = frame.left_panel._devices_tab
        assert frame.size() == available
        assert frame.height() <= available.height()
        assert frame.minimumHeight() <= available.height()
        assert scroll.horizontalScrollBar().maximum() == 0
        QTest.qWait(50)
        content_center = manager.btn_none.mapTo(scroll.widget(), manager.btn_none.rect().center())
        vertical = scroll.verticalScrollBar()
        vertical.setValue(
            min(
                vertical.maximum(),
                max(0, content_center.y() - scroll.viewport().height() // 2),
            )
        )
        QTest.qWait(10)
        button_center = manager.btn_none.mapTo(scroll.viewport(), manager.btn_none.rect().center())
        viewport = scroll.viewport().rect().adjusted(0, 0, 0, 2)
        assert viewport.contains(button_center)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_font_minimum_round_trip_restores_only_untouched_forced_size(
    qt_application,
    monkeypatch,
):
    """字号变化由页面滚动承接，不得覆盖用户窗口首选尺寸。"""

    current_font_size = {"value": 12}
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, _role, size=None: QFont(
                "Arial",
                current_font_size["value"] if size is None else size,
            )
        ),
    )
    settings = _MainFrameSettings()
    settings.values.update(window_width=860, window_height=500)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900))),
        settings=settings,
    )

    def apply_font(size: int) -> None:
        current_font_size["value"] = size
        frame.left_panel._on_fonts_changed(None)
        frame._on_ui_font_changed(None)
        QTest.qWait(50)

    try:
        frame.show()
        apply_font(12)
        baseline_size = QSize(frame.size())
        assert baseline_size.width() == 860
        assert baseline_size.height() == 500

        apply_font(22)
        assert frame.size() == baseline_size

        apply_font(12)
        assert frame.size() == baseline_size

        apply_font(22)
        frame.resize(860, 700)
        qt_application.processEvents()
        assert frame._workspace_forced_size is None
        apply_font(12)
        assert frame.height() == 700
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


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


def test_qt_screen_adapter_treats_invalidated_screen_as_missing(qt_application):
    adapter = QtScreenAdapter()
    screen = qt_application.primaryScreen()
    assert screen is not None

    def callback(*_args):
        pass

    tokens = (
        adapter.connect_available_geometry_changed(screen, callback),
        adapter.connect_logical_dpi_changed(screen, callback),
    )
    assert all(token is not None for token in tokens)
    tokens_disconnected = False

    try:
        invalidate(screen)
        assert not isValid(screen)
        assert not adapter.is_valid_screen(screen)
        assert adapter.available_size(screen) == QSize()
        assert adapter.logical_dpi(screen) == 96.0
        assert adapter.connect_available_geometry_changed(screen, callback) is None
        assert adapter.connect_logical_dpi_changed(screen, callback) is None

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for token in tokens:
                adapter.disconnect(token)
        tokens_disconnected = True

        runtime_warnings = [
            item for item in caught if issubclass(item.category, RuntimeWarning)
        ]
        assert runtime_warnings == []
    finally:
        if not tokens_disconnected:
            for token in tokens:
                adapter.disconnect(token)
        replacement = qt_application.primaryScreen()

    assert replacement is not None
    assert replacement is not screen
    assert isValid(replacement)


def test_responsive_refresh_rebinds_invalidated_native_screen(qt_application):
    frame = build_main_frame()

    try:
        frame.show()
        wait_until(
            qt_application,
            lambda: frame._bound_screen is not None
            and isValid(frame._bound_screen)
            and len(frame._screen_metric_tokens) == 2
            and not frame._workspace_constraint_refresh_timer.isActive(),
        )
        stale_screen = frame._bound_screen
        invalidate(stale_screen)
        assert not isValid(stale_screen)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            frame._refresh_workspace_after_responsive_layout()

        assert frame._bound_screen is not stale_screen
        assert frame._bound_screen is not None
        assert isValid(frame._bound_screen)
        assert len(frame._screen_metric_tokens) == 2
        runtime_warnings = [
            item for item in caught if issubclass(item.category, RuntimeWarning)
        ]
        assert runtime_warnings == []
    finally:
        qt_application.primaryScreen()
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
            design_minimum = QSize(frame.minimumSize())
            frame.resize(target_size)
            assert frame.size() == design_minimum
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
        assert frame._preferred_window_size.width() == expected_preferred.width()
        assert frame._preferred_window_size.height() == expected_preferred.height()
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
        assert not hasattr(frame, "_left_panel_wrapper")
        assert not hasattr(frame, "_panel_splitter")
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
        restored_minimum = frame._workspace_design_minimum()
        assert frame.minimumSize() == restored_minimum
        assert restored_minimum.width() == 860
        assert restored_minimum.height() >= 500
        assert not hasattr(frame, "_panel_splitter")
        assert coordinator.diagnostics.generation == generation

        frame.close()
        assert adapter.token_count() == 0


@pytest.mark.parametrize(
    ("width", "height", "available", "expected"),
    [
        (1120, 640, QSize(1920, 1040), QSize(1120, 640)),
        ("bad", None, QSize(1920, 1040), QSize(1250, 700)),
        (-1, 200, QSize(1920, 1040), QSize(860, 500)),
        (4000, 3000, QSize(1366, 728), QSize(1366, 728)),
    ],
)
def test_normalize_window_size_handles_invalid_and_offscreen_values(
    width, height, available, expected
):
    assert normalize_window_size(width, height, available_size=available) == expected


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
    frame.apply_window_size.assert_called_once_with(1250, 700)


def test_settings_navigation_switches_to_reference_setting_page():
    page = object()
    frame = SimpleNamespace(_settings_page=page, switchTo=Mock())

    MainFrame._show_settings(frame)

    frame.switchTo.assert_called_once_with(page)


def test_settings_navigation_reuses_existing_page():
    page = object()
    frame = SimpleNamespace(_settings_page=page, switchTo=Mock())

    MainFrame._show_settings(frame)
    MainFrame._show_settings(frame)

    assert frame.switchTo.call_count == 2
    assert all(item.args == (page,) for item in frame.switchTo.call_args_list)


def test_settings_reset_syncs_reference_cards_and_runtime(qt_application):
    settings = _MainFrameSettings()
    settings.values.update(
        {
            "theme": "Dark",
            "font_family": "Arial",
            "ui_font_size": 18,
            "log_font_size": 14,
            "log_max_lines": 5000,
            "continuous_device_scan": False,
            "always_on_top": True,
        }
    )
    frame = build_main_frame(settings=settings)
    try:
        page = frame._settings_page
        frame.set_continuous_scan = Mock()
        frame.set_always_on_top = Mock()
        frame.restore_default_window_size = Mock()

        with (
            patch.object(BaseStyles, "switch_theme"),
            patch.object(BaseStyles, "reload_from_settings"),
        ):
            page._reset_settings()

        assert page.scan_card.isChecked() is True
        assert page.pin_card.isChecked() is False
        assert page.log_lines_card.value() == "2000"
        assert page.font_family_card.value() == "系统默认"
        assert page.ui_size_card.value() == "12"
        assert page.log_size_card.value() == "9"
        assert page.theme_card.value() == "跟随系统"
        assert page.accent_card.color_button.color.name().upper() == "#0F6CBD"
        assert page.mica_card.isChecked() is True
        assert page.save_card.contentLabel.text() == "系统默认目录"
        frame.set_continuous_scan.assert_called_once_with(True)
        frame.set_always_on_top.assert_called_once_with(False)
        frame.restore_default_window_size.assert_called_once_with()
    finally:
        frame._close_ready = True
        frame.close()


def test_settings_page_applies_typography_in_one_batch(qt_application):
    settings = _MainFrameSettings()
    frame = build_main_frame(settings=settings)
    try:
        page = frame._settings_page
        blockers = [
            QSignalBlocker(page.font_family_card),
            QSignalBlocker(page.ui_size_card),
            QSignalBlocker(page.log_size_card),
        ]
        page.font_family_card.combo_box.addItem("Test UI")
        page.font_family_card.combo_box.setCurrentText("Test UI")
        page.ui_size_card.combo_box.setCurrentText("18")
        page.log_size_card.combo_box.setCurrentText("14")
        del blockers
        settings.writes.clear()

        with patch.object(BaseStyles, "reload_from_settings") as reload_styles:
            page._apply_typography("")

        assert settings.writes == [
            {
                "font_family": "Test UI",
                "ui_font_size": 18,
                "log_font_size": 14,
            }
        ]
        reload_styles.assert_called_once_with()
    finally:
        frame._close_ready = True
        frame.close()


def test_gallery_page_header_height_does_not_follow_vertical_window_resize(
    qt_application,
):
    """Gallery 页面标题区保持参考项目固定高度，剩余空间交给页面内容。"""

    frame = build_main_frame()
    try:
        frame.show()
        frame._on_nav_requested("apps")
        header = frame._apps_page.header
        heights = []
        body_heights = []
        for height in (500, 640, 800):
            frame.resize(1120, height)
            qt_application.processEvents()
            heights.append(header.height())
            body_heights.append(frame._apps_page.body.height())

        assert heights == [108, 108, 108]
        assert body_heights[-1] > body_heights[0]
        assert not hasattr(frame, "_toolbar")
        assert frame._settings_page.save_card.contentLabel.text()
    finally:
        frame._close_ready = True
        frame.close()

def test_minimum_window_keeps_independent_log_page_visible_with_large_font(
    qt_application,
    monkeypatch,
):
    """最大字号下 Logs 独立页面仍可见，不再依赖设备/日志 splitter。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 22)),
    )
    frame = build_main_frame()
    try:
        frame.resize(860, 500)
        frame.show()
        frame._on_nav_requested("logs")
        qt_application.processEvents()

        assert not hasattr(frame, "_device_log_splitter")
        assert frame.stackedWidget.currentWidget() is frame._logs_page
        assert frame.log_panel.isVisibleTo(frame._logs_page)
        assert frame.log_panel.text_output.isVisibleTo(frame._logs_page)
        assert frame._logs_page.header.height() == 108
        assert frame.minimumHeight() <= frame.height()
    finally:
        frame._close_ready = True
        frame.close()
