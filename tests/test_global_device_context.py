"""全局多选、稳定会话及设备功能迁移的可观察契约。"""

import sys
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ComboBox, PushButton
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceConnectionForm, DeviceContextBar, DevicePicker
from models.device_store import DeviceStore
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame


@pytest.fixture
def frame(monkeypatch):
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda devices: [])
    window = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("test", QSize(1600, 1100)))
    )
    window._on_nav_requested("apps")
    yield window
    if isValid(window):
        window._unbind_window_screen()
        window._close_ready = True
        window.close()


def test_picker_updates_two_targets_once_and_refresh_does_not_emit(qt_application):
    picker = DevicePicker()
    spy = QSignalSpy(picker.selection_requested)
    picker.set_context(["demo-a"], ["demo-a", "demo-b"])
    assert spy.count() == 0
    picker.device_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert spy.count() == 1
    assert spy.at(0)[0] == ["demo-a", "demo-b"]
    picker.set_context(["demo-a", "demo-b"], ["demo-a", "demo-b"])
    assert spy.count() == 1
    picker.clear_button.click()
    assert spy.at(1)[0] == []
    picker.select_all_button.click()
    assert spy.at(2)[0] == ["demo-a", "demo-b"]


def test_current_package_result_cannot_overwrite_edited_input(frame, qt_application):
    frame._on_devices_updated(["demo-a"])
    frame.left_panel._devices_tab.set_selected_devices(["demo-a"])
    apps = frame.left_panel._apps_tab
    apps.program_edit.setText("example.before")
    apps.btn_get_program.click()
    frame.adb_controller.get_current_package.assert_called_once_with(["demo-a"])
    assert not apps.btn_get_program.isEnabled()
    apps.program_edit.setText("example.manual")
    frame._on_current_package_received("demo-a", "example.late")
    qt_application.processEvents()
    assert apps.package_text == "example.manual"
    assert apps.btn_get_program.isEnabled()


def test_current_package_result_keeps_request_target_and_failure_recovers(frame, qt_application):
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame.left_panel._devices_tab.set_selected_devices(["demo-a"])
    apps = frame.left_panel._apps_tab
    apps.btn_get_program.click()
    frame.left_panel._devices_tab.set_selected_devices(["demo-b"])
    frame._on_current_package_received("demo-a", "example.old")
    assert apps.package_text != "example.old"
    apps.btn_get_program.click()
    frame._on_operation_completed("get_package", False, "No foreground package")
    assert apps.btn_get_program.isEnabled()
    apps.btn_get_program.click()
    frame._on_current_package_received("demo-b", "example.current")
    assert apps.package_text == "example.current"


def test_package_query_survives_metadata_refresh_but_not_discovery_failure(frame, qt_application):
    frame._on_devices_updated(["demo-a"])
    frame.left_panel._devices_tab.set_selected_devices(["demo-a"])
    apps = frame.left_panel._apps_tab
    apps.btn_get_program.click()
    frame._on_devices_updated(["demo-a"])
    frame._on_current_package_received("demo-a", "example.valid")
    assert apps.package_text == "example.valid"
    apps.btn_get_program.click()
    frame.left_panel.set_device_discovery_state("unavailable")
    assert not apps.btn_get_program.isEnabled()
    frame.left_panel.set_device_discovery_state("ready")
    frame._on_current_package_received("demo-a", "example.stale")
    assert apps.package_text == "example.valid"
    assert apps.btn_get_program.isEnabled()


def test_device_metadata_updates_visible_hub_without_persistence(frame, qt_application):
    frame._on_devices_updated(["demo-a"])
    frame._on_device_info_updated("demo-a", {
        "Brand": "Example", "Model": "Phone", "SDK Version": "35",
        "CPU Architecture": "arm64-v8a", "Serial Number": "private-test-value",
    })
    assert frame._device_metadata["demo-a"]["SDK Version"] == "35"
    assert "Serial Number" not in frame._device_metadata["demo-a"]
    card = frame._device_hub.device_cards[0]
    assert "Phone" in card.name_label.text()
    frame._on_devices_updated([])
    frame._on_device_info_updated("demo-a", {"Model": "Late"})
    assert "demo-a" not in frame._device_metadata


