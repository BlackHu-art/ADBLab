"""Remote 输入使用当前设备能力，发送不确定时不重放，关闭取消贯通执行器。"""

import io
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import adb_runtime as runtime_module
from core import exec as execution
from core.adb_bridge import ADBBridge
from core.adb_runtime import AdbRuntime
from core.adb_transport import ExecutionResult
from gui.panels.remote_panel_input import RemotePanelInput
from services.remote.control_service import REMOTE_ACTIONS, RemoteControlService

ADB = "C:/test/adb.exe"
SERIAL = "fake-device"
LISTING = "List of devices attached\nfake-device\tdevice transport_id:1\n"


@pytest.fixture
def fast_backend(monkeypatch):
    for key in (
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS",
        "ANDROID_ADB_SERVER_PORT", "ANDROID_SERIAL",
    ):
        monkeypatch.delenv(key, raising=False)
    clock = [100.0]
    monkeypatch.setattr(
        runtime_module, "time", SimpleNamespace(monotonic=lambda: clock[0]),
    )
    calls = []

    def capture(command, args, **kwargs):
        calls.append((command, args, kwargs.get("serial")))
        clock[0] += 0.01
        if command == "devices":
            return ExecutionResult(LISTING.encode())
        return ExecutionResult(b"ADBLAB_OUT", b"ADBLAB_ERR", 7)

    def native(_cmd, timeout, _cancelled):
        clock[0] += timeout
        return ExecutionResult(kind="timeout")

    monkeypatch.setattr(runtime_module, "capture", capture)
    monkeypatch.setattr(runtime_module, "native_capture", native)
    ready = threading.Event()
    runtime = AdbRuntime(
        lambda: ADB,
        changed=lambda snapshot: ready.set() if not snapshot.checking else None,
    )
    assert runtime.start()
    assert ready.wait(2)
    assert runtime.wait(2)
    execution.install_adb_runtime(runtime)
    calls.clear()
    yield runtime, calls
    runtime.close()
    assert runtime.wait(2)
    execution.install_adb_runtime(None)


def test_shell_capability_is_read_only_and_specific_to_path_and_device(fast_backend, monkeypatch):
    runtime, calls = fast_backend
    probe = Mock(side_effect=AssertionError("read-only query must not probe"))
    monkeypatch.setattr(runtime, "request_device_check", probe)
    monkeypatch.setattr(runtime, "_resolver", probe)

    assert runtime.can_shell_fast(ADB, SERIAL) is True
    assert runtime.can_shell_fast("C:/another/adb.exe", SERIAL) is False
    assert runtime.can_shell_fast(ADB, "other-device") is False
    assert runtime.can_shell_fast(ADB, "") is False
    assert runtime.can_shell_fast(ADB, "fake-device\n") is False
    assert calls == []
    probe.assert_not_called()


@pytest.mark.parametrize("key", [
    "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
])
def test_shell_capability_rejects_custom_server(fast_backend, monkeypatch, key):
    runtime, _ = fast_backend
    monkeypatch.setenv(key, "custom")
    assert runtime.can_shell_fast(ADB, SERIAL) is False


@pytest.mark.parametrize("state", ["native", "draining", "closed", "native_faster"])
def test_shell_capability_rechecks_current_runtime_policy(fast_backend, state):
    runtime, _ = fast_backend
    if state == "native":
        runtime.set_native_only(True)
    elif state == "draining":
        runtime.prepare_shutdown()
    elif state == "closed":
        runtime.close()
    else:
        with runtime._condition:
            runtime._shell[SERIAL].preference = False
    assert runtime.can_shell_fast(ADB, SERIAL) is False


@pytest.mark.parametrize("listing", [
    "fake-device\tdevice transport_id:2\n",
    "fake-device\toffline transport_id:1\n",
    "other-device\tdevice transport_id:1\n",
])
def test_shell_capability_invalidates_changed_connection(fast_backend, monkeypatch, listing):
    runtime, _ = fast_backend
    monkeypatch.setattr(runtime, "request_device_check", lambda: None)
    runtime.observe_devices(listing)
    assert runtime.can_shell_fast(ADB, SERIAL) is False


