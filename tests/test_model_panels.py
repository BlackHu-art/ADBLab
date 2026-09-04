# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import os
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)
from qfluentwidgets import ComboBox, EditableComboBox, PrimaryPushButton

from controllers._system import ADBSystemControllerMixin
from gui.panels.app_panel import AppPanel
from gui.panels.base_panel import BasePanel
from gui.panels.device_manager import DeviceManager
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel import SidePanel
from gui.panels.side_panel_signals import SidePanelSignals
from utils.adb_targets import normalize_adb_connect_target


def test_device_manager_shows_placeholder_for_new_unstored_device():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = SimpleNamespace(selected_devices=[])
    manager.panel = panel
    manager.listbox_devices = QListWidget()
    manager.set_discovery_state = Mock()
    manager._device_items_by_ip = lambda: DeviceManager._device_items_by_ip(manager)

    with patch("gui.panels.device_manager.DeviceStore.get_full_devices_info", return_value=[]):
        DeviceManager.update_device_list(manager, ["emulator-5554"])

    assert manager.listbox_devices.count() == 1
    item = manager.listbox_devices.item(0)
    assert "Detecting" in item.text()
    assert item.data(Qt.UserRole)["ip"] == "emulator-5554"
    manager.set_discovery_state.assert_not_called()


def test_device_manager_updates_device_list_incrementally():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = SimpleNamespace(selected_devices=[])
    manager.panel = panel
    manager.listbox_devices = QListWidget()
    manager.set_discovery_state = Mock()
    manager._device_items_by_ip = lambda: DeviceManager._device_items_by_ip(manager)

    first_infos = [
        {"Brand": "Google", "Model": "Pixel", "Aversion": "15", "ip": "device-1"},
        {"Brand": "Redmi", "Model": "K70", "Aversion": "14", "ip": "device-2"},
    ]
    second_infos = [
        {"Brand": "Google", "Model": "Pixel", "Aversion": "15", "ip": "device-1"},
    ]
    with patch(
        "gui.panels.device_manager.DeviceStore.get_full_devices_info",
        side_effect=[first_infos, second_infos],
    ):
        DeviceManager.update_device_list(manager, ["device-1", "device-2"])
        first_item = manager.listbox_devices.item(0)
        first_item.setCheckState(Qt.Checked)
        manager.selected_devices = ["device-1"]

        DeviceManager.update_device_list(manager, ["device-1", "device-3"])

    assert manager.listbox_devices.count() == 2
    assert manager.listbox_devices.item(0) is first_item
    assert first_item.checkState() == Qt.Checked
    assert manager.listbox_devices.item(1).data(Qt.UserRole)["ip"] == "device-3"
    assert "Detecting" in manager.listbox_devices.item(1).text()
    manager.set_discovery_state.assert_not_called()


def test_device_manager_none_device_list_clears_without_model_lookup():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = SimpleNamespace(selected_devices=["device-1"])
    manager.panel = panel
    manager.listbox_devices = QListWidget()
    manager.set_discovery_state = Mock()
    manager._device_items_by_ip = lambda: DeviceManager._device_items_by_ip(manager)
    item = QListWidgetItem("device-1")
    item.setData(Qt.UserRole, {"ip": "device-1"})
    item.setCheckState(Qt.Checked)
    manager.listbox_devices.addItem(item)

    with patch("models.adb_device.ADBDevice.get_connected_devices_async") as get_devices:
        DeviceManager.update_device_list(manager, None)

    get_devices.assert_not_called()
    assert manager.listbox_devices.count() == 0
    assert panel._connected_device_cache == []
    manager.set_discovery_state.assert_not_called()


def _build_connect_device_manager():
    panel = Mock()
    panel.signals = SidePanelSignals()
    panel._font_sm = QFont()
    panel._font_mono = QFont()
    panel._font_base = QFont()
    panel._user_selected_ip = False
    panel.selected_devices = []
    manager = DeviceManager(panel)
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        widget = manager.build_ui()
    manager.connect_signals()
    return manager, widget, panel