def test_overview_shortcut_rechecks_selected_device_at_main_window(frame, qt_application):
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._open_workspace_feature = Mock()
    frame._device_hub.device_action_requested.emit("devices", "files", "demo-a")
    frame._open_workspace_feature.assert_not_called()
    frame.left_panel._devices_tab.set_selected_devices(["demo-a", "demo-b"])
    frame._device_hub.device_action_requested.emit("devices", "files", "demo-b")
    frame._open_workspace_feature.assert_called_once_with("devices", "files", device_id="demo-b")
    assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    frame._open_workspace_feature.reset_mock()
    frame.left_panel._devices_tab.set_selected_devices(["demo-a"])
    frame._device_hub.device_action_requested.emit("devices", "files", "demo-b")
    frame._open_workspace_feature.assert_not_called()
    frame.left_panel.set_device_discovery_state("scanning")
    frame._device_hub.device_action_requested.emit("devices", "files", "demo-a")
    frame._open_workspace_feature.assert_not_called()


def test_overview_metrics_refresh_without_stale_battery_values(frame, qt_application):
    frame._on_devices_updated(["demo-a"])
    frame._on_device_info_updated("demo-a", {
        "Model": "Example", "Battery Level": "84%", "Total Memory": "8.0 GiB",
        "Resolution": "1080 × 2400", "Storage Available": "64.0 GiB",
    })
    metadata = frame._device_metadata["demo-a"]
    assert metadata["Battery Level"] == "84%" and metadata["Total Memory"] == "8.0 GiB"
    frame._on_device_info_updated("demo-a", {"Model": "Example"})
    assert frame._device_metadata["demo-a"] == {"Model": "Example"}


def test_connection_history_uses_target_and_rejects_invalid_input(qt_application):
    form = DeviceConnectionForm([("示例设备 · 无线", "192.0.2.10:5555")])
    spy = QSignalSpy(form.connect_requested)
    form.address.setCurrentIndex(0)
    assert form.address.currentText() == "192.0.2.10:5555"
    form.connect_button.click()
    assert spy.at(0)[0] == "192.0.2.10:5555"
    form.address.setText("192.0.2.10; unexpected")
    form.connect_button.click()
    assert spy.count() == 1
    assert not form.error_label.isHidden()


def test_device_workflows_keep_multiselect_bar_outside_scrolling_content(frame, qt_application):
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    for route in ("apps", "system", "tasks"):
        frame._on_nav_requested(route)
        qt_application.processEvents()
        bar = frame._global_device_bar
        assert bar.isVisible()
        assert bar.targets_button.isVisible()
        assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
        assert bar.geometry().bottom() < frame.stackedWidget.geometry().top()
        assert frame.left_panel.device_widget.isHidden()
    for route in ("settings", "devices", "home"):
        frame._on_nav_requested(route)
        qt_application.processEvents()
        assert frame._global_device_bar.isHidden()
        assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    frame._on_nav_requested("settings")
    assert frame._settings_page.restart_adb_card.isVisible()


def test_device_overview_connects_and_refreshes_without_top_bar(frame, qt_application):
    frame._on_nav_requested("devices")
    frame.show()
    frame._on_devices_updated(["demo-a"])
    qt_application.processEvents()
    hub = frame._device_hub
    assert frame._global_device_bar.isHidden()
    assert hub.connect_button.isVisible() and hub.refresh_button.isVisible()
    host = frame._workspace_feature_hosts["devices"]
    assert host.session_badge.isHidden()
    refresh = QSignalSpy(hub.refresh_requested)
    hub.refresh_button.click()
    assert refresh.count() == 1
    assert not hub.refresh_button.isEnabled()
    assert not hub.connect_button.isEnabled()
    frame._on_devices_updated(["demo-a"])
    qt_application.processEvents()
    assert hub.connect_button.isEnabled()
    hub.connect_button.click()
    QTest.qWait(230)
    form = frame._global_device_bar.findChild(DeviceConnectionForm)
    assert form is not None and form.isVisible()
    assert form.mapToGlobal(QPoint()).y() >= hub.connect_button.mapToGlobal(
        QPoint(0, hub.connect_button.height())
    ).y()
    frame._on_nav_requested("settings")
    qt_application.processEvents()
    assert not isValid(form) or not form.isVisible()


