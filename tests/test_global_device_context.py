"""全局多选、稳定会话及设备功能迁移的可观察契约。"""

import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEvent,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QAbstractButton, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, ComboBox, PushButton, SettingCard
from shiboken6 import isValid

from gui.pages.device_hub import DeviceHubPage
from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceConnectionForm, DeviceContextBar, DevicePicker
from models.device_store import DeviceStore
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame
from tests.test_navigation_rendering import _native_content_color
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)


@pytest.fixture
def frame(monkeypatch, qt_application):
    from tests.test_device_connection import PairingDouble

    class ConnectedPairingDouble(PairingDouble):
        connected = Signal(object)

    def create_pairing(_supervisor, parent):
        pairing = ConnectedPairingDouble()
        pairing.setParent(parent)
        return pairing

    monkeypatch.setattr("adblab.presentation.qt_adb_pairing.QtAdbPairing", create_pairing)
    monkeypatch.setattr("gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", Mock())
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda devices: [])
    window = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("test", QSize(1600, 1100)))
    )
    window._on_nav_requested("apps")
    yield window
    if isValid(window):
        if window._connection_panel is not None:
            window._connection_panel.prepare_shutdown()
            window._connection_panel.collapse()
        qt_application.processEvents()
        window._unbind_window_screen()
        window._close_ready = True
        window.close()


class _ClosableSessionPage(QWidget):
    dispose_ready = Signal(object)

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.dispose_reasons = []
        self.dispose_immediately = True

    def request_dispose(self, reason):
        self.dispose_reasons.append(reason)
        return self.dispose_immediately


def test_public_device_snapshot_preserves_admission_and_is_immutable(frame):
    """设备真源继续由协调器拥有，快照不能被页面持有后改写。"""
    from dataclasses import FrozenInstanceError

    panel = frame.left_panel
    frame._on_devices_updated(["demo-a", "demo-b"])
    panel.set_selected_devices(["demo-a"])
    snapshot = panel.device_context_snapshot()
    assert snapshot.selected_devices == ("demo-a",)
    assert snapshot.connected_devices == ("demo-a", "demo-b")
    assert snapshot.discovery_state == "ready"
    with pytest.raises(FrozenInstanceError):
        snapshot.discovery_state = "empty"

    panel.set_selected_devices(["demo-b"])
    assert snapshot.selected_devices == ("demo-a",)
    assert panel.device_context_snapshot().selected_devices == ("demo-b",)
    panel.set_device_discovery_state("scanning")
    assert panel.device_context_snapshot().selected_devices == ("demo-b",)
    assert frame._remote_operation_devices() == []
    panel.set_device_discovery_state("unavailable")
    unavailable = panel.device_context_snapshot()
    assert unavailable.selected_devices == ()
    assert unavailable.connected_devices == ("demo-a", "demo-b")


def test_connection_history_is_a_value_snapshot(frame):
    panel = frame.left_panel
    entry = panel._devices_tab.ip_entry
    entry.clear()
    entry.addItem("测试连接", userData="192.0.2.1:5555")
    history = panel.connection_history()
    assert history == [("测试连接", "192.0.2.1:5555")]
    history.clear()
    assert panel.connection_history() == [("测试连接", "192.0.2.1:5555")]


def test_public_overview_transfer_preserves_widgets_and_controller_ownership(qt_application):
    from gui.panels.side_panel import SidePanel

    panel = SidePanel()
    original_scroll = panel._tab_scroll_areas[0]
    original_content = original_scroll.widget()
    try:
        scroll, content = panel.take_overview_content(0)
        assert scroll is original_scroll
        assert content is original_content
        assert scroll.widget() is None
        assert panel.app_panel.parent() is panel
        assert panel.system_panel is None
        assert panel.remote_panel is None
        scroll.setWidget(content)
        assert content.parent() is scroll.viewport()
    finally:
        panel.shutdown()
        panel.close()


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


def test_single_picker_switches_one_target_once_and_allows_clear(qt_application):
    picker = DevicePicker()
    picker.set_selection_mode(single=True)
    picker.set_context(["demo-a"], ["demo-a", "demo-b"])
    spy = QSignalSpy(picker.selection_requested)
    picker.device_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert spy.count() == 1
    assert spy.at(0)[0] == ["demo-b"]
    assert picker.device_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert picker.select_all_button.isHidden()
    picker.clear_button.click()
    assert spy.count() == 2 and spy.at(1)[0] == []


@pytest.mark.parametrize("section,feature", [
    ("apps", "manager"), ("devices", "files"), ("system", "logcat"),
])
def test_single_feature_picker_selects_and_activates_same_device(
    frame, qt_application, section, feature,
):
    host = frame._workspace_feature_hosts[section]
    host._definitions[feature] = replace(host._definitions[feature], factory=lambda _key: QWidget())
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._open_workspace_feature(section, feature)
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker
    picker.device_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert host.current_device_id == "demo-a"
    first_key = host.registry.current_key
    picker.device_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert frame.left_panel.selected_devices == ["demo-b"]
    assert host.current_device_id == "demo-b"
    assert host.registry.get(first_key) is not None
    assert picker.select_all_button.isHidden()
    page = host.stack.currentWidget()
    picker.clear_button.click()
    assert frame.left_panel.selected_devices == []
    assert host.stack.currentWidget() is page