def test_adb_connect_target_validation_requires_complete_ip_and_port():
    assert normalize_adb_connect_target(" 10.0.0.195 : 5555 ") == (
        "10.0.0.195:5555",
        "",
    )
    assert normalize_adb_connect_target("[::1]:5555") == ("[::1]:5555", "")
    assert "IP and port" in normalize_adb_connect_target("10.0.0.195")[1]
    assert "valid IP" in normalize_adb_connect_target("10.0.0.999:5555")[1]
    assert "65535" in normalize_adb_connect_target("10.0.0.195:70000")[1]


def test_device_manager_return_pressed_requests_connect_with_normalized_target():
    _app = QApplication.instance() or QApplication([])
    manager, widget, panel = _build_connect_device_manager()
    emitted = []
    panel.signals.connect_requested.connect(emitted.append)

    try:
        manager.ip_entry.setText(" 10.0.0.195 : 5555 ")
        manager.ip_entry.returnPressed.emit()
    finally:
        widget.close()
        manager.close()

    assert emitted == ["10.0.0.195:5555"]


def test_device_manager_rejects_incomplete_connect_target_before_signal_emit():
    _app = QApplication.instance() or QApplication([])
    manager, widget, panel = _build_connect_device_manager()
    emitted = []
    logs = []
    panel.signals.connect_requested.connect(emitted.append)
    panel.signals.log_message.connect(lambda level, message: logs.append((level, message)))

    try:
        manager.ip_entry.setText("10.0.0.195")
        manager.btn_connect_devices.click()
    finally:
        widget.close()
        manager.close()

    assert emitted == []
    assert logs
    assert logs[-1][0] == "WARNING"
    assert "IP and port" in logs[-1][1]


def test_base_panel_button_factory_adds_functional_help_and_icon_name():
    panel = Mock()
    panel._font_sm = QFont()
    base = BasePanel(panel)

    button = base._b("Refresh", "arrows-clockwise.svg", tooltip="Reload the device list")

    assert button.toolTip() == "Reload the device list"
    assert button.accessibleDescription() == "Reload the device list"
    assert button.property("functionalToolTip") == "Reload the device list"
    assert button.property("iconName") == "arrows-clockwise.svg"
    assert button.cursor().shape() == Qt.PointingHandCursor


def test_base_panel_button_factory_rejects_missing_functional_help():
    panel = Mock()
    panel._font_sm = QFont()
    base = BasePanel(panel)

    with pytest.raises(ValueError, match="must provide a functional tooltip"):
        base._b("Refresh", "arrows-clockwise.svg")


def test_base_panel_text_factories_apply_panel_fonts():
    _app = QApplication.instance() or QApplication([])
    panel = Mock()
    panel._font_sm = QFont("Arial", 13)
    panel._font_base = QFont("Arial", 15)
    base = BasePanel(panel)

    label = base._label("Events:")
    status = base._status_text("Total")
    checkbox = base._checkbox("Ignore crashes")

    assert label.property("fontRole") == "ui"
    assert status.objectName() == "statusLabel"
    assert checkbox.property("fontRole") == "ui"


def test_device_manager_skips_unchanged_device_combo_refresh():
    _app = QApplication.instance() or QApplication([])
    panel = Mock()
    manager = SimpleNamespace()
    manager.panel = panel
    manager.ip_entry = EditableComboBox()

    with patch(
        "gui.panels.device_manager_view.DeviceStore.get_basic_devices_info",
        return_value=[("Google", "Pixel", "device-1")],
    ):
        DeviceManager._refresh_device_combobox(manager)
        first_item = manager.ip_entry.items[0]
        DeviceManager._refresh_device_combobox(manager)

    assert manager.ip_entry.count() == 1
    assert manager.ip_entry.itemData(0) == "device-1"
    assert manager.ip_entry.items[0] is first_item


def test_device_history_refresh_preserves_current_input_and_cursor():
    _app = QApplication.instance() or QApplication([])
    manager = SimpleNamespace(panel=Mock(), ip_entry=EditableComboBox())
    manager.ip_entry.setText("192.0.2.20:5555")
    manager.ip_entry.setCursorPosition(8)

    with patch(
        "gui.panels.device_manager_view.DeviceStore.get_basic_devices_info",
        return_value=[("Google", "Pixel", "device-1")],
    ):
        DeviceManager._refresh_device_combobox(manager)

    assert manager.ip_entry.currentText() == "192.0.2.20:5555"
    assert manager.ip_entry.cursorPosition() == 8
    assert manager.ip_entry.itemData(0) == "device-1"


