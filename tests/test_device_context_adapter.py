"""设备上下文的 Qt 桥接保持原选择通知、行复用和刷新时序。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from gui.panels.device_manager import DeviceManager
from gui.panels.side_panel import SidePanel
from models.device_store import DeviceStore
from services.devices.device_context import DeviceContext, DeviceContextSnapshot

pytestmark = pytest.mark.ui


@pytest.fixture
def panel(qt_application, monkeypatch):
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda devices: [])
    owner = SidePanel()
    yield owner
    owner.device_widget.close()
    owner.close()


def test_panel_and_manager_share_context_and_queries_do_not_read_rows(panel):
    manager = panel._devices_tab
    panel.update_device_list(["a"])
    panel.set_selected_devices(["a"])
    assert manager._device_context is panel._device_context
    with QSignalBlocker(manager.listbox_devices):
        manager.listbox_devices.clear()
    assert manager.selected_devices == panel.selected_devices == ["a"]
    assert panel.device_context_snapshot() == DeviceContextSnapshot(("a",), ("a",), "ready")


def test_injected_context_survives_ui_build_and_instances_are_independent(panel):
    context = DeviceContext()
    context.replace_connected_devices(["a"])
    context.set_selected_devices(["a"])
    context.set_discovery_state("ready")
    manager = DeviceManager(panel, parent=panel, device_context=context)
    widget = manager.build_ui(parent=panel)
    assert context.snapshot() == DeviceContextSnapshot(("a",), ("a",), "ready")
    assert manager.listbox_devices.item(0).checkState() == Qt.CheckState.Checked
    assert manager.selected_devices == ["a"]
    assert manager.btn_refresh.isEnabled()
    separate = DeviceManager(panel, parent=panel)
    second_panel = SidePanel()
    try:
        assert separate._device_context is not context
        assert separate._device_context.snapshot() == DeviceContextSnapshot((), (), "scanning")
        assert second_panel._device_context is not panel._device_context
        second_panel.update_device_list(["b"])
        second_panel.set_selected_devices(["b"])
        assert panel.device_context_snapshot() == DeviceContextSnapshot((), (), "scanning")
    finally:
        widget.close()
        second_panel.close()


def test_reordered_scan_reuses_surviving_rows_and_matches_context(panel):
    manager = panel._devices_tab
    panel.update_device_list(["a", "b"])
    panel.set_selected_devices(["a", "b"])
    a_item, b_item = manager.listbox_devices.item(0), manager.listbox_devices.item(1)
    panel.update_device_list(["b", "a", "c"])
    assert manager.listbox_devices.item(0) is a_item
    assert manager.listbox_devices.item(1) is b_item
    assert panel.device_context_snapshot().connected_devices == ("b", "a", "c")
    assert panel.selected_devices == ["a", "b"]
    panel.update_device_list(["b", "c"])
    panel.update_device_list(["a", "b", "c"])
    assert manager.listbox_devices.item(0) is b_item
    assert [
        manager.listbox_devices.item(row).data(Qt.ItemDataRole.UserRole)["ip"]
        for row in range(3)
    ] == ["b", "c", "a"]
    assert panel.selected_devices == ["b"]
    assert manager.listbox_devices.item(2).checkState() == Qt.CheckState.Unchecked


@pytest.mark.parametrize(
    ("entry", "expected"),
    [("setter", ["b"]), ("all", ["a", "b"]), ("none", []),
     ("checkbox", ["a", "b"]), ("double_click", ["a", "b"])],
)
def test_selection_entries_publish_once_without_render_echo(panel, qt_application, entry, expected):
    manager = panel._devices_tab
    panel.update_device_list(["a", "b"])
    panel.set_selected_devices(["a"])
    panel.device_widget.resize(700, 450)
    panel.device_widget.show()
    manager.listbox_devices.doItemsLayout()
    qt_application.processEvents()
    changed = QSignalSpy(panel.selected_devices_changed)
    if entry == "setter":
        panel.set_selected_devices(["b"])
    elif entry == "all":
        manager.btn_all.click()
    elif entry == "none":
        manager.btn_none.click()
    elif entry == "double_click":
        manager.listbox_devices.itemDoubleClicked.emit(manager.listbox_devices.item(1))
    else:
        item = manager.listbox_devices.item(1)
        option = QStyleOptionViewItem()
        manager.listbox_devices.initViewItemOption(option)
        option.rect = manager.listbox_devices.visualItemRect(item)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        option.checkState = item.checkState()
        check_rect = manager.listbox_devices.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, manager.listbox_devices,
        )
        QTest.mouseClick(
            manager.listbox_devices.viewport(), Qt.MouseButton.LeftButton, pos=check_rect.center(),
        )
    assert changed.count() == 1
    assert changed.at(0)[0] == expected
    assert panel.selected_devices == manager.selected_devices == expected
    panel.selected_devices.clear()
    manager.selected_devices.clear()
    assert panel.selected_devices == manager.selected_devices == expected
    panel.set_selected_devices(expected)
    panel.set_selected_devices(expected)
    assert changed.count() == 3


def test_list_refresh_keeps_raw_payload_and_state_publication_order(panel):
    panel.update_device_list(["a"])
    panel.set_selected_devices(["a"])
    panel.set_device_discovery_state("unavailable")
    events = []

    def on_selection(devices):
        snapshot = panel.device_context_snapshot()
        events.append((
            "selection", tuple(devices), snapshot.discovery_state, snapshot.selected_devices,
        ))

    panel.selected_devices_changed.connect(on_selection)
    panel.device_discovery_state_changed.connect(
        lambda state: events.append((
            "state", state, panel.device_context_snapshot().selected_devices,
        )),
    )
    panel.update_device_list(["a", "b"])
    assert events == [("selection", ("a",), "unavailable", ()), ("state", "ready", ("a",))]
    events.clear()
    panel.update_device_list(["a", "b"])
    assert events == [("selection", ("a",), "ready", ("a",))]


def test_manual_refresh_publishes_state_before_request_and_restores_once(panel):
    panel.update_device_list(["a"])
    events = []
    panel.device_discovery_state_changed.connect(lambda state: events.append(("state", state)))
    panel.signals.refresh_devices_requested.connect(lambda: events.append(("refresh",)))
    assert panel.request_device_refresh() is True
    assert panel.request_device_refresh() is False
    panel.on_device_refresh_superseded()
    panel.on_device_refresh_superseded()
    assert events == [("state", "scanning"), ("refresh",), ("state", "ready")]
    assert panel.request_device_refresh() is True
    panel.update_device_list(["b"])
    events.clear()
    panel.on_device_refresh_superseded()
    assert events == []
    assert panel.device_context_snapshot() == DeviceContextSnapshot((), ("b",), "ready")


def test_item_metadata_change_keeps_action_refresh_without_selection_submission(panel, monkeypatch):
    panel.update_device_list(["a"])
    panel.set_selected_devices(["a"])
    context = panel._device_context
    submit = Mock(wraps=context.set_selected_devices)
    monkeypatch.setattr(context, "set_selected_devices", submit)
    changed = QSignalSpy(panel.selected_devices_changed)
    panel._devices_tab.listbox_devices.item(0).setText("updated metadata")
    assert submit.call_count == 0
    assert changed.count() == 1
    assert changed.at(0)[0] == ["a"]
    assert panel.device_context_snapshot().selected_devices == ("a",)
