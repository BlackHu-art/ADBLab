"""验证工作台等待设备时的候选同步与路由恢复。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute


class _PayloadPage(QWidget):
    def __init__(self, _key) -> None:
        super().__init__()
        self.activations: list[object | None] = []
        self.deactivations: list[str] = []
        self.connected_states: list[bool] = []

    def activate(self, payload=None) -> None:
        self.activations.append(payload)

    def deactivate(self, reason: str) -> None:
        self.deactivations.append(reason)

    def set_device_connected(self, connected: bool) -> None:
        self.connected_states.append(connected)


def _host() -> WorkspaceFeatureHost:
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature(
        "logcat",
        "实时日志",
        FluentIcon.SCROLL,
        _PayloadPage,
    )
    return host


def _combo_index(host: WorkspaceFeatureHost, device_id: str) -> int:
    return next(
        index
        for index in range(host.device_combo.count())
        if host.device_combo.itemData(index) == device_id
    )


def test_pending_route_resumes_when_device_candidates_become_unique(qt_application):
    host = _host()
    payload = {"package_name": "example.package"}
    host.set_device_context([], ["device-1", "device-2"])

    assert host.open_feature("logcat", payload=payload) is True
    assert host.stack.currentWidget() is host.no_device_page

    host.set_device_context([], ["device-2"])

    page = host.stack.currentWidget()
    assert isinstance(page, _PayloadPage)
    assert page.activations == [payload]
    assert page.connected_states[-1] is True
    assert host.pending_route is None
    assert host.current_device_id == "device-2"
    assert host.device_combo.count() == 1
    assert host.device_combo.currentData() == "device-2"
    assert host.device_combo.isEnabled() is False
    assert host.session_badge.text() == "在线"


def test_pending_route_keeps_explicit_choice_and_empty_state_in_sync(qt_application):
    host = _host()
    route = WorkspaceRoute(
        "system",
        "logcat",
        payload={"package_name": "example.package"},
    )
    host.set_device_context([], ["device-1", "device-2"])

    assert host.open_route(route) is True
    assert host.current_device_id == ""
    assert host.device_combo.currentData() == ""
    assert host.device_combo.isEnabled() is True
    assert "多台可用设备" in host.no_device_page.message_label.text()
    assert host.no_device_page.choose_button.isHidden() is True

    host.set_device_context([], [])

    assert host.stack.currentWidget() is host.no_device_page
    assert host.pending_route == route
    assert host.current_device_id == ""
    assert host.device_combo.isHidden() is True
    assert "没有可用设备" in host.no_device_page.message_label.text()
    assert host.no_device_page.choose_button.isHidden() is False
    assert host.session_badge.text() == "等待选择设备"


def test_manual_device_choice_delivers_pending_payload_once(qt_application):
    host = _host()
    payload = {"package_name": "example.package"}
    host.set_device_context([], ["device-1", "device-2"])
    host.open_feature("logcat", payload=payload)

    host.device_combo.setCurrentIndex(_combo_index(host, "device-2"))

    page = host.stack.currentWidget()
    assert isinstance(page, _PayloadPage)
    assert page.activations == [payload]
    assert host.pending_route is None
    assert host.current_device_id == "device-2"


def test_hidden_pending_route_waits_for_activation_before_resume(qt_application):
    host = _host()
    payload = {"package_name": "example.package"}
    host.open_feature("logcat", payload=payload)
    host.deactivate()

    host.set_device_context([], ["device-1"])

    assert host.stack.currentWidget() is host.no_device_page
    assert host.pending_route == WorkspaceRoute(
        "system",
        "logcat",
        payload=payload,
    )

    host.activate()

    page = host.stack.currentWidget()
    assert isinstance(page, _PayloadPage)
    assert page.activations == [payload]
    assert host.pending_route is None
    assert host.current_device_id == "device-1"