def test_performance_picker_keeps_multiple_targets_without_second_selector(frame, qt_application):
    host = frame._workspace_feature_hosts["system"]
    host._definitions["performance"] = replace(
        host._definitions["performance"], factory=lambda _key: QWidget(),
    )
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._open_workspace_feature("system", "performance")
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker
    picker.select_all_button.click()
    assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    assert host.current_device_id in {"demo-a", "demo-b"}
    assert picker.session_box.isHidden()


def test_remote_picker_updates_all_targets_and_keeps_empty_page(frame, qt_application):
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._open_workspace_feature("devices", "remote")
    host = frame._workspace_feature_hosts["devices"]
    page = host.stack.currentWidget()
    remote = frame.left_panel._scrcpy_tab
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker
    assert remote.selected_devices == []
    assert not picker.select_all_button.isHidden()
    picker.select_all_button.click()
    assert remote.selected_devices == ["demo-a", "demo-b"]
    picker.device_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert remote.selected_devices == ["demo-b"]
    picker.clear_button.click()
    assert remote.selected_devices == []
    assert host.stack.currentWidget() is page


@pytest.mark.parametrize("section,feature", [
    ("apps", "manager"), ("devices", "files"), ("system", "logcat"),
])
def test_picker_closes_only_current_session_and_preserves_device_context(
    frame, qt_application, section, feature,
):
    host = frame._workspace_feature_hosts[section]
    host._definitions[feature] = replace(
        host._definitions[feature], factory=_ClosableSessionPage,
    )
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame.left_panel.set_selected_devices(["demo-a", "demo-b"])
    frame._open_workspace_feature(section, feature, device_id="demo-b")
    retained_key = host.registry.current_key
    retained_page = host.stack.currentWidget()
    frame._open_workspace_feature(section, feature, device_id="demo-a")
    current_key = host.registry.current_key
    current_page = host.stack.currentWidget()
    context = frame.left_panel.device_context_snapshot()
    disconnected = QSignalSpy(frame.left_panel.signals.disconnect_requested)
    bar = frame._global_device_bar
    assert [button for button in bar.findChildren(QAbstractButton)
            if button.isVisibleTo(frame)] == [bar.targets_button]
    bar.open_picker()
    picker = bar._picker
    selection = QSignalSpy(picker.selection_requested)
    assert picker.close_button.isVisible()
    assert picker.close_button.text() == host.close_session_button.text()

    QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)

    assert current_page.dispose_reasons == ["user"]
    assert retained_page.dispose_reasons == []
    assert host.registry.get(current_key) is None
    assert host.registry.get(retained_key) is retained_page
    assert host.current_feature == "overview"
    assert frame.left_panel.device_context_snapshot() == context
    assert selection.count() == disconnected.count() == 0
    assert not isValid(picker) or not picker.isVisible()


def test_screenshot_picker_keeps_clear_results_label(frame, qt_application):
    host = frame._workspace_feature_hosts["apps"]
    host._definitions["media"] = replace(
        host._definitions["media"], factory=_ClosableSessionPage,
    )
    frame.show()
    frame._open_workspace_feature("apps", "media")
    page = host.stack.currentWidget()
    key = host.registry.current_key
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker
    assert picker.close_button.isVisible()
    assert picker.close_button.text() == "清除截图结果"
    assert picker.close_button.accessibleName() == "清除截图结果"

    QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)

    assert page.dispose_reasons == ["user"]
    assert host.registry.get(key) is None
    assert host.current_feature == "overview"
    assert not isValid(picker) or not picker.isVisible()


@pytest.mark.parametrize("section,feature", [
    ("apps", "overview"), ("system", "overview"),
    ("devices", "remote"), ("system", "performance"),
])
def test_picker_has_no_close_action_for_features_without_one(
    frame, qt_application, section, feature,
):
    host = frame._workspace_feature_hosts[section]
    if feature == "performance":
        host._definitions[feature] = replace(
            host._definitions[feature], factory=_ClosableSessionPage,
        )
    frame.show()
    frame._on_devices_updated(["demo-a"])
    frame.left_panel.set_selected_devices(["demo-a"])
    frame._open_workspace_feature(section, feature)
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker
    assert picker.isVisible()
    assert host.close_session_button.isHidden()
    assert not picker.close_button.isVisible()
    assert picker.clear_button.isVisible()


