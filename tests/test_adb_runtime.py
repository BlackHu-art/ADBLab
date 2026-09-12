"""应用 ADB 自动选择、代次隔离、故障不重放和关闭契约。"""

import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import adb_runtime as module
from core import adb_transport
from core import exec as execution
from core.adb_runtime import AdbRuntime, native_capture
from core.adb_transport import ExecutionResult

LISTING = b"List of devices attached\nfake-device\tdevice transport_id:1\n"
PROBE = ExecutionResult(b"ADBLAB_OUT", b"ADBLAB_ERR", 7)


@pytest.fixture
def pending_discovery(monkeypatch):
    """固定路径解析、主机验证或启动窗口，并把后续测速保持为未结束。"""
    for key in (
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    state = SimpleNamespace(
        entered=threading.Event(), release=threading.Event(), waiting=threading.Event(),
        benchmark=threading.Event(), finish_benchmark=threading.Event(),
        bootstrap_done=False, native=[], captures=[], runtime=None,
        host_result=ExecutionResult(b"List of devices attached\n"),
    )

    def start(stage):
        def resolver():
            if stage == "resolver":
                state.entered.set()
                assert state.release.wait(3)
            return "C:/test/adb.exe"

        runtime = state.runtime = AdbRuntime(resolver)

        def capture(command, args, **kwargs):
            if threading.current_thread() is runtime._thread:
                if stage == "bootstrap" and not state.bootstrap_done:
                    return ExecutionResult(kind="unavailable")
                if stage == "host":
                    state.entered.set()
                    assert state.release.wait(3)
                return state.host_result
            else:
                state.captures.append(kwargs)
            return ExecutionResult(b"List of devices attached\n")

        def native(cmd, timeout, cancelled):
            state.native.append(cmd)
            assert cmd == ["C:/test/adb.exe", "start-server"]
            state.entered.set()
            assert state.release.wait(3)
            state.bootstrap_done = True
            return ExecutionResult()

        def benchmark(*_):
            state.benchmark.set()
            assert state.finish_benchmark.wait(3)

        original_wait = runtime._condition.wait

        def wait(timeout):
            state.waiting.set()
            return original_wait(timeout)

        monkeypatch.setattr(module, "capture", capture)
        monkeypatch.setattr(module, "native_capture", native)
        monkeypatch.setattr(runtime, "_probe_backends", benchmark)
        monkeypatch.setattr(runtime._condition, "wait", wait)
        assert runtime.start()
        assert state.entered.wait(2)
        return state

    yield start
    if state.runtime is not None:
        state.runtime.close()
        state.release.set()
        state.finish_benchmark.set()
        assert state.runtime.wait(2)


@pytest.mark.parametrize("stage", ["resolver", "host", "bootstrap"])
@pytest.mark.parametrize("args", [["devices"], ["devices", "-l"]])
def test_discovery_waits_for_host_before_selecting_backend(pending_discovery, stage, args):
    state = pending_discovery(stage)
    results = []
    worker = threading.Thread(target=lambda: results.append(
        state.runtime.try_run(["C:/test/adb.exe", *args], 2),
    ))
    try:
        worker.start()
        assert state.waiting.wait(1), "devices selected a backend before host verification"
        assert results == []
        state.release.set()
        assert state.benchmark.wait(1)
        worker.join(1)
        assert not worker.is_alive(), "discovery must not wait for native benchmarking"
        assert results[0] is not None and results[0].kind == "completed"
        assert len(state.captures) == 1
        assert 0 < state.captures[0]["timeout"] <= 2
        assert state.runtime.snapshot().checking
        assert state.native == (
            [["C:/test/adb.exe", "start-server"]] if stage == "bootstrap" else []
        )
    finally:
        state.runtime.close()
        worker.join(1)


@pytest.mark.parametrize("action", ["cancel", "native", "prepare_shutdown", "close"])
def test_waiting_discovery_obeys_cancellation_and_native_selection(pending_discovery, action):
    state = pending_discovery("host")
    stopped = threading.Event()
    results = []
    worker = threading.Thread(target=lambda: results.append(
        state.runtime.try_run(["C:/test/adb.exe", "devices"], 30, stopped.is_set),
    ))
    try:
        worker.start()
        assert state.waiting.wait(1)
        if action == "cancel":
            stopped.set()
        elif action == "native":
            state.runtime.set_mode("native")
        else:
            getattr(state.runtime, action)()
        worker.join(1)
        assert not worker.is_alive()
        if action == "native":
            assert results == [None]
        else:
            assert results[0] is not None and results[0].kind == "cancelled"
        assert not state.captures
        assert not state.native
    finally:
        state.runtime.close()
        worker.join(1)


def test_pending_discovery_exhausts_original_budget_without_native_fallback(
    pending_discovery, monkeypatch,
):
    state = pending_discovery("host")
    monkeypatch.setattr(execution, "_adb_runtime", state.runtime)
    monkeypatch.setattr(execution, "resolve_adb_program", lambda: "C:/test/adb.exe")
    monkeypatch.setattr(execution, "_log_if_slow", lambda *_: None)
    native = Mock(return_value=ExecutionResult(b"List of devices attached\n"))
    monkeypatch.setattr(execution, "native_capture", native)
    started = time.monotonic()
    result = execution.CommandRunner.run(["adb", "devices"], timeout=0.05, cancelled=lambda: False)
    assert not result.success and result.error == "Timeout(0.05s)"
    assert time.monotonic() - started < 1
    native.assert_not_called()


def test_waiting_discovery_rechecks_resolved_path_before_routing(pending_discovery):
    state = pending_discovery("resolver")
    results = []
    worker = threading.Thread(target=lambda: results.append(
        state.runtime.try_run(["C:/other/adb.exe", "devices"], 2),
    ))
    try:
        worker.start()
        assert state.waiting.wait(1)
        state.release.set()
        assert state.benchmark.wait(1)
        worker.join(1)
        assert not worker.is_alive()
        assert results == [None]
        assert not state.captures
    finally:
        state.runtime.close()
        worker.join(1)


def test_discovery_for_other_known_path_does_not_wait_for_host(pending_discovery):
    state = pending_discovery("host")
    assert state.runtime.try_run(["C:/other/adb.exe", "devices"], 2) is None
    assert not state.waiting.is_set()
    assert not state.captures


def test_failed_host_verification_uses_only_remaining_native_budget(pending_discovery, monkeypatch):
    state = pending_discovery("host")
    state.host_result = ExecutionResult(kind="protocol")
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(execution, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(execution, "_adb_runtime", state.runtime)
    monkeypatch.setattr(execution, "resolve_adb_program", lambda: "C:/test/adb.exe")
    monkeypatch.setattr(execution, "_log_if_slow", lambda *_: None)
    native = Mock(return_value=ExecutionResult(b"List of devices attached\n"))
    monkeypatch.setattr(execution, "native_capture", native)
    results = []
    worker = threading.Thread(target=lambda: results.append(
        execution.CommandRunner.run(["adb", "devices"], timeout=2, cancelled=lambda: False),
    ))
    try:
        worker.start()
        assert state.waiting.wait(1)
        native.assert_not_called()
        clock[0] += 0.6
        state.release.set()
        worker.join(1)
        assert not worker.is_alive()
        assert results[0].success
        native.assert_called_once()
        assert native.call_args.args[1] == pytest.approx(1.4)
        assert not state.captures
    finally:
        state.runtime.close()
        worker.join(1)


def test_discovery_cleanup_after_prepare_shutdown_keeps_original_native_admission(
    pending_discovery,
):
    state = pending_discovery("host")
    state.runtime.prepare_shutdown()
    assert state.runtime.try_run(["C:/test/adb.exe", "devices"], 2) is None
    assert not state.waiting.is_set()


@pytest.mark.parametrize("command", ["devices", "shell"])
@pytest.mark.parametrize("failure", ["timeout", "transport"])
def test_initial_transient_probe_recovers_within_same_detection(
    backend, monkeypatch, command, failure,
):
    runtime, clock, native, _ = backend
    original = module.capture
    budgets = []
    elapsed = []

    def capture(target, args, **kwargs):
        if target == command:
            budgets.append(kwargs["timeout"])
            if len(budgets) == 1:
                # 操作系统也可能在调用方截止时间前报告临时失败，复核只能用余量。
                clock[0] += 1.0
                elapsed.append(1.0)
                return ExecutionResult(kind=failure)
        return original(target, args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    prepare(runtime)
    assert len(budgets) == 2
    assert budgets == ([3.0, 2.0] if command == "devices" else [1.0, 2.0])
    assert elapsed[0] + budgets[1] <= 3.0
    assert runtime.snapshot().status == "ready"
    assert all("start-server" not in cmd for cmd in native)


def test_persistent_initial_host_timeout_is_bounded_and_diagnosed(host_transport):
    runtime, clock, native, server = host_transport
    diagnostics = []
    runtime._diagnostic = diagnostics.append
    server.response_delay = 4.0
    started = clock[0]
    assert runtime.start()
    wait_for_probe(runtime)
    assert server.budgets == [3.0]
    assert clock[0] - started == pytest.approx(3.0)
    assert runtime.snapshot().status == "host_timeout"
    assert runtime.snapshot().effective_native_only
    assert any("timeout" in message for message in diagnostics)
    assert native == []
    assert all(sock.closed for sock in server.sockets)


@pytest.mark.parametrize("bootstrap_delay", [0.0, 16.4])
def test_delayed_connection_refusal_bootstraps_once_and_enables_fast_discovery(
    host_transport, bootstrap_delay,
):
    runtime, clock, native, server = host_transport
    server.listening = False
    server.bootstrap_delay = bootstrap_delay
    diagnostics, statuses = [], []
    runtime._diagnostic = diagnostics.append
    runtime._changed = lambda snapshot: statuses.append(snapshot.status)
    assert runtime.start()
    wait_for_probe(runtime)
    assert runtime.snapshot().status == "ready"
    assert runtime.can_scan_fast()
    assert server.budgets[:2] == [3.0, 3.0]
    assert server.bootstrap_budgets == [30.0]
    assert "starting_server" in statuses
    assert any("ADB bootstrap status=starting_server" in line for line in diagnostics)
    assert any(
        f"elapsed_ms={bootstrap_delay * 1000:.0f}" in line and "result=completed" in line
        for line in diagnostics
    )
    assert all("C:/test" not in line for line in diagnostics)
    result = runtime.try_run(["C:/test/adb.exe", "devices", "-l"], 5)
    assert result is not None and result.kind == "completed"
    assert result.stdout == b"List of devices attached\n\n"

    # 后续服务再次消失时，自动恢复及手动重测都不能重复启动服务。
    server.listening = False
    clock[0] += 11
    runtime.request_device_check()
    wait_for_probe(runtime)
    assert not runtime.can_scan_fast()
    assert runtime.recheck()
    wait_for_probe(runtime)
    assert runtime.snapshot().status == "host_unavailable"
    assert sum("start-server" in cmd for cmd in native) == 1
    assert all(sock.closed for sock in server.sockets)


@pytest.mark.parametrize("was_available", [False, True])
def test_unavailable_host_recovers_with_slow_warm_response(host_transport, was_available):
    runtime, clock, native, server = host_transport
    if was_available:
        assert runtime.start()
        wait_for_probe(runtime)
        assert runtime.can_scan_fast()
        server.response_delay = 4.0
        clock[0] += 11
        runtime.request_device_check()
        wait_for_probe(runtime)
        # 已验证服务的普通健康检查继续只用一秒，失败才进入恢复预算。
        assert server.budgets[-1] == 1.0
    else:
        server.response_delay = 4.0
        assert runtime.start()
        wait_for_probe(runtime)
    assert runtime.snapshot().status == "host_timeout"
    assert not runtime.can_scan_fast()
    attempts = len(server.budgets)
    server.response_delay = 1.2
    runtime.request_device_check()
    wait_for_probe(runtime)
    assert len(server.budgets) == attempts

    clock[0] += 11
    runtime.request_device_check()
    wait_for_probe(runtime)
    assert runtime.snapshot().status == "ready"
    assert runtime.can_scan_fast()
    assert server.budgets[-1] == 3.0
    assert len(native) == 1
    assert all("start-server" not in cmd for cmd in native)
    result = runtime.try_run(["C:/test/adb.exe", "devices"], 5)
    assert result is not None and result.kind == "completed"
    assert result.stdout == b"List of devices attached\n\n"
    assert server.budgets[-1] == pytest.approx(5.0)
    assert all(sock.closed for sock in server.sockets)


def test_failed_host_retries_early_transport_failure_within_recovery_budget(backend, monkeypatch):
    runtime, clock, native, _ = backend
    original = module.capture

    def timeout(*_args, **kwargs):
        clock[0] += kwargs["timeout"]
        return ExecutionResult(kind="timeout")

    monkeypatch.setattr(module, "capture", timeout)
    assert runtime.start()
    wait_for_probe(runtime)
    assert not runtime.can_scan_fast()
    budgets = []

    def capture(command, args, **kwargs):
        if command == "devices":
            budgets.append(kwargs["timeout"])
            if len(budgets) == 1:
                clock[0] += 1.0
                return ExecutionResult(kind="transport")
        return original(command, args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    clock[0] += 11
    runtime.request_device_check()
    wait_for_probe(runtime)
    assert runtime.snapshot().status == "ready"
    assert runtime.can_scan_fast()
    assert budgets == [3.0, 2.0]
    assert all("start-server" not in cmd for cmd in native)


def test_shutdown_cancels_slow_initial_service_bootstrap(host_transport, monkeypatch):
    runtime, clock, _, server = host_transport
    server.listening = False
    entered, release = threading.Event(), threading.Event()
    diagnostics = []
    runtime._diagnostic = diagnostics.append

    class BootstrapProcess:
        returncode = None
        killed = False
        drained = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def communicate(self, timeout=None):
            if timeout is None:
                assert self.killed
                self.drained = True
                return b"", b""
            assert 0 < timeout <= 0.1
            entered.set()
            assert release.wait(2)
            clock[0] += timeout
            raise subprocess.TimeoutExpired("offline-bootstrap", timeout)

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

    proc = BootstrapProcess()
    commands = []

    def popen(cmd, **_kwargs):
        commands.append(cmd)
        return proc

    monkeypatch.setattr(module, "native_capture", native_capture)
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    try:
        assert runtime.start() and entered.wait(2)
        assert runtime.snapshot().status == "starting_server"
        runtime.prepare_shutdown()
    finally:
        runtime.prepare_shutdown()
        release.set()
        wait_for_probe(runtime)
    assert proc.killed and proc.drained
    assert commands == [["C:/test/adb.exe", "start-server"]]
    assert server.budgets == [3.0]
    assert not runtime.snapshot().checking
    assert runtime.snapshot().status != "starting_server"
    assert not runtime.snapshot().available
    assert any("ADB bootstrap result=cancelled" in line for line in diagnostics)


def test_shutdown_during_first_probe_does_not_retry(backend, monkeypatch):
    runtime, _, native, _ = backend
    calls = []

    def capture(*_args, **_kwargs):
        calls.append(True)
        runtime.prepare_shutdown()
        return ExecutionResult(kind="timeout")

    monkeypatch.setattr(module, "capture", capture)
    assert runtime.start()
    assert runtime.wait(2)
    assert len(calls) == 1
    assert native == []


@pytest.mark.parametrize("invalidate", [False, True])
def test_retry_rechecks_budget_and_state_after_notification(backend, monkeypatch, invalidate):
    runtime, clock, _, _ = backend
    calls = []

    def capture(*_args, **kwargs):
        calls.append(kwargs["timeout"])
        clock[0] += 1.0
        return ExecutionResult(kind="transport")

    def changed(snapshot):
        if snapshot.status == "retrying":
            if invalidate:
                runtime.observe_devices(LISTING.decode())
            else:
                clock[0] += 3.0

    runtime._changed = changed
    monkeypatch.setattr(module, "capture", capture)
    assert runtime.start() and runtime.wait(2)
    assert calls == [3.0]


@pytest.mark.parametrize("failure", [
    ExecutionResult(kind="transport"),
    ExecutionResult(stderr=b"native startup failed", returncode=1),
])
def test_invalid_native_benchmark_keeps_verified_fast_backend(backend, monkeypatch, failure):
    runtime, clock, native, _ = backend

    def failed(cmd, _timeout, _cancelled):
        native.append(cmd)
        clock[0] += 0.001
        return failure

    monkeypatch.setattr(module, "native_capture", failed)
    prepare(runtime)
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert runtime.can_scan_fast()
    assert runtime.can_shell_fast("C:/test/adb.exe", "fake-device")
    assert len(native) == 2


@pytest.mark.parametrize("cold_command", ["devices", "shell"])
def test_cold_sample_is_confirmed_before_selecting_native(backend, monkeypatch, cold_command):
    runtime, clock, _, _ = backend
    calls = {"devices": 0, "shell": 0}

    def capture(command, _args, **_kwargs):
        calls[command] += 1
        clock[0] += 0.9 if command == cold_command and calls[command] == 1 else 0.005
        return ExecutionResult(LISTING) if command == "devices" else PROBE

    def native(cmd, _timeout, _cancelled):
        clock[0] += 0.2
        return PROBE if "shell" in cmd else ExecutionResult(LISTING)

    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.setattr(module, "native_capture", native)
    prepare(runtime)
    assert calls[cold_command] == 2


def test_manual_fast_switch_overrides_speed_preference_immediately(backend, monkeypatch):
    runtime, clock, _, calls = backend

    def native(cmd, _timeout, _cancelled):
        clock[0] += 0.001
        return PROBE if "shell" in cmd else ExecutionResult(LISTING)

    monkeypatch.setattr(module, "native_capture", native)
    assert runtime.start() and runtime.wait(2)
    assert runtime.snapshot().effective_native_only
    count = len(calls)
    runtime.set_native_only(False)
    assert runtime.snapshot().selection_mode == "fast"
    assert not runtime.snapshot().effective_native_only
    assert runtime.can_scan_fast()
    assert runtime.can_shell_fast("C:/test/adb.exe", "fake-device")
    assert len(calls) == count
    runtime.set_native_only(True)
    assert runtime.snapshot().effective_native_only
    assert runtime.try_run(["C:/test/adb.exe", "devices"], 5) is None
    assert len(calls) == count


def test_explicit_recheck_restores_automatic_selection(backend):
    runtime, _, _, _ = backend
    prepare(runtime)
    runtime.set_native_only(True)
    assert runtime.recheck() and runtime.wait(2)
    assert runtime.snapshot().selection_mode == "auto"
    assert not runtime.snapshot().effective_native_only


def test_manual_choice_during_benchmark_survives_detection_completion(backend, monkeypatch):
    runtime, _, _, _ = backend
    entered, release = threading.Event(), threading.Event()
    original = module.native_capture

    def native(*args):
        entered.set()
        assert release.wait(2)
        return original(*args)

    monkeypatch.setattr(module, "native_capture", native)
    try:
        assert runtime.start() and entered.wait(1)
        runtime.set_native_only(True)
        release.set()
        assert runtime.wait(2)
        assert runtime.snapshot().native_only
        assert runtime.snapshot().selection_mode == "native"
        assert runtime.snapshot().effective_native_only
    finally:
        release.set()
        assert runtime.wait(2)


def test_replaced_device_does_not_receive_capability_retry(backend, monkeypatch):
    runtime, clock, _, _ = backend
    original = module.capture
    old_calls = []

    def capture(command, args, **kwargs):
        if command == "shell" and kwargs["serial"] == "fake-device":
            old_calls.append(True)
            runtime.observe_devices("List of devices attached\nnew-device device transport_id:2\n")
            clock[0] += kwargs["timeout"]
            return ExecutionResult(kind="timeout")
        if command == "devices" and old_calls:
            clock[0] += 0.01
            return ExecutionResult(b"List of devices attached\nnew-device device transport_id:2\n")
        return original(command, args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    assert runtime.start() and runtime.wait(2)
    assert len(old_calls) == 1
    assert runtime.can_shell_fast("C:/test/adb.exe", "new-device")


def test_many_unresponsive_devices_finish_one_bounded_detection(backend, monkeypatch):
    runtime, clock, native, _ = backend
    calls = []
    listing = b"List of devices attached\n" + b"".join(
        f"fake-{i} device transport_id:{i}\n".encode() for i in range(6)
    )

    def capture(command, _args, **kwargs):
        if command == "devices":
            clock[0] += 0.01
            return ExecutionResult(listing)
        calls.append(kwargs["serial"])
        clock[0] += kwargs["timeout"]
        if len(calls) > 12:
            runtime.prepare_shutdown()
        return ExecutionResult(kind="timeout")

    monkeypatch.setattr(module, "capture", capture)
    assert runtime.start() and runtime.wait(2)
    assert len(calls) == 12
    assert not runtime.snapshot().checking
    assert runtime.snapshot().checked_devices == 6
    assert len(native) == 1


@pytest.mark.parametrize("kind", ["timeout", "transport", "protocol"])
def test_failed_warm_sample_does_not_commit_cold_native_preference(backend, monkeypatch, kind):
    runtime, clock, _, _ = backend
    counts = {"devices": 0, "shell": 0}

    def capture(command, _args, **_kwargs):
        counts[command] += 1
        clock[0] += 0.9 if counts[command] == 1 else 0.01
        if counts[command] > 1:
            return ExecutionResult(kind=kind)
        return ExecutionResult(LISTING) if command == "devices" else PROBE

    def native(cmd, _timeout, _cancelled):
        clock[0] += 0.2
        return PROBE if "shell" in cmd else ExecutionResult(LISTING)

    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.setattr(module, "native_capture", native)
    prepare(runtime)


def test_native_timeout_without_sufficient_advantage_keeps_verified_capability(
    backend, monkeypatch
):
    runtime, clock, _, _ = backend

    def capture(command, _args, **_kwargs):
        clock[0] += 1.9
        return ExecutionResult(LISTING) if command == "devices" else PROBE

    monkeypatch.setattr(module, "capture", capture)
    prepare(runtime)


def test_late_warm_listing_does_not_replace_a_newer_device_snapshot(backend, monkeypatch):
    runtime, clock, _, _ = backend
    host_calls = []
    newer = b"List of devices attached\nnew-device device transport_id:2\n"

    def capture(command, _args, **_kwargs):
        if command == "devices":
            host_calls.append(True)
            clock[0] += 0.9 if len(host_calls) == 1 else 0.005
            if len(host_calls) == 2:
                runtime.observe_devices(newer.decode())
            return ExecutionResult(LISTING)
        clock[0] += 0.005
        return PROBE

    def native(cmd, _timeout, _cancelled):
        clock[0] += 0.2
        return PROBE if "shell" in cmd else ExecutionResult(LISTING)

    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.setattr(module, "native_capture", native)
    assert runtime.start() and runtime.wait(2)
    assert runtime.can_shell_fast("C:/test/adb.exe", "new-device")
    assert not runtime.can_shell_fast("C:/test/adb.exe", "fake-device")


def test_superseded_recheck_finishes_without_stale_checking_status(backend, monkeypatch):
    runtime, _, _, _ = backend
    prepare(runtime)

    def capture(command, _args, **_kwargs):
        if command == "devices":
            runtime.observe_devices("List of devices attached\n")
            return ExecutionResult(LISTING)
        return PROBE

    monkeypatch.setattr(module, "capture", capture)
    assert runtime.recheck() and runtime.wait(2)
    snapshot = runtime.snapshot()
    assert not snapshot.checking
    assert snapshot.status == "ready"
    assert snapshot.checked_devices == 0


@pytest.fixture
def backend(monkeypatch):
    for key in (
        "ADB_SERVER_SOCKET",
        "ANDROID_ADB_SERVER_ADDRESS",
        "ANDROID_ADB_SERVER_PORT",
        "ANDROID_SERIAL",
    ):
        monkeypatch.delenv(key, raising=False)
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    native_calls = []
    socket_calls = []

    def native(cmd, timeout, cancelled):
        native_calls.append(cmd)
        clock[0] += timeout
        return ExecutionResult(kind="timeout")

    def capture(command, args, **kwargs):
        socket_calls.append((command, args, kwargs))
        clock[0] += 0.01
        return ExecutionResult(LISTING) if command == "devices" else PROBE

    monkeypatch.setattr(module, "native_capture", native)
    monkeypatch.setattr(module, "capture", capture)
    runtime = AdbRuntime(lambda: "C:/test/adb.exe")
    yield runtime, clock, native_calls, socket_calls
    runtime.close()
    assert runtime.wait(2)
    execution.install_adb_runtime(None)


@pytest.fixture
def host_transport(backend, monkeypatch):
    """保留真实协议和运行实例，只隔离系统连接、服务启动与时钟。"""
    runtime, clock, native, _ = backend
    server = SimpleNamespace(
        listening=True, response_delay=0.01, budgets=[], sockets=[],
        bootstrap_delay=0.0, bootstrap_budgets=[],
    )

    class HostSocket:
        def __init__(self):
            self.response = bytearray(b"OKAY0000")
            self.delay = server.response_delay
            self.timeout = 0.0
            self.closed = False

        def settimeout(self, timeout):
            self.timeout = timeout

        def sendall(self, data):
            assert data in (b"000chost:devices", b"000ehost:devices-l")

        def recv(self, size):
            elapsed = min(self.delay, self.timeout)
            clock[0] += elapsed
            self.delay -= elapsed
            if self.delay > 0:
                raise TimeoutError
            data = bytes(self.response[:size])
            del self.response[:size]
            return data

        def close(self):
            self.closed = True

    def connect(address, timeout):
        assert address == ("127.0.0.1", 5037)
        server.budgets.append(timeout)
        if not server.listening:
            # 模拟 Windows 未监听端口延后报告拒绝，每次新连接重新计时。
            clock[0] += min(timeout, 2.031)
            if timeout < 2.031:
                raise TimeoutError
            raise ConnectionRefusedError
        sock = HostSocket()
        server.sockets.append(sock)
        return sock

    original_native = module.native_capture

    def native_capture(cmd, timeout, cancelled):
        if "start-server" in cmd:
            native.append(cmd)
            server.bootstrap_budgets.append(timeout)
            clock[0] += min(server.bootstrap_delay, timeout)
            if server.bootstrap_delay > timeout:
                return ExecutionResult(kind="timeout")
            server.listening = True
            return ExecutionResult()
        return original_native(cmd, timeout, cancelled)

    monkeypatch.setattr(adb_transport, "time", module.time)
    monkeypatch.setattr(adb_transport.socket, "create_connection", connect)
    monkeypatch.setattr(module, "capture", adb_transport.capture)
    monkeypatch.setattr(module, "native_capture", native_capture)
    return runtime, clock, native, server


def wait_for_probe(runtime):
    """以真实线程退出同步，避免探针推进的模拟时钟耗尽测试等待预算。"""
    assert runtime._thread is not None
    runtime._thread.join(2)
    assert runtime.wait(0)


def prepare(runtime):
    completed = threading.Event()
    previous = runtime._changed

    def changed(snapshot):
        previous(snapshot)
        if not snapshot.checking:
            completed.set()

    runtime._changed = changed
    assert runtime.start()
    assert completed.wait(2)
    assert runtime.wait(2)
    assert runtime.snapshot().fast_devices
    assert runtime.snapshot().fast_shell_devices == 1


def test_service_ready_precedes_native_benchmark_and_reuses_server(backend):
    runtime, _, native, _ = backend
    observed = []
    runtime._ready = lambda: observed.append((runtime.snapshot().available, len(native)))
    prepare(runtime)
    assert observed == [(True, 0)]
    assert all("start-server" not in cmd for cmd in native)
    assert len(native) == 2


@pytest.mark.parametrize("blocked_kind", ["host", "shell"])
def test_new_device_capability_preempts_old_native_benchmark(backend, monkeypatch, blocked_kind):
    runtime, clock, native_calls, _ = backend
    entered = threading.Event()
    release = threading.Event()
    validated = threading.Event()
    published = threading.Event()
    preempted = threading.Event()
    original_capture = module.capture
    original_changed = runtime._changed
    blocked_once = False

    def changed(snapshot):
        original_changed(snapshot)
        if snapshot.fast_shell_devices == 2:
            published.set()

    def native(cmd, timeout, cancelled):
        nonlocal blocked_once
        native_calls.append(cmd)
        kind = "host" if "devices" in cmd else "shell"
        if kind == blocked_kind and not blocked_once:
            blocked_once = True
            entered.set()
            while not release.wait(0.005):
                if cancelled():
                    preempted.set()
                    return ExecutionResult(kind="cancelled")
        clock[0] += timeout
        return ExecutionResult(kind="timeout")

    def capture(command, args, **kwargs):
        result = original_capture(command, args, **kwargs)
        if kwargs.get("serial") == "new-device":
            validated.set()
        return result

    monkeypatch.setattr(module, "native_capture", native)
    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.setattr(runtime, "_changed", changed)
    try:
        assert runtime.start()
        assert entered.wait(1)
        runtime.observe_devices((LISTING + b"new-device\tdevice transport_id:2\n").decode())
        assert validated.wait(0.5), "新目标仍被已有原生基准阻塞"
        assert preempted.is_set()
        # 底层响应返回先于能力写入，等待发布完成后才读取共享快照。
        assert published.wait(0.5), "新目标能力未发布"
        assert runtime.snapshot().fast_shell_devices == 2
        release.set()
        assert runtime.wait(2)
        assert runtime.snapshot().checked_devices == 2
        assert runtime.snapshot().fast_devices
        assert runtime._shell["fake-device"].preference is True
        assert runtime._shell["new-device"].preference is True
    finally:
        release.set()
        runtime.close()
        assert runtime.wait(2)


def test_device_arriving_as_probe_drains_is_checked_without_another_scan(backend, monkeypatch):
    runtime, _, _, _ = backend
    drained = threading.Event()
    release = threading.Event()
    original = runtime._probe_backends
    original_capture = module.capture
    listing = [LISTING]

    def drain(*args):
        original(*args)
        if not drained.is_set():
            drained.set()
            assert release.wait(1)

    def capture(command, args, **kwargs):
        if command == "devices":
            return ExecutionResult(listing[0])
        return original_capture(command, args, **kwargs)

    monkeypatch.setattr(runtime, "_probe_backends", drain)
    monkeypatch.setattr(module, "capture", capture)
    try:
        assert runtime.start()
        assert drained.wait(1)
        listing[0] += b"new-device\tdevice transport_id:2\n"
        runtime.observe_devices(listing[0].decode())
        release.set()
        assert runtime.wait(2)
        assert runtime.snapshot().checked_devices == 2
        assert runtime.snapshot().fast_shell_devices == 2
    finally:
        release.set()
        runtime.close()
        assert runtime.wait(2)


def test_start_missing_server_only_once(backend, monkeypatch):
    runtime, _, native, _ = backend
    original = module.capture
    first = True

    def capture(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            return ExecutionResult(kind="unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    prepare(runtime)
    assert sum("start-server" in cmd for cmd in native) == 1


def test_probe_handoff_joins_old_thread_before_new_io(backend, monkeypatch):
    runtime, _, _, calls = backend
    returned = threading.Event()
    release = threading.Event()
    original_probe = runtime._probe
    original_capture = module.capture
    listing = [LISTING]

    def probe(previous=None):
        original_probe(previous)
        if previous is None:
            returned.set()
            assert release.wait(2)

    def capture(command, args, **kwargs):
        if command == "devices":
            return ExecutionResult(listing[0])
        return original_capture(command, args, **kwargs)

    monkeypatch.setattr(runtime, "_probe", probe)
    monkeypatch.setattr(module, "capture", capture)
    try:
        assert runtime.start()
        assert returned.wait(1)
        previous = runtime._thread
        count = len(calls)
        listing[0] += b"new-device\tdevice transport_id:2\n"
        runtime.observe_devices(listing[0].decode())
        assert runtime._thread is not previous
        assert runtime.snapshot().checking
        assert not runtime.wait(0.02)
        assert len(calls) == count
        release.set()
        assert runtime.wait(2)
        assert runtime.snapshot().fast_shell_devices == 2
    finally:
        release.set()
        runtime.close()
        assert runtime.wait(2)


def test_timeout_does_not_restart_server(backend, monkeypatch):
    runtime, _, native, _ = backend
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="timeout"))
    runtime.start()
    assert runtime.wait(2)
    assert native == []
    assert not runtime.snapshot().available


def test_automatic_refresh_does_not_repeat_existing_benchmarks(backend):
    runtime, clock, native, _ = backend
    prepare(runtime)
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert len(native) == 2


def test_worker_probe_only_validates_its_target_and_revalidates_reconnect(backend, monkeypatch):
    runtime, clock, native, socket_calls = backend
    runtime._probe_serial = "fake-device"
    listing = [LISTING + b"other-device\tdevice transport_id:2\n"]
    original = module.capture

    def capture(command, args, **kwargs):
        if command == "devices":
            return ExecutionResult(listing[0])
        return original(command, args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    prepare(runtime)
    assert {call[2]["serial"] for call in socket_calls} == {"fake-device"}
    assert len(native) == 2
    listing[0] = listing[0].replace(b"transport_id:1", b"transport_id:3")
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert len(native) == 3
    assert runtime.snapshot().fast_shell_devices == 1


@pytest.mark.parametrize(
    "tail",
    [
        ["push", "a", "b"],
        ["shell"],
        ["-s", "fake-device", "shell", "-t", "ls"],
        ["-H", "another-host", "devices"],
        ["-t", "1", "shell", "ls"],
    ],
)
def test_unsupported_arguments_do_not_enter_socket_backend(backend, tail):
    runtime, _, _, calls = backend
    prepare(runtime)
    count = len(calls)
    assert runtime.try_run(["C:/test/adb.exe", *tail], 5) is None
    assert len(calls) == count


def test_custom_executable_and_server_are_not_redirected(backend, monkeypatch):
    runtime, _, _, calls = backend
    prepare(runtime)
    count = len(calls)
    assert runtime.try_run(["C:/other/adb.exe", "devices"], 5) is None
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:elsewhere:5037")
    assert runtime.try_run(["C:/test/adb.exe", "devices"], 5) is None
    assert not runtime.can_scan_fast()
    assert len(calls) == count


def test_screenshot_stream_preserves_binary_and_avoids_native_client(
    backend, monkeypatch, tmp_path,
):
    runtime, _, _, _ = backend
    prepare(runtime)
    execution.install_adb_runtime(runtime)
    payload = b"\x89PNG\r\n\x1a\n\x00\xff\r\n\r"

    def capture(command, args, **kwargs):
        assert command == "shell" and args == ["screencap", "-p"]
        kwargs["stdout_sink"].write(payload)
        return ExecutionResult()

    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.setattr(execution, "native_capture", Mock(side_effect=AssertionError))
    path = tmp_path / "shot.png"
    result = execution.CommandRunner.run_to_file(
        ["C:/test/adb.exe", "-s", "fake-device", "exec-out", "screencap", "-p"],
        str(path), cancelled=lambda: False,
    )
    assert result.success and result.output == str(path)
    assert path.read_bytes() == payload


@pytest.mark.parametrize("kind", ["transport", "protocol", "output", "timeout", "cancelled"])
def test_binary_failure_does_not_fall_back_or_replay(backend, monkeypatch, tmp_path, kind):
    runtime, _, _, _ = backend
    prepare(runtime)
    execution.install_adb_runtime(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind=kind))
    native = Mock(side_effect=AssertionError)
    monkeypatch.setattr(execution, "native_capture", native)
    result = execution.CommandRunner.run_to_file(
        ["C:/test/adb.exe", "-s", "fake-device", "exec-out", "screencap", "-p"],
        str(tmp_path / "shot.png"), cancelled=lambda: False,
    )
    assert not result.success
    native.assert_not_called()
    if kind == "output":
        assert runtime.snapshot().fast_shell_devices == 1


def test_only_explicit_screenshot_binary_command_can_use_shell(backend):
    runtime, _, _, _ = backend
    prepare(runtime)
    prefix = ["C:/test/adb.exe", "-s", "fake-device"]
    for args in (["exec-out", "cat", "/file"], ["shell", "screencap", "-p"], ["devices"]):
        assert runtime._parse(prefix + args, binary=True) is None


@pytest.mark.parametrize("kind", ["timeout", "transport", "protocol", "cancelled"])
def test_failure_after_connection_never_replays(backend, monkeypatch, kind):
    runtime, _, native, _ = backend
    prepare(runtime)
    execution.install_adb_runtime(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind=kind))
    native_run = Mock()
    monkeypatch.setattr(execution.subprocess, "run", native_run)
    result = execution.CommandRunner.run(
        ["C:/test/adb.exe", "-s", "fake-device", "shell", "pm clear x"]
    )
    assert not result.success
    native_run.assert_not_called()
    assert len(native) == 2
    assert execution.CommandRunner.active_count() == 0


def test_refused_connection_falls_back_once(backend, monkeypatch):
    runtime, _, _, _ = backend
    prepare(runtime)
    execution.install_adb_runtime(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="unavailable"))
    native = Mock(return_value=subprocess.CompletedProcess([], 0, "ok\n", ""))
    monkeypatch.setattr(execution.subprocess, "run", native)
    result = execution.CommandRunner.run(
        ["C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok"]
    )
    assert result.success and result.output == "ok"
    native.assert_called_once()
    assert 0 < native.call_args.kwargs["timeout"] <= 30


@pytest.mark.parametrize(
    "raw,expected",
    [
        (ExecutionResult(b" a\r\nb \r\n", b"warning", 0), (True, "a\nb", "", 0)),
        (ExecutionResult(b"out", b"err\n", 7), (False, "", "err", 7)),
        (ExecutionResult(b"out", b"", 1), (False, "", "out", 1)),
    ],
)
def test_backends_share_result_contract(backend, monkeypatch, raw, expected):
    runtime, _, _, _ = backend
    prepare(runtime)
    execution.install_adb_runtime(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: raw)
    cmd = ["C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok"]
    fast = execution.CommandRunner.run(cmd)
    monkeypatch.setattr(
        execution.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [],
            raw.returncode,
            raw.stdout.decode(),
            raw.stderr.decode(),
        ),
    )
    native = execution.CommandRunner.run(cmd, native_only=True)
    for result in (fast, native):
        assert (result.success, result.output, result.error, result.returncode) == expected


def test_reconnection_invalidates_policy_before_reprobe(backend, monkeypatch):
    runtime, _, _, _ = backend
    prepare(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="timeout"))
    runtime.observe_devices(LISTING.decode().replace("transport_id:1", "transport_id:2"))
    assert runtime.wait(2)
    assert runtime.snapshot().fast_shell_devices == 0
    assert runtime.try_run(["C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok"], 5) is None


def test_native_override_applies_only_to_later_requests(backend, monkeypatch):
    runtime, _, _, _ = backend
    prepare(runtime)

    def capture(*a, **k):
        runtime.set_native_only(True)
        return ExecutionResult(b"ok")

    monkeypatch.setattr(module, "capture", capture)
    cmd = ["C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok"]
    assert runtime.try_run(cmd, 5).stdout == b"ok"
    assert runtime.try_run(cmd, 5) is None


def test_shutdown_cancels_active_request_but_allows_cleanup_before_final_close(
    backend, monkeypatch
):
    runtime, _, _, _ = backend
    prepare(runtime)
    admitted = threading.Event()
    finish = threading.Event()
    results = []

    def blocked(*args, cancelled, **kwargs):
        admitted.set()
        assert finish.wait(2)
        return ExecutionResult(kind="cancelled" if cancelled() else "completed")

    monkeypatch.setattr(module, "capture", blocked)
    cmd = ["C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok"]
    worker = threading.Thread(target=lambda: results.append(runtime.try_run(cmd, 5)))
    worker.start()
    assert admitted.wait(2)
    runtime.prepare_shutdown()
    finish.set()
    worker.join(2)
    assert results[0].kind == "cancelled"
    assert runtime.try_run(cmd, 5).kind == "completed"
    runtime.close()
    assert runtime.try_run(cmd, 5).kind == "cancelled"
    assert runtime.wait(2)


def test_concurrent_start_is_deduplicated_and_cancellable(backend, monkeypatch):
    runtime, _, _, _ = backend
    entered, release = threading.Event(), threading.Event()

    def resolver():
        entered.set()
        assert release.wait(2)
        return None

    runtime._resolver = resolver
    assert runtime.start()
    assert entered.wait(2)
    assert not runtime.start()
    runtime.close()
    release.set()
    assert runtime.wait(2)
    assert not runtime.start()


def test_remote_command_timeout_keeps_valid_backend(backend, monkeypatch):
    runtime, _, _, _ = backend
    prepare(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="timeout"))
    result = runtime.try_run(["C:/test/adb.exe", "-s", "fake-device", "shell", "sleep 99"], 1)
    assert result.kind == "timeout"
    assert runtime.snapshot().fast_shell_devices == 1


