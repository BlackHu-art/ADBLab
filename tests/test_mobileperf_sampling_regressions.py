"""覆盖 MobilePerf 首次清理和异常采样路径的节拍与归属。"""

import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.adb_transport import ExecutionResult
from mobileperf.android import startup as startup_module
from mobileperf.android.fps import SurfaceStatsCollector
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.heap_ownership import HeapOwnership
from mobileperf.android.meminfos import MemInfoPackageCollector
from mobileperf.android.startup import StartUp
from mobileperf.android.tools.androiddevice import ADB
from mobileperf.android.trafficstats import TrafficCollecor


@pytest.fixture
def runtime(tmp_path):
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    yield
    RuntimeData.end_run()


def test_first_startup_cleans_only_owned_heap_after_result_directory_exists(monkeypatch, tmp_path):
    RuntimeData.begin_run()
    try:
        result_dir = tmp_path / "com.example.app" / "test-start"
        owned = HeapOwnership(str(result_dir), "test-device")
        remote = owned.reserve("com.example.app")
        owned.mark_pulled(remote)
        rows = owned.entries()
        rows[0]["created"] = 0
        owned._write(rows)
        RuntimeData.package_save_path = None
        RuntimeData.top_dir = str(tmp_path)

        adb = ADB.__new__(ADB)
        adb._device_id = "test-device"
        adb._execution = None
        adb._owned_heap_command = Mock(return_value=ExecutionResult(kind="completed", returncode=0))
        adb.is_connected = Mock(return_value=True)
        adb.is_app_installed = Mock(return_value=True)
        monkeypatch.setattr(
            startup_module.TimeUtils, "getCurrentTimeUnderline", lambda: "test-start",
        )
        for name in ("CpuMonitor", "MemMonitor", "TrafficMonitor", "FPSMonitor",
                     "FdMonitor", "ThreadNumMonitor"):
            monkeypatch.setattr(startup_module, name, Mock(return_value=SimpleNamespace(
                start=Mock(), stop=Mock(),
            )))
        startup = StartUp.__new__(StartUp)
        startup.serialnum = "test-device"
        startup.packages = ["com.example.app"]
        startup.frequency = 1
        startup.timeout = 10
        startup.config_dic = {"monkey": "false", "main_activity": "", "activity_list": "",
                              "save_path": str(tmp_path)}
        startup.exceptionlog_list = []
        startup.monitors = []
        startup.logcat_monitor = None
        startup._adb_execution = None
        startup.device = SimpleNamespace(adb=adb)
        startup.save_device_info = lambda: RuntimeData.exit_event.set()
        startup.stop = Mock()
        startup._run_collection(time_out=10)

        adb._owned_heap_command.assert_called_once_with(["shell", f"rm -f -- '{remote}'"], 10)
        assert owned.entries() == []
    finally:
        RuntimeData.end_run()


def test_legacy_fps_waits_each_cycle_and_limits_backlog():
    collector = SurfaceStatsCollector(SimpleNamespace(adb=Mock()), 1, "com.example.app", None, 166,
                                      use_legacy=True)
    samples = []
    waits = []

    def sample():
        samples.append(True)
        return {"page_flip_count": len(samples)}

    collector._get_surface_stats_legacy = sample
    collector.stop_event = SimpleNamespace(
        is_set=lambda: len(samples) >= 5,
        wait=lambda seconds: waits.append(seconds),
    )
    collector._collector_thread()
    assert len(waits) == 5
    assert all(0 < seconds <= 1 for seconds in waits)
    assert collector.data_queue.maxsize > 0
    assert collector.data_queue.qsize() <= collector.data_queue.maxsize
    assert collector.data_queue.get_nowait() == "Stop"


def test_traffic_missing_pid_keeps_package_columns_and_restarts_baseline(monkeypatch, runtime):
    from mobileperf.android import trafficstats

    clock = [0.0]
    waits = []
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))
    pids = [None, 42, 42, 77, 77]
    lookup_count = [0]

    def pid(package):
        assert package == "com.example.app"
        index = lookup_count[0]
        lookup_count[0] += 1
        if index >= len(pids):
            collector._stop_event.set()
            return None
        return pids[index]

    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34, get_pid_from_pck=pid,
    )), ["com.example.app"], interval=1, timeout=5, traffic_queue=queue.Queue())
    collector._cat_traffic_device_dev = lambda: SimpleNamespace(
        source="ok", total=100, rx=50, tx=50,
    )
    values = {42: [(100, 50, 50), (1100, 550, 550)],
              77: [(9000, 4500, 4500), (10000, 5000, 5000)]}

    def process_snapshot(process_pid):
        total, rx, tx = values[process_pid].pop(0)
        return SimpleNamespace(source="ok", total=total, rx=rx, tx=tx)

    collector._cat_traffic_pid_dev = process_snapshot
    original_wait = collector._stop_event.wait

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        return original_wait(0)

    collector._stop_event.wait = wait
    collector.get_traffic_with_dev()
    rows = list(collector.traffic_queue.queue)
    assert len(waits) >= 5
    assert len(rows) == 5
    assert all(len(row) == 9 for row in rows[1:])
    assert [row[-1] for row in rows] == ["", 0.0, 0.98, 0.0, 0.98]


