"""配对服务穿过真实命令层和运行时；仅替换 socket 与原生进程边界。"""

import threading
from collections import deque
from types import SimpleNamespace

import pytest

from core import adb_runtime as runtime_module
from core import exec as execution
from core.adb_runtime import AdbRuntime
from core.adb_transport import ExecutionResult
from core.native_process import NativeCommandScope
from services.adb_pairing import PairingContext, PairingService, create_qr_request

pytestmark = pytest.mark.integration


HEADER = "List of discovered mdns services\n"
MDNS_CHECK = b"mdns daemon version [OpenScreen discovery 0.0.0]\n"
PAIR_ENDPOINT = "192.0.2.1:37001"
CONNECT_ENDPOINT = "192.0.2.1:37002"
GUID = "adb-offline-fixture"


@pytest.fixture
def mdns_flow(monkeypatch, tmp_path):
    for key in (
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    adb = tmp_path / "adb.exe"
    adb.touch()
    runtime = AdbRuntime(lambda: str(adb))
    # 只注入已选路径，不启动自动探测线程；mDNS 不依赖设备 Shell 能力。
    runtime._path = str(adb)
    scope = NativeCommandScope()
    flow = SimpleNamespace(
        runtime=runtime, scope=scope, now=0.0, cancelled=threading.Event(),
        fast=deque(), native=deque(), calls=[], progress=[],
        request=create_qr_request(1), context=PairingContext(str(adb), {}, 3),
    )

    def capture(command, args, **_kwargs):
        assert command == "mdns"
        flow.calls.append(("fast", tuple(args)))
        assert flow.fast, f"unexpected fast command: {args}"
        expected, result = flow.fast.popleft()
        assert args == expected
        assert runtime.is_running()
        assert execution.CommandRunner.active_count() == 1
        return result() if callable(result) else result

    def native_capture(cmd, timeout, cancelled, **kwargs):
        flow.calls.append(("native", tuple(cmd[1:])))
        assert flow.native, f"unexpected native command: {cmd[1:]}"
        expected, result = flow.native.popleft()
        assert cmd == [str(adb), *expected]
        assert 0 < timeout <= 15
        assert not cancelled()
        assert kwargs["command_scope"] is scope
        assert kwargs["env"] == {}
        return result

    def wait(event, seconds):
        flow.now += seconds
        return event.is_set()

    monkeypatch.setattr(execution, "_adb_runtime", runtime)
    monkeypatch.setattr(runtime_module, "capture", capture)
    monkeypatch.setattr(execution, "native_capture", native_capture)
    flow.service = PairingService(clock=lambda: flow.now, wait=wait)
    yield flow
    runtime.close()
    assert runtime.wait(0)
    assert execution.CommandRunner.active_count() == 0
    assert not scope.is_running() and scope.wait(0)


def run(flow, on_qr):
    return flow.service.run(
        flow.request, flow.context, flow.cancelled, flow.scope,
        flow.progress.append, on_qr,
    )


def pairing_service(flow):
    return ExecutionResult(
        f"{HEADER}{flow.request.service_name} _adb-tls-pairing._tcp {PAIR_ENDPOINT}\n".encode(),
    )


def test_fast_qr_waits_for_visible_ack_before_scan_budget_and_native_pair(mdns_flow):
    flow = mdns_flow
    flow.fast.extend([
        (["check"], ExecutionResult(MDNS_CHECK)),
        (["services"], pairing_service(flow)),
    ])
    flow.native.append((["pair", PAIR_ENDPOINT], ExecutionResult(kind="transport")))

    def shown(request_id, png, modules, remaining):
        assert request_id == 1 and png.startswith(b"\x89PNG\r\n\x1a\n") and modules > 0
        assert flow.calls == [("fast", ("check",))]
        assert all(event.state == "Checking" for event in flow.progress)
        assert 0 < remaining <= 15
        # 显示确认消耗准备预算，确认之后仍应得到完整的扫码预算。
        flow.now += 7
        return True

    outcome = run(flow, shown)

    assert outcome.state == "Uncertain" and outcome.reason == "pair_uncertain"
    scan = [event for event in flow.progress if event.state == "WaitingForScan"]
    assert scan and scan[0].remaining_seconds == 120
    assert flow.calls == [
        ("fast", ("check",)), ("fast", ("services",)),
        ("native", ("pair", PAIR_ENDPOINT)),
    ]
    assert not flow.fast and not flow.native


def test_fast_discovery_keeps_connect_failure_native_and_does_not_replay(mdns_flow):
    flow = mdns_flow
    connect_service = ExecutionResult(
        f"{HEADER}{GUID} _adb-tls-connect._tcp {CONNECT_ENDPOINT}\n".encode(),
    )
    flow.fast.extend([
        (["check"], ExecutionResult(MDNS_CHECK)),
        (["services"], pairing_service(flow)),
        (["services"], connect_service),
        (["services"], connect_service),
    ])
    flow.native.extend([
        (["pair", PAIR_ENDPOINT], ExecutionResult(
            f"Successfully paired to {PAIR_ENDPOINT} [guid={GUID}]\n".encode(),
        )),
        (["devices"], ExecutionResult(b"List of devices attached\n")),
        (["connect", f"{GUID}._adb-tls-connect._tcp"], ExecutionResult(kind="transport")),
        (["devices"], ExecutionResult(b"List of devices attached\n")),
    ])
    flow.service = PairingService(
        clock=lambda: flow.now,
        wait=lambda _event, _seconds: setattr(flow, "now", flow.now + 30),
    )

    outcome = run(flow, lambda *_: True)

    assert outcome.state == "PairedOnly" and outcome.reason == "connection_timeout"
    assert outcome.continuation is not None
    assert [args[0] for route, args in flow.calls if route == "native"] == [
        "pair", "devices", "connect", "devices",
    ]
    assert not flow.fast and not flow.native


def test_fast_check_failure_falls_back_once_and_qr_cancellation_blocks_scan(mdns_flow):
    flow = mdns_flow
    flow.fast.append((["check"], ExecutionResult(kind="protocol")))
    flow.native.append((["mdns", "check"], ExecutionResult(MDNS_CHECK)))

    def cancelled_during_display(_request_id, png, _modules, _remaining):
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        flow.cancelled.set()
        return True

    outcome = run(flow, cancelled_during_display)

    assert outcome.state == "Idle" and outcome.reason == "cancelled"
    assert flow.calls == [("fast", ("check",)), ("native", ("mdns", "check"))]
    assert all(event.state != "WaitingForScan" for event in flow.progress)
    assert not flow.fast and not flow.native


def test_cancelling_fast_check_discards_success_without_qr_or_native_fallback(mdns_flow):
    flow = mdns_flow

    def late_success():
        flow.cancelled.set()
        return ExecutionResult(MDNS_CHECK)

    def unexpected_qr(*_args):
        pytest.fail("取消后的检查结果不能重新显示二维码")

    flow.fast.append((["check"], late_success))
    outcome = run(flow, unexpected_qr)

    assert outcome.state == "Idle" and outcome.reason == "cancelled"
    assert flow.calls == [("fast", ("check",))]
    assert all(event.state != "WaitingForScan" for event in flow.progress)
    assert not flow.fast and not flow.native