def test_first_query_waits_for_pending_capability_without_running_native(backend, monkeypatch):
    import time

    runtime, _, native, _ = backend
    prepare(runtime)
    monkeypatch.setattr(module, "time", time)
    runtime._shell["fake-device"].available = False
    runtime._shell["fake-device"].next_check = 0.0
    runtime._checking = True
    waiting = threading.Event()
    original_wait = runtime._condition.wait

    def wait(timeout):
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(runtime._condition, "wait", wait)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            runtime.try_run(
                ["C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok"],
                2,
            )
        )
    )
    try:
        worker.start()
        assert waiting.wait(1)
        with runtime._condition:
            runtime._shell["fake-device"].available = True
            runtime._checking = False
            runtime._condition.notify_all()
        worker.join(1)
        assert not worker.is_alive()
        assert results[0].kind == "completed"
        assert len(native) == 2
    finally:
        runtime.close()
        worker.join(1)


@pytest.mark.parametrize("failure", ["timeout", "protocol", "invalid_output"])
def test_first_capability_failure_retries_after_delay(backend, monkeypatch, failure):
    runtime, clock, native, socket_calls = backend
    original = module.capture
    fail = [True]

    def capture(command, args, **kwargs):
        result = original(command, args, **kwargs)
        if command == "shell" and fail[0]:
            return (
                ExecutionResult(b"invalid")
                if failure == "invalid_output" else ExecutionResult(kind=failure)
            )
        return result

    monkeypatch.setattr(module, "capture", capture)
    assert runtime.start()
    assert runtime.wait(2)
    assert runtime.snapshot().fast_shell_devices == 0
    assert len(native) == 1
    count = len(socket_calls)
    fail[0] = False
    runtime.request_device_check()
    assert runtime.wait(2)
    assert len(socket_calls) == count
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert runtime.snapshot().fast_shell_devices == 1
    assert len(native) == 2


