"""验证移除重复入口后的首页、同页运行记录和原生 Fluent 按钮交互。"""

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
from tests.ui_geometry_helpers import wait_until


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
        if route in ("devices", "settings"):
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


def test_runtime_records_belong_to_task_center_and_survive_collapsing(frame, qt_application):
    assert "logsPage" not in frame.navigationInterface.panel.items
    assert not hasattr(frame, "_logs_page")
    frame.log_panel._append_log("ERROR", "示例操作失败，请重试")
    frame._on_nav_requested("tasks")
    task_page = frame._task_page
    records = task_page.runtime_records
    assert records is not None
    assert records.content is frame.log_panel
    assert task_page.isAncestorOf(frame.log_panel)
    assert frame.log_panel.isHidden()
    task_page.show_runtime_records()
    wait_until(qt_application, lambda: "示例操作失败" in frame.log_panel.text_output.toPlainText())
    assert frame.log_panel.isVisible()
    records.toggle_button.click()
    frame._on_nav_requested("home")
    frame._on_nav_requested("tasks")
    task_page.show_runtime_records()
    assert "示例操作失败" in frame.log_panel.text_output.toPlainText()
    frame.log_panel.logClearButton.click()
    assert frame.log_panel.text_output.toPlainText() == ""


def test_device_information_opens_the_runtime_records_destination(frame):
    frame._on_nav_requested("devices")
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    frame._global_device_bar.info_requested.emit()
    assert frame.stackedWidget.currentWidget() is frame._tasks_page
    assert frame.log_panel.isVisible()
    frame.adb_controller.get_device_info.assert_called_once_with(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit([])
    frame._on_nav_requested("devices")
    frame._show_selected_device_info()
    assert frame.stackedWidget.currentWidget() is frame._devices_page
    assert frame.adb_controller.get_device_info.call_count == 1


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
