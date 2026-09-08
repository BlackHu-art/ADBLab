"""验证启动成本耗尽采集预算或收到停止信号后不会启动后续监控。"""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android import startup as startup_module
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.startup import StartUp


@pytest.mark.parametrize(
    ("boundary", "started_count"),
    [("device_info", 0), ("first_monitor", 1), ("logcat_wait", 6), ("stop", 1)],
)
def test_collection_start_checks_deadline_and_stop_before_each_monitor(
    monkeypatch, tmp_path, boundary, started_count,
):
    RuntimeData.begin_run()
    clock = [0.0]
    monkeypatch.setattr(startup_module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=time.time,
    ))
    monitors = [SimpleNamespace(start=Mock(), stop=Mock()) for _ in range(6)]
    for name, monitor in zip(
        ("CpuMonitor", "MemMonitor", "TrafficMonitor", "FPSMonitor", "FdMonitor",
         "ThreadNumMonitor"), monitors, strict=True,
    ):
        monkeypatch.setattr(startup_module, name, Mock(return_value=monitor))
    logcat = SimpleNamespace(start=Mock(), stop=Mock())
    monkeypatch.setattr(startup_module, "LogcatMonitor", Mock(return_value=logcat))
    report = Mock()
    monkeypatch.setattr(startup_module, "Report", report)
    startup = StartUp.__new__(StartUp)
    startup.serialnum = "test-device"
    startup.packages = ["com.example.app"]
    startup.frequency = 3
    startup.timeout = 1
    startup.config_dic = {
        "monkey": "false", "main_activity": "", "activity_list": "",
        "save_path": str(tmp_path),
    }
    startup.exceptionlog_list = []
    startup.monitors = []
    startup.logcat_monitor = None
    startup.stop_file = None
    startup._adb_execution = None
    startup.device = SimpleNamespace(adb=SimpleNamespace(
        is_connected=Mock(return_value=True), is_app_installed=Mock(return_value=True),
    ))
    for name in (
        "clear_heapdump", "save_device_info", "add_device_info", "pull_heapdump",
        "pull_log_files",
    ):
        setattr(startup, name, Mock())

    def consume_budget(*_args):
        clock[0] = 2.0

    def wait(seconds):
        clock[0] += seconds
        return RuntimeData.exit_event.is_set()

    startup._wait_for_stop = wait
    if boundary == "device_info":
        startup.save_device_info.side_effect = consume_budget
    elif boundary == "first_monitor":
        monitors[0].start.side_effect = consume_budget
    elif boundary == "stop":
        monitors[0].start.side_effect = lambda *_args: RuntimeData.exit_event.set()
    try:
        startup._run_collection(time_out=1)
        assert [monitor.start.call_count for monitor in monitors] == (
            [1] * started_count + [0] * (6 - started_count)
        )
        logcat.start.assert_not_called()
        for monitor in monitors:
            monitor.stop.assert_called_once()
        report.assert_called_once()
        assert startup._stop_called
    finally:
        RuntimeData.end_run()


@pytest.mark.parametrize("kind", ["fd", "threads"])
def test_process_metric_does_not_resample_when_interval_wait_returns_early(
    monkeypatch, tmp_path, kind,
):
    from mobileperf.android import fd, thread_num

    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    clock = [0.0]
    waits = []
    module = fd if kind == "fd" else thread_num
    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0],
    ))
    device = SimpleNamespace(adb=Mock())
    collector = (
        fd.FdInfoPackageCollector(device, "com.example.app", interval=10, timeout=2)
        if kind == "fd" else thread_num.ThreadNumPackageCollector(
            device, "com.example.app", interval=10, timeout=2,
        )
    )

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds / 2 if len(waits) == 1 else seconds
        return False

    collector._stop_event = SimpleNamespace(is_set=lambda: False, wait=wait)
    sample = Mock(return_value=[0.0, "com.example.app", 42, "64"])
    if kind == "fd":
        collector.get_process_fd = sample
        collect = collector._collect_fd_thread
    else:
        collector.get_process_thread_num = sample
        collect = collector._collect_thread_num_thread
    try:
        collect("test-start")
        sample.assert_called_once()
        assert clock[0] == 2
    finally:
        RuntimeData.end_run()
