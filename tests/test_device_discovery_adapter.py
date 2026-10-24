"""设备发现归位后，旧入口仍执行新 owner 的边界并保留代次与清理语义。"""

import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def discovery_boundary(tmp_path, monkeypatch):
    for name in (
        "LOCALAPPDATA",
        "APPDATA",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "MOBILEPERF_LOG_DIR",
    ):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    from shiboken6 import delete, isValid

    discovery = importlib.import_module("adblab.presentation.qt_device_discovery")
    from core import adb_transport
    from core import exec as execution
    from gui import main_frame

    forbidden = []

    def unexpected(*args, **kwargs):
        forbidden.append((args, kwargs))
        raise AssertionError("设备发现测试触及未替换的执行边界")

    monkeypatch.setattr(execution, "popen_native", unexpected)
    monkeypatch.setattr(execution.CommandRunner, "run", unexpected)
    monkeypatch.setattr(execution.ProcessRunner, "start", unexpected)
    monkeypatch.setattr(adb_transport, "capture", unexpected)
    monkeypatch.setattr(discovery, "adb_runtime", lambda: None)
    monkeypatch.setattr(discovery, "acquire_adb_client", unexpected)
    monkeypatch.setattr(discovery, "ProcessRunner", unexpected)
    monkeypatch.setattr(
        discovery, "CommandRunner", SimpleNamespace(active_count=lambda: 0, run=unexpected)
    )
    monkeypatch.setattr(discovery, "local_server_environment", unexpected)
    monkeypatch.setattr(discovery, "cancel_and_drain_native", unexpected)
    monkeypatch.setattr(discovery, "close_native_pipes", unexpected)
    scans = []

    def make_scan(**kwargs):
        scan = main_frame._ScanThread(**kwargs)
        scans.append(scan)
        return scan

    yield SimpleNamespace(discovery=discovery, legacy=main_frame, make_scan=make_scan)
    for scan in reversed(scans):
        if isValid(scan):
            scan.stop()
            delete(scan)
    assert forbidden == [], "所有设备执行边界都必须由用例显式替换"


def test_scan_classes_are_identical_through_legacy_entry(discovery_boundary):
    from PySide6.QtCore import QObject
    from shiboken6 import delete

    boundary = discovery_boundary
    for name in ("_ScanThread", "_ScannedDevices", "_ScanDiscoveryState"):
        assert getattr(boundary.legacy, name) is getattr(boundary.discovery, name)
    assert boundary.legacy._ScanThread.__module__ == "adblab.presentation.qt_device_discovery"
    owner = QObject()
    try:
        scan = boundary.make_scan(parent=owner, interval_ms=1)
        assert scan.parent() is owner
        assert scan._interval_ms == 3000
        assert boundary.make_scan()._interval_ms == 15000
    finally:
        delete(owner)