def test_side_panel_refresh_owns_scanning_state_and_rejects_duplicates():
    _app = QApplication.instance() or QApplication([])
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    requested = []
    states = []
    panel.signals.refresh_devices_requested.connect(lambda: requested.append(True))
    panel.device_discovery_state_changed.connect(states.append)

    try:
        panel.set_device_discovery_state("ready")
        states.clear()

        panel._devices_tab.btn_refresh.click()
        panel._devices_tab._request_refresh()

        assert requested == [True]
        assert states == ["scanning"]
        assert panel._device_discovery_state == "scanning"
        assert not panel._devices_tab.btn_refresh.isEnabled()
        assert "正在扫描" in panel._devices_tab.btn_refresh.toolTip()

        panel.set_device_discovery_state("empty")
        assert panel._devices_tab.btn_refresh.isEnabled()
        assert panel._devices_tab.btn_refresh.toolTip() == "扫描已连接设备"
    finally:
        panel.close()


def test_device_card_keeps_native_check_indicator_visible_and_clickable(qt_application):
    device = "device-1"
    info = {
        "Brand": "Google",
        "Model": "Pixel",
        "Aversion": "15",
        "ip": device,
    }
    with (
        patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]),
        patch(
            "gui.panels.device_manager_view.DeviceStore.get_full_devices_info",
            return_value=[info],
        ),
    ):
        panel = SidePanel()
        panel.update_device_list([device])
    manager = panel._devices_tab
    widget = panel.device_widget

    try:
        widget.resize(700, 450)
        widget.show()
        manager.listbox_devices.doItemsLayout()
        qt_application.processEvents()

        item = manager.listbox_devices.item(0)
        card = manager.listbox_devices.itemWidget(item)
        option = QStyleOptionViewItem()
        manager.listbox_devices.initViewItemOption(option)
        option.rect = manager.listbox_devices.visualItemRect(item)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        option.checkState = item.checkState()
        check_rect = manager.listbox_devices.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option,
            manager.listbox_devices,
        )
        check_center_in_card = card.mapFrom(
            manager.listbox_devices.viewport(),
            check_rect.center(),
        )

        assert card.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert not card._content.geometry().contains(check_center_in_card)
        assert item.checkState() == Qt.CheckState.Unchecked

        QTest.mouseClick(
            manager.listbox_devices.viewport(),
            Qt.MouseButton.LeftButton,
            pos=check_rect.center(),
        )
        qt_application.processEvents()
        assert item.checkState() == Qt.CheckState.Checked
        assert panel.selected_devices == [device]
    finally:
        widget.close()
        panel.close()


def test_side_panel_theme_refresh_updates_button_icons():
    _app = QApplication.instance() or QApplication([])
    panel = SimpleNamespace()
    panel._font_sm = QFont()
    panel._font_base = QFont()
    panel._font_mono = QFont()
    panel._create_fonts = Mock()
    panel._devices_tab = Mock()
    panel._devices_tab._apply_device_list_style = Mock()
    panel._apps_tab = Mock()
    button = QPushButton("Refresh")
    button.setProperty("iconName", "arrows-clockwise.svg")
    panel.findChildren = Mock(return_value=[button])
    panel._visual_roots = lambda: [panel]
    panel.setStyleSheet = Mock()
    panel.apply_device_theme = Mock()

    with patch("gui.panels.side_panel.get_themed_icon", return_value=QIcon()) as themed_icon:
        SidePanel._on_theme_changed(panel, "Dark")

    themed_icon.assert_called_once_with("arrows-clockwise.svg")


def test_side_panel_public_helpers_wrap_internal_tabs():
    device_widget = QWidget()
    panel = SimpleNamespace()
    panel._device_widget = device_widget
    panel._devices_tab = Mock()
    panel._apps_tab = Mock(package_text="com.example.app")

    assert SidePanel.device_widget.fget(panel) is device_widget
    assert SidePanel.current_package_text(panel) == "com.example.app"

    SidePanel.refresh_device_choices(panel)
    SidePanel.apply_device_theme(panel)

    panel._devices_tab._refresh_device_combobox.assert_called_once()
    panel._devices_tab._apply_device_list_style.assert_called_once()


