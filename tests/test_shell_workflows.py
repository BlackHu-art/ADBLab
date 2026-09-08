"""验证首页入口、功能分区结果和原生 Fluent 按钮交互。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter
from PySide6.QtTest import QSignalSpy
from qfluentwidgets import FluentIcon, PrimaryPushButton

from controllers.signals import ADBControllerSignals
from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles
from gui.styles.icon_loader import DEVICE_ICON, get_fluent_icon, get_themed_icon
from tests.test_main_window_layout import build_main_frame


@pytest.fixture
def frame(qt_application):
    window = build_main_frame()
    window.show()
    qt_application.processEvents()
    yield window
    window._unbind_window_screen()
    window._close_ready = True
    window.close()


def test_device_bar_visibility_follows_page_without_retargeting(
    frame, qt_application
):
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    assert frame._global_device_bar.isHidden()
    home_top = frame.stackedWidget.y()
    for route in ("devices", "apps", "system", "tasks", "settings"):
        frame._on_nav_requested(route)
        qt_application.processEvents()
        if route in ("devices", "tasks", "settings"):
            assert frame._global_device_bar.isHidden()
            assert frame.stackedWidget.y() == home_top
        else:
            assert frame._global_device_bar.isVisible()
            assert frame.stackedWidget.y() > home_top
        assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    frame._on_nav_requested("home")
    qt_application.processEvents()
    assert frame._global_device_bar.isHidden()
    assert frame.stackedWidget.y() == home_top


def test_action_results_belong_to_section_and_survive_navigation(frame, qt_application):
    from adblab.application.action_results import ActionItem, ActionResult, ActionSpec

    assert "logsPage" not in frame.navigationInterface.panel.items
    assert not hasattr(frame, "log_panel")
    result = ActionResult(
        "synthetic", ActionSpec("query", "apps.diagnostics", "内存", "text"),
        ("demo",), 1, state="failed",
        items=(ActionItem("job", "demo", "设备 1", "failed", "示例操作失败，请重试"),),
        finished_at=2,
    )
    frame._action_feedback.present(result)
    frame._on_nav_requested("tasks")
    frame._task_page.history_views.set_current("operations")
    view = frame._task_page.action_results
    assert view.isVisibleTo(frame._tasks_page)
    assert "示例操作失败" in view.output.toPlainText()
    view.detail_toggle.setChecked(False)
    frame._on_nav_requested("home")
    frame._on_nav_requested("tasks")
    view.detail_toggle.setChecked(True)
    assert "示例操作失败" in view.output.toPlainText()
    assert frame._action_feedback._diagnostics._records["synthetic"] is result


def test_overview_disconnect_uses_current_selection_and_stays_in_device_page(frame):
    frame._on_nav_requested("devices")
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    frame._device_hub.disconnect_action.trigger()
    assert frame.stackedWidget.currentWidget() is frame._devices_page
    frame.adb_controller.disconnect_devices.assert_called_once_with(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-b"])
    frame._device_hub.disconnect_action.trigger()
    frame.adb_controller.disconnect_devices.assert_called_with(["demo-b"])
    frame._global_device_bar.selection_requested.emit([])
    frame._device_hub.disconnect_action.trigger()
    assert frame.stackedWidget.currentWidget() is frame._devices_page
    assert frame.adb_controller.disconnect_devices.call_count == 2


def test_monkey_alias_opens_diagnostics_without_duplicate_sidebar_entry(frame):
    assert "monkeyPage" not in frame.navigationInterface.panel.items
    frame._open_workspace_feature("apps", "monkey")
    assert frame._apps_page.current_route.feature == "overview"
    assert frame.navigationInterface.panel.currentItem() is (
        frame.navigationInterface.widget("appsPage")
    )
    panel = frame.left_panel._apps_tab
    assert panel.category_stack.current_key == "daily"
    assert panel.category_stack.page("daily").isAncestorOf(panel.start_monkey_btn)


@pytest.mark.parametrize("cancel", (False, True))
def test_main_window_routes_package_preparation_before_monkey_start(qt_application, cancel):
    controller = Mock(signals=ADBControllerSignals())
    window = build_main_frame(controller=controller)
    try:
        window._on_devices_updated(["demo-a", "demo-b"])
        window._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
        window._on_nav_requested("apps")
        panel = window.left_panel._apps_tab
        panel.program_edit.setText("com.example.demo")
        panel.start_monkey_btn.click()
        controller.prepare_monkey_targets.assert_called_once()
        devices, package, request_id, token = controller.prepare_monkey_targets.call_args.args
        assert devices == ["demo-a", "demo-b"]
        assert package == "com.example.demo"
        controller.run_monkey_test.assert_not_called()
        if cancel:
            panel.monkey_cancel_prepare_btn.click()
            assert token.is_cancelled
        result = {
            "success": True,
            "devices": devices,
            "package_name": package,
            "packages": [
                {"device_ip": device, "package_name": package,
                 "version_name": "1.0", "version_code": "1", "target_sdk": "34"}
                for device in devices
            ],
        }
        controller.signals.monkey_preparation_finished.emit(request_id, result)
        controller.signals.monkey_preparation_finished.emit(request_id, result)
        if cancel:
            controller.run_monkey_test.assert_not_called()
        else:
            controller.run_monkey_test.assert_called_once()
            targets, config, batch_id = controller.run_monkey_test.call_args.args
            assert targets == devices
            assert config["package_name"] == package
            assert batch_id
    finally:
        window._unbind_window_screen()
        window._close_ready = True
        window.close()


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_reference_icons_render_in_both_themes_and_primary_buttons_keep_native_icons(
    qt_application, theme
):
    BaseStyles.switch_theme(theme)
    icon = get_themed_icon("play.svg")
    assert isinstance(icon, QIcon)
    pixels = icon.pixmap(24, 24).toImage()
    assert not pixels.isNull()
    assert any(pixels.pixelColor(x, y).alpha() for x in range(24) for y in range(24))
    owner = BasePanel.__new__(BasePanel)
    button = owner._b("开始", "play.svg", variant="accent", tooltip="开始测试")
    assert type(button) is PrimaryPushButton
    assert button._icon is get_fluent_icon("play.svg") is FluentIcon.PLAY
    clicks = QSignalSpy(button.clicked)
    button.setEnabled(False)
    button.click()
    assert clicks.count() == 0
    button.setEnabled(True)
    button.click()
    assert clicks.count() == 1
    assert button.focusPolicy() != Qt.FocusPolicy.NoFocus


def test_existing_icons_and_performance_primary_buttons_follow_theme_changes(qt_application):
    from gui.dialogs.performance_launcher import PerformancePage

    BaseStyles.switch_theme("Light")
    icon = get_themed_icon("play.svg")
    light = icon.pixmap(24, 24).toImage()
    page = PerformancePage(device_ip="demo-a")
    try:
        for theme in ("Dark", "Light"):
            BaseStyles.switch_theme(theme)
            qt_application.processEvents()
            assert page.start_btn._icon is FluentIcon.PLAY
            assert page.stop_btn._icon is FluentIcon.CANCEL
            assert isinstance(page.start_btn, PrimaryPushButton)
            if theme == "Dark":
                dark = icon.pixmap(24, 24).toImage()
                assert any(
                    dark.pixelColor(x, y) != light.pixelColor(x, y)
                    for x in range(24) for y in range(24)
                )
    finally:
        page.close()


def test_device_outline_follows_live_theme_in_qicon_and_direct_render(qt_application):
    icon = get_themed_icon("device-mobile.svg")
    assert get_fluent_icon("device-mobile.svg") is DEVICE_ICON
    assert get_fluent_icon("phone-call.svg") is FluentIcon.PHONE
    for theme, channel in (("Light", 0), ("Dark", 255), ("Light", 0)):
        BaseStyles.switch_theme(theme)
        direct = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
        direct.fill(Qt.GlobalColor.transparent)
        painter = QPainter(direct)
        DEVICE_ICON.render(painter, QRectF(0, 0, 32, 32))
        painter.end()
        for rendered in (icon.pixmap(32, 32).toImage(), direct):
            solid = [rendered.pixelColor(x, y) for x in range(32) for y in range(32)
                     if rendered.pixelColor(x, y).alpha() > 240]
            assert solid
            assert all(pixel.red() == pixel.green() == pixel.blue() == channel for pixel in solid)
        assert icon.pixmap(32, 32).toImage() != FluentIcon.PHONE.qicon().pixmap(32, 32).toImage()
    colored = DEVICE_ICON.icon(color=QColor("#0078d4")).pixmap(32, 32).toImage()
    assert any(colored.pixelColor(x, y) == QColor("#0078d4")
               for x in range(32) for y in range(32))