def test_adapter_import_does_not_load_main_frame_or_fluent_widgets(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for name in (
        "LOCALAPPDATA",
        "APPDATA",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "MOBILEPERF_LOG_DIR",
    ):
        env[name] = str(tmp_path / name.lower())
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import subprocess
import sys

def forbidden(*args, **kwargs):
    raise AssertionError('import must not start a process')

subprocess.Popen.__init__ = forbidden
import adblab.presentation.qt_device_discovery
assert 'gui.main_frame' not in sys.modules
assert not any(
    name == 'qfluentwidgets' or name.startswith('qfluentwidgets.') for name in sys.modules
)
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, f"exit={result.returncode}\n{result.stdout}{result.stderr}"


@pytest.mark.parametrize("patch_time", ["before_construct", "after_construct"])
def test_legacy_entry_uses_new_runtime_and_runners_after_patch(
    discovery_boundary,
    monkeypatch,
    patch_time,
):
    from PySide6.QtCore import Qt

    boundary = discovery_boundary
    scan = boundary.make_scan() if patch_time == "after_construct" else None
    runtime = SimpleNamespace(
        request_device_check=Mock(),
        can_scan_fast=lambda: True,
        wait_for_device_check=Mock(return_value=None),
    )
    calls = []

    def run(command, *, timeout, cancelled):
        calls.append((command, timeout, cancelled))
        return SimpleNamespace(
            success=True, stale=False, output="List of devices attached\nmock-device\tdevice\n"
        )

    native = Mock(side_effect=AssertionError("快速扫描不能创建原生客户端"))
    monkeypatch.setattr(boundary.discovery, "adb_runtime", lambda: runtime)
    monkeypatch.setattr(
        boundary.discovery, "CommandRunner", SimpleNamespace(active_count=lambda: 1, run=run)
    )
    monkeypatch.setattr(boundary.discovery, "ProcessRunner", native)
    if scan is None:
        scan = boundary.make_scan()
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _delay: True)
    delivered = []
    scan.devices_changed.connect(delivered.append, Qt.ConnectionType.DirectConnection)
    scan.run()
    assert delivered == [["mock-device"]]
    assert len(calls) == 1
    command, timeout, cancelled = calls[0]
    assert command == ["adb", "devices", "-l"]
    assert 0 < timeout <= 15
    assert cancelled() is False
    scan.stop()
    assert cancelled() is True
    runtime.request_device_check.assert_called_once_with()
    runtime.wait_for_device_check.assert_called_once()
    native.assert_not_called()


@pytest.mark.parametrize("patch_time", ["before_construct", "after_construct"])
def test_legacy_entry_uses_new_clock_and_client_lock_after_patch(
    discovery_boundary,
    monkeypatch,
    patch_time,
):
    from PySide6.QtCore import Qt

    boundary = discovery_boundary
    scan = boundary.make_scan() if patch_time == "after_construct" else None
    runner = object()
    acquired = []
    released = []
    calls = []
    monkeypatch.setattr(boundary.discovery, "time", SimpleNamespace(monotonic=lambda: 100.0))
    monkeypatch.setattr(boundary.discovery, "adb_runtime", lambda: None)
    monkeypatch.setattr(
        boundary.discovery, "CommandRunner", SimpleNamespace(active_count=lambda: 0)
    )
    monkeypatch.setattr(boundary.discovery, "ProcessRunner", lambda: runner)
    monkeypatch.setattr(
        boundary.discovery,
        "acquire_adb_client",
        lambda deadline, cancelled: acquired.append((deadline, cancelled)),
    )
    monkeypatch.setattr(
        boundary.discovery,
        "adb_client_lock",
        SimpleNamespace(release=lambda: released.append(True)),
    )
    if scan is None:
        scan = boundary.make_scan()

    def execute(actual_runner, *, deadline):
        calls.append((actual_runner, deadline))
        return "List of devices attached\nmock-device\tdevice\n"

    monkeypatch.setattr(scan, "_run_devices_scan", execute)
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _delay: True)
    delivered = []
    scan.devices_changed.connect(delivered.append, Qt.ConnectionType.DirectConnection)
    scan.run()
    assert calls == [(runner, 115.0)]
    assert delivered == [["mock-device"]]
    assert len(acquired) == 1
    assert acquired[0][0] == 115.0
    assert acquired[0][1]() is False
    assert released == [True]
    scan.stop()
    assert acquired[0][1]() is True


@pytest.mark.parametrize("patch_time", ["before_construct", "after_construct"])
def test_legacy_class_start_and_msleep_patches_remain_effective(
    discovery_boundary,
    monkeypatch,
    patch_time,
):
    boundary = discovery_boundary
    scan = boundary.make_scan() if patch_time == "after_construct" else None
    started, slept = Mock(), Mock()
    monkeypatch.setattr(boundary.legacy._ScanThread, "start", started)
    monkeypatch.setattr(boundary.legacy._ScanThread, "msleep", slept)
    if scan is None:
        scan = boundary.make_scan()
    assert boundary.legacy._ScanThread is boundary.discovery._ScanThread
    scan.start()
    started.assert_called_once_with()
    assert scan._sleep_interruptibly(250) is False
    assert [call.args for call in slept.call_args_list] == [(100,), (100,), (50,)]
    scan.stop()
    assert scan._sleep_interruptibly(250) is True
    assert slept.call_count == 3