def test_side_panel_initializes_only_default_function_tab():
    _app = QApplication.instance() or QApplication([])
    panel = SidePanel()
    try:
        assert panel._apps_tab is not None
        assert panel._advanced_tab is None
        assert panel._scrcpy_tab is None
        assert panel._loaded_lazy_tabs == {0}
        assert panel._connected_lazy_tabs == {0}
    finally:
        panel.close()


def test_side_panel_lazy_loads_and_connects_later_tabs():
    _app = QApplication.instance() or QApplication([])
    panel = SidePanel()
    try:
        panel._ensure_tab_loaded(2)

        assert panel._scrcpy_tab is not None
        assert 2 in panel._loaded_lazy_tabs
        assert 2 in panel._connected_lazy_tabs
    finally:
        panel.close()


def test_side_panel_shutdown_forwards_to_loaded_tabs():
    panel = SimpleNamespace()
    apps_tab = object()
    remote_tab = Mock()
    panel._loaded_lazy_tabs = {0, 2}
    panel._lazy_tab_specs = [
        ("_apps_tab", AppPanel, "Apps"),
        ("_advanced_tab", object, "System"),
        ("_scrcpy_tab", RemotePanel, "Remote"),
    ]
    panel._apps_tab = apps_tab
    panel._advanced_tab = None
    panel._scrcpy_tab = remote_tab

    SidePanel.shutdown(panel)

    remote_tab.shutdown.assert_called_once()


def test_remote_status_style_does_not_override_global_font():
    remote = SimpleNamespace()
    remote._status_label = Mock()
    RemotePanel._update_status(remote, "Running", None)

    style = remote._status_label.setStyleSheet.call_args.args[0]
    assert "font-size" not in style
    assert "font-weight: bold" in style


def test_remote_start_stop_buttons_follow_running_state():
    _app = QApplication.instance() or QApplication([])
    owner = QWidget()
    remote = SimpleNamespace(
        btn_start=PrimaryPushButton(owner),
        btn_stop=PrimaryPushButton(owner),
        _SESSION_IDLE=RemotePanel._SESSION_IDLE,
        workspace_target_lock_changed=Mock(),
    )
    remote._refresh_button_style = lambda button: BasePanel._refresh_button_style(remote, button)
    remote._set_button_enabled = lambda button, enabled: BasePanel._set_button_enabled(
        remote, button, enabled
    )
    try:
        RemotePanel._set_running(remote, False)

        assert remote.btn_start.isEnabled() is True
        assert remote.btn_stop.isEnabled() is False

        RemotePanel._set_running(remote, True)

        assert remote.btn_start.isEnabled() is False
        assert remote.btn_stop.isEnabled() is True

        RemotePanel._set_running(remote, False)

        assert remote.btn_start.isEnabled() is True
        assert remote.btn_stop.isEnabled() is False
        assert remote.workspace_target_lock_changed.emit.call_args_list == [
            call(False),
            call(True),
            call(False),
        ]
    finally:
        owner.close()


def test_remote_control_buttons_are_grouped_without_duplicate_shortcuts():
    _app = QApplication.instance() or QApplication([])
    side_panel = SidePanel()
    try:
        remote = side_panel._ensure_tab_loaded(2)

        key_codes = [button.property("remoteKey") for button in remote._remote_key_buttons]
        actions = [button.property("remoteAction") for button in remote._remote_action_buttons]

        assert "RECENTS" in key_codes
        assert "APP_SWITCH" not in key_codes
        assert "NOTIFICATION" not in key_codes
        assert not any(str(code).startswith("DPAD_") for code in key_codes)
        assert len(key_codes) == len(set(key_codes))
        assert {"notif_expand", "notif_collapse", "rotate_portrait", "rotate_landscape"}.issubset(
            actions
        )
        assert {"swipe_up", "swipe_down", "swipe_left", "swipe_right"}.issubset(actions)
        assert len(remote._remote_control_buttons) == len(remote._remote_key_buttons) + len(
            remote._remote_action_buttons
        )
        assert all(button.property("iconName") for button in remote._remote_control_buttons)
    finally:
        side_panel.close()


