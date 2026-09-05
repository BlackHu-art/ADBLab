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
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    NavigationDisplayMode,
    NavigationPanel,
)
from shiboken6 import invalidate, isValid

from core.settings_manager import DEFAULTS, AppSettings
from gui import window_layout
from gui.main_frame import MainFrame
from gui.pages.workspace_features import WorkspaceRoute
from gui.screen_adapter import QtScreenAdapter
from gui.styles import BaseStyles
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.responsive_layout import reflow_widgets
from gui.window_layout import normalize_window_size
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    assert_text_fits,
    mapped_rect,
    wait_until,
)


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


def build_main_frame(
    *, screen_adapter=None, settings=None, mouse_buttons_provider=None, controller=None
):
    """用本地依赖替身构造 MainFrame，不访问 ADB 或外部 helper。"""

    settings = settings or _MainFrameSettings()
    if controller is None:
        controller = Mock()
        controller.signals = Mock()
    controller.operation_manager.active_snapshot.return_value = ()
    with (
        patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
        patch("gui.main_frame.ADBController", lambda _log_service: controller),
        patch.object(MainFrame, "_bootstrap_adb_async", lambda _self: None),
    ):
        return MainFrame(
            screen_adapter=screen_adapter,
            mouse_buttons_provider=mouse_buttons_provider,
        )


def populate_device_workbench(frame, count=8):
    """用合成设备形成真实可滚动内容，不依赖已移除的概览跳转卡。"""
    devices = [f"demo-device-{index}" for index in range(count)]
    frame._on_devices_updated(devices)
    frame.left_panel._devices_tab.set_selected_devices(devices[:1])
    return frame._device_hub.device_cards


def test_tasks_navigation_refreshes_task_history(qt_application):
    page = object()
    task_page = SimpleNamespace(refresh=Mock())
    frame = SimpleNamespace(
        _home_page=None,
        _devices_page=None,
        _apps_page=None,
        _system_page=None,
        _tasks_page=page,
        _task_page=task_page,
        _settings_page=None,
        switchTo=Mock(),
    )

    MainFrame._on_nav_requested(frame, "tasks")

    frame.switchTo.assert_called_once_with(page)
    task_page.refresh.assert_called_once_with()


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
    """一次真实主窗口 resize 只发布一次稳定结果，并应用最终 viewport 几何。"""

    # 关闭异步设备扫描：真实 adb 环境下扫描随时更新设备列表最小宽，会让分栏
    # 在 settle 后漂移，破坏本用例的确定性（P1 NavBar 改变事件时序后更易触发）。
    monkeypatch.setattr(MainFrame, "_start_scan_thread", lambda _self: None)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900)))
    )
    try:
        frame.show()
        frame._on_nav_requested("apps")
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
    """独立设备任务页共享内容宽度，切换不恢复旧分栏。"""

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
        assert frame.stackedWidget.currentWidget() is frame._devices_page
        assert frame._devices_page.isVisibleTo(frame)
        devices_scroll = frame._workspace_feature_hosts["devices"].overview.body
        wait_until(qt_application, lambda: devices_scroll.viewport().width() > 1000)
        devices_width = devices_scroll.viewport().width()
        frame._on_nav_requested("apps")
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        apps_scroll = frame._workspace_feature_hosts["apps"].overview.body
        wait_until(qt_application, lambda: apps_scroll.viewport().width() > 1000)
        apps_width = apps_scroll.viewport().width()

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
        assert frame._apps_page.autoFillBackground()
        assert frame._apps_page.palette().window().color().name() == expected
        assert frame._settings_page.viewport().palette().window().color().name() == expected

        wrapper = frame._workspace_feature_hosts["apps"].overview.body.widget()
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


