"""使用模拟 ADB 进程验证性能采集的 Monkey 真实启动、失败和停止链路。"""

from __future__ import annotations

import io
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android import monkey as monkey_module
from mobileperf.android import startup as startup_module
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.monkey import Monkey, MonkeyError
from mobileperf.android.startup import StartUp
from mobileperf.android.tools import androiddevice
from mobileperf.android.tools.androiddevice import ADB


class _Process:
    """EOF 提交退出码，阻塞模式只在显式终止后结束读取。"""

    def __init__(self, output=b"", *, exit_code=0, block=False):
        self.returncode = None
        self.exit_code = exit_code
        self.terminated = 0
        self.killed = 0
        self._released = threading.Event()
        process = self

        class Output(io.BytesIO):
            def readline(self, *args):
                if block:
                    if not process._released.wait(2):
                        raise RuntimeError("test process was not stopped")
                value = super().readline(*args)
                if not value and process.returncode is None:
                    process.returncode = process.exit_code
                return value

        self.stdout = Output(output)
        self.stdin = io.BytesIO()
        self.stderr = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = -15
        self._released.set()

    def kill(self):
        self.killed += 1
        self.returncode = -9
        self._released.set()

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-adb", timeout)
        return self.returncode


@pytest.fixture
def monkey_factory(monkeypatch, tmp_path):
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    instances = []

    def build(process):
        adb = SimpleNamespace(run_shell_cmd=Mock(return_value=process), kill_process=Mock())
        monkeypatch.setattr(
            monkey_module, "AndroidDevice", lambda _device: SimpleNamespace(adb=adb),
        )
        monitor = Monkey("demo-device", "com.example.app", timeout=60)
        instances.append(monitor)
        return monitor, adb

    yield build
    for monitor in instances:
        monitor.stop()
    RuntimeData.end_run()


def test_monkey_start_launches_once_and_stop_reaps_reader(monkey_factory):
    process = _Process(block=True)
    monitor, adb = monkey_factory(process)

    monitor.start("2026_09_06_00_00_00")
    monitor.start("2026_09_06_00_00_00")

    adb.run_shell_cmd.assert_called_once()
    command = adb.run_shell_cmd.call_args.args[0]
    assert command.startswith("monkey -p com.example.app ")
    assert adb.run_shell_cmd.call_args.kwargs == {"sync": False, "merge_stderr": True}
    assert monitor.running
    monitor.stop()
    assert not monitor.running
    assert not monitor._monkey_thread.is_alive()
    assert process.terminated == 1
    assert process.stdout.closed
    assert process.stdin.closed
    adb.kill_process.assert_called_once_with("com.android.commands.monkey")
    monitor.raise_if_failed()


