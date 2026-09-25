"""原生命令输入与会话资源归属，使用受控进程替身覆盖启动和取消交错。"""

from __future__ import annotations

import io
import os
import subprocess
import threading

import pytest

from core import adb_runtime, native_process


class ControlledProcess:
    def __init__(self):
        self.returncode = None
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.inputs = []
        self.kill_count = 0
        self.wait_count = 0
        self.poll_error = False
        self.exit_on_kill = True
        self.communicate_timeout = False

    def poll(self):
        if self.poll_error:
            raise OSError("synthetic poll failure")
        return self.returncode

    def kill(self):
        self.kill_count += 1
        if self.exit_on_kill:
            self.returncode = -9

    def wait(self, timeout):
        self.wait_count += 1
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic", timeout)
        return self.returncode

    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if self.communicate_timeout:
            self.communicate_timeout = False
            raise subprocess.TimeoutExpired("synthetic", timeout)
        self.returncode = 0 if self.returncode is None else self.returncode
        return b"done", b""


def new_scope():
    scope_type = getattr(native_process, "NativeCommandScope", None)
    assert scope_type is not None, "会话需要在 popen 前登记并保留未退出客户端"
    return scope_type()


def test_capture_sends_input_only_on_first_communicate(monkeypatch):
    process = ControlledProcess()
    process.communicate_timeout = True
    observed = []

    def spawn(command, **kwargs):
        observed.append((command, kwargs))
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    result = adb_runtime.native_capture(
        ["synthetic", "pair", "example.test:1234"], 1, lambda: False,
        input_bytes=b"123456\n",
    )
    assert result.kind == "completed"
    assert process.inputs == [b"123456\n", None]
    assert observed[0][1]["stdin"] == subprocess.PIPE
    assert b"123456" not in repr(observed[0][0]).encode()


def test_capture_copies_environment_and_preserves_default_stdin(monkeypatch):
    environment = {"ADB_SERVER_SOCKET": "tcp:localhost:5038", "ADB_TRACE": ""}
    parent = dict(os.environ)
    observed = []

    def spawn(_command, **kwargs):
        observed.append(dict(kwargs["env"]))
        assert kwargs["stdin"] == subprocess.DEVNULL
        kwargs["env"]["ADB_TRACE"] = "synthetic child mutation"
        return ControlledProcess()

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    result = adb_runtime.native_capture(["synthetic"], 1, lambda: False, env=environment)
    assert result.kind == "completed"
    assert observed == [{"ADB_SERVER_SOCKET": "tcp:localhost:5038", "ADB_TRACE": ""}]
    assert environment == observed[0]
    assert dict(os.environ) == parent


def test_scope_tracks_spawn_window_and_cancels_late_process(monkeypatch):
    scope = new_scope()
    entered = threading.Event()
    release = threading.Event()
    process = ControlledProcess()
    results = []

    def spawn(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    worker = threading.Thread(target=lambda: results.append(adb_runtime.native_capture(
        ["synthetic"], 5, lambda: False, command_scope=scope,
    )))
    worker.start()
    try:
        assert entered.wait(2)
        assert scope.is_running()
        scope.request_stop()
        scope.request_stop()
        assert not scope.wait(0.01)
        assert process.kill_count == 0
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert results[0].kind == "cancelled"
        assert process.kill_count == 1
        assert process.poll() is not None
        assert scope.wait(0) and not scope.is_running()
    finally:
        release.set()
        worker.join(2)


def test_stopped_scope_never_starts_a_new_process(monkeypatch):
    scope = new_scope()
    scope.request_stop()

    def forbidden(*_args, **_kwargs):
        pytest.fail("停止后的作用域不能再创建客户端")

    monkeypatch.setattr(adb_runtime, "popen_native", forbidden)
    result = adb_runtime.native_capture(["synthetic"], 1, lambda: False, command_scope=scope)
    assert result.kind == "cancelled"
    assert scope.wait(0)


def test_spawn_failure_releases_pending_registration(monkeypatch):
    scope = new_scope()

    def spawn(*_args, **_kwargs):
        assert scope.is_running()
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    result = adb_runtime.native_capture(["synthetic"], 1, lambda: False, command_scope=scope)
    assert result.kind == "transport"
    assert not scope.is_running() and scope.wait(0)


def test_normal_completion_releases_scope_for_next_command(monkeypatch):
    scope = new_scope()
    processes = []

    def spawn(*_args, **_kwargs):
        process = ControlledProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    for _ in range(2):
        result = adb_runtime.native_capture(["synthetic"], 1, lambda: False, command_scope=scope)
        assert result.kind == "completed"
        assert not scope.is_running() and scope.wait(0)
    assert len(processes) == 2


def test_cleanup_timeout_retains_handle_and_refuses_next_spawn(monkeypatch):
    scope = new_scope()
    process = ControlledProcess()
    process.exit_on_kill = False
    cancelled = threading.Event()
    spawns = []

    def spawn(*_args, **_kwargs):
        spawns.append(process)
        cancelled.set()
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    result = adb_runtime.native_capture(["synthetic"], 1, cancelled.is_set, command_scope=scope)
    assert result.kind == "transport"
    assert scope.is_running()
    rejected = adb_runtime.native_capture(["synthetic"], 1, lambda: False, command_scope=scope)
    assert rejected.kind == "transport"
    assert len(spawns) == 1
    scope.request_stop()
    assert not scope.wait(0.01)
    assert scope.is_running()
    process.exit_on_kill = True
    assert scope.wait(0.5)
    assert process.poll() is not None
    assert not scope.is_running()


def test_poll_failure_keeps_unconfirmed_handle(monkeypatch):
    scope = new_scope()
    process = ControlledProcess()
    process.poll_error = True
    monkeypatch.setattr(adb_runtime, "popen_native", lambda *_args, **_kwargs: process)
    result = adb_runtime.native_capture(["synthetic"], 1, lambda: False, command_scope=scope)
    assert result.kind == "completed"
    assert scope.is_running()
    scope.request_stop()
    assert not scope.wait(0.01)
    process.poll_error = False
    assert scope.wait(0.1)


def test_wait_does_not_take_process_from_active_communicate(monkeypatch):
    scope = new_scope()
    entered = threading.Event()
    release = threading.Event()
    process = ControlledProcess()
    results = []
    original_communicate = process.communicate

    def communicate(input=None, timeout=None):
        entered.set()
        assert release.wait(2)
        return original_communicate(input, timeout)

    process.communicate = communicate
    monkeypatch.setattr(adb_runtime, "popen_native", lambda *_args, **_kwargs: process)
    worker = threading.Thread(target=lambda: results.append(adb_runtime.native_capture(
        ["synthetic"], 5, lambda: False, command_scope=scope,
    )))
    worker.start()
    try:
        assert entered.wait(2)
        scope.request_stop()
        assert not scope.wait(0.01)
        assert process.kill_count == process.wait_count == 0
        assert process.inputs == []
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert scope.wait(0)
        assert len(results) == 1
    finally:
        release.set()
        worker.join(2)