@pytest.mark.ui
def test_scan_payload_keeps_token_through_queued_delivery(
    discovery_boundary,
    monkeypatch,
    qt_application,
):
    from PySide6.QtCore import QObject, Qt, Slot
    from shiboken6 import delete

    boundary = discovery_boundary
    scan = boundary.make_scan()
    runtime = SimpleNamespace(
        request_device_check=lambda: None,
        can_scan_fast=lambda: True,
        wait_for_device_check=lambda *_args: None,
    )
    results = iter(
        [
            SimpleNamespace(
                success=True, stale=False, output="List of devices attached\nmock-device\tdevice\n"
            ),
            SimpleNamespace(success=False, stale=False, output=""),
        ]
    )
    tokens = iter([(7, 0), (8, 0)])
    monkeypatch.setattr(boundary.discovery, "adb_runtime", lambda: runtime)
    monkeypatch.setattr(
        boundary.discovery,
        "CommandRunner",
        SimpleNamespace(active_count=lambda: 0, run=lambda *_args, **_kwargs: next(results)),
    )
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _delay: True)
    scan.discovery_token = lambda: next(tokens)
    delivered = []

    class Receiver(QObject):
        @Slot(object)
        def receive(self, payload):
            delivered.append(payload)

    receiver = Receiver()
    try:
        scan.devices_changed.connect(receiver.receive, Qt.ConnectionType.QueuedConnection)
        scan.discovery_state_changed.connect(receiver.receive, Qt.ConnectionType.QueuedConnection)
        scan.run()
        scan.run()
        assert delivered == []
        qt_application.processEvents()
        assert len(delivered) == 2
        assert isinstance(delivered[0], boundary.discovery._ScannedDevices)
        assert delivered[0] == ["mock-device"]
        assert delivered[0].discovery_token == (7, 0)
        assert isinstance(delivered[1], boundary.discovery._ScanDiscoveryState)
        assert delivered[1] == "unavailable"
        assert delivered[1].discovery_token == (8, 0)
    finally:
        delete(receiver)


@pytest.mark.parametrize("failure", ["none", "drain", "close"])
def test_native_cleanup_attempts_all_finally_steps_for_exact_process(
    discovery_boundary,
    monkeypatch,
    failure,
):
    boundary = discovery_boundary
    scan = boundary.make_scan()
    events = []
    process = SimpleNamespace(returncode=None)

    def communicate(*, timeout):
        assert 0 < timeout <= 0.1
        raise OSError("synthetic output failure")

    process.communicate = communicate

    def start(key, command, **kwargs):
        assert key == "device_scan"
        assert command == ["adb", "devices"]
        assert kwargs == {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "ignore",
        }
        return process

    def drain(actual, *, timeout):
        events.append(("drain", actual, timeout))
        if failure == "drain":
            raise OSError("synthetic drain failure")

    def close(actual):
        events.append(("close", actual))
        if failure == "close":
            raise OSError("synthetic close failure")

    tracked = [process]

    def release(key, actual):
        events.append(("release", key, actual))
        if actual.returncode is not None:
            tracked.remove(actual)
            return True
        return False

    runner = SimpleNamespace(start=start, release_finished=release)
    monkeypatch.setattr(boundary.discovery, "cancel_and_drain_native", drain)
    monkeypatch.setattr(boundary.discovery, "close_native_pipes", close)
    assert scan._run_devices_scan(runner) is None
    assert events == [
        ("drain", process, 0.5),
        ("close", process),
        ("release", "device_scan", process),
    ]
    assert tracked == [process]