def test_host_recovery_restores_preferences_without_repeating_benchmarks(backend, monkeypatch):
    runtime, clock, native, _ = backend
    prepare(runtime)
    original = module.capture
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="transport"))
    result = runtime.try_run(["C:/test/adb.exe", "devices"], 5)
    assert result.kind == "transport"
    assert not runtime.can_scan_fast()
    monkeypatch.setattr(module, "capture", original)
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert runtime.can_scan_fast()
    assert runtime.snapshot().fast_shell_devices == 1
    assert len(native) == 2


def test_automatic_recovery_and_manual_retest_do_not_restart_server(backend, monkeypatch):
    runtime, clock, native, _ = backend
    prepare(runtime)
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="unavailable"))
    for _ in range(2):
        clock[0] += 11
        runtime.request_device_check()
        assert runtime.wait(2)
    assert runtime.start(force=True)
    assert runtime.wait(2)
    assert all("start-server" not in cmd for cmd in native)


def test_external_server_restart_invalidates_capability_and_reprobes(backend):
    """重启本机 ADB 服务后立即作废能力并重测，避免沿用已断开的直连状态。"""

    runtime, _clock, _native, captures = backend
    assert runtime.start()
    assert runtime.wait(2)
    assert runtime.can_scan_fast()
    devices_before = sum(1 for command, _args, _kwargs in captures if command == "devices")

    runtime.note_server_restart()
    assert runtime.wait(2)

    assert runtime.can_scan_fast()
    assert runtime.snapshot().status == "ready"
    assert sum(1 for command, _args, _kwargs in captures if command == "devices") > devices_before


