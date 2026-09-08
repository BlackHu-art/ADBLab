"""验证采集停止时的等待边界，以及进程状态在单周期内的共享。"""

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android import startup as startup_module
from mobileperf.android.fd import FdInfoPackageCollector
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.startup import StartUp
from mobileperf.android.thread_num import ThreadNumPackageCollector


@pytest.fixture
def runtime(tmp_path):
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    yield
    RuntimeData.end_run()


@pytest.mark.parametrize("signal", ["event", "file"])
def test_collection_stop_interrupts_the_sampling_interval(monkeypatch, tmp_path, runtime, signal):
    startup = StartUp.__new__(StartUp)
    startup.serialnum = "test-device"
    startup.packages = ["com.example.app"]
    startup.frequency = 3
    startup.timeout = 30
    startup.config_dic = {
        "monkey": "false", "main_activity": "", "activity_list": "",
        "save_path": str(tmp_path),
    }
    startup.exceptionlog_list = []
    startup.monitors = []
    startup.stop_file = str(tmp_path / "stop")
    startup._adb_execution = None
    startup.device = Mock()
    startup.device.adb.is_connected.return_value = True
    startup.device.adb.is_app_installed.return_value = True
    startup.clear_heapdump = Mock()
    startup.save_device_info = Mock()
    stopped = threading.Event()
    startup.stop = stopped.set
    entered_interval = threading.Event()
    original_check = startup.check_exit_signal_quit

    def check_exit():
        entered_interval.set()
        return original_check()

    startup.check_exit_signal_quit = check_exit
    for name in (
        "CpuMonitor", "MemMonitor", "TrafficMonitor", "FPSMonitor", "FdMonitor",
        "ThreadNumMonitor", "LogcatMonitor",
    ):
        monkeypatch.setattr(startup_module, name, Mock())
    # 固定 Logcat 启动等待不属于本回归；保留真正的采样间隔等待。
    monkeypatch.setattr(startup_module, "time", SimpleNamespace(
        time=time.time, monotonic=time.monotonic,
        sleep=lambda seconds: None if seconds == 1 else time.sleep(seconds),
    ))
    worker = threading.Thread(target=startup._run_collection, args=(30,))
    worker.start()
    try:
        assert entered_interval.wait(2)
        if signal == "event":
            RuntimeData.exit_event.set()
        else:
            (tmp_path / "stop").write_text("stop")
        assert stopped.wait(0.6), "stop waited for the full sampling interval"
    finally:
        RuntimeData.exit_event.set()
        worker.join(4)
        assert not worker.is_alive()


@pytest.mark.parametrize("kind", ["fd", "threads"])
def test_process_collector_stop_interrupts_interval_wait(tmp_path, runtime, kind):
    sampled = threading.Event()

    def status(*_args, **_kwargs):
        sampled.set()
        return "FDSize:\t64\nThreads:\t8\n"

    device = SimpleNamespace(adb=SimpleNamespace(
        get_pid_from_pck=lambda *_args, **_kwargs: 42, run_shell_cmd=status,
    ))
    collector = (
        FdInfoPackageCollector(device, "com.example.app", interval=3)
        if kind == "fd" else ThreadNumPackageCollector(device, "com.example.app", interval=3)
    )
    collector.start("test-start")
    worker = (
        collector.collect_fd_thread if kind == "fd" else collector.collect_thread_num_thread
    )
    try:
        assert sampled.wait(2)
        collector.stop()
        assert not worker.is_alive(), "stop returned with the interval waiter still alive"
    finally:
        collector._stop_event.set()
        worker.join(4)
        assert not worker.is_alive()


def test_process_metrics_share_a_cycle_and_refresh_after_pid_restart(monkeypatch, runtime):
    from mobileperf.android import process_status
    from mobileperf.android.tools.androiddevice import ADB

    now = [100.0]
    monkeypatch.setattr(process_status, "time", SimpleNamespace(
        monotonic=lambda: now[0], time=lambda: now[0] + 1000,
    ))
    adb = ADB.__new__(ADB)
    adb._sdk_version = 34
    calls = []
    pid = [42]

    def query(command, **_options):
        calls.append(command)
        if command == "ps -A":
            return (
                "USER PID PPID VSZ RSS WCHAN ADDR S NAME\n"
                f"u0 {pid[0]} 1 0 0 0 0 S com.example.app"
            )
        assert command == f"cat /proc/{pid[0]}/status"
        return "FDSize:\t64\nThreads:\t8\n"

    adb.run_shell_cmd = query
    samples = process_status.ProcessStatusSampler(adb, "com.example.app", interval=5)
    device = SimpleNamespace(adb=adb)
    fd = FdInfoPackageCollector(device, "com.example.app", process_samples=samples)
    threads = ThreadNumPackageCollector(device, "com.example.app", process_samples=samples)
    assert fd.get_process_fd() == [1100.0, "com.example.app", 42, 64]
    assert threads.get_process_thread_num("com.example.app") == [1100.0, "com.example.app", 42, 8]
    assert calls == ["ps -A", "cat /proc/42/status"]

    pid[0] = 77
    now[0] = 105.0
    assert threads.get_process_thread_num("com.example.app")[2:] == [77, 8]
    assert fd.get_process_fd()[2:] == [77, 64]
    assert calls == ["ps -A", "cat /proc/42/status", "ps -A", "cat /proc/77/status"]