def test_remote_control_clicks_warn_when_no_device_selected():
    remote = SimpleNamespace()
    remote.selected_devices = []
    remote._remote_control = Mock()
    remote._submit_remote_input = Mock()
    remote._log = Mock()
    remote._selected_remote_device = lambda: RemotePanel._selected_remote_device(remote)

    RemotePanel._send_keyevent(remote, "HOME")
    RemotePanel._send_remote_action(remote, "swipe_up")

    assert remote._log.call_args_list == [
        call("WARNING", "No device selected"),
        call("WARNING", "No device selected"),
    ]
    remote._submit_remote_input.assert_not_called()
    remote._remote_control.send_keyevent.assert_not_called()
    remote._remote_control.perform_action.assert_not_called()


def test_app_panel_monkey_buttons_follow_start_stop_state():
    _app = QApplication.instance() or QApplication([])
    side_panel = Mock()
    side_panel._font_sm = QFont("Arial", 12)
    side_panel._font_base = QFont("Arial", 12)
    side_panel._font_mono = QFont("Courier New", 10)
    side_panel._package_history = []
    side_panel._apply_completer_style = Mock()
    side_panel.selected_devices = ["device-1"]
    side_panel.signals = Mock()
    panel = AppPanel(side_panel)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        settings.get.return_value = {}
        widget = panel.build_ui()
        try:
            panel.program_edit.setText("com.example.app")

            assert panel.start_monkey_btn.isEnabled() is True
            assert panel.kill_monkey_btn.isEnabled() is False

            panel._on_start_monkey()

            assert panel.start_monkey_btn.isEnabled() is False
            assert panel.kill_monkey_btn.isEnabled() is True
            side_panel.signals.start_monkey_batch_requested.emit.assert_called_once()
            batch_id = side_panel.signals.start_monkey_batch_requested.emit.call_args.args[2]

            panel.on_monkey_target_finished(batch_id, "device-1")

            assert panel.start_monkey_btn.isEnabled() is True
            assert panel.kill_monkey_btn.isEnabled() is False

            panel._on_start_monkey()
            second_batch_id = side_panel.signals.start_monkey_batch_requested.emit.call_args.args[2]
            panel.on_operation_completed("install", True, "done")

            assert panel.start_monkey_btn.isEnabled() is False
            assert panel.kill_monkey_btn.isEnabled() is True

            panel._on_kill_monkey()

            assert panel.start_monkey_btn.isEnabled() is False
            assert panel.kill_monkey_btn.isEnabled() is False
            side_panel.signals.kill_monkey_batch_requested.emit.assert_called_once_with(
                ["device-1"], second_batch_id
            )

            panel.on_monkey_target_finished(second_batch_id, "device-1")
            assert panel.start_monkey_btn.isEnabled() is True
        finally:
            widget.deleteLater()


def test_app_panel_screenshot_button_disables_during_operation_then_recovers():
    _app = QApplication.instance() or QApplication([])
    side_panel = Mock()
    side_panel._font_sm = QFont("Arial", 12)
    side_panel._font_base = QFont("Arial", 12)
    side_panel._font_mono = QFont("Courier New", 10)
    side_panel._package_history = []
    side_panel._apply_completer_style = Mock()
    side_panel.selected_devices = ["device-1"]
    side_panel.signals = Mock()
    panel = AppPanel(side_panel)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        settings.get.return_value = {}
        widget = panel.build_ui()
        try:
            assert panel.btn_screenshot.isEnabled() is True

            panel._on_screenshot()

            assert panel.btn_screenshot.isEnabled() is False
            side_panel.signals.screenshot_requested.emit.assert_called_once_with(["device-1"])

            panel.on_operation_completed("screenshot", True, "Screenshot captured")
            assert panel.btn_screenshot.isEnabled() is False

            panel.on_operation_completed("screenshot", True, "Screenshot completed: 1/1 succeeded")
            assert panel.btn_screenshot.isEnabled() is True

            panel._on_screenshot()
            panel.on_operation_completed(
                "screenshot",
                False,
                "Unable to prepare screenshot directory",
            )
            assert panel.btn_screenshot.isEnabled() is True
        finally:
            widget.deleteLater()