@pytest.mark.parametrize("command", ["devices", "shell"])
def test_old_native_benchmark_cannot_restore_failed_backend(backend, monkeypatch, command):
    runtime, _, _, _ = backend
    original_native = module.native_capture
    original_capture = module.capture
    entered, release = threading.Event(), threading.Event()

    def native(cmd, timeout, cancelled):
        target = "shell" if "shell" in cmd else "devices"
        if target == command:
            entered.set()
            assert release.wait(2)
        return original_native(cmd, timeout, cancelled)

    def capture(target, args, **kwargs):
        if (target == "devices" and not args) or (target == "shell" and args == ["echo ok"]):
            return ExecutionResult(kind="transport")
        return original_capture(target, args, **kwargs)

    monkeypatch.setattr(module, "native_capture", native)
    monkeypatch.setattr(module, "capture", capture)
    try:
        assert runtime.start()
        assert entered.wait(2)
        cmd = ["C:/test/adb.exe", "devices"] if command == "devices" else [
            "C:/test/adb.exe", "-s", "fake-device", "shell", "echo ok",
        ]
        assert runtime.try_run(cmd, 5).kind == "transport"
        release.set()
        assert runtime.wait(2)
        snapshot = runtime.snapshot()
        assert not (snapshot.fast_devices if command == "devices" else snapshot.fast_shell_devices)
    finally:
        release.set()
        assert runtime.wait(2)


