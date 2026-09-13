"""持久输入管道背压、进程归属和局部关闭屏障。"""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.adb_bridge import ADBBridge
from gui.panels.remote_panel import RemotePanel, _RemoteInputShutdown

pytestmark = pytest.mark.ui


class InputRunner:
    def __init__(self, *, cooperative=True):
        self.cooperative = cooperative
        self.entered = threading.Event()
        self.released = threading.Event()
        self.processes = {}
        self.requested = []
        self.forced = []

    def start(self, key, command, **kwargs):
        runner = self

        class Pipe:
            def write(self, text):
                runner.entered.set()
                while not stopped.wait(0.01):
                    if runner.released.is_set():
                        break
                raise BrokenPipeError("stopped")

            def flush(self):
                pass

        stopped = threading.Event()
        proc = SimpleNamespace(
            stdin=Pipe(), stopped=stopped,
            poll=lambda: 0 if stopped.is_set() or self.released.is_set() else None,
        )
        self.processes[key] = proc
        return proc

    def request_stop(self, key):
        self.requested.append(key)
        if self.cooperative and key in self.processes:
            self.processes[key].stopped.set()
        return self.cooperative

    def stop(self, key, timeout=1):
        return self.processes[key].poll() if key in self.processes else None

    def force_stop(self, key, timeout=1):
        self.forced.append(key)
        self.processes[key].stopped.set()
        return True


def _blocked_shutdown(*, cooperative=True):
    runner = InputRunner(cooperative=cooperative)
    bridge = ADBBridge("fake-adb")
    bridge._process_runner = runner
    session = bridge._input_session("device-test")
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(session.send, "keyevent 3")
    assert runner.entered.wait(2)
    shutdown = _RemoteInputShutdown(
        executor=executor, warmup_threads=(), close_input=bridge.close_input_sessions,
        has_running_future=lambda: not future.done(),
        request_input_stop=bridge.request_stop_input_sessions,
        force_input_stop=bridge.force_stop_input_sessions,
        input_running=bridge.input_sessions_running,
    )
    return runner, bridge, session, future, shutdown


def test_shutdown_stops_pipe_before_waiting_for_executor():
    runner, bridge, session, future, shutdown = _blocked_shutdown()
    try:
        shutdown.start()
        assert shutdown.wait(2)
        assert future.result(0) is False
        assert runner.requested == [session._key]
        assert not shutdown.is_running()
        assert not bridge.input_sessions_running()
        assert not session.warm()
    finally:
        runner.released.set()
        shutdown.start()
        assert shutdown.wait(2)


def test_failed_stop_retains_residual_and_force_targets_input_process():
    runner, bridge, session, future, shutdown = _blocked_shutdown(cooperative=False)
    try:
        shutdown.start()
        assert not shutdown.wait(0.05)
        assert shutdown.is_running()
        assert shutdown.force_stop(1)
        assert shutdown.wait(2)
        assert future.result(0) is False
        assert runner.forced == [session._key]
        assert not bridge.input_sessions_running()
    finally:
        runner.released.set()
        shutdown.start()
        assert shutdown.wait(2)


def test_retired_old_input_cannot_stop_new_session_for_same_device():
    runner = InputRunner()
    bridge = ADBBridge("fake-adb")
    bridge._process_runner = runner
    old = bridge._input_session("device-test")
    assert old.warm()
    bridge.detach_input_sessions()
    new = bridge._input_session("device-test")
    assert new.warm()
    old.request_stop()
    assert runner.requested == [old._key]
    assert old._key != new._key
    assert not old.warm()
    assert new.is_running()
    bridge.close_input_sessions()


