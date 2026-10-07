"""原生设备扫描的取消、截止时间和输出管道归属回归。"""

from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import psutil
import pytest


@pytest.fixture
def scan_boundary(tmp_path, monkeypatch):
    """只替换本机进程启动边界，保留扫描和 ProcessRunner 的真实清理路径。"""
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "MOBILEPERF_LOG_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from core import exec as execution
    from core import settings_manager

    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(settings_manager.AppSettings, "_instance", None)
    from PySide6.QtCore import Qt

    from gui import main_frame

    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution, "resolve_command", lambda command: list(command))
    monkeypatch.setattr(execution, "_log_if_slow", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(execution.ProcessRunner, "_global_procs", {})
    monkeypatch.setattr(main_frame, "adb_runtime", lambda: None)
    scan_clock = SimpleNamespace(offset=0.0)
    monkeypatch.setattr(
        main_frame, "time",
        SimpleNamespace(monotonic=lambda: time.monotonic() + scan_clock.offset),
    )
    scan = main_frame._ScanThread()
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _delay: True)
    snapshots, states = [], []
    scan.devices_changed.connect(snapshots.append, Qt.ConnectionType.DirectConnection)
    scan.discovery_state_changed.connect(states.append, Qt.ConnectionType.DirectConnection)

    def install_spawn(spawn):
        monkeypatch.setattr(execution, "popen_native", spawn)

    def advance_scan_clock(seconds):
        scan_clock.offset += seconds

    yield SimpleNamespace(
        scan=scan, snapshots=snapshots, states=states, install_spawn=install_spawn,
        advance_scan_clock=advance_scan_clock,
    )
    scan.stop()


class _ObservedProcess:
    """保留真实 Popen 的管道行为，只通知测试 communicate 已经开始。"""

    def __init__(self, process, reading):
        self._process = process
        self._reading = reading

    def __getattr__(self, name):
        return getattr(self._process, name)

    def communicate(self, *args, **kwargs):
        self._reading.set()
        return self._process.communicate(*args, **kwargs)


@pytest.mark.parametrize("completion", ["stop", "deadline"])
def test_scan_leaves_inherited_pipe_owner_alive_without_waiting_for_eof(
    scan_boundary, tmp_path, completion,
):
    """客户端已经退出时，独立后代持有输出写端也不能绕过取消或扫描预算。"""
    release = tmp_path / "release-independent-child"
    ready = tmp_path / "independent-child.pid"
    child_code = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(ready)!r}).write_text(str(os.getpid())); "
        f"release = pathlib.Path({str(release)!r}); deadline = time.monotonic() + 10; "
        "\nwhile not release.exists() and time.monotonic() < deadline: time.sleep(0.01)"
    )
    client_code = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print('List of devices attached', flush=True)"
    )
    reading = threading.Event()
    created = []

    def spawn(_command, **kwargs):
        kwargs.pop("isolate", None)
        process = subprocess.Popen([sys.executable, "-c", client_code], **kwargs)
        created.append(process)
        # 先确认客户端退出，以确保走到旧实现的无界 communicate 分支。
        process.wait(timeout=3)
        return _ObservedProcess(process, reading)

    scan_boundary.install_spawn(spawn)
    scan_boundary.scan.SCAN_CALL_TIMEOUT_S = 30
    worker = threading.Thread(target=scan_boundary.scan.run, daemon=True)
    independent = None
    try:
        worker.start()
        assert reading.wait(3), "扫描未进入输出读取"
        ready_deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < ready_deadline:
            threading.Event().wait(0.01)
        assert ready.exists(), "合成独立后代未启动"
        independent = psutil.Process(int(ready.read_text()))
        if completion == "stop":
            scan_boundary.scan.stop()
        else:
            # 只推进扫描预算，进程启动和 core 清理仍使用真实时钟。
            scan_boundary.advance_scan_clock(scan_boundary.scan.SCAN_CALL_TIMEOUT_S + 1)
        worker.join(1.5)
        assert not worker.is_alive(), "扫描仍在等待独立后代关闭输出管道"
        assert independent.is_running(), "扫描清理不能终止独立的管道拥有者"
        assert scan_boundary.snapshots == []
        assert scan_boundary.states == ([] if completion == "stop" else ["unavailable"])
    finally:
        scan_boundary.scan.stop()
        release.touch()
        worker.join(4)
        assert not worker.is_alive(), "测试释放输出写端后扫描仍未退出"
        if independent is None and ready.exists():
            try:
                independent = psutil.Process(int(ready.read_text()))
            except psutil.NoSuchProcess:
                independent = None
        if independent is not None:
            independent.wait(timeout=3)
        for process in created:
            process.wait(timeout=3)
            process.communicate(timeout=3)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


class _CompletedClient:
    def __init__(self, *, text, read_error=False):
        self.returncode = 0
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.stdin = None
        self._text = text
        self._read_error = read_error

    def poll(self):
        return self.returncode

    def communicate(self, *args, **kwargs):
        if self._read_error:
            raise OSError("synthetic output read failure")
        output = "List of devices attached\nsynthetic-device\tdevice\n"
        return (output, "") if self._text else (output.encode(), b"")


def test_scan_closes_owned_output_streams_after_read_failure(scan_boundary):
    clients = []

    def spawn(_command, **kwargs):
        client = _CompletedClient(text=kwargs.get("text", False), read_error=True)
        clients.append(client)
        return client

    scan_boundary.install_spawn(spawn)
    scan_boundary.scan.run()

    assert len(clients) == 1
    assert scan_boundary.snapshots == []
    assert scan_boundary.states == ["unavailable"]
    assert clients[0].stdout.closed
    assert clients[0].stderr.closed


def test_native_scan_publishes_completed_device_snapshot(scan_boundary):
    scan_boundary.install_spawn(
        lambda _command, **kwargs: _CompletedClient(text=kwargs.get("text", False)),
    )

    scan_boundary.scan.run()

    assert scan_boundary.snapshots == [["synthetic-device"]]
    assert scan_boundary.states == []