def test_plain_devices_request_triggers_due_capability_check(backend, monkeypatch):
    runtime, clock, _, socket_calls = backend
    prepare(runtime)
    before = sum(command == "devices" and args == ["-l"] for command, args, _ in socket_calls)
    clock[0] += 11
    assert runtime.try_run(["C:/test/adb.exe", "devices"], 5).kind == "completed"
    assert runtime.wait(2)
    after = sum(command == "devices" and args == ["-l"] for command, args, _ in socket_calls)
    assert after == before + 1


@pytest.mark.parametrize("mode", ["auto", "fast"])
def test_native_preference_survives_health_checks_and_recovery(backend, monkeypatch, mode):
    runtime, clock, native, socket_calls = backend
    original_capture = module.capture
    diagnostics = []
    runtime._diagnostic = diagnostics.append

    def fast_native(cmd, timeout, cancelled):
        native.append(cmd)
        clock[0] += 0.001
        return PROBE if "shell" in cmd else ExecutionResult(LISTING)

    monkeypatch.setattr(module, "native_capture", fast_native)
    assert runtime.start()
    assert runtime.wait(2)
    assert runtime.snapshot().available
    assert not runtime.snapshot().fast_devices
    assert runtime.snapshot().fast_shell_devices == 0
    runtime.set_mode(mode)
    shell_count = sum(command == "shell" for command, _, _ in socket_calls)
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert sum(command == "shell" for command, _, _ in socket_calls) == shell_count
    monkeypatch.setattr(module, "capture", lambda *a, **k: ExecutionResult(kind="transport"))
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert not runtime.snapshot().available
    monkeypatch.setattr(module, "capture", original_capture)
    clock[0] += 11
    runtime.request_device_check()
    assert runtime.wait(2)
    assert runtime.snapshot().available
    assert runtime.snapshot().fast_devices == (mode == "fast")
    assert runtime.snapshot().fast_shell_devices == int(mode == "fast")
    for command in ("devices", "shell"):
        assert f"ADB recovery {command} fast={mode == 'fast'} benchmark=cached" in diagnostics
    assert len(native) == 2


