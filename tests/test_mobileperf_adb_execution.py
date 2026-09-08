"""验证采集内核的双后端结果、启动隔离和取消收尾契约。"""

import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.adb_transport import ExecutionResult
from mobileperf.android import adb_execution
from mobileperf.android.adb_execution import MobilePerfAdbExecutor
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools import androiddevice
from mobileperf.android.tools.androiddevice import ADB


@pytest.fixture
def execution(monkeypatch):
    monkeypatch.delenv("MOBILEPERF_ADB_MODE", raising=False)
    runtime = Mock()
    runtime.try_run.return_value = ExecutionResult(b"fast\n")
    runtime.wait.return_value = True
    monkeypatch.setattr(adb_execution, "AdbRuntime", Mock(return_value=runtime))
    instance = MobilePerfAdbExecutor(lambda: "fake-adb", "device-test", threading.Event())
    yield instance
    instance.close()


@pytest.fixture
def adb(monkeypatch):
    RuntimeData.begin_run()
    monkeypatch.setattr(ADB, "get_adb_path", staticmethod(lambda: "fake-adb"))
    instance = ADB("device-test")
    yield instance
    RuntimeData.end_run()


@pytest.mark.parametrize("result, expected", [
    (ExecutionResult(b" a\r\nb \n", b"warning", 7), "a\r\nb"),
    (ExecutionResult(b"", b"denied\n", 1), "denied"),
    (ExecutionResult(b"\xff"), "b'\\xff'"),
    (ExecutionResult(kind="timeout"), ""),
    (ExecutionResult(kind="cancelled"), ""),
    (ExecutionResult(stderr=b"ADB connection failed", kind="transport"), ""),
])
def test_adb_preserves_raw_result_conversion(adb, monkeypatch, result, expected):
    executor = Mock()
    executor.run.return_value = result
    adb._execution = executor
    popen = Mock(side_effect=AssertionError("unexpected native replay"))
    monkeypatch.setattr(androiddevice.subprocess, "Popen", popen)

    assert adb.run_shell_cmd("printf output") == expected
    executor.run.assert_called_once_with(
        ["fake-adb", "-s", "device-test", "shell", "printf output"], 10, None
    )
    popen.assert_not_called()


def test_device_failure_preserves_connection_state(adb):
    adb._execution = Mock()
    adb._execution.run.return_value = ExecutionResult(stderr=b"device not found", returncode=1)
    assert adb.run_shell_cmd("getprop") == ""
    assert not adb.before_connect and not adb.after_connect


def test_transport_failure_then_reconnect_records_uptime(adb, tmp_path):
    RuntimeData.package_save_path = str(tmp_path)
    adb._execution = Mock()
    adb._execution.run.side_effect = [
        ExecutionResult(kind="protocol"), ExecutionResult(b"recovered"),
        ExecutionResult(b"100.00"), ExecutionResult(b"next"),
    ]
    assert adb.run_shell_cmd("getprop") == ""
    assert not adb.before_connect and not adb.after_connect
    assert adb.run_shell_cmd("getprop") == "recovered"
    assert adb.run_shell_cmd("getprop") == "next"
    assert "100.00" in (tmp_path / "uptime.txt").read_text()
    assert adb.before_connect and adb.after_connect


def test_cancelled_reconnect_does_not_query_or_write_uptime(adb, tmp_path):
    RuntimeData.package_save_path = str(tmp_path)
    adb.before_connect, adb.after_connect = False, True
    adb._execution = Mock()
    adb._execution.run.return_value = ExecutionResult(b"100.00")

    assert adb.run_shell_cmd("getprop", cancelled=lambda: True) == ""
    adb._execution.run.assert_not_called()
    assert not (tmp_path / "uptime.txt").exists()
    assert not adb.before_connect


@pytest.mark.parametrize("uptime_elapsed", [0.4, 1.0])
def test_reconnect_uptime_and_main_query_share_deadline(adb, tmp_path, monkeypatch, uptime_elapsed):
    RuntimeData.package_save_path = str(tmp_path)
    adb.before_connect, adb.after_connect = False, True
    now = [0.0]
    monkeypatch.setattr(androiddevice, "time", SimpleNamespace(
        monotonic=lambda: now[0], time=lambda: now[0],
    ))
    budgets = []

    def run(_cmd, timeout, _cancelled):
        budgets.append(timeout)
        if len(budgets) == 1:
            now[0] += uptime_elapsed
            return ExecutionResult(b"100.00")
        return ExecutionResult(b" next\r\nline \n")

    adb._execution = SimpleNamespace(run=run)
    result = adb.run_shell_cmd("getprop", timeout=1)

    if uptime_elapsed < 1:
        assert result == "next\r\nline"
        assert budgets == pytest.approx([1, 0.6])
        assert "100.00" in (tmp_path / "uptime.txt").read_text()
    else:
        assert result == ""
        assert budgets == [1]