def test_app_panel_routes_disable_buttons_to_distinct_signals():
    _app = QApplication.instance() or QApplication([])
    side_panel = Mock()
    side_panel._font_sm = QFont("Arial", 12)
    side_panel._font_base = QFont("Arial", 12)
    side_panel._font_mono = QFont("Courier New", 10)
    side_panel._package_history = []
    side_panel._apply_completer_style = Mock()
    side_panel.selected_devices = ["device-1"]
    side_panel.signals = SidePanelSignals()
    regular_requests = []
    user_requests = []
    side_panel.signals.disable_app_requested.connect(
        lambda devices, package: regular_requests.append((devices, package))
    )
    side_panel.signals.disable_app_for_user_requested.connect(
        lambda devices, package: user_requests.append((devices, package))
    )
    panel = AppPanel(side_panel)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings_cls.instance.return_value.get.return_value = {}
        widget = panel.build_ui()
        panel.connect_signals()
        try:
            panel.program_edit.setText("com.example.app")
            panel.btn_disable_app.click()
            panel.btn_disable_user.click()
        finally:
            widget.deleteLater()

    assert regular_requests == [(["device-1"], "com.example.app")]
    assert user_requests == [(["device-1"], "com.example.app")]


def test_controller_routes_disable_scopes_to_distinct_model_methods():
    controller = SimpleNamespace(
        advanced_model=Mock(),
        _require_devices=Mock(return_value=True),
    )

    ADBSystemControllerMixin.disable_app(
        controller,
        ["device-1", "device-2"],
        "com.example.app",
    )
    ADBSystemControllerMixin.disable_app_for_user(
        controller,
        ["device-1", "device-2"],
        "com.example.app",
    )

    assert controller.advanced_model.disable_package_async.call_args_list == [
        call("device-1", "com.example.app"),
        call("device-2", "com.example.app"),
    ]
    assert controller.advanced_model.disable_package_user_async.call_args_list == [
        call("device-1", "com.example.app"),
        call("device-2", "com.example.app"),
    ]
    assert (
        ADBSystemControllerMixin._handlers["disable_package_user"]
        == "_process_disable_package_user_result"
    )


def test_emu_sms_rejects_empty_sender_and_newlines_before_adb():
    controller = SimpleNamespace(
        advanced_model=Mock(),
        _require_devices=Mock(return_value=True),
        _emit_operation=Mock(),
    )

    ADBSystemControllerMixin.emu_sms(controller, ["device-1"], "", "hello")
    ADBSystemControllerMixin.emu_sms(controller, ["device-1"], "555\n1234", "hello")
    ADBSystemControllerMixin.emu_sms(controller, ["device-1"], "555-1234", "first\nsecond")

    controller.advanced_model.emu_sms_send_async.assert_not_called()
    assert [c.args[:2] for c in controller._emit_operation.call_args_list] == [
        ("emu_sms", False),
        ("emu_sms", False),
        ("emu_sms", False),
    ]


def test_emu_call_rejects_empty_and_newline_number_before_adb():
    controller = SimpleNamespace(
        advanced_model=Mock(),
        _require_devices=Mock(return_value=True),
        _emit_operation=Mock(),
    )

    ADBSystemControllerMixin.emu_call(controller, ["device-1"], "")
    ADBSystemControllerMixin.emu_call(controller, ["device-1"], "555\n1234")

    controller.advanced_model.emu_call_async.assert_not_called()
    assert [c.args[:2] for c in controller._emit_operation.call_args_list] == [
        ("emu_call", False),
        ("emu_call", False),
    ]


def test_side_panel_loaded_buttons_have_tooltips_and_registered_icons():
    _app = QApplication.instance() or QApplication([])
    panel = SidePanel()
    try:
        panel._ensure_tab_loaded(1)
        panel._ensure_tab_loaded(2)

        roots = [
            panel.device_widget,
            *(panel._tab_scroll_areas[index].widget() for index in range(3)),
        ]
        buttons = [
            button
            for root in roots
            for button in root.findChildren(QPushButton)
            if not isinstance(button, ComboBox)
        ]

        assert buttons
        assert [button.text() for button in buttons if not button.toolTip().strip()] == []
        assert [
            button.text()
            for button in buttons
            if not button.icon().isNull() and not button.property("iconName")
        ] == []
    finally:
        panel.close()