def test_shell_capability_does_not_reuse_invalidated_epoch(fast_backend):
    runtime, _ = fast_backend
    with runtime._condition:
        runtime._invalidate(runtime._shell[SERIAL])
    assert runtime.can_shell_fast(ADB, SERIAL) is False


def test_fast_warmup_is_ready_without_native_process_or_input(fast_backend, monkeypatch):
    _, calls = fast_backend
    bridge = ADBBridge(ADB)
    start = Mock(side_effect=AssertionError("fast warmup must not start adb"))
    monkeypatch.setattr(bridge._process_runner, "start", start)

    assert bridge.can_input_fast(SERIAL) is True
    assert bridge.can_input_fast() is False
    assert bridge.warm_input_session(SERIAL) is True
    assert calls == []
    start.assert_not_called()


@pytest.mark.parametrize("raw, success", [
    (ExecutionResult(b"ok", b"", 0), True),
    (ExecutionResult(b"", b"input rejected", 1), False),
    (ExecutionResult(kind="timeout"), False),
    (ExecutionResult(kind="transport"), False),
    (ExecutionResult(kind="protocol"), False),
])
def test_fast_input_uses_remote_result_without_native_replay(
    fast_backend, monkeypatch, raw, success,
):
    _, calls = fast_backend
    bridge = ADBBridge(ADB)
    native = Mock(side_effect=AssertionError("sent input must not replay natively"))
    monkeypatch.setattr(bridge._process_runner, "start", native)
    monkeypatch.setattr(execution.subprocess, "run", native)

    def capture(command, args, **kwargs):
        calls.append((command, args, kwargs["serial"]))
        return raw

    monkeypatch.setattr(runtime_module, "capture", capture)
    assert bridge.shell_input("keyevent 3", SERIAL) is success
    assert calls == [("shell", ["input keyevent 3"], SERIAL)]
    native.assert_not_called()


@pytest.mark.parametrize("fast", [True, False])
def test_cancelled_input_and_warmup_do_not_start_work(fast_backend, monkeypatch, fast):
    runtime, calls = fast_backend
    runtime.set_native_only(not fast)
    bridge = ADBBridge(ADB)
    start = Mock(side_effect=AssertionError("cancelled input must not start adb"))
    monkeypatch.setattr(bridge._process_runner, "start", start)
    assert bridge.shell_input("keyevent 3", SERIAL, cancelled=lambda: True) is False
    assert bridge.warm_input_session(SERIAL, cancelled=lambda: True) is False
    assert calls == []
    start.assert_not_called()


