"""原生客户端排队必须遵守请求预算与停止边界，恢复不能改变服务目标。"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import adb_runtime, adb_transport
from core import exec as execution
from core.native_process import NativeCommandScope


class _ObservedLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def acquire(self, *args, **kwargs):
        self.waiting.set()
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


@pytest.fixture
def client_boundary(monkeypatch):
    lock = _ObservedLock()
    for module in (adb_transport, adb_runtime, execution):
        monkeypatch.setattr(module, "adb_client_lock", lock)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution, "resolve_command", lambda command: list(command))
    monkeypatch.setattr(execution, "_launch_command", lambda command: list(command))
    spawn = Mock(return_value=SimpleNamespace(returncode=0, stdout="fixture", stderr=""))
    monkeypatch.setattr(execution, "run_native", spawn)
    native_spawn = Mock(side_effect=AssertionError("排队失败不能创建进程"))
    monkeypatch.setattr(adb_runtime, "popen_native", native_spawn)
    return SimpleNamespace(lock=lock, spawn=spawn, native_spawn=native_spawn)


def _while_client_busy(boundary, action, stop=None):
    boundary.lock.lock.acquire()
    finished = threading.Event()
    result = {}

    def request():
        try:
            result["value"] = action()
        except BaseException as error:
            result["error"] = error
        finally:
            finished.set()

    worker = threading.Thread(target=request)
    worker.start()
    try:
        assert boundary.lock.waiting.wait(1), "请求没有进入客户端排队"
        if stop is not None:
            stop()
        completed_before_release = finished.wait(0.6)
    finally:
        boundary.lock.release()
        worker.join(1)
    assert not worker.is_alive(), "请求没有释放线程"
    assert "error" not in result, result.get("error")
    return completed_before_release, result["value"]


def test_native_timeout_while_queued_never_spawns(client_boundary):
    completed, result = _while_client_busy(
        client_boundary,
        lambda: adb_runtime.native_capture(["adb.exe", "version"], 0.05, lambda: False),
    )
    assert completed
    assert result.kind == "timeout"
    client_boundary.native_spawn.assert_not_called()


@pytest.mark.parametrize("stop_kind", ["cancel", "scope"])
def test_native_stop_while_queued_never_spawns(client_boundary, stop_kind):
    cancelled = threading.Event()
    scope = NativeCommandScope()
    completed, result = _while_client_busy(
        client_boundary,
        lambda: adb_runtime.native_capture(
            ["adb.exe", "shell", "fixture"], 10, cancelled.is_set, command_scope=scope,
        ),
        cancelled.set if stop_kind == "cancel" else scope.request_stop,
    )
    assert completed
    assert result.kind == "cancelled"
    assert not scope.is_running()
    client_boundary.native_spawn.assert_not_called()


@pytest.mark.parametrize("entry", ["command", "file"])
def test_command_timeout_while_queued_never_spawns(client_boundary, tmp_path, entry):
    def request():
        if entry == "file":
            return execution.CommandRunner.run_to_file(
                ["adb.exe", "exec-out", "fixture"], str(tmp_path / "output"), timeout=0.05,
            )
        return execution.CommandRunner.run(["adb.exe", "version"], timeout=0.05)

    completed, result = _while_client_busy(client_boundary, request)
    assert completed
    assert result.outcome == "timed_out"
    assert execution.CommandRunner.active_count() == 0
    client_boundary.spawn.assert_not_called()


@pytest.mark.parametrize("entry", ["command", "file"])
def test_command_preserves_unconfirmed_cleanup_failure(client_boundary, tmp_path, entry):
    failure = "native client exit could not be confirmed"
    client_boundary.spawn.side_effect = TimeoutError(failure)

    if entry == "file":
        result = execution.CommandRunner.run_to_file(
            ["adb.exe", "exec-out", "fixture"], str(tmp_path / "output"), timeout=1,
        )
    else:
        result = execution.CommandRunner.run(["adb.exe", "version"], timeout=1)

    assert result.outcome == "failed"
    assert result.error == failure
    assert execution.CommandRunner.active_count() == 0
    assert client_boundary.lock.lock.acquire(blocking=False)
    client_boundary.lock.release()


@pytest.mark.parametrize("variable,value", [
    ("ADB_SERVER_SOCKET", "tcp:127.0.0.1:15037"),
    ("ANDROID_ADB_SERVER_ADDRESS", "fixture-host"),
    ("ANDROID_ADB_SERVER_PORT", "15037"),
])
def test_protocol_fault_preserves_custom_server(client_boundary, monkeypatch, variable, value):
    for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, value)
    client_boundary.spawn.return_value = SimpleNamespace(
        returncode=1, stdout="", stderr="failed to check server version: protocol fault",
    )
    direct = Mock(return_value=adb_transport.ExecutionResult(stdout=b"fixture-local\tdevice\n"))
    monkeypatch.setattr(adb_transport, "capture", direct)
    monkeypatch.setattr(execution.time, "sleep", lambda _: None)

    result = execution.CommandRunner.run(["adb.exe", "devices"])

    assert not result.success
    assert "failed to check server version" in result.error
    direct.assert_not_called()


def test_protocol_fault_recovery_keeps_original_deadline(client_boundary, monkeypatch):
    for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
        monkeypatch.delenv(name, raising=False)
    clock = [100.0]
    monkeypatch.setattr(execution.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(execution, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(
        execution.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    def fail_native(*_args, **_kwargs):
        clock[0] += 0.08
        return SimpleNamespace(returncode=1, stdout="", stderr="failed to check server version")

    client_boundary.spawn.side_effect = fail_native
    direct = Mock(return_value=adb_transport.ExecutionResult(kind="unavailable"))
    monkeypatch.setattr(adb_transport, "capture", direct)

    result = execution.CommandRunner.run(["adb.exe", "devices"], timeout=0.1)

    assert result.outcome == "timed_out"
    assert client_boundary.spawn.call_count == 1
    direct.assert_not_called()


def test_protocol_fault_retry_preparation_cannot_spawn_after_deadline(client_boundary, monkeypatch):
    for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
        monkeypatch.delenv(name, raising=False)
    clock = [100.0]
    monkeypatch.setattr(execution.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        execution.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    def prepare(command):
        clock[0] += 0.2
        return list(command)

    monkeypatch.setattr(execution, "_launch_command", prepare)
    monkeypatch.setattr(
        adb_transport, "capture",
        Mock(return_value=adb_transport.ExecutionResult(kind="unavailable")),
    )
    result = execution._devices_after_server_protocol_fault(
        ["adb.exe", "devices"],
        adb_transport.ExecutionResult(stderr=b"failed to check server version", returncode=1),
        0.9,
    )

    assert result is not None and result.kind == "timeout"
    client_boundary.spawn.assert_not_called()