def test_picker_disables_close_until_async_session_disposal_finishes(frame, qt_application):
    host = frame._workspace_feature_hosts["system"]
    host._definitions["logcat"] = replace(
        host._definitions["logcat"], factory=_ClosableSessionPage,
    )
    frame.show()
    frame._on_devices_updated(["demo-a"])
    frame.left_panel.set_selected_devices(["demo-a"])
    frame._open_workspace_feature("system", "logcat")
    page = host.stack.currentWidget()
    page.dispose_immediately = False
    key = host.registry.current_key
    bar = frame._global_device_bar
    bar.open_picker()
    picker = bar._picker

    QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)

    assert page.dispose_reasons == ["user"]
    assert host.registry.is_disposing(key)
    assert host.stack.currentWidget() is host.closing_page
    assert picker.isVisible()
    assert picker.close_button.text() == "正在关闭"
    assert not picker.close_button.isEnabled()
    QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)
    picker.close_session_requested.emit()
    assert page.dispose_reasons == ["user"]
    page.dispose_ready.emit(page)
    assert host.registry.get(key) is None
    assert host.current_feature == "overview"
    assert not isValid(picker) or not picker.isVisible()


@pytest.mark.parametrize("state", ["ready", "empty", "unavailable"])
def test_superseded_manual_refresh_restores_state_and_allows_retry(frame, state):
    panel = frame.left_panel
    frame.adb_controller.signals.device_refresh_superseded.connect.assert_called_once_with(
        panel.on_device_refresh_superseded,
    )
    panel.set_device_discovery_state(state)
    assert panel.request_device_refresh()
    assert panel._device_discovery_state == "scanning"
    assert not panel.request_device_refresh()
    panel.on_device_refresh_superseded()
    assert panel._device_discovery_state == state
    assert panel.request_device_refresh()


def test_superseded_refresh_cannot_replace_new_device_snapshot(frame):
    panel = frame.left_panel
    panel.set_device_discovery_state("empty")
    assert panel.request_device_refresh()
    frame._on_devices_updated(["demo-a"])
    panel.on_device_refresh_superseded()
    assert panel._device_discovery_state == "ready"
    assert panel._connected_device_cache == ["demo-a"]


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


def test_system_shared_host_ports_and_device_private_pid_require_one_target(frame):
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    panel = frame.left_panel._advanced_tab
    panel.fwd_local.setText("8080")
    panel.fwd_remote.setText("80")
    panel.kill_pid_input.setText("1234")
    assert not panel.btn_forward.isEnabled()
    assert not panel.btn_kill_pid.isEnabled()
    assert panel.btn_reverse.isEnabled()
    # 即使直接触发 clicked，也必须重新校验当次目标，不能绕过置灰状态。
    forward = QSignalSpy(frame.left_panel.signals.forward_port_requested)
    kill = QSignalSpy(frame.left_panel.signals.kill_process_requested)
    panel.btn_forward.clicked.emit()
    panel.btn_kill_pid.clicked.emit()
    assert forward.count() == kill.count() == 0
    frame._global_device_bar.selection_requested.emit(["demo-b"])
    assert panel.btn_forward.isEnabled() and panel.btn_kill_pid.isEnabled()
    panel.btn_forward.click()
    panel.btn_kill_pid.click()
    assert forward.at(0)[0] == ["demo-b"]
    assert kill.at(0)[0] == ["demo-b"]


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
    for route in ("apps", "system"):
        frame._on_nav_requested(route)
        qt_application.processEvents()
        bar = frame._global_device_bar
        assert bar.isVisible()
        assert bar.targets_button.isVisible()
        assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
        assert bar.geometry().bottom() < frame.stackedWidget.geometry().top()
        assert frame.left_panel.device_widget.isHidden()
    for route in ("settings", "devices", "home", "tasks"):
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
    panel = frame._connection_panel
    assert panel.isVisible() and not panel.isWindow()
    assert panel.current_page == "qr"
    assert hub.isAncestorOf(panel)
    assert hub.connect_button.isChecked()
    assert frame._adb_pairing.calls == [("qr",)]
    frame._on_nav_requested("settings")
    qt_application.processEvents()
    assert not panel.isVisible() and not panel.is_expanded
    assert not hub.connect_button.isChecked()
    assert frame._adb_pairing.calls[-1] == ("cancel",)


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


def test_connection_panel_forwards_only_validated_target(frame, qt_application):
    calls = []
    frame.left_panel.signals.connect_requested.connect(calls.append)
    frame.show()
    frame._on_devices_updated([])
    frame._on_nav_requested("devices")
    qt_application.processEvents()
    frame._device_hub.connect_button.click()
    panel = frame._connection_panel
    panel.request_page("address")
    frame._adb_pairing.finish()
    form = panel.address_form
    assert form is not None
    form.address.setText("invalid")
    form.connect_button.click()
    assert calls == []
    form.address.setText("192.0.2.10:5555")
    form.connect_button.click()
    assert calls == ["192.0.2.10:5555"]
    assert panel.isHidden() and not frame._device_hub.connect_button.isChecked()


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
        frame._on_nav_requested("devices")
        qt_application.processEvents()
        bar.open_connection([], anchor=frame._device_hub.connect_button)
        view = bar.findChild(DeviceConnectionForm)
        anchor = frame._device_hub.connect_button
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
    # 关闭云母仍保留原生内容层，设备栏必须透出同一层而非重复刷根背景。
    frame.setMicaEffectEnabled(False)
    frame.show()
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    QTest.qWait(200)
    BaseStyles.switch_theme(theme)
    QTest.qWait(200)
    bar = frame._global_device_bar
    assert bar.isVisible()
    assert bar.palette().color(QPalette.ColorRole.Window) == QColor(BaseStyles.color("WINDOW_BG"))
    background = _native_content_color(frame.backgroundColor)
    rendered = frame.grab().toImage()
    point = bar._surface.mapTo(frame, QPoint(2, 2))
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


