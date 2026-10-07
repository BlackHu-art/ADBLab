"""扫描异常不能丢弃自有客户端的跟踪，也不能发布伪成功快照。"""

from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def scan_cleanup_boundary(tmp_path, monkeypatch):
    """只隔离外部环境和进程创建，保留真实扫描及进程登记逻辑。"""
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "MOBILEPERF_LOG_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    from core import exec as execution
    from core import settings_manager
    from utils import adb_debug

    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(settings_manager.AppSettings, "_instance", None)
    from PySide6.QtCore import Qt

    from gui import main_frame

    monkeypatch.setattr(execution, "resolve_command", lambda command: list(command))
    monkeypatch.setattr(adb_debug, "command", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(execution.ProcessRunner, "_global_procs", {})
    monkeypatch.setattr(main_frame, "adb_runtime", lambda: None)
    scan = main_frame._ScanThread()
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _delay: True)
    snapshots, states = [], []
    scan.devices_changed.connect(snapshots.append, Qt.ConnectionType.DirectConnection)
    scan.discovery_state_changed.connect(states.append, Qt.ConnectionType.DirectConnection)
    yield SimpleNamespace(
        scan=scan, execution=execution, snapshots=snapshots, states=states,
    )
    scan.stop()


class _UnconfirmedClient:
    """终止可能被拒绝或无法确认退出；仅测试显式改变退出状态。"""

    def __init__(self, failure: str):
        self.failure = failure
        self.returncode = None
        self.stdin = None
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def poll(self):
        return self.returncode

    def terminate(self):
        if self.failure == "kill":
            raise OSError("synthetic termination denied")

    def kill(self):
        if self.failure == "kill":
            raise OSError("synthetic termination denied")

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic-device-scan", timeout)
        return self.returncode

    def communicate(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic-device-scan", timeout)
        return "", ""


@pytest.mark.parametrize("failure", ["kill", "wait"])
def test_scan_retains_unconfirmed_client_until_exact_instance_exits(
    scan_cleanup_boundary, monkeypatch, failure,
):
    boundary = scan_cleanup_boundary
    execution = boundary.execution
    runner = execution.ProcessRunner()
    client = _UnconfirmedClient(failure)

    def spawn(_command, **_kwargs):
        boundary.scan.stop()
        return client

    monkeypatch.setattr(execution, "popen_native", spawn)
    try:
        assert boundary.scan._run_devices_scan(runner) is None
        assert client.poll() is None
        assert runner.active_keys == ["device_scan"]
        assert execution.ProcessRunner.tracked_active_count() == 1
        assert not runner.release_finished("device_scan", client)

        client.returncode = -9
        assert runner.release_finished("device_scan", client)
        assert runner.active_keys == []
        assert execution.ProcessRunner.tracked_active_count() == 0

        replacement = _UnconfirmedClient(failure)
        monkeypatch.setattr(execution, "popen_native", lambda *_args, **_kwargs: replacement)
        runner.start("device_scan", ["adb", "devices"])
        try:
            assert not runner.release_finished("device_scan", client)
            assert runner.active_keys == ["device_scan"]
            assert execution.ProcessRunner.tracked_active_count() == 1
        finally:
            replacement.returncode = -9
            assert runner.release_finished("device_scan", replacement)
            replacement.stdout.close()
            replacement.stderr.close()
        assert execution.ProcessRunner.tracked_active_count() == 0
    finally:
        client.returncode = -9
        runner.release_finished("device_scan", client)
        client.stdout.close()
        client.stderr.close()


def test_scan_start_failure_publishes_unavailable_without_device_snapshot(
    scan_cleanup_boundary, monkeypatch,
):
    boundary = scan_cleanup_boundary

    def fail_spawn(_command, **_kwargs):
        raise OSError("synthetic process creation failure")

    monkeypatch.setattr(boundary.execution, "popen_native", fail_spawn)
    boundary.scan.run()

    assert boundary.snapshots == []
    assert boundary.states == ["unavailable"]
    assert boundary.execution.ProcessRunner.tracked_active_count() == 0