def test_monkey_failed_launch_leaves_start_retryable(monkey_factory):
    process = _Process(block=True)
    monitor, adb = monkey_factory(process)
    adb.run_shell_cmd.side_effect = [OSError("simulated launch failure"), process]

    with pytest.raises(RuntimeError, match="Monkey"):
        monitor.start("2026_09_06_00_00_00")
    assert not monitor.running

    monitor.start("2026_09_06_00_00_01")
    assert adb.run_shell_cmd.call_count == 2
    assert monitor.running
    monitor.stop()
    monitor.raise_if_failed()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_monkey_eof_flushes_short_log_and_reports_failed_exit(
    monkey_factory, tmp_path, exit_code,
):
    output = b"Monkey diagnostic: test output\nEvents injected: 3\n"
    process = _Process(output, exit_code=exit_code)
    monitor, adb = monkey_factory(process)

    monitor.start("2026_09_06_00_00_00")
    adb.run_shell_cmd.assert_called_once()
    monitor._monkey_thread.join(timeout=1)
    assert not monitor._monkey_thread.is_alive()
    assert not monitor.running
    logs = list(tmp_path.glob("monkey_*.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8") == output.decode()
    assert process.stdout.closed
    if exit_code:
        with pytest.raises(RuntimeError, match="Monkey"):
            monitor.raise_if_failed()
    else:
        monitor.raise_if_failed()


@pytest.mark.parametrize("merge_stderr", [False, True])
def test_async_adb_can_merge_monkey_stderr_without_changing_default(monkeypatch, merge_stderr):
    captured = {}
    process = object()

    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return process

    monkeypatch.setattr(androiddevice.subprocess, "Popen", popen)
    adb = ADB.__new__(ADB)
    adb._adb_path = "fake-adb"
    adb._device_id = "demo-device"

    options = {"merge_stderr": True} if merge_stderr else {}
    result = adb._run_cmd_once("shell", "monkey -p com.example.app 1", sync=False, **options)
    assert result is process
    assert captured["stderr"] == (subprocess.STDOUT if merge_stderr else subprocess.PIPE)
    assert captured["shell"] is False


@pytest.fixture
def startup_factory(monkeypatch, tmp_path):
    other_monitors = []
    execution = Mock()
    execution.stop_requested.return_value = False
    monkeypatch.setattr(startup_module, "MobilePerfAdbExecutor", Mock(return_value=execution))
    RuntimeData.begin_run()

    def build_monitor(*_args, process_samples=None):
        result = SimpleNamespace(start=Mock(), stop=Mock())
        other_monitors.append(result)
        return result

    for name in (
        "CpuMonitor", "MemMonitor", "TrafficMonitor", "FPSMonitor", "FdMonitor", "ThreadNumMonitor",
    ):
        monkeypatch.setattr(startup_module, name, build_monitor)
    monkeypatch.setattr(startup_module, "LogcatMonitor", Mock())
    clock = [0.0]
    monkeypatch.setattr(startup_module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=time.time,
    ))
    report = Mock()
    monkeypatch.setattr(startup_module, "Report", report)
    startup = StartUp.__new__(StartUp)
    startup.serialnum = "demo-device"
    startup.packages = ["com.example.app"]
    startup.frequency = 1
    startup.timeout = 60
    startup.config_dic = {
        "monkey": "true", "main_activity": [], "activity_list": [],
        "save_path": str(tmp_path), "timeout": 60,
    }
    startup.exceptionlog_list = []
    startup.monitors = []
    startup.logcat_monitor = None
    startup.device = SimpleNamespace(adb=SimpleNamespace(
        is_connected=Mock(return_value=True), is_app_installed=Mock(return_value=True),
        kill_process=Mock(),
    ))
    for name in (
        "clear_heapdump", "save_device_info", "add_device_info", "pull_heapdump", "pull_log_files",
    ):
        setattr(startup, name, Mock())
    startup.stop_file = None

    def wait(seconds):
        if startup._exit_event.is_set() or startup.check_stop_file_quit():
            return True
        clock[0] += seconds
        return startup._exit_event.is_set() or startup.check_stop_file_quit()

    startup._wait_for_stop = wait

    def build(monitor):
        monkeypatch.setattr(startup_module, "Monkey", Mock(return_value=monitor))
        return startup, other_monitors, report

    yield build
    RuntimeData.end_run()


def test_requested_monkey_launch_failure_stops_monitors_and_cannot_report_success(
    monkey_factory, startup_factory,
):
    monitor, adb = monkey_factory(_Process())
    adb.run_shell_cmd.side_effect = OSError("simulated launch failure")
    startup, other_monitors, report = startup_factory(monitor)

    with pytest.raises(RuntimeError, match="Monkey"):
        startup.run(time_out=2)

    assert len(other_monitors) == 6
    for other in other_monitors:
        other.start.assert_called_once()
        other.stop.assert_called_once()
    report.assert_called_once()


def test_monkey_reader_start_failure_reclaims_the_created_process(
    monkeypatch, monkey_factory,
):
    process = _Process(block=True)
    monitor, adb = monkey_factory(process)
    monkeypatch.setattr(
        threading.Thread, "start", Mock(side_effect=RuntimeError("simulated thread failure")),
    )

    with pytest.raises(MonkeyError, match="启动失败"):
        monitor.start("2026_09_06_00_00_00")

    assert not monitor.running
    assert process.terminated == 1
    assert process.stdout.closed and process.stdin.closed
    adb.kill_process.assert_called_once_with("com.android.commands.monkey")


def test_monkey_missing_stdout_reclaims_the_created_process(monkey_factory):
    process = _Process()
    process.stdout.close()
    process.stdout = None
    monitor, adb = monkey_factory(process)

    with pytest.raises(MonkeyError, match="启动失败"):
        monitor.start("2026_09_06_00_00_00")

    assert not monitor.running
    assert process.terminated == 1 and process.stdin.closed
    adb.kill_process.assert_called_once_with("com.android.commands.monkey")