def test_each_device_keeps_its_own_recovery_deadline(backend, monkeypatch):
    runtime, clock, native, _ = backend
    original = module.capture
    probes = []
    listing = LISTING + b"other-device\tdevice transport_id:2\n"

    def capture(command, args, **kwargs):
        if command == "devices":
            return ExecutionResult(listing)
        if args == [AdbRuntime.PROBE_COMMAND]:
            probes.append(kwargs["serial"])
            return original(command, args, **kwargs)
        return ExecutionResult(kind="transport")

    monkeypatch.setattr(module, "capture", capture)
    assert runtime.start()
    assert runtime.wait(2)
    assert runtime.snapshot().fast_shell_devices == 2
    for serial, elapsed in [("fake-device", 0), ("other-device", 9)]:
        clock[0] += elapsed
        result = runtime.try_run(["C:/test/adb.exe", "-s", serial, "shell", "fail"], 5)
        assert result.kind == "transport"
        assert runtime.wait(2)
    clock[0] += 2
    runtime.request_device_check()
    assert runtime.wait(2)
    assert probes.count("fake-device") == 2
    assert probes.count("other-device") == 1
    assert runtime.snapshot().fast_shell_devices == 1
    clock[0] += 9
    runtime.request_device_check()
    assert runtime.wait(2)
    assert probes.count("other-device") == 2
    assert runtime.snapshot().fast_shell_devices == 2
    assert len(native) == 3


