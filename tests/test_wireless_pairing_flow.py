"""真实窗口、Qt 协调器和配对服务的离线信号链验收。"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import SmoothScrollArea
from shiboken6 import isValid

from adblab.presentation.qt_adb_pairing import QtAdbPairing
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from core import settings_manager
from core.exec import CommandResult
from core.native_process import NativeCommandScope
from gui.widgets.device_connection import DeviceConnectionPanel
from models.device_store import DeviceStore
from services.adb_pairing import PairingContext, PairingService
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui

PAIR = "192.0.2.18:37123"
CONNECT = "192.0.2.18:42222"
GUID = "adb-synthetic-flow-guid"
TRANSPORT = GUID + "._adb-tls-connect._tcp"
HEADER = "List of discovered mdns services"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wait(self, cancel_event, seconds):
        self.now += seconds
        return cancel_event.is_set()


@pytest.fixture
def flow(qt_application, monkeypatch, tmp_path):
    """历史显式传空，设置路径指向临时目录；命令完全注入且不解析真实 ADB。"""
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(settings_manager.AppSettings, "_instance", None)

    def forbidden_history(*_args, **_kwargs):
        pytest.fail("连接窗口集成测试不得读取用户设备历史")

    monkeypatch.setattr(DeviceStore, "load", forbidden_history)
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", forbidden_history)
    instances = []

    def create(runner, *, clock=None, wait=None):
        clock = clock or Clock()
        scopes = []
        contexts = []
        calls = []
        gates = []
        path = str(tmp_path / "not-a-real-adb.exe")
        environment = {"ADB_SERVER_SOCKET": "tcp:synthetic.example:5038"}

        def command(argv, **kwargs):
            assert argv[0] == path
            assert kwargs["shell"] is False and kwargs["native_only"] is True
            assert kwargs["env"] == environment
            assert kwargs["command_scope"] in scopes
            calls.append(tuple(argv[1:]))
            return runner(argv[1:], kwargs)

        def context(revision):
            value = PairingContext(path, environment, revision)
            contexts.append(value)
            return value

        def scope():
            value = NativeCommandScope()
            scopes.append(value)
            return value

        supervisor = QtTaskSupervisor()
        coordinator = QtAdbPairing(
            supervisor,
            service_factory=lambda: PairingService(
                command_runner=command,
                clock=clock,
                wait=wait or clock.wait,
            ),
            scope_factory=scope,
            context_factory=context,
        )
        host = SmoothScrollArea()
        host.setWidgetResizable(True)
        host.resize(800, 680)
        content = QWidget()
        layout = QVBoxLayout(content)
        window = DeviceConnectionPanel(coordinator, history=(), parent=content)
        layout.addWidget(window)
        layout.addStretch()
        host.setWidget(content)
        harness = SimpleNamespace(
            coordinator=coordinator,
            supervisor=supervisor,
            window=window,
            host=host,
            scopes=scopes,
            contexts=contexts,
            calls=calls,
            gates=gates,
            clock=clock,
        )
        instances.append(harness)
        host.show()
        qt_application.processEvents()
        return harness

    yield create
    for harness in instances:
        for gate in harness.gates:
            gate.set()
        harness.coordinator.prepare_shutdown()
        stopped = QSignalSpy(harness.supervisor.application_stopped)
        harness.supervisor.stop_all_async(deadline=1)
        wait_until(qt_application, lambda: stopped.count() == 1 and not harness.coordinator.busy)
        assert all(scope.wait(0) and not scope.is_running() for scope in harness.scopes)
        harness.window.prepare_shutdown()
        harness.window.close()
        harness.host.close()
        harness.host.deleteLater()
        harness.coordinator.deleteLater()
        harness.supervisor.deleteLater()
    qt_application.processEvents()


def ok(output):
    return CommandResult(True, output=output)


def test_qr_visible_ack_drives_real_service_to_verified_connected(flow, qt_application):
    discovered = threading.Event()
    release = threading.Event()
    request = None

    def runner(args, kwargs):
        if args == ["mdns", "check"]:
            return ok("mdns daemon version [Openscreen discovery 0.0.0]")
        if args == ["mdns", "services"]:
            discovered.set()
            assert release.wait(3)
            assert request is not None
            return ok(f"{HEADER}\n{request.service_name} _adb-tls-pairing._tcp. {PAIR}")
        if args == ["pair", PAIR]:
            assert kwargs["input_bytes"] == (request.secret + "\n").encode("ascii")
            return ok(f"Enter pairing code: Successfully paired to {PAIR} [guid={GUID}]")
        assert args == ["devices"]
        return ok(f"List of devices attached\nUSB-synthetic\tdevice\n{TRANSPORT}\tdevice")

    harness = flow(runner)
    harness.gates.append(release)
    window, coordinator = harness.window, harness.coordinator
    connected = QSignalSpy(coordinator.connected)
    window.expand()
    worker = coordinator._worker
    request = worker.request
    wait_until(qt_application, discovered.is_set)

    # mDNS services 只能发生在真实视图已加载 PNG 并完成可见确认之后。
    assert window.isVisible() and window.qr_label.isVisible()
    assert window._qr_acknowledged
    pixmap = window.qr_label.pixmap()
    assert not pixmap.isNull()
    viewport = window.scroll_area.viewport()
    origin = window.qr_label.mapTo(viewport, QPoint())
    side = pixmap.width() / pixmap.devicePixelRatioF()
    top = origin.y() + (window.qr_label.height() - side) / 2
    assert 0 <= top and top + side <= viewport.height()
    assert coordinator.busy and connected.count() == 0
    release.set()

    wait_until(qt_application, lambda: connected.count() == 1 and not coordinator.busy)
    outcome = connected.at(0)[0]
    assert outcome.connected and outcome.device_id == TRANSPORT and outcome.guid == GUID
    assert coordinator.accepts_outcome(outcome)
    assert coordinator.state == "Connected" and window.status_label.text()
    assert window._qr_image.isNull() and window.pairing_code.text() == ""
    assert harness.calls == [
        ("mdns", "check"),
        ("mdns", "services"),
        ("pair", PAIR),
        ("devices",),
    ]
    assert harness.supervisor.supervisor.active_count == 0
    assert not harness.scopes[0].is_running()
    wait_until(qt_application, lambda: not isValid(worker))


def test_manual_paired_only_continues_through_real_guid_verification(flow, qt_application):
    connecting = False

    def runner(args, kwargs):
        nonlocal connecting
        if args == ["mdns", "check"]:
            return ok("mdns daemon version [Bonjour 1.0]")
        if args == ["pair", PAIR]:
            assert kwargs["input_bytes"] == b"001234\n"
            return ok(f"Successfully paired to {PAIR} [guid={GUID}]")
        if args == ["connect", CONNECT]:
            connecting = True
            return ok("connected")
        if args == ["devices"]:
            return ok("List of devices attached" + (f"\n{CONNECT}\tdevice" if connecting else ""))
        if args == ["mdns", "services"]:
            return CommandResult(False, error="mdns disabled")
        assert args == ["-s", CONNECT, "shell", "getprop", "persist.adb.wifi.guid"]
        return ok(GUID)

    harness = flow(runner)
    window, coordinator = harness.window, harness.coordinator
    connected = QSignalSpy(coordinator.connected)
    results = QSignalSpy(coordinator.outcome_ready)
    window.expand()
    window.request_page("manual")
    wait_until(qt_application, lambda: window.current_page == "manual" and not coordinator.busy)
    window.pairing_address.setText(PAIR)
    window.pairing_code.setText("001234")
    assert window.pair_button.isEnabled()
    window.pair_button.click()
    assert window.pairing_code.text() == ""
    wait_until(qt_application, lambda: coordinator.state == "PairedOnly" and not coordinator.busy)
    first = results.at(0)[0]
    context_count = len(harness.contexts)
    assert first.paired and not first.connected and connected.count() == 0
    assert harness.clock.now == 30.0
    assert window.continuation_box.isVisible() and coordinator.continuation is not None
    window.connection_address.setText(CONNECT)
    assert window.continue_button.isEnabled()
    window.continue_button.click()

    wait_until(qt_application, lambda: connected.count() == 1 and not coordinator.busy)
    outcome = connected.at(0)[0]
    assert outcome.request_id != first.request_id
    assert outcome.context_revision == first.context_revision
    assert outcome.device_id == outcome.connection_endpoint == CONNECT
    assert coordinator.accepts_outcome(outcome) and coordinator.state == "Connected"
    assert harness.calls.count(("pair", PAIR)) == 1
    assert harness.calls.count(("connect", CONNECT)) == 1
    assert harness.calls[-1] == ("-s", CONNECT, "shell", "getprop", "persist.adb.wifi.guid")
    assert len(harness.contexts) == context_count
    assert harness.supervisor.supervisor.active_count == 0
    assert all(scope.wait(0) and not scope.is_running() for scope in harness.scopes)


def test_close_during_real_scan_releases_resources_without_late_connected(flow, qt_application):
    waiting = threading.Event()

    def wait(cancel_event, seconds):
        waiting.set()
        return cancel_event.wait(seconds)

    def runner(args, kwargs):
        if args == ["mdns", "check"]:
            return ok("mdns daemon version [Bonjour 1.0]")
        assert args == ["mdns", "services"]
        return ok(HEADER)

    harness = flow(runner, wait=wait)
    window, coordinator = harness.window, harness.coordinator
    connected = QSignalSpy(coordinator.connected)
    collapsed = QSignalSpy(window.expanded_changed)
    window.expand()
    worker = coordinator._worker
    wait_until(qt_application, lambda: waiting.is_set() and coordinator.state == "WaitingForScan")
    assert window._qr_acknowledged and coordinator.busy
    window.close()
    assert not window.isVisible() and not window.is_expanded
    wait_until(qt_application, lambda: collapsed.count() == 2 and not coordinator.busy)
    wait_until(qt_application, lambda: not isValid(worker))
    assert not window.isVisible() and window._qr_image.isNull()
    assert coordinator.state == "Idle" and connected.count() == 0
    assert harness.supervisor.supervisor.active_count == 0
    assert all(scope.wait(0) and not scope.is_running() for scope in harness.scopes)
    assert not any(command[0] in {"pair", "connect"} for command in harness.calls)