def test_connection_panel_repeated_toggle_reuses_view_and_waits_for_cleanup(frame, qt_application):
    frame.show()
    frame._on_nav_requested("devices")
    frame._on_devices_updated([])
    qt_application.processEvents()
    button = frame._device_hub.connect_button
    assert button.text() == "连接设备"
    frame._show_global_connection()
    first = frame._connection_panel
    pairing = frame._adb_pairing
    assert button.text() == "收起连接" and button.accessibleName() == "收起连接"
    first.pairing_code.setText("012345")
    frame._show_global_connection()
    assert first.isHidden() and first.pairing_code.text() == ""
    assert not frame._device_hub.connect_button.isChecked()
    assert button.text() == "连接设备"
    assert pairing.calls == [("qr",), ("cancel",)]
    frame._show_global_connection()
    assert frame._connection_panel is first
    assert first.is_expanded and frame._device_hub.connect_button.isChecked()
    assert button.text() == "收起连接"
    assert len([call for call in pairing.calls if call == ("qr",)]) == 1
    pairing.finish()
    qt_application.processEvents()
    assert len([call for call in pairing.calls if call == ("qr",)]) == 1
    frame._show_global_connection()
    frame._show_global_connection()
    assert frame._connection_panel is first and first.is_expanded
    assert len([call for call in pairing.calls if call == ("qr",)]) == 2


@pytest.mark.parametrize("route", ["home", "apps", "tasks", "settings", "files"])
def test_connection_panel_leaving_overview_cancels_and_never_reopens(
    frame, qt_application, route,
):
    frame.show()
    frame._on_nav_requested("devices")
    frame._on_devices_updated([])
    qt_application.processEvents()
    assert frame._device_hub.connect_button.isEnabled()
    frame._device_hub.connect_button.click()
    panel = frame._connection_panel
    pairing = frame._adb_pairing
    if route == "files":
        frame._open_workspace_feature("devices", "files")
    else:
        frame._on_nav_requested(route)
    qt_application.processEvents()
    assert panel.isHidden() and not panel.is_expanded
    assert pairing.calls == [("qr",), ("cancel",)]
    frame._show_global_connection()
    pairing.finish()
    frame._on_nav_requested("devices")
    qt_application.processEvents()
    assert panel.isHidden() and not frame._device_hub.connect_button.isChecked()
    assert frame._device_hub.connect_button.text() == "连接设备"
    assert pairing.calls == [("qr",), ("cancel",)]


def test_connection_panel_collapsed_restores_cards_and_creates_no_window(frame, qt_application):
    frame.show()
    frame._on_nav_requested("devices")
    frame._on_devices_updated(["demo-a"])
    hub = frame._device_hub
    wait_for_stable_geometry(qt_application, (hub, hub.toolbar, hub.cards_container))
    collapsed_top = hub.cards_container.y()
    visible_windows = {widget for widget in qt_application.topLevelWidgets() if widget.isVisible()}
    assert frame._adb_pairing is None
    hub.connect_button.click()
    panel = frame._connection_panel
    wait_for_stable_geometry(qt_application, (hub, panel, hub.cards_container))
    assert hub.cards_container.y() > collapsed_top
    assert hub.toolbar.geometry().bottom() < panel.y()
    assert panel.geometry().bottom() < hub.cards_container.y()
    assert {widget for widget in qt_application.topLevelWidgets() if widget.isVisible()} == (
        visible_windows
    )
    hub.connect_button.click()
    wait_for_stable_geometry(qt_application, (hub, hub.toolbar, hub.cards_container))
    assert hub.cards_container.y() == collapsed_top
    assert panel.isHidden()


def test_connection_panel_pages_align_with_device_card_content(frame, qt_application):
    frame.show()
    frame._on_nav_requested("devices")
    frame._on_devices_updated(["demo-a"])
    hub = frame._device_hub
    hub.connect_button.click()
    panel = frame._connection_panel
    pairing = frame._adb_pairing
    pairing.finish("Idle", "")
    card = hub._cards["demo-a"]
    for page, content in (
        ("qr", panel.qr_text),
        ("manual", panel.pairing_address),
        ("address", panel.address_form.address),
    ):
        panel.request_page(page)
        wait_for_stable_geometry(qt_application, (panel, content, card))
        left = card.selection.mapTo(hub, QPoint()).x()
        assert content.mapTo(hub, QPoint()).x() == left
        assert panel.stack.currentWidget().mapTo(hub, QPoint()).x() == left
        assert (
            panel.stack.currentWidget().mapTo(hub, QPoint()).x()
            + panel.stack.currentWidget().width()
            <= card.x() + card.width() - (left - card.x())
        )