@pytest.mark.parametrize("command", ["devices", "shell"])
def test_old_capability_probe_cannot_restore_newly_failed_backend(backend, monkeypatch, command):
    runtime, _, _, _ = backend
    prepare(runtime)
    original = module.capture
    entered, release = threading.Event(), threading.Event()

    def capture(target, args, **kwargs):
        if target == command and args in (["-l"], [AdbRuntime.PROBE_COMMAND]):
            entered.set()
            assert release.wait(2)
        if not args or args == ["fail"]:
            return ExecutionResult(kind="transport")
        return original(target, args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    try:
        assert runtime.start(force=True)
        assert entered.wait(2)
        cmd = ["C:/test/adb.exe", "devices"] if command == "devices" else [
            "C:/test/adb.exe", "-s", "fake-device", "shell", "fail",
        ]
        assert runtime.try_run(cmd, 5).kind == "transport"
        release.set()
        assert runtime.wait(2)
        snapshot = runtime.snapshot()
        assert not (snapshot.fast_devices if command == "devices" else snapshot.fast_shell_devices)
    finally:
        release.set()
        assert runtime.wait(2)


@pytest.mark.parametrize("command", ["devices", "shell"])
def test_old_business_failure_cannot_invalidate_recovered_backend(backend, monkeypatch, command):
    runtime, clock, native, _ = backend
    prepare(runtime)
    original = module.capture
    entered, release = threading.Event(), threading.Event()
    blocked = [False]
    results = []

    def capture(target, args, **kwargs):
        if target == command and args in (["-l"], ["old"]) and not blocked[0]:
            blocked[0] = True
            entered.set()
            assert release.wait(2)
            return ExecutionResult(kind="transport")
        if target == command and args in ([], ["fail"]):
            return ExecutionResult(kind="transport")
        return original(target, args, **kwargs)

    monkeypatch.setattr(module, "capture", capture)
    prefix = ["C:/test/adb.exe", "devices"] if command == "devices" else [
        "C:/test/adb.exe", "-s", "fake-device", "shell",
    ]
    old = prefix + (["-l"] if command == "devices" else ["old"])
    failed = prefix + ([] if command == "devices" else ["fail"])
    worker = threading.Thread(target=lambda: results.append(runtime.try_run(old, 30)))
    try:
        worker.start()
        assert entered.wait(2)
        assert runtime.try_run(failed, 5).kind == "transport"
        clock[0] += 11
        recovered = threading.Event()
        previous = runtime._changed

        def changed(snapshot):
            previous(snapshot)
            if not snapshot.checking:
                recovered.set()

        runtime._changed = changed
        runtime.request_device_check()
        assert recovered.wait(2)
        assert runtime.snapshot().fast_devices
        assert runtime.snapshot().fast_shell_devices == 1
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert runtime.wait(2)
        assert results[0].kind == "transport"
        assert runtime.snapshot().fast_devices
        assert runtime.snapshot().fast_shell_devices == 1
        assert len(native) == 2
    finally:
        release.set()
        worker.join(2)


def test_native_override_suppresses_automatic_checks_but_keeps_manual_retest(backend):
    runtime, clock, native, calls = backend
    prepare(runtime)
    runtime.set_native_only(True)
    clock[0] += 11
    count = len(calls)
    runtime.request_device_check()
    assert runtime.try_run(["C:/test/adb.exe", "devices"], 5) is None
    assert runtime.wait(2)
    assert len(calls) == count
    assert runtime.start(force=True)
    assert runtime.wait(2)
    assert len(native) == 4
    assert runtime.snapshot().native_only
    assert not runtime.can_scan_fast()
    runtime.set_native_only(False)
    assert runtime.can_scan_fast()


@pytest.mark.parametrize("args", [[], ["-l"]], ids=["plain", "long"])
@pytest.mark.parametrize("use_runner", [False, True], ids=["runtime", "runner"])
@pytest.mark.parametrize("change", ["reconnect", "retest"])
def test_old_successful_listing_is_stale_after_runtime_refresh(
    backend, monkeypatch, args, use_runner, change,
):
    runtime, _, native, _ = backend
    prepare(runtime)
    execution.install_adb_runtime(runtime)
    original = module.capture
    entered, release, refreshed = threading.Event(), threading.Event(), threading.Event()
    blocked = [False]
    listing = (
        LISTING.replace(b"transport_id:1", b"transport_id:2")
        if change == "reconnect" else LISTING
    )
    results = []

    def capture(command, args, **kwargs):
        if command == "devices":
            if not blocked[0]:
                blocked[0] = True
                entered.set()
                assert release.wait(2)
                return ExecutionResult(LISTING)
            return ExecutionResult(listing)
        return original(command, args, **kwargs)

    previous = runtime._changed

    def changed(snapshot):
        previous(snapshot)
        if not snapshot.checking:
            refreshed.set()

    runtime._changed = changed
    monkeypatch.setattr(module, "capture", capture)
    native_run = Mock()
    monkeypatch.setattr(execution.subprocess, "run", native_run)
    run = execution.CommandRunner.run if use_runner else runtime.try_run
    worker = threading.Thread(
        target=lambda: results.append(run(["C:/test/adb.exe", "devices", *args], 30))
    )
    try:
        worker.start()
        assert entered.wait(2)
        if change == "reconnect":
            runtime.observe_devices(listing.decode())
        else:
            assert runtime.start(force=True)
        assert refreshed.wait(2)
        assert runtime.snapshot().fast_shell_devices == 1
        native_count = 3 if change == "reconnect" else 4
        assert len(native) == native_count
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert runtime.wait(2)
        result = results[0]
        if use_runner:
            assert not result.success
            assert result.stale
            assert result.output == result.error == ""
        else:
            assert result.kind == "stale"
            assert result.stdout == result.stderr == b""
        assert runtime.snapshot().fast_devices
        assert runtime.snapshot().fast_shell_devices == 1
        assert len(native) == native_count
        native_run.assert_not_called()
        assert execution.CommandRunner.active_count() == 0
    finally:
        release.set()
        worker.join(2)


def test_completed_shell_result_survives_device_reconnection(backend, monkeypatch):
    runtime, _, native, _ = backend
    prepare(runtime)
    original = module.capture
    listing = LISTING.replace(b"transport_id:1", b"transport_id:2")
    refreshed = threading.Event()
    expected = ExecutionResult(b"business output", b"business stderr", 7)
    business_calls = []
    previous = runtime._changed

    def changed(snapshot):
        previous(snapshot)
        if not snapshot.checking:
            refreshed.set()

    def capture(command, args, **kwargs):
        if command == "devices":
            return ExecutionResult(listing)
        if args == ["business"]:
            business_calls.append(args)
            runtime.observe_devices(listing.decode())
            assert refreshed.wait(2)
            return expected
        return original(command, args, **kwargs)

    runtime._changed = changed
    monkeypatch.setattr(module, "capture", capture)
    result = runtime.try_run(
        ["C:/test/adb.exe", "-s", "fake-device", "shell", "business"], 30,
    )

    assert result == expected
    assert runtime.wait(2)
    assert runtime.snapshot().fast_devices
    assert runtime.snapshot().fast_shell_devices == 1
    assert business_calls == [["business"]]
    assert len(native) == 3