def test_concurrent_metric_readers_share_inflight_status_and_keep_cancellation_local(runtime):
    from concurrent.futures import ThreadPoolExecutor

    from mobileperf.android.process_status import ProcessStatusSampler

    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    reads = []

    def query(*_args, **_options):
        reads.append(True)
        entered.set()
        assert release.wait(2)
        return "FDSize:\t32\nThreads:\t4\n"

    adb = SimpleNamespace(get_pid_from_pck=lambda *_args, **_options: 42, run_shell_cmd=query)
    samples = ProcessStatusSampler(adb, "com.example.app", interval=30)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(samples.read)
        assert entered.wait(1)
        second = pool.submit(samples.read)
        stopping = pool.submit(samples.read, cancelled=cancelled.is_set)
        cancelled.set()
        try:
            assert stopping.result(timeout=0.5) is None
        finally:
            release.set()
        assert first.result(timeout=1) == second.result(timeout=1)
    assert reads == [True]


@pytest.mark.parametrize("bad_pid", [None, "", "bad;cmd", 0])
def test_missing_or_invalid_pid_does_not_issue_status_query(runtime, bad_pid):
    from mobileperf.android.process_status import ProcessStatusSampler

    def status(*_args, **_kwargs):
        pytest.fail("status queried without a valid PID")

    adb = SimpleNamespace(get_pid_from_pck=lambda *_args, **_kwargs: bad_pid, run_shell_cmd=status)
    samples = ProcessStatusSampler(adb, "com.example.app", interval=5)
    assert samples.read() is None


@pytest.mark.parametrize(
    "kind", ["traffic_old", "traffic_new", "activity", "fps", "fps_result", "memory"],
)
def test_other_collector_intervals_are_woken_by_stop(monkeypatch, runtime, kind):
    from mobileperf.android import devicemonitor
    from mobileperf.android.fps import SurfaceStatsCollector
    from mobileperf.android.meminfos import MemInfoPackageCollector
    from mobileperf.android.trafficstats import TrafficCollecor

    sampled = threading.Event()
    device = SimpleNamespace(adb=Mock())
    if kind.startswith("traffic"):
        device.adb.get_sdk_version.return_value = 28 if kind == "traffic_old" else 34

        def empty_sample(command, **_kwargs):
            if command.startswith("dumpsys package"):
                return "userId=10000"
            sampled.set()
            return ""

        device.adb.run_shell_cmd.side_effect = empty_sample
        collector = TrafficCollecor(device, ["com.example.app"], interval=3)
        collector.start("2026_09_08_12_00_00")
        worker = collector.collect_traffic_thread
        event = collector._stop_event
    elif kind == "activity":
        monkeypatch.setattr(devicemonitor, "AndroidDevice", lambda _target: device)

        def activity():
            sampled.set()
            return "com.example.app/Main"

        device.adb.get_current_activity.side_effect = activity
        collector = devicemonitor.DeviceMonitor("test-device", "com.example.app", interval=3)
        collector.start("2026_09_08_12_00_00")
        worker = collector.activity_monitor_thread
        event = collector.stop_event
    elif kind.startswith("fps"):
        collector = SurfaceStatsCollector(device, 3, "com.example.app", None, 166)
        collector.focus_window = "test-window"
        if kind == "fps":
            def frames():
                sampled.set()
                return 1 / 60, [[0.0, 1.0, 1.0]]

            collector._get_surfaceflinger_frame_data = frames
            worker = threading.Thread(target=collector._collector_thread)
            collector.collector_thread = worker
        else:
            def calculate(*_args):
                sampled.set()
                return 30, 0

            collector._calculate_results_new = calculate
            collector.data_queue.put((1 / 60, [[0.0, 1.0, 1.0]], time.time()))
            worker = threading.Thread(target=collector._calculator_thread, args=("test-start",))
            collector.calculator_thread = worker
        event = collector.stop_event
        worker.start()
    else:
        RuntimeData.config_dic = {"dumpheap_freq": 3600, "pid_change_focus_package": []}
        device.adb.list_dir.return_value = []
        collector = MemInfoPackageCollector(device, ["com.example.app"], interval=3)
        collector._dumpsys_process_meminfo = lambda _package: SimpleNamespace(
            totalPSS=1, pid=42, javaHeap=0, nativeHeap=0, system=1,
        )

        def memory():
            sampled.set()
            return SimpleNamespace(
                package_pid_pss_list=[{"package": "com.example.app", "pid": 42, "pss": 1}],
                totalmem=4096, freemem=1024, total_pss=1,
            )

        collector._dumpsys_meminfo = memory
        collector.start("2026_09_08_12_00_00")
        worker = collector.collect_mem_thread
        event = collector._stop_event
    try:
        assert sampled.wait(2)
        collector.stop()
        assert not worker.is_alive(), "sampling interval survived stop"
    finally:
        event.set()
        if kind.startswith("fps"):
            collector.data_queue.put("Stop")
        worker.join(4)
        assert not worker.is_alive()