def test_cancellation_during_reconnect_uptime_stops_main_query(adb, tmp_path):
    RuntimeData.package_save_path = str(tmp_path)
    adb.before_connect, adb.after_connect = False, True
    stopped = threading.Event()
    observed_cancel = []

    def run(_cmd, _timeout, cancelled):
        stopped.set()
        observed_cancel.append(cancelled is not None and cancelled())
        return ExecutionResult(kind="cancelled")

    adb._execution = SimpleNamespace(run=run)
    assert adb.run_shell_cmd("getprop", timeout=1, cancelled=stopped.is_set) == ""
    assert observed_cancel == [True]
    assert not (tmp_path / "uptime.txt").exists()


def test_async_reconnect_returns_process_without_blocking_uptime(adb, tmp_path, monkeypatch):
    RuntimeData.package_save_path = str(tmp_path)
    adb.before_connect, adb.after_connect = False, True
    adb._execution = Mock()
    adb._execution.run.return_value = ExecutionResult(b"100.00")
    process = Mock()
    monkeypatch.setattr(androiddevice.subprocess, "Popen", Mock(return_value=process))

    assert adb.run_shell_cmd("top", sync=False, cancelled=lambda: True) is process
    adb._execution.run.assert_not_called()
    process.communicate.assert_not_called()
    assert not (tmp_path / "uptime.txt").exists()
    assert not adb.before_connect


@pytest.mark.parametrize("timeout", [None, 0, -1])
def test_reconnect_preserves_infinite_native_wait(adb, tmp_path, monkeypatch, timeout):
    RuntimeData.package_save_path = str(tmp_path)
    adb.before_connect, adb.after_connect = False, True
    adb._execution = Mock()
    adb._execution.run.return_value = ExecutionResult(b"100.00")
    process = Mock()
    process.communicate.side_effect = [(b"100.00", b""), (b"native", b"")]
    process.poll.return_value = 0
    monkeypatch.setattr(androiddevice.subprocess, "Popen", Mock(return_value=process))

    assert adb.run_shell_cmd("top", timeout=timeout) == "native"
    adb._execution.run.assert_not_called()
    assert [call.kwargs["timeout"] for call in process.communicate.call_args_list] == [None, None]


def test_reconnect_keeps_executor_cleanup_thread_permission(adb, execution, tmp_path):
    RuntimeData.package_save_path = str(tmp_path)
    adb.before_connect, adb.after_connect = False, True
    adb._execution = execution
    execution._exit_event.set()
    execution.begin_cleanup()
    execution.runtime.try_run.side_effect = [
        ExecutionResult(b"100.00"), ExecutionResult(b"cleanup"),
    ]

    assert adb.run_shell_cmd("getprop", timeout=1) == "cleanup"
    assert "100.00" in (tmp_path / "uptime.txt").read_text()
    assert adb.before_connect and adb.after_connect


@pytest.mark.parametrize("options", [
    {"sync": False}, {"sync": False, "merge_stderr": True},
    {"merge_stderr": True}, {"timeout": None}, {"timeout": 0},
])
def test_special_calls_preserve_native_process_contract(adb, monkeypatch, options):
    executor = Mock()
    adb._execution = executor
    process = Mock()
    process.communicate.return_value = (b"native", b"")
    process.poll.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(androiddevice.subprocess, "Popen", popen)

    result = adb.run_shell_cmd("top", **options)
    assert result is process if options.get("sync") is False else result == "native"
    executor.run.assert_not_called()
    assert popen.call_args.kwargs["stderr"] == (
        subprocess.STDOUT if options.get("merge_stderr") else subprocess.PIPE
    )


def test_file_transfer_keeps_native_boundary(adb, monkeypatch):
    adb._execution = Mock()
    process = Mock()
    process.communicate.return_value = (b"copied", b"")
    process.poll.return_value = 0
    monkeypatch.setattr(androiddevice.subprocess, "Popen", Mock(return_value=process))
    assert adb.run_adb_cmd("pull", "/device/file", "local-file") == "copied"
    adb._execution.run.assert_not_called()


def test_devices_uses_session_and_preserves_online_filter(adb, monkeypatch):
    RuntimeData.adb_execution = Mock()
    RuntimeData.adb_execution.run.return_value = ExecutionResult(
        b"List of devices attached\na\tdevice\nb\toffline\nc\tunauthorized\n"
    )
    monkeypatch.setattr(androiddevice.subprocess, "run", Mock(side_effect=AssertionError))
    assert ADB.list_device() == ["a"]
    RuntimeData.adb_execution.run.return_value = ExecutionResult(kind="cancelled")
    assert ADB.list_device() == []