def test_device_bar_returns_for_feature_in_same_host_and_hides_on_back(frame, qt_application):
    frame.show()
    frame._on_nav_requested("devices")
    qt_application.processEvents()
    overview_top = frame.stackedWidget.geometry().top()
    assert frame._global_device_bar.isHidden()
    frame._open_workspace_feature("devices", "files")
    qt_application.processEvents()
    assert frame._global_device_bar.isVisible()
    assert frame.stackedWidget.geometry().top() > overview_top
    frame._on_nav_requested("devices")
    qt_application.processEvents()
    assert frame._global_device_bar.isHidden()
    assert frame.stackedWidget.geometry().top() == overview_top


def test_popup_multiselect_round_trip_keeps_clicked_items_alive(frame, qt_application):
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker
    assert picker is not None
    item = picker.device_list.item(0)
    item.setCheckState(Qt.CheckState.Checked)
    assert frame.left_panel.selected_devices == ["demo-a"]
    assert picker.device_list.item(0) is item
    picker.select_all_button.click()
    assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    assert picker.device_list.item(0) is item
    picker.clear_button.click()
    assert frame.left_panel.selected_devices == []


def test_connection_popup_forwards_only_validated_target(frame, qt_application):
    calls = []
    frame.left_panel.signals.connect_requested.connect(calls.append)
    frame.show()
    frame._show_global_connection()
    form = frame._global_device_bar.findChild(DeviceConnectionForm)
    assert form is not None
    form.address.setText("192.0.2.10:5555")
    form.connect_button.click()
    assert calls == ["192.0.2.10:5555"]


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_top_device_popups_open_below_their_anchor(frame, qt_application, kind):
    frame.move(100, 0)
    frame.show()
    frame.move(100, 0)
    frame._on_devices_updated(["demo-a", "demo-b"])
    bar = frame._global_device_bar
    if kind == "picker":
        bar.open_picker()
        view = bar._picker
        anchor = bar.targets_button
    else:
        frame._show_global_connection()
        view = bar.findChild(DeviceConnectionForm)
        anchor = bar.connect_button
    QTest.qWait(230)
    assert view is not None and view.isVisible()
    anchor_bottom = anchor.mapToGlobal(QPoint(0, anchor.height())).y()
    assert view.mapToGlobal(QPoint()).y() >= anchor_bottom
    if qt_application.platformName() == "windows":
        assert frame.screen().availableGeometry().contains(
            QRect(view.mapToGlobal(QPoint()), view.size())
        )


@pytest.mark.parametrize("font_size", [12, 22])
def test_device_popups_follow_fonts_and_compact_row_count(
    qt_application, monkeypatch, font_size
):
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    picker = DevicePicker()
    connection = DeviceConnectionForm([])
    picker.set_context(["demo-a"], ["demo-a", "demo-b"])
    for widget in (
        picker.description,
        picker.device_list,
        picker.select_all_button,
        connection.address,
    ):
        assert widget.font().pointSize() == font_size
    assert connection.address.minimumHeight() >= connection.address.fontMetrics().height() + 16
    for listing in (picker.device_list,):
        row_height = listing.item(0).sizeHint().height()
        assert row_height >= listing.fontMetrics().height() + 18
        assert listing.height() == row_height * 2 + 8


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_main_window_device_bar_surface_tracks_theme_switch(frame, qt_application, theme):
    """从整窗取像素，防止原生窗口继承旧调色板导致白条或白色按钮。"""
    frame.show()
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    QTest.qWait(200)
    BaseStyles.switch_theme(theme)
    QTest.qWait(200)
    bar = frame._global_device_bar
    background = QColor(BaseStyles.color("WINDOW_BG"))
    assert bar.palette().color(QPalette.ColorRole.Window) == background
    rendered = frame.grab().toImage()
    point = bar.mapTo(frame, QPoint(2, 2))
    scale = rendered.devicePixelRatio()
    assert rendered.pixelColor(round(point.x() * scale), round(point.y() * scale)) == background
    button = bar.targets_button
    point = button.mapTo(frame, QPoint(10, button.height() - 5))
    button_color = rendered.pixelColor(round(point.x() * scale), round(point.y() * scale))
    text_color = button.palette().color(QPalette.ColorRole.ButtonText)
    assert abs(button_color.lightness() - text_color.lightness()) >= 100