def test_dark_theme_switch_finishes_fluent_window_background_immediately(qt_application):
    """主题 QSS 生效时根背景必须同步完成，避免外框短暂叠出浅色线。"""

    original_theme = BaseStyles.current_theme()
    settings = _MainFrameSettings()
    settings.values["mica_enabled"] = False
    BaseStyles.switch_theme("Light")
    frame = build_main_frame(settings=settings)
    try:
        frame.show()
        qt_application.processEvents()

        BaseStyles.switch_theme("Dark")

        expected = BaseStyles.color("WINDOW_BG").lower()
        assert frame.backgroundColorAni.state() == QAbstractAnimation.State.Stopped
        assert frame.backgroundColor.name() == expected
    finally:
        BaseStyles.switch_theme(original_theme)
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_theme_switch_keeps_mica_content_stack_edges_borderless(qt_application):
    """Mica 合成前后都不能恢复内容栈默认的上边和左边。"""

    original_theme = BaseStyles.current_theme()
    settings = _MainFrameSettings()
    settings.values.update(
        window_width=1000,
        window_height=700,
        mica_enabled=True,
    )
    BaseStyles.switch_theme("Light")
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )

    def assert_edges_match_window_surface() -> None:
        image = frame.grab().toImage()
        origin = frame.stackedWidget.mapTo(frame, QPoint())
        left_y = origin.y() + frame.stackedWidget.height() // 2
        top_x = origin.x() + frame.stackedWidget.width() // 2
        scale = image.devicePixelRatio()
        for edge, adjacent in (
            (QPoint(origin.x(), left_y), QPoint(origin.x() - 1, left_y)),
            (QPoint(top_x, origin.y()), QPoint(top_x, origin.y() - 1)),
        ):
            color = image.pixelColor(round(edge.x() * scale), round(edge.y() * scale))
            assert color.alpha() == 255
            assert color.name() == BaseStyles.color("WINDOW_BG").lower()
            assert color == image.pixelColor(
                round(adjacent.x() * scale), round(adjacent.y() * scale)
            )

    try:
        frame.show()
        # 首页滚动区有独立原生边框；用无边框设置页隔离内容栈边缘的绘制。
        frame._on_nav_requested("settings")
        wait_until(
            qt_application,
            lambda: frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped,
        )
        qt_application.processEvents()
        # 验证实际边缘像素；离屏覆盖 Qt 绘制，原生平台再覆盖 Mica/DWM 路径。
        assert_edges_match_window_surface()

        for theme in ("Dark", "Light"):
            BaseStyles.switch_theme(theme)
            # 同步返回态覆盖“边框先切换、页面稍后切换”的瞬间。
            assert_edges_match_window_surface()
            QTest.qWait(250)
            qt_application.processEvents()
            # Mica/DWM 稳定后，样式管理器也不能恢复半透明边框。
            assert_edges_match_window_surface()
    finally:
        BaseStyles.switch_theme(original_theme)
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
    """一级功能入口同步内容与语义路由，物理宿主继续复用。"""

    frame = build_main_frame()
    try:
        pages = {
            "devices": frame._devices_page,
            "apps": frame._apps_page,
            "system": frame._system_page,
        }
        assert len({page.objectName() for page in pages.values()}) == 3
        for key, page in pages.items():
            frame._on_nav_requested(key)
            assert frame.stackedWidget.currentWidget() is page
            assert frame.navigationInterface.panel.currentItem().property(
                "routeKey"
            ) == page.objectName()

        frame._on_nav_requested("remote")
        assert frame.stackedWidget.currentWidget() is frame._devices_page
        assert frame._devices_page.current_route.feature == "remote"
        assert frame.navigationInterface.panel.currentItem().property("routeKey") == (
            frame._workspace_navigation_keys[("devices", "remote")]
        )

        packages_key = frame._workspace_navigation_keys[("apps", "manager")]
        frame.navigationInterface.widget(packages_key).click()
        media_key = frame._workspace_navigation_keys[("apps", "media")]
        frame.navigationInterface.widget(media_key).click()
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert frame._apps_page.current_route.feature == "media"
        assert frame.navigationInterface.panel.currentItem().property(
            "routeKey"
        ) == media_key

        overview_key = frame._workspace_navigation_keys[("apps", "overview")]
        frame.navigationInterface.widget(overview_key).click()
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert frame._apps_page.current_route.feature == "overview"
        assert frame.navigationInterface.panel.currentItem().property("routeKey") == (
            overview_key
        )

        frame._on_nav_requested("settings")
        assert frame.navigationInterface.panel.currentItem().property("routeKey") == (
            frame._settings_page.objectName()
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_workspace_overviews_expose_task_categories(qt_application):
    """九个业务入口唯一登记在左栏，三个宿主不再展示区内功能选择器。"""

    frame = build_main_frame()
    try:
        expected_panels = (
            (frame.left_panel._apps_tab, ("daily",)),
            (
                frame.left_panel._advanced_tab,
                ("commands",),
            ),
            (frame.left_panel._scrcpy_tab, ("mirroring",)),
        )
        for panel, keys in expected_panels:
            assert panel is not None
            assert panel.category_stack.category_keys == keys
            assert panel.category_stack.stack.count() == len(keys)
            assert panel.category_stack.stack.currentWidget() is panel.category_stack.page(
                keys[0]
            )
            assert panel.panel_header.isHidden()
            assert panel.category_stack.pivot.isHidden()
            assert panel.category_stack.combo.isHidden()

        expected_navigation = {
            "devices": ("overview", "files", "remote"),
            "apps": (
                "overview",
                "manager",
                "media",
            ),
            "system": (
                "overview",
                "logcat",
                "performance",
            ),
        }
        route_keys = []
        for section, features in expected_navigation.items():
            host = frame._workspace_feature_hosts[section]
            assert tuple(item.feature for item in host.navigation_items()) == features
            assert host.feature_selector.isHidden()
            assert host.feature_combo.isHidden()
            assert host.feature_pivot.isHidden()
            for feature in features:
                route_key = frame._workspace_navigation_keys[(section, feature)]
                route_keys.append(route_key)
                item = frame.navigationInterface.widget(route_key)
                assert item is not None
                assert item.isSelectable is True
                assert item.treeParent is None
                assert not item.property("parentRouteKey")

        assert len(route_keys) == len(set(route_keys))
        assert all(frame.navigationInterface.widget(key) is not None for key in route_keys)
        assert all(
            f"workspace-group:{section}" not in frame.navigationInterface.panel.items
            for section in expected_navigation
        )
        assert len(route_keys) == 9
        assert len(frame._workspace_pages) == 3
        assert frame.stackedWidget.count() == 6
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_programmatic_workspace_route_selects_native_navigation_item(qt_application):
    frame = build_main_frame()
    try:
        frame.show()
        assert frame._open_workspace_feature("system", "connectivity") is True

        route_key = frame._system_page.objectName()
        assert frame.stackedWidget.currentWidget() is frame._system_page
        assert frame._system_page.current_route == WorkspaceRoute(
            "system",
            "overview",
        )
        assert frame.navigationInterface.panel.currentItem().property(
            "routeKey"
        ) == route_key
        assert frame.navigationInterface.panel.currentItem() is (
            frame.navigationInterface.widget(route_key)
        )
        assert frame._workspace_feature_hosts["system"].feature_selector.isHidden()
        assert frame._system_page.header.title_label.text() == "系统工具"
        assert "设备配置" in frame._system_page.header.subtitle_label.text()
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_history_restores_workspace_child_and_lifecycle(qt_application):
    """返回业务宿主页时须恢复功能入口选中态并重新激活当前会话。"""

    frame = build_main_frame()
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "packages") is True
        assert frame._apps_page._active is True

        frame._on_nav_requested("tasks")
        assert frame._apps_page._active is False

        frame.navigationInterface.panel.returnButton.click()
        wait_until(
            qt_application,
            lambda: frame.stackedWidget.currentWidget() is frame._apps_page,
        )

        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert frame._apps_page._active is True
        assert frame._apps_page.current_route.feature == "manager"
        assert frame.navigationInterface.panel.currentItem().property(
            "routeKey"
        ) == frame._workspace_navigation_keys[("apps", "manager")]
        assert frame._workspace_feature_hosts["apps"].feature_selector.isHidden()
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_history_tracks_workspace_leaves_on_same_physical_page(
    qt_application,
):
    """同一业务宿主页内切换功能后，返回应逐个恢复逻辑入口。"""

    frame = build_main_frame()
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "packages")
        assert frame._open_workspace_feature("apps", "monkey")

        frame.navigationInterface.panel.returnButton.click()
        assert frame._apps_page.current_route.feature == "manager"
        assert frame.stackedWidget.currentWidget() is frame._apps_page

        frame.navigationInterface.panel.returnButton.click()
        assert frame.stackedWidget.currentWidget() is frame._home_page
        assert frame.navigationInterface.panel.returnButton.isEnabled() is False
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_device_picker_is_transient_and_ignores_ambiguous_resume(qt_application):
    """全局设备弹层不改变历史，多选和隐藏宿主信号不能夺走待打开意图。"""

    frame = build_main_frame()
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "manager")
        host = frame._workspace_feature_hosts["apps"]
        pending = host.pending_route
        assert pending is not None
        history = tuple(frame._navigation_history)
        host.no_device_page.choose_button.click()
        assert frame._global_device_bar._picker is not None
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert tuple(frame._navigation_history) == history

        frame._on_devices_updated(["device-1", "device-2"])
        frame._global_device_bar.selection_requested.emit(["device-1", "device-2"])
        frame._on_workspace_route_changed(WorkspaceRoute("system", "overview"))
        assert host.pending_route == pending
        assert host.stack.currentWidget() is host.no_device_page
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert tuple(frame._navigation_history) == history

        frame._on_nav_requested("tasks")
        assert host.pending_route == pending
        frame.navigationInterface.panel.returnButton.click()
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert frame._apps_page.current_route.feature == "manager"
        assert host.pending_route == pending

        from gui.features.app_manager import AppManagerPage

        with patch.object(AppManagerPage, "_load_apps"):
            frame._global_device_bar.selection_requested.emit(["device-1"])
        assert host.pending_route is None
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert frame._apps_page.current_route == WorkspaceRoute(
            "apps",
            "manager",
            "device-1",
        )

        frame.navigationInterface.panel.returnButton.click()
        assert frame.stackedWidget.currentWidget() is frame._home_page
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_narrow_workspace_exposes_distinct_function_and_device_controls(qt_application):
    adapter = _FakeScreenAdapter(_FakeScreen("narrow", QSize(720, 500)))
    frame = build_main_frame(screen_adapter=adapter)
    try:
        frame.show()
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["device-1"], ["device-1"])
        assert frame._open_workspace_feature(
            "system",
            "performance",
            device_id="device-1",
        )
        qt_application.processEvents()

        visible_combos = [
            combo
            for combo in host.findChildren(ComboBox)
            if combo.isVisibleTo(host)
        ]
        assert host.feature_combo not in visible_combos
        assert host.feature_combo.isHidden()
        assert host.feature_pivot.isHidden()
        assert host.feature_selector.isHidden()
        assert host.session_toolbar.isHidden()
        assert frame.navigationInterface.panel.currentItem() is frame.navigationInterface.widget(
            frame._workspace_navigation_keys[("system", "performance")]
        )
        bar = frame._global_device_bar
        assert bar.targets_button.isVisible()
        assert bar.session_combo.isVisible()
        assert bar.session_combo.currentData() == "device-1"
        assert bar.session_combo.accessibleName() == "当前查看的会话设备"
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_workspace_header_owns_status_and_aligns_overview_content(qt_application):
    """状态归入页头，概览内容与标题使用同一条左侧基线。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=1120, window_height=640)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "overview") is True
        page = frame._apps_page
        host = frame._workspace_feature_hosts["apps"]
        qt_application.processEvents()

        assert host.session_badge.parentWidget() is page.header
        assert page.header.actions_layout.indexOf(host.session_badge) >= 0
        assert host.session_toolbar.isHidden()
        wrapper = host.overview.body.widget()
        assert wrapper is not None and wrapper.layout() is not None
        title_left = page.header.title_label.mapTo(page, QPoint()).x()
        content_left = wrapper.mapTo(
            page,
            QPoint(wrapper.layout().contentsRect().left(), 0),
        ).x()
        assert abs(title_left - content_left) <= 2
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_remote_workspace_requires_an_explicit_session_device_when_multiple_online(
    qt_application,
):
    frame = build_main_frame()
    try:
        frame.show()
        host = frame._workspace_feature_hosts["devices"]
        host.set_device_context([], ["device-1", "device-2"])

        assert frame._open_workspace_feature("devices", "remote") is True
        assert host.stack.currentWidget() is host.no_device_page
        assert host.device_combo.currentData() == ""

        host.device_combo.setCurrentIndex(2)
        assert host.current_device_id == "device-2"
        assert frame.left_panel._scrcpy_tab is not None
        remote = frame.left_panel._scrcpy_tab
        assert remote.selected_devices == ["device-2"]
        assert remote.category_stack.current_key == "mirroring"

        remote._set_session_state(remote._SESSION_STARTING)
        assert host.device_combo.isEnabled() is False
        assert "停止后" in host.device_combo.toolTip()
        remote._set_session_state(remote._SESSION_IDLE)
        assert host.device_combo.isEnabled() is True

        host.set_device_context([], [])
        assert host.session_badge.text() == "离线"
        assert remote.selected_devices == []
        assert remote.btn_start.isEnabled() is False
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_workspace_page_switches_pause_only_the_previous_feature_host(qt_application):
    """跨主页面切换只停用前一领域，并且每个目标页只激活一次。"""

    frame = build_main_frame()
    try:
        with (
            patch.object(
                frame._devices_page,
                "activate",
                wraps=frame._devices_page.activate,
            ) as activate_devices,
            patch.object(
                frame._devices_page,
                "deactivate",
                wraps=frame._devices_page.deactivate,
            ) as deactivate_devices,
            patch.object(
                frame._apps_page,
                "activate",
                wraps=frame._apps_page.activate,
            ) as activate_apps,
            patch.object(
                frame._apps_page,
                "deactivate",
                wraps=frame._apps_page.deactivate,
            ) as deactivate_apps,
        ):
            frame._on_nav_requested("devices")
            frame._on_nav_requested("apps")
            frame._on_nav_requested("settings")

        activate_devices.assert_called_once_with()
        deactivate_devices.assert_called_once_with("top_level_navigation")
        activate_apps.assert_called_once_with()
        deactivate_apps.assert_called_once_with("top_level_navigation")
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_no_device_feature_resumes_inline_after_device_selection(qt_application):
    """空态选择设备后恢复原功能，且只创建主窗口内的稳定会话。"""

    from gui.features.app_manager import AppManagerPage

    frame = build_main_frame()
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "manager") is True
        apps_host = frame._workspace_feature_hosts["apps"]
        assert apps_host.stack.currentWidget() is apps_host.no_device_page
        pending = apps_host.pending_route
        assert pending is not None

        apps_host.no_device_page.choose_button.click()
        assert frame._global_device_bar._picker is not None
        assert apps_host.pending_route == pending
        assert frame.stackedWidget.currentWidget() is frame._apps_page

        frame._on_devices_updated(["device-1", "device-2"])
        with patch.object(AppManagerPage, "_load_apps"):
            frame._global_device_bar.selection_requested.emit(["device-1"])

        page = apps_host.stack.currentWidget()
        assert isinstance(page, AppManagerPage)
        assert page.device_ip == "device-1"
        assert page.isWindow() is False
        assert frame._apps_page.current_route == WorkspaceRoute(
            "apps",
            "manager",
            "device-1",
        )
        assert apps_host.pending_route is None
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_app_manager_fits_inside_small_workspace_page(qt_application):
    """App Manager 在 720×420 中保留完整内容并可滚动到底部。"""

    from gui.features.app_manager import AppManagerPage

    adapter = _FakeScreenAdapter(_FakeScreen("small", QSize(720, 420)))
    frame = build_main_frame(screen_adapter=adapter)
    try:
        frame.show()
        host = frame._workspace_feature_hosts["apps"]
        host.set_device_context(["device-1"], ["device-1"])
        with patch.object(AppManagerPage, "_load_apps"):
            assert frame._open_workspace_feature(
                "apps",
                "manager",
                device_id="device-1",
            )
        qt_application.processEvents()

        page = host.stack.currentWidget()
        assert isinstance(page, AppManagerPage)
        assert page.minimumSize() == QSize(0, 0)
        assert page.geometry() == host.stack.rect()
        content_minimum = page.workspace_content_minimum_size()
        assert page.width() >= content_minimum.width()
        assert page.height() >= content_minimum.height()
        assert host.content_scroll.verticalScrollBar().maximum() > 0

        layout = page._master_panel.layout()
        visible_rects = sorted(
            (
                layout.itemAt(index).geometry()
                for index in range(layout.count())
                if not layout.itemAt(index).isEmpty()
            ),
            key=lambda rect: rect.top(),
        )
        assert all(rect.width() > 0 and rect.height() > 0 for rect in visible_rects)
        assert all(
            current.bottom() < following.top()
            for current, following in zip(visible_rects, visible_rects[1:])
        )
        assert_scroll_target_reachable(host.content_scroll, page.status_bar)
        assert frame.minimumSizeHint().width() <= 720
        assert frame.minimumSizeHint().height() <= 420
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_all_embedded_feature_pages_remain_reachable_on_short_workspace(qt_application):
    """所有深层功能页都由同一宿主滚动契约承载，不裁切底部动作。"""

    from gui.dialogs.file_explorer import FileExplorerPage
    from gui.features.app_manager import AppManagerPage

    adapter = _FakeScreenAdapter(_FakeScreen("small", QSize(720, 420)))
    frame = build_main_frame(screen_adapter=adapter)
    try:
        frame.show()
        targets = (
            ("devices", "files", "status_bar", True),
            ("apps", "manager", "status_bar", True),
            ("apps", "media", "_bottom_bar", False),
            ("system", "logcat", "status_bar", True),
            ("system", "performance", "start_btn", True),
        )
        with (
            patch.object(AppManagerPage, "_load_apps"),
            patch.object(FileExplorerPage, "_refresh"),
        ):
            for section, feature, target_name, requires_device in targets:
                host = frame._workspace_feature_hosts[section]
                if requires_device:
                    host.set_device_context(["device-1"], ["device-1"])
                assert frame._open_workspace_feature(
                    section,
                    feature,
                    device_id="device-1" if requires_device else "",
                )
                qt_application.processEvents()
                qt_application.processEvents()

                page = host.stack.currentWidget()
                provider = getattr(page, "workspace_content_minimum_size", None)
                minimum = provider() if callable(provider) else page.minimumSizeHint()
                minimum = minimum.expandedTo(page.minimumSize())
                assert page.width() >= max(0, minimum.width())
                assert page.height() >= max(0, minimum.height())
                assert host.content_scroll.verticalScrollBar().maximum() > 0

                if feature == "performance":
                    assert page._config_scroll.isHidden()
                    assert not page._config_scroll.isVisibleTo(page)

                target = getattr(page, target_name)
                assert page.rect().contains(mapped_rect(target, page))
                assert_scroll_target_reachable(host.content_scroll, target)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_logcat_route_injects_mainframe_owned_services(qt_application):
    """真实 Workspace factory 必须把主窗口资源注入 Logcat 页面。"""

    from gui.features.logcat import LiveLogcatPage

    frame = build_main_frame()
    try:
        frame.show()
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["device-1"], ["device-1"])

        assert frame._open_workspace_feature(
            "system",
            "logcat",
            device_id="device-1",
        ) is True

        page = host.stack.currentWidget()
        assert isinstance(page, LiveLogcatPage)
        assert page.device_ip == "device-1"
        assert page._task_supervisor is frame.task_supervisor
        assert page._log_service is frame.log_service
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_screenshot_batch_updates_inline_media_without_stealing_navigation(
    qt_application,
    tmp_path,
):
    """后台截图更新结果页，但用户主动查看前不抢走当前顶层页面。"""

    from PySide6.QtGui import QPixmap

    from gui.features.media import ScreenshotPage

    image_paths = []
    for name in ("first.png", "second.png", "third.png"):
        path = tmp_path / name
        pixmap = QPixmap(8, 8)
        pixmap.fill(Qt.GlobalColor.blue)
        assert pixmap.save(str(path))
        image_paths.append(str(path))

    frame = build_main_frame()
    try:
        frame.show()
        top_levels = set(qt_application.topLevelWidgets())
        current_page = frame.stackedWidget.currentWidget()
        frame._on_screenshot_batch_ready(image_paths[:2])

        host = frame._workspace_feature_hosts["apps"]
        page = next(
            page
            for key, page in zip(host.registry.keys(), host.registry.pages(), strict=True)
            if key.feature == "media"
        )
        assert isinstance(page, ScreenshotPage)
        assert page.isWindow() is False
        assert page.image_paths == tuple(image_paths[:2])
        assert frame.stackedWidget.currentWidget() is current_page
        assert set(qt_application.topLevelWidgets()) == top_levels

        frame._on_screenshot_batch_ready(image_paths[1:])
        assert page.image_paths == tuple(image_paths)
        frame._open_workspace_feature("apps", "media")
        assert host.stack.currentWidget() is page
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_screenshot_batch_preserves_pending_device_route(qt_application, tmp_path):
    """截图后台完成时，不覆盖等待设备选择后恢复的目标功能。"""

    from PySide6.QtGui import QPixmap

    image_path = tmp_path / "pending-route.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.GlobalColor.blue)
    assert pixmap.save(str(image_path))
    pending = WorkspaceRoute(
        "system",
        "logcat",
        payload={"package_name": "com.example.app"},
    )

    frame = build_main_frame()
    try:
        frame.show()
        frame._on_nav_requested(pending)
        host = frame._workspace_feature_hosts["system"]
        host.no_device_page.choose_button.click()
        assert frame._global_device_bar._picker is not None
        current_route = frame._system_page.current_route
        history = tuple(frame._navigation_history)

        frame._on_screenshot_batch_ready([str(image_path)])

        assert host.pending_route == pending
        assert host.stack.currentWidget() is host.no_device_page
        assert frame.stackedWidget.currentWidget() is frame._system_page
        assert frame._system_page.current_route == current_route
        assert tuple(frame._navigation_history) == history
        assert current_route.section == "system"
        assert current_route.feature == "logcat"
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_settings_contains_inline_about_panel(qt_application):
    frame = build_main_frame()
    try:
        frame.show()
        frame._on_nav_requested("settings")

        assert frame._settings_page.about_panel.isVisibleTo(frame._settings_page)
        assert "ADBLab" in frame._settings_page.about_panel.title_label.text()
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
        wait_until(
            qt_application,
            lambda: frame.navigationInterface.panel.displayMode
            == NavigationDisplayMode.COMPACT,
        )
        assert frame.width() == 860
        panel = frame.navigationInterface.panel
        assert panel.displayMode == NavigationDisplayMode.COMPACT

        panel.menuButton.click()
        assert panel.displayMode == NavigationDisplayMode.MENU
        assert panel.expandAni.state() == QAbstractAnimation.State.Running

        frame.navigationInterface.widget(frame._tasks_page.objectName()).click()

        assert frame.stackedWidget.currentWidget() is frame._tasks_page
        assert panel.currentItem().property("routeKey") == frame._tasks_page.objectName()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT and panel.width() == 48,
        )
        assert panel.parentWidget() is frame.navigationInterface
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_back_closes_narrow_overlay_menu(qt_application):
    """覆盖菜单打开时返回，菜单与页面必须在同一交互内一起恢复。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=600)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "packages")
        frame._on_nav_requested("tasks")
        panel = frame.navigationInterface.panel
        panel.menuButton.click()
        assert panel.displayMode == NavigationDisplayMode.MENU

        panel.returnButton.click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT,
        )
        assert frame.stackedWidget.currentWidget() is frame._apps_page
        assert frame._apps_page.current_route.feature == "manager"
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_menu_resize_to_wide_settles_as_persistent_sidebar(
    qt_application,
):
    """覆盖菜单跨越宽屏断点后必须重新归位为常驻左栏。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=600)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        panel = frame.navigationInterface.panel
        panel.menuButton.click()
        assert panel.displayMode == NavigationDisplayMode.MENU

        frame.resize(1120, 640)
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND,
        )
        assert panel.parentWidget() is frame.navigationInterface
        assert panel.width() == panel.expandWidth == 220
        assert frame._navigation_wide_state is True
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_compact_navigation_exposes_flat_routes_without_tree_flyouts(
    qt_application,
):
    """窄栏只保留一级入口，点击功能时不再创建树形 Flyout。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=600)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        panel = frame.navigationInterface.panel
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT,
        )
        assert panel.width() == 48
        visible_items = 0
        for route_key in frame._workspace_navigation_keys.values():
            item = frame.navigationInterface.widget(route_key)
            visible = item.visibleRegion().boundingRect()
            if visible.isEmpty():
                continue
            visible_items += 1
            left = item.mapTo(panel, visible.topLeft()).x()
            right = item.mapTo(panel, visible.bottomRight()).x()
            assert 0 <= left <= right < panel.width()
        assert visible_items > 0

        route = frame.navigationInterface.widget(frame._apps_page.objectName())
        assert route.treeParent is None
        assert not route.property("parentRouteKey")
        route.click()
        frame.navigationInterface.widget(
            frame._workspace_navigation_keys[("apps", "media")]
        ).click()
        assert frame._apps_page.current_route.feature == "media"

        panel.menuButton.click()
        assert panel.displayMode == NavigationDisplayMode.MENU
        frame.navigationInterface.widget(frame._system_page.objectName()).click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT,
        )
        frame.navigationInterface.widget(
            frame._workspace_navigation_keys[("system", "performance")]
        ).click()
        assert frame._system_page.current_route.feature == "performance"
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_workspace_navigation_animation_keeps_flat_item_geometry_inside_panel(
    qt_application,
):
    """菜单动画期间切换一级入口后，控件不得溢出导航面板。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=600)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "packages")
        panel = frame.navigationInterface.panel
        panel.menuButton.click()
        media_key = frame._workspace_navigation_keys[("apps", "media")]
        frame.navigationInterface.widget(media_key).click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT,
        )
        current = frame.navigationInterface.widget(media_key)
        assert panel.currentItem() is current
        assert current.treeParent is None
        assert current.width() <= panel.expandWidth
        panel.menuButton.click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.MENU,
        )
        assert current.isVisibleTo(panel)
        assert current.rect().right() < panel.expandWidth
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_hamburger_replays_click_received_during_collapse(qt_application):
    """收起动画中的第二次点击不能被 NavigationPanel 静默丢弃。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=600)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        panel = frame.navigationInterface.panel
        panel.menuButton.click()
        panel.menuButton.click()
        assert panel.expandAni.state() == QAbstractAnimation.State.Running
        panel.menuButton.click()

        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.MENU
            and panel.expandAni.state() != QAbstractAnimation.State.Running,
        )
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_wide_workspace_opens_native_navigation_and_reveals_active_route(
    qt_application,
):
    """桌面宽度直接展示左栏；切入业务页后当前入口必须可见。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=1120, window_height=640)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        panel = frame.navigationInterface.panel
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND,
        )

        assert frame._open_workspace_feature("apps", "packages") is True
        current = frame.navigationInterface.widget(
            frame._workspace_navigation_keys[("apps", "manager")]
        )
        assert current.isVisibleTo(panel.scrollArea.viewport())
        assert current.treeParent is None
        assert panel.currentItem() is current
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_narrow_navigation_overlay_reveals_the_active_flat_route(qt_application):
    """窄窗菜单不得挤压内容，打开后应直接露出当前一级入口。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=900, window_height=600)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        assert frame._open_workspace_feature("apps", "packages") is True
        panel = frame.navigationInterface.panel
        assert panel.displayMode == NavigationDisplayMode.COMPACT
        page_width = frame._apps_page.width()

        panel.menuButton.click()
        assert panel.displayMode == NavigationDisplayMode.MENU
        assert frame.navigationInterface.widget(
            frame._workspace_navigation_keys[("apps", "manager")]
        ).isVisibleTo(panel)
        assert frame._apps_page.width() == page_width
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_workspace_navigation_has_nine_flat_features_and_three_persistent_pages(qt_application):
    """业务功能与三个常驻页均为一级入口，六个物理页面继续复用。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=1120, window_height=640)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        panel = frame.navigationInterface.panel
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND,
        )
        assert len(frame._workspace_navigation_page_keys) == 3
        assert len(frame._workspace_navigation_keys) == 9
        route_keys = tuple(frame._workspace_navigation_keys.values()) + tuple(
            page.objectName() for page in (
                frame._home_page, frame._tasks_page, frame._settings_page
            )
        )
        assert len(set(route_keys)) == 12
        assert frame.stackedWidget.count() == 6
        for route_key in route_keys:
            item = frame.navigationInterface.widget(route_key)
            assert item is not None
            assert item.isSelectable is True
            assert item.treeParent is None
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_short_navigation_scrolls_current_workspace_item_into_view(qt_application):
    """短窗口切换到领域末项时，选中入口不能留在左栏视口之外。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=1120, window_height=500)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        panel = frame.navigationInterface.panel
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND,
        )
        assert frame._open_workspace_feature("system", "performance") is True
        item = frame.navigationInterface.widget(
            frame._workspace_navigation_keys[("system", "performance")]
        )
        assert panel.currentItem() is item
        wait_until(
            qt_application,
            lambda: panel.scrollArea.viewport().rect().contains(
                item.mapTo(panel.scrollArea.viewport(), item.rect().center())
            ),
        )

        center = item.mapTo(panel.scrollArea.viewport(), item.rect().center())
        assert panel.scrollArea.viewport().rect().contains(center)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_navigation_animation_reflows_system_against_final_viewport(qt_application):
    """左栏动画结束后重新规划 System，不能停在保守单列回退。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=1600, window_height=900)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        assert frame._open_workspace_feature("system", "overview") is True
        panel = frame.navigationInterface.panel
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND,
        )
        panel.collapse()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT,
        )

        previous_generation = (
            frame.left_panel._responsive_coordinator.diagnostics.generation
        )
        panel.menuButton.click()
        coordinator = frame.left_panel._responsive_coordinator
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped
            and coordinator.diagnostics.stable
            and coordinator.diagnostics.generation > previous_generation,
        )

        system = frame.left_panel._advanced_tab
        assert system is not None
        assert coordinator.diagnostics.fallback_reason is None
        assert all(
            binding.applied_plan is not None
            and binding.applied_plan.available_width
            == binding.responsive_context().width
            for binding in system._responsive_rows
        )
        assert any(
            binding.applied_plan.mode.name != "one"
            for binding in system._responsive_rows
            if binding.applied_plan is not None
        )
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
        frame._on_nav_requested(WorkspaceRoute("apps", "monkey"))
        coordinator = frame.left_panel._responsive_coordinator
        wait_until(qt_application, lambda: coordinator.diagnostics.stable)

        assert app_panel.monkey_events.isVisibleTo(frame)

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

            assert app_panel.monkey_events.isVisibleTo(frame)

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
        cards = populate_device_workbench(frame)
        frame._on_nav_requested("devices")
        wait_until(
            qt_application,
            lambda: frame._device_scroll_area.verticalScrollBar().maximum() > 0,
        )

        scroll = frame._device_scroll_area
        last_action = cards[-1].apps_button
        assert frame.size() == available
        assert frame.height() <= available.height()
        assert frame.minimumHeight() <= available.height()
        assert scroll.horizontalScrollBar().maximum() == 0
        QTest.qWait(50)
        content_center = last_action.mapTo(scroll.widget(), last_action.rect().center())
        vertical = scroll.verticalScrollBar()
        vertical.setValue(
            min(
                vertical.maximum(),
                max(0, content_center.y() - scroll.viewport().height() // 2),
            )
        )
        QTest.qWait(10)
        button_center = last_action.mapTo(scroll.viewport(), last_action.rect().center())
        viewport = scroll.viewport().rect().adjusted(0, 0, 0, 2)
        assert viewport.contains(button_center), (
            f"button={button_center!r}, viewport={viewport!r}, "
            f"scroll={vertical.value()}/{vertical.maximum()}, "
            f"content_center={content_center!r}, content={scroll.widget().size()!r}"
        )
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


def test_manually_shortened_devices_page_keeps_bottom_action_reachable(
    qt_application,
):
    """大屏上的短窗口也必须由可见滚动区承接 Devices 全部动作。"""

    settings = _MainFrameSettings()
    settings.values.update(window_width=860, window_height=500)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1920, 1080))),
        settings=settings,
    )
    try:
        frame.show()
        cards = populate_device_workbench(frame)
        frame._on_nav_requested("devices")
        inner_scroll = frame._device_scroll_area
        outer_scroll = frame._workspace_feature_hosts["devices"].content_scroll
        wait_until(
            qt_application,
            lambda: inner_scroll.verticalScrollBar().maximum() > 0,
        )

        assert inner_scroll.height() <= outer_scroll.viewport().height()
        inner_scroll.verticalScrollBar().setValue(
            inner_scroll.verticalScrollBar().maximum()
        )
        QTest.qWait(20)
        button = cards[-1].apps_button
        center = button.mapTo(outer_scroll.viewport(), button.rect().center())
        assert outer_scroll.viewport().rect().adjusted(0, 0, 0, 2).contains(center)
    finally:
        frame._unbind_window_screen()
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
    """紧凑页头保持固定高度，剩余空间交给页面内容。"""

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

        assert heights == [88, 88, 88]
        assert body_heights[-1] > body_heights[0]
        assert not hasattr(frame, "_toolbar")
        assert frame._settings_page.save_card.contentLabel.text()
    finally:
        frame._close_ready = True
        frame.close()

def test_minimum_window_keeps_task_runtime_records_reachable_with_large_font(
    qt_application,
    monkeypatch,
):
    """最大字号展开任务运行记录后自动定位，稳定视口内正文全部可达。"""

    from tests.ui_geometry_helpers import wait_for_stable_geometry

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 22)),
    )
    frame = build_main_frame()
    try:
        frame.resize(860, 500)
        frame.show()
        frame._on_nav_requested("tasks")
        frame._task_page.show_runtime_records()
        scroll = frame._task_page._scroll
        output = frame.log_panel.text_output
        wait_until(
            qt_application,
            lambda: scroll.viewport().rect().contains(mapped_rect(output, scroll.viewport())),
        )
        wait_for_stable_geometry(qt_application, (scroll.viewport(), scroll.widget(), output))

        assert not hasattr(frame, "_device_log_splitter")
        assert frame.stackedWidget.currentWidget() is frame._tasks_page
        assert frame.log_panel.isVisibleTo(frame._tasks_page)
        assert frame.log_panel.text_output.isVisibleTo(frame._tasks_page)
        assert scroll.viewport().rect().contains(mapped_rect(output, scroll.viewport()))
        assert_scroll_target_reachable(scroll, output)
        assert frame.minimumHeight() <= frame.height()
    finally:
        frame._close_ready = True
        frame.close()