@pytest.mark.parametrize("kind", ["fd", "threads"])
def test_single_metric_keeps_csv_shape_and_does_not_sleep_past_its_deadline(
    tmp_path, runtime, kind,
):
    import csv

    device = SimpleNamespace(adb=SimpleNamespace(
        get_pid_from_pck=lambda *_args, **_kwargs: 42,
        run_shell_cmd=lambda *_args, **_kwargs: "FDSize:\t64\nThreads:\t8\n",
    ))
    collector = (
        FdInfoPackageCollector(device, "com.example.app", interval=3, timeout=0.1)
        if kind == "fd" else ThreadNumPackageCollector(
            device, "com.example.app", interval=3, timeout=0.1,
        )
    )
    collector.start("test-start")
    worker = collector.collect_fd_thread if kind == "fd" else collector.collect_thread_num_thread
    try:
        worker.join(0.6)
        assert not worker.is_alive(), "interval extended the collection deadline"
    finally:
        collector.stop()
        worker.join(1)
    filename, column, metric = (
        ("fd_num.csv", "fd_num", "64") if kind == "fd"
        else ("thread_num.csv", "thread_num", "8")
    )
    with (tmp_path / filename).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["datatime", "packagename", "pid", column]
    assert len(rows) == 2
    assert rows[1][1:] == ["com.example.app", "42", metric]


def test_failed_sample_recovers_next_cycle_and_other_device_has_separate_state(
    monkeypatch, runtime,
):
    from mobileperf.android import process_status

    now = [10.0]
    monkeypatch.setattr(process_status, "time", SimpleNamespace(
        monotonic=lambda: now[0], time=lambda: now[0],
    ))
    reads = []

    def first_device(*_args, **_kwargs):
        reads.append(True)
        return "" if len(reads) == 1 else "FDSize:\t64\nThreads:\t8\n"

    first = process_status.ProcessStatusSampler(SimpleNamespace(
        get_pid_from_pck=lambda *_args, **_kwargs: 42, run_shell_cmd=first_device,
    ), "com.example.app", 5)
    second = process_status.ProcessStatusSampler(SimpleNamespace(
        get_pid_from_pck=lambda *_args, **_kwargs: 77,
        run_shell_cmd=lambda *_args, **_kwargs: "FDSize:\t32\nThreads:\t4\n",
    ), "com.example.app", 5)
    assert first.read() is None
    assert first.read() is None
    assert second.read().pid == 77
    assert len(reads) == 1
    now[0] = 15.0
    assert first.read().pid == 42
    assert len(reads) == 2


def test_pid_lookup_exhaustion_prevents_a_new_status_command(monkeypatch, runtime):
    from mobileperf.android import process_status

    now = [10.0]
    monkeypatch.setattr(process_status, "time", SimpleNamespace(
        monotonic=lambda: now[0], time=lambda: now[0],
    ))

    def lookup(*_args, **options):
        assert options["timeout"] == 1
        now[0] = 11.1
        assert options["cancelled"]()
        return 42

    def status(*_args, **_kwargs):
        pytest.fail("status queried after the total budget expired")

    samples = process_status.ProcessStatusSampler(SimpleNamespace(
        get_pid_from_pck=lookup, run_shell_cmd=status,
    ), "com.example.app", 5)
    assert samples.read(timeout=1) is None