def test_picker_row_and_checkbox_clicks_each_toggle_once(qt_application):
    picker = DevicePicker()
    picker.resize(400, 250)
    picker.set_context([], ["demo-a"])
    picker.show()
    qt_application.processEvents()
    spy = QSignalSpy(picker.selection_requested)
    item = picker.device_list.item(0)
    rect = picker.device_list.visualItemRect(item)
    QTest.mouseClick(picker.device_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert spy.count() == 1 and spy.at(0)[0] == ["demo-a"]
    QTest.mouseClick(
        picker.device_list.viewport(), Qt.MouseButton.LeftButton,
        pos=QPoint(rect.left() + 12, rect.center().y()),
    )
    assert spy.count() == 2 and spy.at(1)[0] == []
    picker.device_list.setCurrentItem(item)
    picker.device_list.setFocus()
    QTest.keyClick(picker.device_list, Qt.Key.Key_Space)
    assert spy.count() == 3 and spy.at(2)[0] == ["demo-a"]


def test_connection_popup_repeated_open_preserves_pending_input(frame, qt_application):
    frame.show()
    bar = frame._global_device_bar
    bar.open_connection([])
    first = bar.findChild(DeviceConnectionForm)
    first.address.setText("192.0.2.10:5555")
    bar.open_connection([])
    forms = bar.findChildren(DeviceConnectionForm)
    assert forms == [first]
    assert first.address.currentText() == "192.0.2.10:5555"
    first.parentWidget().close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    bar.open_connection([])
    assert bar.findChild(DeviceConnectionForm) is not first


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("width", [500, 1440])
def test_device_bar_groups_fit_real_window_and_wide_session_shares_row(
    frame, qt_application, monkeypatch, width, font_size
):
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    host = frame._workspace_feature_hosts["apps"]
    host.register_feature("probe", "测试会话", "", lambda _key: QWidget())
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    frame._open_workspace_feature("apps", "probe")
    frame._choose_global_session("demo-a")
    frame._screen_adapter.screen.available_size = QSize(width, 1100)
    frame.show()
    bar = frame._global_device_bar
    bar._apply_fonts()
    frame.resize(width, 900)
    QTest.qWait(300)
    assert frame.width() == width
    for control in (bar.targets_button, bar.status_label, bar.connect_button,
                    bar.refresh_button, bar.more_button, bar.session_combo, bar.close_button):
        assert control.isVisibleTo(frame)
        bounds = QRect(control.mapTo(bar, QPoint()), control.size())
        assert bar.rect().contains(bounds), (control.accessibleName(), bounds, bar.rect())
        assert control.height() >= control.fontMetrics().height()
    if width == 1440 and font_size == 12:
        assert bar.target_row.geometry().center().y() == bar.session_row.geometry().center().y()
        assert (
            bar.connect_button.mapTo(bar, QPoint()).y()
            == bar.targets_button.mapTo(bar, QPoint()).y()
        )


def test_more_menu_keeps_device_actions_and_selection_enablement(qt_application):
    bar = DeviceContextBar()
    bar.set_context([], ["demo-a"], "ready")
    assert not bar.info_button.isEnabled() and not bar.disconnect_button.isEnabled()
    assert not bar.info_action.isEnabled() and not bar.disconnect_action.isEnabled()
    info = QSignalSpy(bar.info_requested)
    disconnect = QSignalSpy(bar.disconnect_requested)
    bar.set_context(["demo-a"], ["demo-a"], "ready")
    assert bar.info_action.isEnabled() and bar.disconnect_action.isEnabled()
    bar.show()
    for row, (button, called) in enumerate(
        ((bar.info_button, info), (bar.disconnect_button, disconnect))
    ):
        assert button.isHidden()
        button.click()
        assert called.count() == 1
        # 菜单行为不依赖隐藏兼容按钮的可用状态或 click 转发。
        button.setEnabled(False)
        QTest.mouseClick(bar.more_button, Qt.MouseButton.LeftButton)
        QTest.qWait(200)
        item = bar._more_menu.view.item(row)
        QTest.mouseClick(
            bar._more_menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=bar._more_menu.view.visualItemRect(item).center(),
        )
        assert called.count() == 2
        assert not bar._more_menu.isVisible()
    bar.set_context([], ["demo-a"], "ready")
    assert not bar.info_action.isEnabled() and not bar.disconnect_action.isEnabled()
    QTest.mouseClick(bar.more_button, Qt.MouseButton.LeftButton)
    QTest.qWait(200)
    for row in range(2):
        item = bar._more_menu.view.item(row)
        QTest.mouseClick(
            bar._more_menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=bar._more_menu.view.visualItemRect(item).center(),
        )
    assert info.count() == 2 and disconnect.count() == 2


@pytest.mark.parametrize("state", ["ready", "scanning", "unavailable", "empty"])
def test_large_font_device_status_remains_visible_in_narrow_bar(
    qt_application, monkeypatch, state
):
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or 22)),
    )
    bar = DeviceContextBar()
    bar.resize(452, 200)
    devices = [] if state == "empty" else ["demo-a", "demo-b"]
    bar.set_context(devices, devices, state)
    bar.show()
    qt_application.processEvents()
    assert bar.width() == 452
    assert bar.status_label.isVisible()
    assert bar.target_row.rect().contains(bar.status_label.geometry())
    assert bar.refresh_button.isEnabled() == (state != "scanning")