def test_monkey_stop_escalates_a_process_that_ignores_terminate(monkey_factory):
    process = _Process(block=True)
    process.terminate = Mock()
    monitor, _adb = monkey_factory(process)
    monitor.start("2026_09_06_00_00_00")

    monitor.stop()

    process.terminate.assert_called_once()
    assert process.killed == 1
    assert not monitor._monkey_thread.is_alive()
    assert process.stdout.closed
    monitor.raise_if_failed()


@pytest.mark.parametrize("stop_requested", [False, True])
def test_startup_success_and_user_stop_reap_monkey_and_preserve_report(
    monkeypatch, monkey_factory, startup_factory, stop_requested,
):
    monitor, adb = monkey_factory(_Process(block=True))
    startup, other_monitors, report = startup_factory(monitor)
    stop_states = []

    def check_stop():
        stopped = stop_requested and monitor.running
        stop_states.append(stopped)
        return stopped

    monkeypatch.setattr(startup, "check_stop_file_quit", check_stop)

    startup.run(time_out=2)

    adb.run_shell_cmd.assert_called_once()
    adb.kill_process.assert_called_once()
    assert not monitor._monkey_thread.is_alive()
    for other in other_monitors:
        other.stop.assert_called_once()
    report.assert_called_once()
    if stop_requested:
        assert stop_states[0] is False and stop_states[-1] is True
    else:
        assert stop_states and not any(stop_states)
    monitor.raise_if_failed()


@pytest.mark.parametrize("failure_phase", ["running", "stopping"])
def test_startup_propagates_required_monkey_failure_after_preserving_partial_report(
    monkeypatch, monkey_factory, startup_factory, failure_phase,
):
    monitor, _adb = monkey_factory(_Process(block=True))
    startup, other_monitors, report = startup_factory(monitor)
    real_stop = monitor.stop

    def fail():
        monitor._failure = MonkeyError("simulated Monkey failure")

    if failure_phase == "running":
        monkeypatch.setattr(
            startup, "check_stop_file_quit",
            lambda: (fail() if monitor.running else None, False)[1],
        )
    else:
        monkeypatch.setattr(monitor, "stop", lambda: (real_stop(), fail()))

    with pytest.raises(MonkeyError, match="simulated Monkey failure"):
        startup.run(time_out=2)

    assert not monitor._monkey_thread.is_alive()
    for other in other_monitors:
        other.stop.assert_called_once()
    report.assert_called_once()


def test_frozen_worker_does_not_turn_required_monkey_failure_into_success(monkeypatch):
    import main

    startup = SimpleNamespace(run=Mock(side_effect=MonkeyError("simulated Monkey failure")))
    monkeypatch.setattr(startup_module, "StartUp", Mock(return_value=startup))

    with pytest.raises(MonkeyError, match="simulated Monkey failure"):
        main._run_mobileperf_worker(["--config", "fake-config.conf"])


def test_startup_monkey_stop_failure_cleans_other_monitors_and_preserves_report(
    monkey_factory, startup_factory,
):
    monitor, adb = monkey_factory(_Process(block=True))
    adb.kill_process.side_effect = [OSError("simulated device disconnect"), None]
    startup, other_monitors, report = startup_factory(monitor)

    with pytest.raises(MonkeyError, match="停止未完成"):
        startup.run(time_out=2)

    assert not monitor._monkey_thread.is_alive()
    for other in other_monitors:
        other.stop.assert_called_once()
    report.assert_called_once()
    assert monitor._owns_process
    monitor.stop()
    assert not monitor._owns_process


def test_optional_metric_failure_does_not_abort_requested_monkey(
    monkeypatch, monkey_factory, startup_factory,
):
    monitor, adb = monkey_factory(_Process(block=True))
    startup, _other_monitors, report = startup_factory(monitor)
    optional = SimpleNamespace(
        start=Mock(side_effect=OSError("simulated unsupported metric")), stop=Mock(),
    )
    monkeypatch.setattr(startup_module, "FdMonitor", Mock(return_value=optional))

    startup.run(time_out=2)

    optional.start.assert_called_once()
    optional.stop.assert_called_once()
    adb.run_shell_cmd.assert_called_once()
    adb.kill_process.assert_called_once()
    report.assert_called_once()