def test_running_fast_input_observes_cancellation(fast_backend, monkeypatch):
    runtime, _ = fast_backend
    monkeypatch.setattr(runtime_module, "time", time)
    with runtime._condition:
        runtime._host.next_check = time.monotonic() + 60
    entered = threading.Event()
    stopped = threading.Event()
    finished = threading.Event()
    result = []
    bridge = ADBBridge(ADB)

    def capture(_command, _args, *, cancelled, **_kwargs):
        entered.set()
        assert stopped.wait(1)
        assert cancelled()
        return ExecutionResult(kind="cancelled")

    monkeypatch.setattr(runtime_module, "capture", capture)

    def run():
        try:
            result.append(bridge.shell_input("keyevent 3", SERIAL, cancelled=stopped.is_set))
        finally:
            finished.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(1)
        stopped.set()
        assert finished.wait(1)
        assert result == [False]
        assert runtime.wait(1)
    finally:
        stopped.set()
        worker.join(2)


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_native_input_uncertain_write_never_replays(monkeypatch, failure):
    monkeypatch.setattr(execution, "_adb_runtime", None)
    bridge = ADBBridge(ADB)
    writes = []

    class Pipe(io.StringIO):
        def write(self, text):
            writes.append(text)
            if failure == "write" and text.startswith("input "):
                raise BrokenPipeError("partial write")
            return len(text)

        def flush(self):
            if failure == "flush":
                raise BrokenPipeError("flush uncertain")

    proc = SimpleNamespace(stdin=Pipe(), poll=lambda: None)
    monkeypatch.setattr(bridge._process_runner, "start", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(bridge._process_runner, "stop", lambda *_args, **_kwargs: None)
    fallback = Mock(return_value=execution.CommandResult(success=True))
    monkeypatch.setattr(execution.CommandRunner, "run", fallback)

    assert bridge.shell_input("keyevent 3", SERIAL) is False
    assert writes == ["input keyevent 3\n"]
    fallback.assert_not_called()


def test_native_input_process_start_failure_can_fallback_before_sending(monkeypatch):
    monkeypatch.setattr(execution, "_adb_runtime", None)
    bridge = ADBBridge(ADB)
    monkeypatch.setattr(bridge._process_runner, "start", Mock(side_effect=OSError("start failed")))
    run = Mock(return_value=execution.CommandResult(success=True))
    monkeypatch.setattr(execution.CommandRunner, "run", run)

    assert bridge.shell_input("keyevent 3", SERIAL) is True
    run.assert_called_once_with([ADB, "-s", SERIAL, "shell", "input keyevent 3"], timeout=15)


@pytest.mark.parametrize("installed", [True, False])
def test_native_input_retains_persistent_session_reuse(fast_backend, monkeypatch, installed):
    runtime, calls = fast_backend
    runtime.set_native_only(True)
    if not installed:
        execution.install_adb_runtime(None)
    bridge = ADBBridge(ADB)
    pipe = io.StringIO()
    proc = SimpleNamespace(stdin=pipe, poll=lambda: None)
    start = Mock(return_value=proc)
    monkeypatch.setattr(bridge._process_runner, "start", start)
    monkeypatch.setattr(bridge._process_runner, "stop", lambda *_args, **_kwargs: None)
    fallback = Mock(side_effect=AssertionError("persistent session must be reused"))
    monkeypatch.setattr(execution.CommandRunner, "run", fallback)

    assert bridge.warm_input_session(SERIAL) is True
    assert pipe.getvalue() == ""
    assert bridge.shell_input("keyevent 3", SERIAL) is True
    assert bridge.shell_input("keyevent 4", SERIAL) is True
    assert pipe.getvalue() == "input keyevent 3\ninput keyevent 4\n"
    assert start.call_count == 1
    assert calls == []
    fallback.assert_not_called()
    bridge.close_input_sessions()


def test_native_input_cancelled_during_warmup_never_sends(monkeypatch):
    monkeypatch.setattr(execution, "_adb_runtime", None)
    bridge = ADBBridge(ADB)
    stopped = threading.Event()
    pipe = io.StringIO()
    proc = SimpleNamespace(stdin=pipe, poll=lambda: None)

    def start(*_args, **_kwargs):
        stopped.set()
        return proc

    monkeypatch.setattr(bridge._process_runner, "start", start)
    monkeypatch.setattr(bridge._process_runner, "stop", lambda *_args, **_kwargs: None)
    native = Mock(side_effect=AssertionError("cancelled input must not fallback"))
    monkeypatch.setattr(execution.subprocess, "Popen", native)
    assert bridge.shell_input("keyevent 3", SERIAL, cancelled=stopped.is_set) is False
    assert pipe.getvalue() == ""
    native.assert_not_called()
    bridge.close_input_sessions()


@pytest.mark.parametrize("action", ["keyevent", *REMOTE_ACTIONS])
def test_remote_control_cancels_complete_action_chain(fast_backend, monkeypatch, action):
    _, calls = fast_backend
    stop = threading.Event()
    service = RemoteControlService(ADBBridge(ADB))
    observed = []

    def capture(command, args, **kwargs):
        calls.append((command, args, kwargs["serial"]))
        stop.set()
        observed.append(kwargs["cancelled"]())
        return ExecutionResult(kind="cancelled")

    monkeypatch.setattr(runtime_module, "capture", capture)
    if action == "keyevent":
        result = service.send_keyevent(SERIAL, "HOME", cancelled=stop.is_set)
    else:
        result = service.perform_action(SERIAL, action, cancelled=stop.is_set)
    assert RemotePanelInput._remote_input_succeeded(result) is False
    assert len(calls) == 1, "取消后不能继续尺寸后的输入或旋转的后续写操作"
    assert calls[0][2] == SERIAL
    assert observed == [True]


@pytest.mark.parametrize("cancel_after", [1, 2])
def test_remote_rotation_cancelled_between_writes_stops_remaining_settings(
    fast_backend, monkeypatch, cancel_after,
):
    _, calls = fast_backend
    stop = threading.Event()
    service = RemoteControlService(ADBBridge(ADB))

    def capture(command, args, **kwargs):
        calls.append((command, args, kwargs["serial"]))
        if len(calls) == cancel_after:
            stop.set()
        return ExecutionResult(returncode=1 if len(calls) == 2 else 0)

    monkeypatch.setattr(runtime_module, "capture", capture)
    result = service.perform_action(SERIAL, "rotate_landscape", cancelled=stop.is_set)
    assert result.success is False
    assert result.error == "Cancelled"
    assert len(calls) == cancel_after


@pytest.mark.parametrize("action", ["keyevent", "swipe_up"])
def test_panel_running_input_retains_target_and_observes_shutdown(
    fast_backend, monkeypatch, action,
):
    _, calls = fast_backend
    tasks = []
    bridge = ADBBridge(ADB)
    service = RemoteControlService(bridge)
    service.remember_dimensions(SERIAL, (1080, 2400))
    frame = SimpleNamespace(
        selected_devices=[SERIAL], _closing=False, _remote_input_closing=False,
        _remote_control=service, _submit_remote_input=tasks.append,
    )
    controller = RemotePanelInput(frame)
    observed = []

    def capture(command, args, **kwargs):
        calls.append((command, args, kwargs["serial"]))
        observed.append(kwargs["cancelled"]())
        frame.selected_devices = ["other-device"]
        observed.append(kwargs["cancelled"]())
        frame._remote_input_closing = True
        observed.append(kwargs["cancelled"]())
        return ExecutionResult(kind="cancelled")

    monkeypatch.setattr(runtime_module, "capture", capture)
    if action == "keyevent":
        controller._send_keyevent("HOME")
    else:
        controller._send_remote_action(action)
    assert len(tasks) == 1
    assert tasks[0]() is False
    assert len(calls) == 1
    assert calls[0][2] == SERIAL
    assert observed == [False, False, True]


def test_panel_warmup_passes_live_shutdown_cancellation(monkeypatch):
    monkeypatch.setattr(execution, "_adb_runtime", None)
    bridge = ADBBridge(ADB)
    frame = SimpleNamespace(
        _closing=False, _remote_input_closing=False, _active_device=SERIAL,
        _adb=bridge, _log=Mock(),
    )
    controller = RemotePanelInput(frame)
    pipe = io.StringIO()
    proc = SimpleNamespace(stdin=pipe, poll=lambda: None)

    def start(*_args, **_kwargs):
        frame._remote_input_closing = True
        return proc

    monkeypatch.setattr(bridge._process_runner, "start", start)
    monkeypatch.setattr(bridge._process_runner, "stop", lambda *_args, **_kwargs: None)
    controller._warm_remote_input_session()
    assert pipe.getvalue() == ""
    frame._log.assert_not_called()
    bridge.close_input_sessions()