def test_large_font_session_bar_wraps_close_action_without_clipping(qt_application, monkeypatch):
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or 22)),
    )
    bar = DeviceContextBar()
    source = ComboBox()
    source.addItem("demo-a", userData="demo-a")
    close = PushButton("关闭应用管理")
    bar.resize(452, 200)
    bar.set_context(["demo-a", "demo-b"], ["demo-a", "demo-b"], "ready")
    bar.set_session_context(source, close)
    bar.show()
    qt_application.processEvents()
    assert bar.close_button.width() >= bar.close_button.sizeHint().width()
    assert (
        bar.session_combo.width()
        >= bar.session_combo.fontMetrics().horizontalAdvance("demo-a") + 48
    )
    assert bar.close_button.geometry().top() > bar.session_combo.geometry().bottom()
    assert bar.close_button.geometry().right() < bar.session_row.width()


def test_session_switch_keeps_batch_targets_and_obeys_running_lock(frame, qt_application):
    host = frame._workspace_feature_hosts["apps"]
    host.register_feature("probe", "测试会话", "", lambda _key: QWidget())
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    frame._open_workspace_feature("apps", "probe")
    qt_application.processEvents()
    bar = frame._global_device_bar
    assert host.current_device_id == ""
    assert bar.session_row.isVisible()
    frame._choose_global_session("demo-a")
    assert host.current_device_id == "demo-a"
    first = host.registry.current_key
    frame._choose_global_session("demo-b")
    assert host.current_device_id == "demo-b"
    assert host.registry.get(first) is not None
    assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    host.set_device_selection_locked("probe", True, "运行中")
    assert not bar.session_combo.isEnabled()
    frame._choose_global_session("demo-a")
    assert host.current_device_id == "demo-b"
    host.set_device_selection_locked("probe", False)
    frame._choose_global_session("demo-a")
    assert host.registry.current_key == first


@pytest.mark.parametrize(
    "section, old, new",
    [
        ("devices", "remote-control", "remote"),
        ("apps", "packages", "manager"),
        ("apps", "diagnostics", "overview"),
        ("system", "settings", "overview"),
        ("system", "device", "overview"),
    ],
)
def test_legacy_routes_resolve_without_duplicate_navigation(frame, section, old, new):
    host = frame._workspace_feature_hosts[section]
    assert host.has_feature(old)
    assert old not in [item.feature for item in host.navigation_items()]
    assert frame._open_workspace_feature(section, old)
    assert host.current_feature == new


def test_queued_window_theme_refresh_is_cancelled_with_window(frame, qt_application):
    callback = Mock()
    frame._refresh_window_chrome_theme = callback
    frame.show()
    assert callback.call_count == 1
    frame._unbind_window_screen()
    frame.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    assert callback.call_count == 1


def test_window_destruction_releases_hidden_device_coordinator(
    frame, qt_application, monkeypatch
):
    """保留 Python 引用时，隐藏协调器也必须随主窗销毁并断开全局样式连接。"""

    coordinator = frame.left_panel
    destroyed = QSignalSpy(coordinator.destroyed)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    frame._unbind_window_screen()
    frame.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    try:
        BaseStyles.theme_changed.emit(BaseStyles.current_theme())
        BaseStyles.fonts_changed.emit(BaseStyles.current_font_config())
        assert destroyed.count() == 1
        assert not isValid(coordinator)
        assert errors == []
    finally:
        if isValid(coordinator):
            coordinator.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
