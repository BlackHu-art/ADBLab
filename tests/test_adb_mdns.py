"""mDNS 快速查询只使用离线协议与进程替身，验证路由、预算及取消边界。"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from core import adb_runtime as runtime_module
from core import adb_transport as transport
from core import exec as execution
from core.adb_runtime import AdbRuntime
from core.adb_transport import ExecutionResult
from core.native_process import NativeCommandScope


def forbidden(*_args, **_kwargs):
    pytest.fail("测试不得启动真实进程、连接网络或触发全局探测")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(transport.socket, "create_connection", forbidden)
    monkeypatch.setattr(runtime_module, "popen_native", forbidden)
    monkeypatch.setattr(execution, "run_native", forbidden)


class Socket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = []
        self.closed = False
        self.on_recv = None

    def settimeout(self, _timeout):
        pass

    def sendall(self, payload):
        self.sent.append(payload)

    def recv(self, _size):
        if self.on_recv is not None:
            self.on_recv()
        if not self.response:
            return b""
        value = bytes(self.response[:1])
        del self.response[:1]
        return value

    def close(self):
        self.closed = True


def framed(payload):
    return b"OKAY" + f"{len(payload):04x}".encode() + payload


@pytest.mark.parametrize(
    "action, payload, expected",
    [
        ("check", b"mdns daemon version [adb discovery 0.0.0]",
         b"mdns daemon version [adb discovery 0.0.0]"),
        ("services", b"fixture _adb-tls-pairing._tcp. 192.0.2.1:1234\n",
         b"List of discovered mdns services\nfixture _adb-tls-pairing._tcp. 192.0.2.1:1234\n"),
        ("services", b"", b"List of discovered mdns services\n"),
    ],
)
def test_mdns_wire_request_and_fragmented_raw_response(monkeypatch, action, payload, expected):
    sock = Socket(framed(payload))
    monkeypatch.setattr(transport.socket, "create_connection", lambda *_a, **_k: sock)
    result = transport.capture("mdns", [action], serial=None, timeout=1)
    request = f"host:mdns:{action}".encode()
    assert result == ExecutionResult(expected)
    assert sock.sent == [f"{len(request):04x}".encode() + request]
    assert sock.closed


@pytest.mark.parametrize(
    "args,serial",
    [([], None), (["restart"], None), (["check", "extra"], None), (["services"], "fixture")],
)
def test_invalid_mdns_action_never_opens_connection(args, serial):
    result = transport.capture("mdns", args, serial=serial, timeout=1)
    assert result.kind == "protocol"


@pytest.mark.parametrize(
    "response", [b"FAIL0007private", b"OKAYzzzz", b"OKAY0004ab", b"XXXX", b"OKAY0001\xff"],
)
def test_mdns_protocol_failure_closes_connection_without_private_output(monkeypatch, response):
    sock = Socket(response)
    monkeypatch.setattr(transport.socket, "create_connection", lambda *_a, **_k: sock)
    result = transport.capture("mdns", ["check"], serial=None, timeout=1)
    assert result.kind == "protocol" and sock.closed
    assert b"private" not in result.stderr


@pytest.mark.parametrize("ending", ["cancelled", "timeout", "transport"])
def test_mdns_read_failure_keeps_result_semantics_and_closes(monkeypatch, ending):
    sock = Socket(b"")
    cancelled = threading.Event()

    def fail():
        if ending == "cancelled":
            cancelled.set()
            raise TimeoutError
        if ending == "timeout":
            raise TimeoutError
        raise OSError("private")

    sock.on_recv = fail
    monkeypatch.setattr(transport.socket, "create_connection", lambda *_a, **_k: sock)
    result = transport.capture(
        "mdns", ["check"], serial=None, timeout=1,
        cancelled=cancelled.is_set if ending == "cancelled" else None,
    )
    assert result.kind == ending and sock.closed


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    path = str(tmp_path / "adb.exe")
    instance = AdbRuntime(forbidden)
    instance._path = path
    monkeypatch.setattr(instance, "start", forbidden)
    monkeypatch.setattr(instance, "request_device_check", forbidden)
    monkeypatch.setattr(instance, "wait_for_device_check", forbidden)
    monkeypatch.setattr(runtime_module, "capture", forbidden)
    monkeypatch.setattr(execution, "_adb_runtime", instance)
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)
    monkeypatch.setattr(execution, "_log_if_slow", lambda *_a: None)
    yield instance, path
    instance.close()
    assert instance.wait(1)


def test_frozen_default_environment_ignores_later_global_server_override(runtime, monkeypatch):
    instance, path = runtime
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:elsewhere:5038")
    calls = []

    def capture(command, args, **kwargs):
        calls.append((command, args, kwargs))
        assert instance.is_running()
        return ExecutionResult(b"mdns ready")

    monkeypatch.setattr(runtime_module, "capture", capture)
    assert instance.try_run_mdns([path, "mdns", "check"], 15, env={}).stdout == b"mdns ready"
    assert calls[0][:2] == ("mdns", ["check"])
    assert calls[0][2]["serial"] is None and 0 < calls[0][2]["timeout"] <= 1
    assert not instance.is_running() and instance.wait(0)
    assert not instance._host.available and not instance._shell


@pytest.mark.parametrize(
    "key",
    [
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS",
        "ANDROID_ADB_SERVER_PORT", "adb_server_socket",
    ],
)
@pytest.mark.parametrize("value", ["", "custom"])
def test_frozen_custom_server_environment_never_routes_to_default_server(runtime, key, value):
    instance, path = runtime
    assert instance.try_run_mdns([path, "mdns", "check"], 15, env={key: value}) is None


@pytest.mark.parametrize("case", ["missing-path", "different-path", "native", "invalid-action"])
def test_mdns_requires_selected_client_and_current_mode(runtime, case):
    instance, path = runtime
    args = [path, "mdns", "check"]
    if case == "missing-path":
        instance._path = None
    elif case == "different-path":
        args[0] += "-other"
    elif case == "native":
        instance.set_mode("native")
    else:
        args.append("extra")
    assert instance.try_run_mdns(args, 15, env={}) is None


def test_mdns_reads_native_mode_again_for_each_query(runtime, monkeypatch):
    instance, path = runtime
    calls = []

    def capture(*_args, **_kwargs):
        calls.append(True)
        return ExecutionResult(b"ready")

    monkeypatch.setattr(runtime_module, "capture", capture)
    assert instance.try_run_mdns([path, "mdns", "check"], 15, env={}).kind == "completed"
    instance.set_mode("native")
    assert instance.try_run_mdns([path, "mdns", "services"], 15, env={}) is None
    assert len(calls) == 1


def test_mdns_expired_budget_never_connects(runtime):
    instance, path = runtime
    result = instance.try_run_mdns([path, "mdns", "check"], 0, env={})
    assert result.kind == "timeout" and not instance.is_running()


@pytest.mark.parametrize("action", ["close", "prepare_shutdown", "cancel"])
def test_mdns_rejects_stopped_runtime_before_capture(runtime, action):
    instance, path = runtime
    cancelled = threading.Event()
    if action == "cancel":
        cancelled.set()
    else:
        getattr(instance, action)()
    result = instance.try_run_mdns([path, "mdns", "check"], 15, cancelled.is_set, env={})
    assert result.kind == "cancelled" and not instance.is_running()


@pytest.mark.parametrize("action", ["close", "prepare_shutdown", "cancel"])
def test_mdns_active_query_observes_stop_and_releases_runtime(runtime, monkeypatch, action):
    instance, path = runtime
    cancelled = threading.Event()

    def capture(*_args, **kwargs):
        assert instance.is_running() and not instance.wait(0)
        if action == "cancel":
            cancelled.set()
        else:
            getattr(instance, action)()
        assert kwargs["cancelled"]()
        return ExecutionResult(b"late success")

    monkeypatch.setattr(runtime_module, "capture", capture)
    result = instance.try_run_mdns([path, "mdns", "check"], 15, cancelled.is_set, env={})
    assert result.kind == "cancelled"
    assert not instance.is_running() and instance.wait(0)


@pytest.mark.parametrize("kind", ["unavailable", "transport", "protocol", "timeout"])
def test_readonly_failure_can_fall_back_without_invalidating_other_capabilities(
    runtime, monkeypatch, kind,
):
    instance, path = runtime
    host = dataclasses.asdict(instance._host)
    shell = dict(instance._shell)
    monkeypatch.setattr(runtime_module, "capture", lambda *_a, **_k: ExecutionResult(kind=kind))
    assert instance.try_run_mdns([path, "mdns", "services"], 15, env={}) is None
    assert dataclasses.asdict(instance._host) == host and instance._shell == shell
    assert not instance.is_running()


def test_mdns_exception_still_releases_active_request(runtime, monkeypatch):
    instance, path = runtime

    def capture(*_args, **_kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(runtime_module, "capture", capture)
    with pytest.raises(RuntimeError, match="synthetic"):
        instance.try_run_mdns([path, "mdns", "check"], 15, env={})
    assert not instance.is_running()


@pytest.mark.parametrize("budget,expected", [(15.0, 14.0), (0.5, None)])
def test_command_runner_mdns_fallback_shares_budget_and_preserves_scope(
    runtime, monkeypatch, budget, expected,
):
    _instance, path = runtime
    now = [0.0]
    scope = NativeCommandScope()
    environment = {"FIXTURE": "snapshot"}
    native_calls = []
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(execution, "perf_counter", lambda: now[0])

    def capture(_command, _args, **kwargs):
        now[0] += kwargs["timeout"]
        return ExecutionResult(kind="timeout")

    def native(command, timeout, cancelled, **kwargs):
        native_calls.append((command, timeout, kwargs))
        assert not cancelled()
        return ExecutionResult(b"native response")

    monkeypatch.setattr(runtime_module, "capture", capture)
    monkeypatch.setattr(execution, "native_capture", native)
    result = execution.CommandRunner.run(
        [path, "mdns", "check"], timeout=budget, env=environment, command_scope=scope,
    )
    if expected is None:
        assert result.timed_out and native_calls == []
    else:
        assert result.success and result.output == "native response"
        assert len(native_calls) == 1 and native_calls[0][1] == pytest.approx(expected)
        assert native_calls[0][2]["env"] is environment
        assert native_calls[0][2]["command_scope"] is scope


@pytest.mark.parametrize("budget,expected", [(2.0, []), (2.5, [0.5])])
def test_mdns_admission_deducts_client_resolution_from_total_budget(
    runtime, monkeypatch, budget, expected,
):
    _instance, path = runtime
    now = [0.0]
    captures = []
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(execution, "perf_counter", lambda: now[0])
    monkeypatch.setattr(execution, "native_capture", forbidden)

    def resolve(command):
        now[0] += 2
        return command

    def capture(*_args, **kwargs):
        captures.append(kwargs["timeout"])
        return ExecutionResult(b"ready")

    monkeypatch.setattr(execution, "resolve_command", resolve)
    monkeypatch.setattr(runtime_module, "capture", capture)
    result = execution.CommandRunner.run([path, "mdns", "check"], timeout=budget, env={})
    assert captures == expected
    assert result.success if expected else result.timed_out


def test_command_runner_closes_failed_socket_before_native_fallback(runtime, monkeypatch):
    _instance, path = runtime
    sock = Socket(b"FAIL0007private")
    monkeypatch.setattr(transport.socket, "create_connection", lambda *_a, **_k: sock)
    monkeypatch.setattr(runtime_module, "capture", transport.capture)

    def native(*_args, **_kwargs):
        assert sock.closed
        return ExecutionResult(b"native response")

    monkeypatch.setattr(execution, "native_capture", native)
    result = execution.CommandRunner.run([path, "mdns", "check"], env={})
    assert result.success and result.output == "native response"
    assert sock.sent


@pytest.mark.parametrize("during_query", [False, True])
def test_scope_stop_alone_cancels_direct_mdns_without_native_fallback(
    runtime, monkeypatch, during_query,
):
    _instance, path = runtime
    scope = NativeCommandScope()
    monkeypatch.setattr(execution, "native_capture", forbidden)
    if during_query:
        def capture(*_args, **kwargs):
            scope.request_stop()
            assert kwargs["cancelled"]()
            return ExecutionResult(kind="protocol")

        monkeypatch.setattr(runtime_module, "capture", capture)
    else:
        scope.request_stop()
    result = execution.CommandRunner.run(
        [path, "mdns", "check"], env={}, command_scope=scope, cancelled=lambda: False,
    )
    assert result.cancelled and not scope.is_running()


def test_scope_with_pending_client_never_starts_concurrent_mdns_query(runtime):
    _instance, path = runtime
    scope = NativeCommandScope()
    token = scope._begin_command()
    assert token is not None
    try:
        result = execution.CommandRunner.run(
            [path, "mdns", "check"], env={}, command_scope=scope,
        )
        assert not result.success and scope.is_running()
    finally:
        scope._finish_command(token)
    assert not scope.is_running()


@pytest.mark.parametrize("scoped", [False, True])
def test_mdns_without_frozen_environment_preserves_existing_native_route(
    runtime, monkeypatch, scoped,
):
    _instance, path = runtime
    scope = NativeCommandScope() if scoped else None
    calls = []

    def native(command, _timeout, _cancelled, **kwargs):
        calls.append((command, kwargs))
        return ExecutionResult(b"native")

    monkeypatch.setattr(execution, "native_capture", native)
    result = execution.CommandRunner.run(
        [path, "mdns", "check"], cancelled=lambda: False, command_scope=scope,
    )
    assert result.success and result.output == "native"
    assert len(calls) == 1 and calls[0][1].get("command_scope") is scope


@pytest.mark.parametrize(
    "args,options",
    [
        (["pair", "192.0.2.1:1234"], {"input_bytes": b"123456\n"}),
        (["connect", "192.0.2.1:1234"], {}),
        (["devices"], {}),
        (["mdns", "check", "extra"], {}),
        (["mdns", "check"], {"native_only": True}),
        (["mdns", "check"], {"input_bytes": b"input"}),
    ],
)
def test_other_scoped_commands_keep_native_execution(runtime, monkeypatch, args, options):
    _instance, path = runtime
    scope = NativeCommandScope()
    calls = []

    def native(command, _timeout, _cancelled, **kwargs):
        calls.append((command, kwargs))
        return ExecutionResult(b"native")

    monkeypatch.setattr(execution, "native_capture", native)
    result = execution.CommandRunner.run(
        [path, *args], env={}, command_scope=scope, **options,
    )
    assert result.success and result.output == "native"
    assert len(calls) == 1 and calls[0][0] == [path, *args]
    assert calls[0][1]["command_scope"] is scope
    assert calls[0][1]["input_bytes"] == options.get("input_bytes")


def test_shell_mdns_with_environment_remains_rejected(runtime, monkeypatch):
    _instance, path = runtime
    monkeypatch.setattr(execution, "native_capture", forbidden)
    result = execution.CommandRunner.run([path, "mdns", "check"], shell=True, env={})
    assert not result.success
