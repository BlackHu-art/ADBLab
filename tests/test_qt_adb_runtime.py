"""ADB 运行实例的 Qt 延迟启动、扫描、展示和资源收口验证。"""

import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtWidgets import QWidget

from adblab.presentation.qt_adb_runtime import QtAdbRuntime
from core import adb_transport
from core import exec as execution
from core.adb_runtime import RuntimeSnapshot
from gui.main_frame import _ScanThread
from gui.pages.fluent_pages import SettingsPage


def test_adapter_defers_resolution_and_cancels_before_event_loop(monkeypatch):
    resolver = Mock(return_value=None)
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", resolver)
    owner = QObject()
    adapter = QtAdbRuntime(owner)
    adapter.schedule()
    resolver.assert_not_called()
    adapter.prepare_shutdown()
    QCoreApplication.processEvents()
    resolver.assert_not_called()
    adapter.close()
    assert adapter.runtime.wait(1)


def test_adapter_publishes_ready_on_gui_thread_and_releases_runtime(monkeypatch):
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", lambda: None)
    adapter = QtAdbRuntime()
    delivered = []
    adapter.ready.connect(lambda: delivered.append(threading.get_ident()))
    adapter.schedule()
    QCoreApplication.processEvents()
    assert adapter.runtime.wait(2)
    QCoreApplication.processEvents()
    assert delivered == [threading.get_ident()]
    assert execution.adb_runtime() is adapter.runtime
    adapter.close()
    assert execution.adb_runtime() is None


def test_fast_scan_runs_while_other_commands_are_busy(monkeypatch):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    monkeypatch.setattr(execution.CommandRunner, "active_count", lambda: 1)
    thread = _ScanThread()
    snapshots = []
    thread.devices_changed.connect(snapshots.append)
    run = Mock(return_value=execution.CommandResult(True, "List of devices attached\nfake\tdevice"))
    monkeypatch.setattr(execution.CommandRunner, "run", run)
    monkeypatch.setattr(thread, "_sleep_interruptibly", lambda _: True)
    native = Mock()
    monkeypatch.setattr("gui.main_frame.ProcessRunner", native)
    thread.run()
    assert snapshots == [["fake"]]
    assert run.call_args.args[0] == ["adb", "devices", "-l"]
    assert not run.call_args.kwargs["cancelled"]()
    thread.stop()
    assert run.call_args.kwargs["cancelled"]()
    native.assert_not_called()


@pytest.mark.parametrize("busy", [False, True])
def test_scan_requests_recovery_before_busy_gate_or_failed_native_scan(monkeypatch, busy):
    runtime = Mock()
    runtime.can_scan_fast.return_value = False
    events = []
    runtime.request_device_check.side_effect = lambda: events.append("check")
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)

    def active_count():
        events.append("busy")
        return int(busy)

    monkeypatch.setattr(execution.CommandRunner, "active_count", active_count)
    thread = _ScanThread()

    def failed_scan(_runner):
        events.append("native")
        return None

    monkeypatch.setattr(thread, "_run_devices_scan", failed_scan)
    monkeypatch.setattr(thread, "_sleep_interruptibly", lambda _: True)
    states = []
    thread.discovery_state_changed.connect(states.append)
    thread.run()

    assert events == (["check", "busy"] if busy else ["check", "busy", "native"])
    assert states == ([] if busy else ["unavailable"])
    runtime.request_device_check.assert_called_once()


def test_socket_wait_is_actually_cancellable_and_closes_connection(monkeypatch):
    local, peer = socket.socketpair()
    stop, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(adb_transport.socket, "create_connection", lambda *a, **k: local)
    result = []

    def worker():
        entered.set()
        result.append(
            adb_transport.capture("devices", [], serial=None, timeout=10, cancelled=stop.is_set)
        )

    thread = threading.Thread(target=worker)
    try:
        thread.start()
        assert entered.wait(1)
        peer.settimeout(1)
        assert peer.recv(1024)
        stop.set()
        thread.join(1)
        assert not thread.is_alive()
        assert result[0].kind == "cancelled"
        assert peer.recv(1) == b""
    finally:
        stop.set()
        local.close()
        peer.close()
        thread.join(1)


def test_settings_reports_partial_acceleration_and_session_override():
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_native_only=Mock(),
    )
    parent = QWidget()
    page = SettingsPage(frame, parent)
    try:
        page.update_adb_environment(RuntimeSnapshot(True, True, False, True, 2, 2))
        assert "2" in page.adb_check_card.contentLabel.text()
        assert not page.adb_check_card.button.isEnabled()
        page.update_adb_environment(RuntimeSnapshot(False, True, False, True, 2, 2))
        page.adb_check_card.button.click()
        frame.recheck_adb_environment.assert_called_once()
        page.adb_native_card.setChecked(True)
        frame.set_adb_native_only.assert_called_with(True)
        page.update_adb_environment(RuntimeSnapshot(False, True, True, False, 0, 2))
        assert "原生" in page.adb_check_card.contentLabel.text()
    finally:
        page.close()


@pytest.mark.parametrize("kind", ["timeout", "protocol"])
def test_fast_scan_failure_preserves_last_snapshot(monkeypatch, kind):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    results = iter(
        [
            execution.CommandResult(True, "List of devices attached\nfake\tdevice"),
            execution.CommandResult(False, error=kind),
        ]
    )
    monkeypatch.setattr(execution.CommandRunner, "run", lambda *a, **k: next(results))
    thread = _ScanThread()
    snapshots, states = [], []
    thread.devices_changed.connect(snapshots.append)
    thread.discovery_state_changed.connect(states.append)
    pauses = iter([False, True])
    monkeypatch.setattr(thread, "_sleep_interruptibly", lambda _: next(pauses))
    thread.run()
    assert snapshots == [["fake"]]
    assert states == ["unavailable"]


def test_superseded_scan_keeps_snapshot_and_state_and_waits_normally(monkeypatch):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    results = iter([
        execution.CommandResult(True, "List of devices attached\ncurrent\tdevice"),
        execution.CommandResult(False, stale=True),
        execution.CommandResult(True, "List of devices attached\ncurrent\tdevice"),
    ])
    run = Mock(side_effect=lambda *a, **k: next(results))
    monkeypatch.setattr(execution.CommandRunner, "run", run)
    thread = _ScanThread()
    snapshots, states = [], []
    thread.devices_changed.connect(snapshots.append)
    thread.discovery_state_changed.connect(states.append)
    pauses = Mock(side_effect=[False, False, True])
    monkeypatch.setattr(thread, "_sleep_interruptibly", pauses)
    thread.run()
    assert snapshots == [["current"]]
    assert states == []
    assert run.call_count == pauses.call_count == 3