def test_pairing_invalidation_precedes_environment_recheck_only(frame):
    calls = []
    frame._adb_pairing = SimpleNamespace(invalidate=lambda reason: calls.append(reason))
    frame._adb_environment = SimpleNamespace(
        recheck=lambda: calls.append("recheck"),
        set_selection_mode=lambda mode: calls.append(mode),
        set_native_only=lambda enabled: calls.append(enabled),
    )
    frame.recheck_adb_environment()
    assert calls == ["environment_recheck", "recheck"]
    frame.set_adb_selection_mode("native")
    frame.set_adb_native_only(True)
    assert calls == ["environment_recheck", "recheck", "native", True]
    frame._adb_pairing = None
    frame._adb_environment = None


def test_device_management_actions_are_routed_from_overview(frame, qt_application, monkeypatch):
    """概览入口复用当前多选和原信号，功能页顶部只承担目标及会话选择。"""
    refresh = Mock()
    monkeypatch.setattr(frame.left_panel, "request_device_refresh", refresh)
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._on_nav_requested("devices")
    qt_application.processEvents()
    hub = frame._device_hub
    assert hub.isVisibleTo(frame)
    assert not frame._global_device_bar.isVisibleTo(frame)
    hub.refresh_button.click()
    refresh.assert_called_once_with()
    disconnected = QSignalSpy(frame.left_panel.signals.disconnect_requested)
    frame.left_panel._devices_tab.set_selected_devices(["demo-a"])
    frame.left_panel._devices_tab.set_selected_devices(["demo-b"])
    hub.disconnect_button.click()
    assert disconnected.count() == 1
    assert disconnected.at(0)[0] == ["demo-b"]
    frame._on_nav_requested("apps")
    qt_application.processEvents()
    bar = frame._global_device_bar
    assert bar.isVisibleTo(frame)
    assert [button for button in bar.findChildren(QAbstractButton)
            if button.isVisibleTo(frame)] == [bar.targets_button]
    frame._show_global_connection()
    assert bar._connection is None
    assert frame._connection_panel is None and frame._adb_pairing is None


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("width", [500, 1440])
def test_device_bar_and_picker_close_fit_real_window(
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
    for control in (bar.targets_button,):
        assert control.isVisibleTo(frame)
        bounds = QRect(control.mapTo(bar, QPoint()), control.size())
        assert bar.rect().contains(bounds), (control.accessibleName(), bounds, bar.rect())
        assert control.height() >= control.fontMetrics().height()
    assert bar.target_row.isVisible()
    assert [button for button in bar.findChildren(QAbstractButton)
            if button.isVisibleTo(frame)] == [bar.targets_button]
    assert bar.session_hint.isHidden()
    bar.open_picker()
    picker = bar._picker
    qt_application.processEvents()
    for control in (picker.device_list, picker.clear_button, picker.close_button):
        assert control.isVisible()
        assert picker.rect().contains(mapped_rect(control, picker))
        assert control.height() >= control.fontMetrics().height()
    assert mapped_rect(picker.close_button, picker).top() > mapped_rect(
        picker.clear_button, picker,
    ).bottom()
    assert picker.session_box.isHidden()
    assert picker.select_all_button.isHidden()


def test_overview_disconnect_button_keeps_selection_enablement(qt_application):
    bar = DeviceHubPage()
    bar.set_device_context([], ["demo-a"], "ready")
    assert not bar.disconnect_button.isEnabled()
    assert bar.disconnect_button.toolTip() == "断开已勾选设备的 ADB 连接"
    assert bar.disconnect_button.accessibleName() == "断开已勾选设备的 ADB 连接"
    disconnect = QSignalSpy(bar.disconnect_requested)
    bar.set_device_context(["demo-a"], ["demo-a"], "ready")
    assert bar.disconnect_button.isEnabled()
    bar.show()
    QTest.mouseClick(bar.disconnect_button, Qt.MouseButton.LeftButton)
    assert disconnect.count() == 1
    bar.set_device_context([], ["demo-a"], "ready")
    assert not bar.disconnect_button.isEnabled()
    QTest.mouseClick(bar.disconnect_button, Qt.MouseButton.LeftButton)
    assert disconnect.count() == 1


def test_device_bar_status_color_tracks_state_and_theme(qt_application):
    bar = DeviceContextBar()
    bar.show()
    for state, caption, color_key in (
        ("ready", "在线 1 台", "LOG_SUCCESS"),
        ("scanning", "正在扫描", "LOG_INFO"),
        ("unavailable", "ADB 暂不可用", "LOG_WARNING"),
        ("empty", "未发现设备", "TEXT_SECONDARY"),
    ):
        devices = [] if state == "empty" else ["demo-a"]
        bar.set_context(devices, devices, state)
        for theme in ("Light", "Dark"):
            BaseStyles.switch_theme(theme)
            qt_application.processEvents()
            assert bar.status_label.text() == caption
            assert bar.status_label.palette().color(QPalette.ColorRole.WindowText) == QColor(
                BaseStyles.color_for(theme, color_key)
            )


@pytest.mark.parametrize("state", ["ready", "scanning", "unavailable", "empty"])
def test_large_font_device_status_remains_accessible_in_narrow_bar(
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
    assert bar.status_label.text() in bar.targets_button.accessibleDescription()
    assert bar.rect().contains(mapped_rect(bar.targets_button, bar))


def test_large_font_session_close_remains_readable_in_picker(qt_application, monkeypatch):
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
    assert bar.targets_button.isVisible()
    assert bar.rect().contains(mapped_rect(bar.targets_button, bar))
    bar.open_picker()
    picker = bar._picker
    qt_application.processEvents()
    assert picker.session_combo.currentData() == "demo-a"
    assert picker.close_button.isVisible()
    assert picker.close_button.width() >= picker.close_button.sizeHint().width()
    assert picker.close_button.height() >= picker.close_button.fontMetrics().height() + 16
    assert picker.close_button.font().pointSize() == 22
    assert picker.close_button.accessibleName() == "关闭应用管理"
    assert picker.close_button.text() == "关闭应用管理"
    assert picker.rect().contains(mapped_rect(picker.close_button, picker))
    assert mapped_rect(picker.close_button, picker).top() > mapped_rect(
        picker.clear_button, picker,
    ).bottom()


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
    assert bar.targets_button.isVisible()
    bar.open_picker()
    assert bar._picker.session_box.isHidden()
    frame._choose_global_session("demo-a")
    assert host.current_device_id == "demo-a"
    first = host.registry.current_key
    frame._choose_global_session("demo-b")
    assert host.current_device_id == "demo-b"
    assert host.registry.get(first) is not None
    assert frame.left_panel.selected_devices == ["demo-a", "demo-b"]
    host.set_device_selection_locked("probe", True, "运行中")
    assert not bar.session_combo.isEnabled()
    assert not bar._picker.device_list.isEnabled()
    frame._choose_global_session("demo-a")
    assert host.current_device_id == "demo-b"
    host.set_device_selection_locked("probe", False)
    frame._choose_global_session("demo-a")
    assert host.registry.current_key == first


def test_single_list_changes_target_without_losing_cached_page(frame, qt_application):
    host = frame._workspace_feature_hosts["apps"]
    host.register_feature("probe", "测试会话", "", lambda _key: QWidget())
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    bar = frame._global_device_bar
    bar.selection_requested.emit(["demo-b"])
    frame._open_workspace_feature("apps", "probe", device_id="demo-a")
    qt_application.processEvents()
    page = host.stack.currentWidget()
    history = tuple(frame._navigation_history)
    bar.open_picker()
    picker = bar._picker
    item = picker.device_list.item(0)
    assert item.checkState() == Qt.CheckState.Unchecked
    picker.device_list.setCurrentItem(item)
    picker.device_list.setFocus()
    QTest.keyClick(picker.device_list, Qt.Key.Key_Space)
    assert frame.left_panel.selected_devices == ["demo-a"]
    assert item.checkState() == Qt.CheckState.Checked
    QTest.keyClick(picker.device_list, Qt.Key.Key_Space)
    assert frame.left_panel.selected_devices == []
    assert item.checkState() == Qt.CheckState.Unchecked
    assert host.stack.currentWidget() is page
    assert bar.session_combo.currentData() == "demo-a"
    assert tuple(frame._navigation_history) == history
    frame._on_devices_updated(["demo-b"])
    assert picker.device_list.count() == 1
    assert picker.device_list.item(0).data(Qt.ItemDataRole.UserRole) == "demo-b"
    assert host.stack.currentWidget() is page


@pytest.mark.parametrize("section,feature", [
    ("apps", "manager"), ("devices", "files"), ("system", "logcat"),
])
def test_no_device_primary_action_opens_device_management(frame, qt_application, section, feature):
    frame.show()
    frame._on_devices_updated([])
    frame._open_workspace_feature(section, feature)
    qt_application.processEvents()
    host = frame._workspace_feature_hosts[section]
    assert host.stack.currentWidget() is host.no_device_page
    assert host.no_device_page.choose_button.text() == "前往设备概览"
    host.no_device_page.choose_button.click()
    qt_application.processEvents()
    assert frame.stackedWidget.currentWidget() is frame._devices_page
    assert frame._devices_page.current_route.feature == "overview"
    assert frame._device_hub.connect_button.isVisibleTo(frame)
    assert frame._global_device_bar._picker is None


@pytest.mark.parametrize("section,feature", [
    ("devices", "files"), ("devices", "remote"), ("apps", "manager"),
    ("apps", "overview"), ("apps", "media"), ("system", "overview"),
    ("system", "logcat"), ("system", "performance"),
])
@pytest.mark.parametrize("window_width", [860, 1017])
def test_workspace_selection_keeps_visible_page_and_bar_geometry(
    frame, qt_application, monkeypatch, section, feature, window_width
):
    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerPage._load_apps", Mock())
    monkeypatch.setattr("gui.dialogs.file_explorer.FileExplorerPage._refresh", Mock())
    frame._on_devices_updated(["demo-device-01", "demo-b"])
    bar = frame._global_device_bar
    bar.selection_requested.emit(["demo-device-01"])
    frame.show()
    assert frame._open_workspace_feature(section, feature, device_id="demo-device-01")
    host = frame._workspace_feature_hosts[section]
    page = host.stack.currentWidget()
    qt_application.processEvents()
    wait_until(qt_application, lambda: (
        frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
        and frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
    ))
    # 首次显示会恢复窗口尺寸，必须在恢复完成后检查截图对应的实际可用宽度。
    frame.resize(window_width, 900)
    qt_application.processEvents()
    wait_until(qt_application, lambda: (
        frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
    ))
    wait_for_stable_geometry(qt_application, (frame, bar, host, page))
    assert frame.size() == QSize(window_width, 900)
    initial = (bar.height(), mapped_rect(host, frame).top(), host.current_device_id)
    history = tuple(frame._navigation_history)
    for selected in ([], ["demo-b"], ["demo-device-01"]):
        # 其他页面更新共享目标时不重定向已有会话；本页下拉切换另有回归覆盖。
        frame.left_panel._devices_tab.set_selected_devices(selected)
        wait_for_stable_geometry(qt_application, (frame, bar, host, page))
        assert bar.isVisibleTo(frame)
        assert host.stack.currentWidget() is page
        assert (bar.height(), mapped_rect(host, frame).top(), host.current_device_id) == initial
        assert tuple(frame._navigation_history) == history
        if host.feature_requires_device(feature):
            assert mapped_rect(bar.session_combo, bar).top() == (
                mapped_rect(bar.session_target, bar).top()
            )
            assert bar.session_hint.isHidden()
            assert bar.session_combo.currentData() == "demo-device-01"
            assert bar.session_hint.text() == (
                "在线" if "demo-device-01" in selected else "未选为操作目标"
            )
            assert bar.session_hint.text() in bar.session_combo.accessibleDescription()


@pytest.mark.parametrize("route", [
    "homePage", "devicesPage", "filesPage", "remotePage", "appManagerPage", "appsPage",
    "screenshotsPage", "systemPage", "logcatPage", "performancePage", "tasksPage", "settingsPage",
])
def test_page_scrollbars_stay_close_to_content(frame, qt_application, monkeypatch, route):
    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerPage._load_apps", Mock())
    monkeypatch.setattr("gui.dialogs.file_explorer.FileExplorerPage._refresh", Mock())
    frame._on_devices_updated(["demo-a", "demo-b", "demo-c", "demo-d"])
    frame._global_device_bar.selection_requested.emit(["demo-a"])
    frame.show()
    frame.navigationInterface.widget(route).click()
    qt_application.processEvents()
    wait_until(qt_application, lambda: (
        frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
        and frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
    ))
    window_width = 860 if route == "homePage" else 1048
    frame.resize(window_width, 500)
    qt_application.processEvents()
    wait_until(qt_application, lambda: (
        frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
    ))
    page = frame.stackedWidget.currentWidget()
    assert frame.navigationInterface.panel.currentItem() is frame.navigationInterface.widget(route)
    if frame._global_device_bar.isVisibleTo(frame):
        assert frame._global_device_bar.page_title.text() == page.accessibleName()
    wait_for_stable_geometry(qt_application, (frame, page))
    assert frame.size() == QSize(window_width, 500)
    areas = page.findChildren(QScrollArea)
    if isinstance(page, QScrollArea):
        areas.append(page)
    assert areas
    checked = 0
    for area in areas:
        if not area.isVisibleTo(frame):
            continue
        delegate = getattr(area, "delegate", None) or getattr(area, "scrollDelagate", None)
        if delegate is None or not delegate.vScrollBar.isVisibleTo(frame):
            continue
        bar = delegate.vScrollBar
        assert area.viewport().geometry().adjusted(-2, -2, 2, 2).contains(
            mapped_rect(bar, area)
        ), route
        # 阅读留白在正文内部；滚动条与 viewport 对齐，不能拿卡片边缘作外壳边界。
        assert abs(
            mapped_rect(bar, area).right() - area.viewport().geometry().right()
        ) <= 2, route
        cards = [card for card in area.widget().findChildren(QWidget)
                 if isinstance(card, (CardWidget, SettingCard))
                 and card.isVisibleTo(area.widget())]
        anchors = cards or [button for button in area.widget().findChildren(QAbstractButton)
                            if button.isVisibleTo(area.widget())]
        if anchors:
            for anchor in anchors:
                if anchor.height() <= area.viewport().height():
                    assert_scroll_target_reachable(area, anchor)
                    continue
                # 长卡片无需同时装进短窗口，但四角和每个动作都必须能滚动到达。
                rect = anchor.rect()
                corners = (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())
                for corner in corners:
                    position = anchor.mapTo(area.widget(), corner)
                    area.ensureVisible(position.x(), position.y(), 1, 1)
                    qt_application.processEvents()
                    assert area.viewport().rect().contains(anchor.mapTo(area.viewport(), corner))
                for button in anchor.findChildren(QAbstractButton):
                    if button.isVisibleTo(anchor):
                        assert_scroll_target_reachable(area, button)
            checked += 1
    if route in {"homePage", "settingsPage", "appsPage", "systemPage", "performancePage"}:
        assert checked > 0


@pytest.mark.parametrize("route", ["home", "settings"])
def test_page_scrollbar_uses_full_viewport_and_accepts_drag(frame, qt_application, route):
    frame.show()
    frame._on_nav_requested(route)
    page = frame.stackedWidget.currentWidget()
    qt_application.processEvents()
    wait_until(qt_application, lambda: (
        frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
        and frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
    ))
    for width in (1048, 860, 1048, 860):
        frame.resize(width, 500)
        qt_application.processEvents()
        wait_until(qt_application, lambda: (
            frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
        ))
        wait_for_stable_geometry(qt_application, (frame, page, page.viewport()))
        assert frame.size() == QSize(width, 500)
        assert page.viewport().geometry() == page.rect()
        bar = page.scrollDelagate.vScrollBar
        assert bar.isVisibleTo(frame) is (page.verticalScrollBar().maximum() > 0)
        assert page.viewport().geometry().contains(mapped_rect(bar, page))
        assert abs(mapped_rect(bar, page).right() - page.viewport().geometry().right()) <= 2
        assert page.horizontalScrollBar().maximum() == 0
    assert bar.isVisibleTo(frame)
    start = bar.handle.geometry().center()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bar, start + QPoint(0, 60))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=start + QPoint(0, 60))
    wait_until(qt_application, lambda: page.verticalScrollBar().value() > 0)
    page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
    wait_for_stable_geometry(qt_application, (page, page.widget(), bar))
    if route == "settings":
        last = page.about_panel
    else:
        last = page.widget().layout().itemAt(page.widget().layout().count() - 1).widget()
    assert mapped_rect(last, page.viewport()).bottom() <= page.viewport().rect().bottom()
    if route == "settings":
        assert (
            page.viewport().rect().bottom() - mapped_rect(last, page.viewport()).bottom()
            == page.expand_layout.contentsMargins().bottom()
        )


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