def test_stop_during_warmup_never_falls_back_to_new_command(monkeypatch):
    from core import exec as execution

    bridge = ADBBridge("fake-adb")
    runner = InputRunner()
    bridge._process_runner = runner
    monkeypatch.setattr(bridge, "can_input_fast", lambda _device: False)
    start = runner.start

    def retiring_start(*args, **kwargs):
        proc = start(*args, **kwargs)
        bridge.request_stop_input_sessions()
        return proc

    monkeypatch.setattr(runner, "start", retiring_start)
    fallback = []
    monkeypatch.setattr(execution.CommandRunner, "run", lambda *a, **k: fallback.append(a))
    assert bridge.shell_input("keyevent 3", "device-test") is False
    assert not fallback
    assert not bridge.warm_input_session("device-test")
    bridge.close_input_sessions()


def test_failed_termination_keeps_process_visible_after_producers_finish():
    runner = InputRunner(cooperative=False)
    bridge = ADBBridge("fake-adb")
    bridge._process_runner = runner
    assert bridge.warm_input_session("device-test")
    shutdown = _RemoteInputShutdown(
        executor=None, warmup_threads=(), close_input=bridge.close_input_sessions,
        has_running_future=lambda: False,
        request_input_stop=bridge.request_stop_input_sessions,
        force_input_stop=bridge.force_stop_input_sessions,
        input_running=bridge.input_sessions_running,
    )
    try:
        shutdown.start()
        assert shutdown._finished.wait(2)
        assert not shutdown.wait(0)
        assert shutdown.is_running()
        assert bridge.input_sessions_running()
        assert shutdown.force_stop(1)
        assert shutdown.wait(1)
    finally:
        runner.released.set()
        bridge.close_input_sessions()


def test_starting_retired_session_survives_unrelated_cleanup(monkeypatch):
    runner = InputRunner(cooperative=False)
    bridge = ADBBridge("fake-adb")
    bridge._process_runner = runner
    entered, release = threading.Event(), threading.Event()
    start = runner.start

    def delayed_start(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return start(*args, **kwargs)

    monkeypatch.setattr(runner, "start", delayed_start)
    session = bridge._input_session("device-test")
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(session.warm)
    try:
        assert entered.wait(2)
        bridge.detach_input_sessions()
        bridge.close_input_sessions("unrelated-device")
        release.set()
        assert future.result(2) is False
        assert session.is_running()
        assert bridge.input_sessions_running()
        assert bridge.force_stop_input_sessions(1)
    finally:
        release.set()
        runner.released.set()
        executor.shutdown(wait=True)
        bridge.close_input_sessions()


def test_stop_attempts_other_sessions_even_if_one_raises(monkeypatch):
    runner = InputRunner()
    bridge = ADBBridge("fake-adb")
    bridge._process_runner = runner
    first = bridge._input_session("first")
    second = bridge._input_session("second")
    assert first.warm() and second.warm()
    request = runner.request_stop

    def stop(key):
        if key == first._key:
            raise OSError("cannot stop")
        return request(key)

    monkeypatch.setattr(runner, "request_stop", stop)
    try:
        with pytest.raises(OSError):
            bridge.request_stop_input_sessions()
        assert first.is_running()
        assert not second.is_running()
    finally:
        runner.released.set()
        bridge.close_input_sessions()


def test_input_force_error_does_not_skip_scrcpy_force_stop():
    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._remote_input_shutdown_handle = lambda: SimpleNamespace(
        has_resources=True, force_stop=Mock(side_effect=OSError("input stop failed")),
        error_type=lambda: "", is_running=lambda: True,
    )
    panel._scrcpy_process_keys = lambda: ("owned-scrcpy",)
    panel._scrcpy_service = Mock(
        is_active=Mock(return_value=True), force_stop=Mock(return_value=True),
    )
    supervisor = Mock()
    assert panel.register_shutdown_task(supervisor, owner_id="owner", task_id="remote")
    force = supervisor.register.call_args.kwargs["force_stop"]
    with pytest.raises(OSError, match="input stop failed"):
        force(1)
    assert panel._scrcpy_service.force_stop.call_args.args[0] == "owned-scrcpy"