def test_traffic_missing_first_package_does_not_spin_or_shift_baseline(monkeypatch, runtime):
    from mobileperf.android import trafficstats

    clock = [0.0]
    waits = []
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))
    lookups = [0]

    def pid(package):
        lookups[0] += 1
        if lookups[0] > 12:
            collector._stop_event.set()
        return None if package == "com.example.first" else 42

    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34, get_pid_from_pck=pid,
    )), ["com.example.first", "com.example.second"], interval=1, timeout=3,
        traffic_queue=queue.Queue())
    collector._cat_traffic_device_dev = lambda: SimpleNamespace(
        source="ok", total=100, rx=50, tx=50,
    )
    collector._cat_traffic_pid_dev = lambda _pid: SimpleNamespace(
        source="ok", total=100, rx=50, tx=50,
    )
    original_wait = collector._stop_event.wait

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        return original_wait(0)

    collector._stop_event.wait = wait
    collector.get_traffic_with_dev()
    rows = list(collector.traffic_queue.queue)
    assert len(waits) == 3
    assert len(rows) == 3
    assert all(len(row) == 15 for row in rows)
    assert all(row[5:9] == ["", "", "", ""] for row in rows)


def test_traffic_collector_restarts_with_new_device_baseline(monkeypatch, runtime):
    from mobileperf.android import trafficstats

    clock = [0.0]
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))
    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34,
        get_pid_from_pck=lambda _package: 42,
    )), ["com.example.app"], interval=1, timeout=2, traffic_queue=queue.Queue())
    collector._cat_traffic_device_dev = lambda: SimpleNamespace(
        source="ok", total=clock[0] * 1000, rx=clock[0] * 500, tx=clock[0] * 500,
    )
    collector._cat_traffic_pid_dev = lambda _pid: SimpleNamespace(
        source="ok", total=clock[0] * 1000, rx=clock[0] * 500, tx=clock[0] * 500,
    )
    original_wait = collector._stop_event.wait

    def wait(seconds):
        clock[0] += seconds
        return original_wait(0)

    collector._stop_event.wait = wait
    collector.get_traffic_with_dev()
    collector.get_traffic_with_dev()
    rows = list(collector.traffic_queue.queue)
    assert len(rows) == 4
    assert [row[1] for row in rows] == [0.0, 0.98, 0.0, 0.98]


@pytest.mark.parametrize("failure", [RuntimeError("device offline"), ValueError("bad sample")])
def test_traffic_repeated_failure_waits_and_remains_cancellable(monkeypatch, runtime, failure):
    from mobileperf.android import trafficstats

    clock = [0.0]
    waits = []
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))
    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34,
    )), ["com.example.app"], interval=1, timeout=10)
    sample = Mock(side_effect=failure)
    collector._cat_traffic_device_dev = sample
    original_wait = collector._stop_event.wait

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        if len(waits) == 3:
            collector._stop_event.set()
        return original_wait(0)

    collector._stop_event.wait = wait
    collector.get_traffic_with_dev()
    assert sample.call_count == 3
    assert waits == [1, 1, 1]


def test_invalid_system_meminfo_waits_and_dumps_heap_once(monkeypatch, runtime):
    from mobileperf.android import meminfos

    clock = [0.0]
    waits = []
    monkeypatch.setattr(meminfos, "time", SimpleNamespace(time=lambda: clock[0]))
    RuntimeData.config_dic = {"dumpheap_freq": 3600, "pid_change_focus_package": []}
    adb = SimpleNamespace(run_shell_cmd=Mock(), cleanup_owned_heapdumps=Mock(), dumpheap=Mock())
    collector = MemInfoPackageCollector(SimpleNamespace(adb=adb), ["com.example.app"],
                                        interval=1, timeout=10)
    collector._dumpsys_process_meminfo = lambda _package: SimpleNamespace(
        totalPSS=1, pid=42, javaHeap=1, nativeHeap=1, system=1,
    )
    results = [None, None, SimpleNamespace(
        package_pid_pss_list=[{"package": "com.example.app", "pid": 42, "pss": 1}],
        totalmem=4096, freemem=1024, total_pss=1,
    )]
    reads = [0]

    def system_snapshot():
        reads[0] += 1
        if reads[0] > 8:
            collector._stop_event.set()
            return None
        return results.pop(0) if results else None

    collector._dumpsys_meminfo = system_snapshot
    original_wait = collector._stop_event.wait

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        if len(waits) == 3:
            collector._stop_event.set()
        return original_wait(0)

    collector._stop_event.wait = wait
    collector._collect_memory_thread("2026_09_26_00_00_00")
    assert len(waits) == 3
    adb.dumpheap.assert_called_once_with("com.example.app", RuntimeData.package_save_path)