@pytest.mark.parametrize("kind", ["completed", "protocol", "transport", "timeout", "cancelled"])
def test_runtime_result_never_replayed(execution, monkeypatch, kind):
    raw = ExecutionResult(returncode=7, kind=kind)
    execution.runtime.try_run.return_value = raw
    native = Mock(side_effect=AssertionError("unexpected replay"))
    monkeypatch.setattr(adb_execution, "native_capture", native)
    assert execution.run(["fake-adb", "shell", "cmd"], 10) is raw
    native.assert_not_called()


def test_native_selection_uses_remaining_deadline(execution, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(adb_execution, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def select(*_args):
        now[0] = 0.4
        return None

    execution.runtime.try_run.side_effect = select
    native = Mock(return_value=ExecutionResult(b"native"))
    monkeypatch.setattr(adb_execution, "native_capture", native)
    assert execution.run(["fake-adb", "shell", "cmd"], 1).stdout == b"native"
    assert native.call_args.args[1] == pytest.approx(0.6)


def test_stop_file_cancels_wait_and_allows_only_cleanup_thread(execution, tmp_path):
    stop_path = tmp_path / "stop"
    execution._stop_file = str(stop_path)
    entered = threading.Event()
    results = []

    def capture(_cmd, _timeout, cancelled):
        entered.set()
        deadline = time.monotonic() + 2
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        return ExecutionResult(kind="cancelled" if cancelled() else "timeout")

    execution.runtime.try_run.side_effect = capture
    worker = threading.Thread(target=lambda: results.append(execution.run(["adb"], 5)))
    worker.start()
    assert entered.wait(1)
    stop_path.write_text("stop")
    worker.join(1)
    assert not worker.is_alive() and results[0].kind == "cancelled"
    execution.begin_cleanup()
    execution.runtime.try_run.side_effect = None
    execution.runtime.try_run.return_value = ExecutionResult(b"cleanup")
    assert execution.run(["adb"], 1).stdout == b"cleanup"
    worker = threading.Thread(target=lambda: results.append(execution.run(["adb"], 1)))
    worker.start()
    worker.join(1)
    assert results[-1].kind == "cancelled"
    assert execution.close()
    assert execution.run(["adb"], 1).kind == "cancelled"


def test_close_waits_for_native_request(execution, monkeypatch):
    execution.runtime.try_run.return_value = None
    entered = threading.Event()

    def native(_cmd, _timeout, cancelled):
        entered.set()
        while not cancelled():
            time.sleep(0.01)
        return ExecutionResult(kind="cancelled")

    monkeypatch.setattr(adb_execution, "native_capture", native)
    worker = threading.Thread(target=lambda: execution.run(["adb"], 10))
    worker.start()
    assert entered.wait(1)
    assert execution.close(1)
    worker.join(1)
    assert not worker.is_alive()


def test_forced_native_skips_environment_probe(monkeypatch):
    monkeypatch.setenv("MOBILEPERF_ADB_MODE", "native")
    runtime = Mock()
    runtime.try_run.return_value = None
    monkeypatch.setattr(adb_execution, "AdbRuntime", Mock(return_value=runtime))
    native = Mock(return_value=ExecutionResult(b"native"))
    monkeypatch.setattr(adb_execution, "native_capture", native)
    execution = MobilePerfAdbExecutor(lambda: "adb", "device-test", threading.Event())
    try:
        execution.start()
        assert execution.run(["adb"], 1).stdout == b"native"
        runtime.start.assert_not_called()
        runtime.request_device_check.assert_not_called()
        runtime.set_native_only.assert_called_once_with(True)
    finally:
        execution.close()


def test_device_instances_keep_original_session(adb):
    old_execution = Mock()
    RuntimeData.adb_execution = old_execution
    old_adb = ADB("device-test")
    RuntimeData.end_run()
    RuntimeData.begin_run()
    RuntimeData.adb_execution = Mock()
    new_adb = ADB("device-test")
    assert old_adb._execution is old_execution
    assert new_adb._execution is RuntimeData.adb_execution
    assert old_adb._execution is not new_adb._execution


@pytest.mark.parametrize("outcome", ["success", "preflight_failure", "exception", "stopped"])
def test_startup_owns_executor_on_every_exit(monkeypatch, tmp_path, outcome):
    from mobileperf.android import startup as module
    from services.mobileperf_runner import MobilePerfRunConfig

    executor = Mock()
    executor.stop_requested.return_value = outcome == "stopped"
    monkeypatch.setattr(module, "MobilePerfAdbExecutor", Mock(return_value=executor))
    monkeypatch.setattr(ADB, "get_adb_path", staticmethod(lambda: "fake-adb"))
    config_path = MobilePerfRunConfig(
        device_id="test-device", package="com.example.app"
    ).write_config(tmp_path)
    startup = module.StartUp(config_path=config_path)
    if outcome == "preflight_failure":
        startup.clear_heapdump = Mock()
        startup.device.adb.is_connected = Mock(return_value=True)
        startup.device.adb.is_app_installed = Mock(return_value=False)
    else:
        run = Mock(side_effect=RuntimeError("simulated") if outcome == "exception" else None)
        monkeypatch.setattr(startup, "_run_collection", run)
    if outcome == "exception":
        with pytest.raises(RuntimeError, match="simulated"):
            startup.run()
    else:
        startup.run()
    executor.start.assert_called_once()
    executor.close.assert_called_once()
    assert startup.device.adb._execution is executor
    assert RuntimeData._instance is None
    if outcome == "stopped":
        run.assert_not_called()


def test_cpu_stop_cancels_inflight_query_and_interval_wait(monkeypatch, tmp_path):
    from mobileperf.android.cpu_top import CpuCollector

    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    device = SimpleNamespace(adb=Mock())
    device.adb.get_sdk_version.return_value = 30
    device.adb.run_shell_cmd.return_value = ""
    collector = CpuCollector(device, ["com.example.app"], interval=30)
    entered = threading.Event()

    def query(_cmd, *, timeout, cancelled):
        entered.set()
        deadline = time.monotonic() + 2
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        return ""

    device.adb.run_shell_cmd.side_effect = query
    try:
        collector.start("unused")
        assert entered.wait(1)
        collector.stop()
        assert not collector.collect_package_cpu_thread.is_alive()
        collector.stop()
        assert (tmp_path / "cpuinfo.csv").read_text().count("\n") == 1
    finally:
        collector._stop_event.set()
        collector.collect_package_cpu_thread.join(2)
        RuntimeData.end_run()


@pytest.mark.integration
@pytest.mark.parametrize("entry", ["source", "worker"])
def test_child_entry_honors_preexisting_stop_without_qt_or_probe(tmp_path, entry):
    from services.mobileperf_runner import MobilePerfRunConfig

    config = MobilePerfRunConfig(device_id="test-device", package="com.example.app")
    path = config.write_config(tmp_path)
    stop_file = tmp_path / "stop"
    stop_file.write_text("stop")
    env = os.environ.copy()
    env.update(
        MOBILEPERF_STOP_FILE=str(stop_file),
        MOBILEPERF_LOG_DIR=str(tmp_path / "logs"),
        MOBILEPERF_ADB_MODE="auto",
        ADB_PATH="nonexistent-adb-must-not-start",
    )
    script = """
import runpy, sys, threading
from mobileperf.android.globaldata import RuntimeData
if sys.argv[1] == 'worker':
    import main
    assert main._dispatch_cli(['--mobileperf-worker', '--config', sys.argv[2]]) == 0
else:
    sys.argv = ['startup', '--config', sys.argv[2]]
    runpy.run_module('mobileperf.android.startup', run_name='__main__')
assert RuntimeData._instance is None
assert not any(name.startswith('PySide6') for name in sys.modules)
assert not any(t.name == 'adblab-adb-probe' for t in threading.enumerate())
print('worker-clean')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, entry, path],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "worker-clean" in result.stdout


def test_cpu_sample_uses_cancellable_finite_query(tmp_path, monkeypatch):
    from mobileperf.android.cpu_top import CpuCollector

    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    device = SimpleNamespace(adb=Mock())
    device.adb.get_sdk_version.return_value = 30
    device.adb.run_shell_cmd.return_value = ""
    collector = CpuCollector(device, ["com.example.app"], interval=2)
    output = (
        "400%cpu 10%user 0%nice 20%sys 370%idle\n"
        "PID USER CPU% NAME\n123 shell 1 com.example.app\n"
    )
    device.adb.run_shell_cmd.return_value = output
    try:
        sample = collector._top_cpuinfo()
        assert sample is not None and sample.source == output
        options = device.adb.run_shell_cmd.call_args.kwargs
        assert options["timeout"] == 10
        assert not options["cancelled"]()
        before = (tmp_path / "top.txt").read_bytes()
        collector._stop_event.set()
        assert options["cancelled"]()
        assert collector._top_cpuinfo() is None
        assert (tmp_path / "top.txt").read_bytes() == before
    finally:
        RuntimeData.end_run()
