"""验证工作区路由的一次性激活参数不会变成可恢复页面状态。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from gui.features import FeatureSessionKey
from gui.pages.fluent_pages import WorkspaceAreaPage
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute


class _PayloadProbe(QWidget):
    dispose_ready = Signal(object)

    def __init__(self, key: FeatureSessionKey) -> None:
        super().__init__()
        self.key = key
        self.activations: list[object | None] = []

    def activate(self, payload=None) -> None:
        self.activations.append(payload)

    def deactivate(self, _reason: str) -> None:
        pass


def _workspace() -> tuple[WorkspaceFeatureHost, WorkspaceAreaPage]:
    host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    host.register_feature(
        "manager",
        "应用管理",
        FluentIcon.APPLICATION,
        _PayloadProbe,
    )
    page = WorkspaceAreaPage(
        "appsPage",
        "apps",
        "应用与自动化",
        "应用概览",
        host,
        feature_host=host,
    )
    return host, page


def test_inactive_payload_is_consumed_once_on_first_activation(qt_application):
    host, page = _workspace()
    host.set_device_context(["device-1"], ["device-1"])
    payload = {"package_name": "example.package"}

    assert page.open_route(
        WorkspaceRoute("apps", "manager", "device-1", payload)
    ) is True
    assert page.current_route == WorkspaceRoute("apps", "manager", "device-1")
    assert host.registry.keys() == ()

    page.activate()
    feature_page = host.stack.currentWidget()

    assert isinstance(feature_page, _PayloadProbe)
    assert feature_page.activations == [payload]
    assert page.current_route == WorkspaceRoute("apps", "manager", "device-1")

    page.deactivate()
    page.activate()

    assert feature_page.activations == [payload, None]


def test_active_payload_is_not_replayed_after_page_resume(qt_application):
    host, page = _workspace()
    host.set_device_context(["device-1"], ["device-1"])
    payload = {"path": "/sdcard/Download"}
    emitted_routes: list[WorkspaceRoute] = []
    page.routeChanged.connect(emitted_routes.append)
    page.activate()

    assert page.open_route(
        WorkspaceRoute("apps", "manager", "device-1", payload)
    ) is True
    feature_page = host.stack.currentWidget()

    assert isinstance(feature_page, _PayloadProbe)
    assert feature_page.activations == [payload]
    assert emitted_routes[-1] == WorkspaceRoute("apps", "manager", "device-1")
    assert emitted_routes[-1].payload is None

    page.deactivate()
    page.activate()

    assert feature_page.activations == [payload, None]


def test_no_device_payload_survives_until_first_real_session_activation(
    qt_application,
):
    host, page = _workspace()
    payload = {"package_name": "example.package"}

    assert page.open_route(WorkspaceRoute("apps", "manager", payload=payload)) is True
    assert page.current_route == WorkspaceRoute("apps", "manager")

    page.activate()

    assert host.pending_route == WorkspaceRoute("apps", "manager", payload=payload)
    assert host.registry.keys() == ()

    page.deactivate()
    # 模拟 MainFrame 从历史恢复同一稳定位置；该路由不携带一次性参数。
    assert page.open_route(WorkspaceRoute("apps", "manager")) is True
    assert host.pending_route == WorkspaceRoute("apps", "manager", payload=payload)
    host.set_device_context(["device-1"], ["device-1"])
    page.activate()
    feature_page = host.stack.currentWidget()

    assert isinstance(feature_page, _PayloadProbe)
    assert feature_page.activations == [payload]
    assert host.pending_route is None

    page.deactivate()
    page.activate()

    assert feature_page.activations == [payload, None]