@pytest.mark.parametrize("font_size,count", [(12, 1), (22, 4), (22, 20)])
@pytest.mark.parametrize("language", ["zh_CN", "en_US", "zh_HK"])
def test_device_picker_respects_short_window_height(
    monkeypatch, qt_application, font_size, count, language,
):
    from gui.i18n import install_translators, tr

    translators = install_translators(qt_application, language)
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda cls, role, size=None: QFont("Arial", size if size is not None else font_size)
    ))
    window = QWidget()
    layout = QVBoxLayout(window)
    bar = DeviceContextBar(window)
    layout.addWidget(bar)
    layout.addStretch()
    window.resize(720, 360)
    window.show()
    bar.set_context([], [f"device-{index}" for index in range(count)], "ready")
    close = PushButton(tr("关闭应用管理"))
    bar.set_session_context(None, close)
    qt_application.processEvents()
    try:
        bar.open_picker()
        qt_application.processEvents()
        picker, popup = bar._picker, bar._picker_flyout
        assert picker is not None and popup is not None
        bounds = bar._popup_bounds(bar.targets_button)
        assert bounds.contains(QRect(popup.pos(), popup.size()))
        assert picker.rect().contains(mapped_rect(picker.clear_button, picker))
        assert picker.close_button.isVisible()
        assert picker.rect().contains(mapped_rect(picker.close_button, picker))
        last = picker.device_list.item(count - 1)
        picker.device_list.scrollToItem(last)
        qt_application.processEvents()
        assert picker.device_list.viewport().rect().intersects(
            picker.device_list.visualItemRect(last)
        )
        spy = QSignalSpy(picker.selection_requested)
        picker.select_all_button.click()
        assert spy.count() == 1 and len(spy.at(0)[0]) == count
        picker.clear_button.click()
        assert spy.count() == 2 and list(spy.at(1)[0]) == []
        picker.device_list.setCurrentItem(last)
        QTest.keyClick(picker.device_list, Qt.Key.Key_Space)
        assert spy.count() == 3 and list(spy.at(2)[0]) == [f"device-{count - 1}"]
        QTest.keyClick(popup, Qt.Key.Key_Escape)
        qt_application.processEvents()
        assert not isValid(popup) or not popup.isVisible()
    finally:
        bar.dismiss_popups()
        window.close()
        window.deleteLater()
        for translator in translators:
            qt_application.removeTranslator(translator)
