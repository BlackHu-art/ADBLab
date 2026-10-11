"""镜像操作条与共享设备选择区之间的路由和页面隔离。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt

from tests import test_global_device_context

pytestmark = pytest.mark.ui
frame = test_global_device_context.frame


def _open_remote(frame):
    frame.show()
    frame._on_devices_updated(["demo-a", "demo-b"])
    frame._open_workspace_feature("devices", "remote")
    return frame.left_panel.remote_panel, frame._global_device_bar


def test_empty_mirror_start_opens_shared_selector(frame, qt_application):
    remote, bar = _open_remote(frame)
    assert remote.selected_devices == []
    assert not bar.is_selector_expanded
    remote.btn_start.click()
    qt_application.processEvents()
    assert bar.is_selector_expanded
    assert remote.selected_devices == []


def test_remote_operations_follow_visible_page_without_changing_targets(
    frame, qt_application, monkeypatch,
):
    from gui.widgets.device_context_bar import DeviceRowOperation

    remote, bar = _open_remote(frame)
    frame.left_panel.set_selected_devices(["demo-b"])
    snapshot = {"demo-a": DeviceRowOperation(
        status="镜像中", action="stop", action_text="停止", enabled=True, retain=True,
    )}
    monkeypatch.setattr(remote, "device_operations", lambda: snapshot)
    action = Mock()
    monkeypatch.setattr(remote, "request_device_operation", action)
    remote.device_operations_changed.emit()
    bar.open_picker()
    qt_application.processEvents()
    row = bar._picker._rows["demo-a"]
    assert row.status_label.text() == "镜像中"
    row.operation_button.click()
    action.assert_called_once_with("demo-a", "stop")
    assert frame.left_panel.selected_devices == ["demo-b"]

    frame._open_workspace_feature("apps", "overview")
    remote.device_operations_changed.emit()
    bar.open_picker()
    assert bar._picker._rows["demo-a"].operation_button.isHidden()
    assert bar._picker._rows["demo-a"].status_label.text() != "镜像中"
    bar.device_operation_requested.emit("demo-a", "stop")
    remote.device_selection_requested.emit()
    assert action.call_count == 1
    frame._open_workspace_feature("devices", "remote")
    bar.open_picker()
    assert bar._picker._rows["demo-a"].status_label.text() == "镜像中"


def test_preparing_mirror_locks_selection_but_discovery_still_updates(
    frame, monkeypatch, qt_application,
):
    remote, bar = _open_remote(frame)
    frame.left_panel.set_selected_devices(["demo-a"])
    locked = True
    monkeypatch.setattr(remote, "is_mirror_selection_locked", lambda: locked)
    remote.device_operations_changed.emit()
    bar.open_picker()
    qt_application.processEvents()
    picker = bar._picker
    assert not picker.clear_button.isEnabled()
    assert not picker.select_all_button.isEnabled()
    assert not picker._rows["demo-b"].check_box.isEnabled()
    bar.selection_requested.emit([])
    frame._select_operation_devices(["demo-b"])
    assert frame.left_panel.selected_devices == ["demo-a"]
    frame._on_devices_updated(["demo-b"])
    assert remote.selected_devices == []
    locked = False
    remote.device_operations_changed.emit()
    picker._rows["demo-b"].check_box.click()
    assert frame.left_panel.selected_devices == ["demo-b"]
    assert picker._rows["demo-b"].item.checkState() == Qt.CheckState.Checked


def test_remote_selection_lock_does_not_leak_into_other_pages(frame, monkeypatch):
    remote, bar = _open_remote(frame)
    frame.left_panel.set_selected_devices(["demo-a"])
    monkeypatch.setattr(remote, "is_mirror_selection_locked", lambda: True)
    remote.device_operations_changed.emit()
    bar.open_picker()
    assert not bar._picker.clear_button.isEnabled()
    frame._open_workspace_feature("apps", "overview")
    remote.device_operations_changed.emit()
    bar.open_picker()
    assert bar._picker.clear_button.isEnabled()
    bar._picker.clear_button.click()
    assert frame.left_panel.selected_devices == []
    bar.collapse_selector()
    remote.device_selection_requested.emit()
    assert not bar.is_selector_expanded


def test_row_retry_recovers_after_synchronous_configuration_failure(
    frame, monkeypatch, qt_application,
):
    from gui.panels.remote_panel_scrcpy import RemoteDeviceSession
    from services.remote import ScrcpyConfig

    remote, bar = _open_remote(frame)
    frame.left_panel.set_selected_devices(["demo-a"])
    config = ScrcpyConfig("", "", "demo-a", "1024", "30", "4M", "auto", "0", "")
    session = RemoteDeviceSession(config, state="failed", error_type="TimeoutError")
    remote._device_sessions = {"demo-a": session}
    remote._refresh_mirror_presentation()
    bar.open_picker()
    failed_config = Mock(side_effect=FileNotFoundError("synthetic tool unavailable"))
    monkeypatch.setattr(remote, "_scrcpy_config", failed_config)
    monkeypatch.setattr(remote, "_log", Mock())
    row = bar._picker._rows["demo-a"]
    assert row.operation_button.isEnabled()
    row.operation_button.click()
    qt_application.processEvents()
    assert remote._device_sessions["demo-a"] is session
    assert remote.selected_devices == ["demo-a"]
    assert row.operation_button.isEnabled()
    row.operation_button.click()
    assert failed_config.call_count == 2
