"""验证启动后的模式切换、重复检测和实际命令执行继续输出可读摘要。"""

import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import adb_runtime as module
from core.adb_runtime import AdbRuntime
from core.adb_transport import ExecutionResult
from core.log_service import LogService
from utils import adb_debug, adb_resolver


@pytest.fixture
def output(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
        monkeypatch.delenv(name, raising=False)
    with patch.object(LogService, "write_developer_console") as writer:
        yield writer


def info_messages(writer):
    return [call.args[1] for call in writer.call_args_list if call.args[0] == "INFO"]


def test_mode_switch_announces_path_and_effective_scan_backend(output):
    runtime = AdbRuntime(lambda: "C:/bundle/adb.exe")
    runtime._path = "C:/bundle/adb.exe"
    runtime._host.available = True
    try:
        runtime.set_native_only(True)
        runtime.set_native_only(False)
        runtime.set_native_only(False)
        rows = info_messages(output)
        assert len(rows) == 2
        assert all("C:/bundle/adb.exe" in row for row in rows)
        assert "原生 ADB" in rows[0]
        assert "优先快速" in rows[1]
        assert "快速直连" in rows[1]
    finally:
        runtime.close()


def test_fast_mode_without_capability_does_not_claim_direct_execution(output, monkeypatch):
    runtime = AdbRuntime(lambda: "C:/bundle/adb.exe")
    runtime._path = "C:/bundle/adb.exe"
    runtime._status = "host_timeout"
    monkeypatch.setattr(runtime, "start", lambda **_: False)
    try:
        runtime.set_native_only(False)
        message, = info_messages(output)
        assert "优先快速" in message
        assert "设备列表选路：原生 ADB" in message
        assert "host_timeout" in message
    finally:
        runtime.close()


def test_missing_client_does_not_claim_native_backend_is_ready(output):
    adb_debug.event(
        "probe_complete", selected_adb=None, selection_mode="auto", status="missing_adb",
        fast_devices=False,
    )
    message, = info_messages(output)
    assert "设备列表选路：不可用" in message
    assert "missing_adb" in message


def test_recheck_announces_start_and_finish_even_with_cached_adb(output, monkeypatch):
    monkeypatch.setattr(adb_resolver, "_resolved", True)
    monkeypatch.setattr(adb_resolver, "_adb_path", "C:/bundle/adb.exe")
    listing = ExecutionResult(b"List of devices attached\n")
    monkeypatch.setattr(module, "capture", lambda *_args, **_kwargs: listing)
    monkeypatch.setattr(module, "native_capture", lambda *_args, **_kwargs: listing)
    runtime = AdbRuntime(adb_resolver.resolve_adb_path)
    try:
        assert runtime.start()
        assert runtime.wait(2)
        output.reset_mock()
        assert runtime.recheck()
        assert runtime.wait(2)
        rows = info_messages(output)
        starts = [row for row in rows if "开始检测" in row]
        ends = [row for row in rows if "检测结束" in row]
        assert len(starts) == len(ends) == 1
        assert "C:/bundle/adb.exe" in starts[0] and "C:/bundle/adb.exe" in ends[0]
        assert "ready" in ends[0]
    finally:
        runtime.close()
        assert runtime.wait(2)


@pytest.mark.parametrize("backend,label", [
    ("native_client", "原生 ADB"), ("server_direct", "快速直连"),
])
def test_each_actual_execution_announces_backend_without_private_arguments(output, backend, label):
    command = ["C:/bundle/adb.exe", "-s", "PRIVATE_DEVICE", "shell", "echo PRIVATE_VALUE"]
    for _ in range(2):
        adb_debug.command(command, backend=backend)
        adb_debug.command(command, backend=backend, phase="finish", status="completed")
    rows = info_messages(output)
    assert len(rows) == 2
    assert all(label in row and "C:/bundle/adb.exe" in row and "shell" in row for row in rows)
    assert "PRIVATE_DEVICE" not in str(output.call_args_list)
    assert "PRIVATE_VALUE" not in str(output.call_args_list)


def test_probe_shutdown_does_not_announce_normal_completion(output, monkeypatch):
    runtime = AdbRuntime(lambda: None)
    entered, release = threading.Event(), threading.Event()

    def probe():
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(runtime, "_probe_once", probe)
    try:
        assert runtime.start()
        assert entered.wait(2)
        runtime.close()
        release.set()
        assert runtime.wait(2)
        assert not any("检测结束" in row for row in info_messages(output))
    finally:
        release.set()
        runtime.close()
        assert runtime.wait(2)


def test_frozen_probe_failure_keeps_stage_diagnostic_without_console(monkeypatch):
    """冻结模式必须通过专用诊断回调保留失败阶段，而不依赖开发控制台。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    messages = []
    detail = SimpleNamespace(
        stage="read_status", reason="timeout", elapsed_ms=2998.0, stage_ms=2997.0,
        budget_ms=3000.0, errno=None, winerror=None, received_bytes=2,
    )
    result = SimpleNamespace(kind="timeout", diagnostics=detail)
    monkeypatch.setattr(module, "capture", lambda *_args, **_kwargs: result)
    runtime = AdbRuntime(lambda: "C:/PRIVATE_PATH/adb.exe", diagnostic=messages.append)
    try:
        actual, _elapsed = runtime._probe_capability(
            "devices", ["-l"], serial=None, retry=False,
            current=lambda: True, initial_timeout=3.0,
        )
        assert actual is result
        record, = [message for message in messages if "stage=read_status" in message]
        for field in (
            "backend=server_direct", "attempt=1", "status=timeout", "reason=timeout",
            "elapsed_ms=2998.0", "stage_ms=2997.0", "budget_ms=3000.0", "received_bytes=2",
        ):
            assert field in record
        assert "PRIVATE_PATH" not in record
    finally:
        runtime.close()


def test_obsolete_probe_does_not_publish_stage_diagnostic(monkeypatch):
    messages = []
    monkeypatch.setattr(
        module, "capture", lambda *_args, **_kwargs: ExecutionResult(kind="timeout"),
    )
    runtime = AdbRuntime(lambda: None, diagnostic=messages.append)
    try:
        runtime._probe_capability(
            "devices", [], serial=None, retry=False, current=lambda: False,
        )
        assert messages == []
    finally:
        runtime.close()


def test_successful_probe_does_not_invent_unmeasured_stage_fields(monkeypatch):
    """成功探测只记录已有测量值，不能把未采集的阶段数据写成零。"""
    messages = []
    monkeypatch.setattr(
        module, "capture", lambda *_args, **_kwargs: ExecutionResult(b"ready"),
    )
    runtime = AdbRuntime(lambda: None, diagnostic=messages.append)
    try:
        runtime._probe_capability(
            "devices", [], serial=None, retry=False, current=lambda: True,
        )
        record, = messages
        assert "stage=completed" in record
        assert "elapsed_ms=" in record
        assert "budget_ms=" in record
        assert "stage_ms=" not in record
        assert "received_bytes=" not in record
    finally:
        runtime.close()
