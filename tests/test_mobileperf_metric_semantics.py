"""验证内存与网络采集值的归属，防止把其他指标当作目标进程数据。"""

import csv
from types import SimpleNamespace

import pytest

from mobileperf.android import trafficstats
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.meminfos import MemInfoDevice
from mobileperf.android.trafficstats import TrafficCollecor
from services.perf_chart_data import load_result_metrics


@pytest.mark.parametrize("pss_line, expected", [
    ("102,400K: com.example.app (pid 123 / activities)", "100.0"),
    ("243786 kB: 0 kB: com.example.app (pid 123 / activities)", "238.07"),
])
def test_memory_uses_pss_section_even_when_rss_precedes_it(pss_line, expected):
    source = (
        "Total RSS by process:\n"
        "  409,600K: com.example.app (pid 123 / activities)\n"
        "Total PSS by process:\n"
        f"  {pss_line}\n"
        "Total PSS by OOM adjustment:\n"
        "  819,200K: com.example.app (pid 456 / activities)\n"
    )

    sample = MemInfoDevice(source, ["com.example.app"])

    assert sample.package_pid_pss_list == [
        {"package": "com.example.app", "pid": "123", "pss": expected},
    ]
    assert sample.total_pss == float(expected)


@pytest.mark.parametrize("source", [
    "Total RSS by process:\n  409,600K: com.example.app (pid 123)\n",
    "Total PSS by process:\n  1K: com.other.app (pid 456)\n"
    "Total PSS by OOM adjustment:\n  409,600K: com.example.app (pid 123)\n",
])
def test_memory_does_not_substitute_other_sections_when_process_pss_is_missing(source):
    sample = MemInfoDevice(source, ["com.example.app"])

    assert sample.package_pid_pss_list == [
        {"package": "com.example.app", "pid": "", "pss": ""},
    ]


@pytest.mark.parametrize("line, expected", [
    ("102400K: com.example.app (pid 123)", "100.0"),
    ("102400 kB: com.example.app (pid 123 / activities)", "100.0"),
    ("243786 kB: 0 kB: com.example.app (pid 123 / activities)", "238.07"),
])
def test_memory_keeps_legacy_single_and_double_column_pss(line, expected):
    sample = MemInfoDevice(line, ["com.example.app"])

    assert sample.package_pid_pss_list == [
        {"package": "com.example.app", "pid": "123", "pss": expected},
    ]


def test_memory_matches_complete_process_names_without_regex_wildcards():
    source = (
        "Total PSS by process:\n"
        "  409,600K: comXexampleYapp (pid 111)\n"
        "  204,800K: com.example.app:remote (pid 222)\n"
        "  102,400K: com.example.app (pid 333)\n"
    )

    sample = MemInfoDevice(source, ["com.example.app", "com.example.app:remote"])

    assert sample.package_pid_pss_list == [
        {"package": "com.example.app", "pid": "333", "pss": "100.0"},
        {"package": "com.example.app:remote", "pid": "222", "pss": "200.0"},
    ]
    assert sample.total_pss == 300.0


@pytest.mark.parametrize("packages", [["com.example.app"],
                                     ["com.example.app", "com.example.other"]])
def test_modern_traffic_csv_keeps_device_values_and_marks_process_bytes_unavailable(
    monkeypatch, tmp_path, packages,
):
    clock = [0.0]
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))
    commands = []

    def query(command):
        commands.append(command)
        # 同一网络命名空间中的所有 /proc/<pid>/net/dev 都返回同一份接口计数。
        received = 1024 + int(clock[0]) * 102400
        return f"wlan0: {received} 0 0 0 0 0 0 0 2048 0 0 0 0 0 0 0\n"

    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34,
        get_pid_from_pck=lambda package: 42 if package == "com.example.app" else 43,
        run_shell_cmd=query,
    )), packages, interval=1, timeout=2)
    collector._stop_event.wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    try:
        collector._collect_traffic_thread("unused-start")
    finally:
        RuntimeData.end_run()

    with (tmp_path / "traffic.csv").open(encoding="utf-8", newline="") as stream:
        header, baseline, sample = list(csv.reader(stream))
    expected_header = ["datetime", "device_total(KB)", "device_receive(KB)",
                       "device_transport(KB)"]
    for _package in packages:
        expected_header.extend(["package", "pid", "pid_rx(KB)", "pid_tx(KB)", "pid_total(KB)"])
    if len(packages) > 1:
        expected_header.append("total_proc_traffic(kB)")
    assert header == expected_header
    assert len(baseline) == len(sample) == len(header)
    assert baseline[1:4] == ["0.0", "0.0", "0.0"]
    assert sample[1:4] == ["100.0", "100.0", "0.0"]
    assert sample[4:9] == ["com.example.app", "42", "", "", ""]
    if len(packages) > 1:
        assert sample[9:] == ["com.example.other", "43", "", "", "", ""]
    assert commands == ["cat /proc/net/dev", "cat /proc/net/dev"]
    metrics = load_result_metrics(str(tmp_path))
    assert metrics["traffic_total"].values == [(0.0, 0.0), (1.0, 100.0)]
    assert metrics["traffic_rx"].values == [(0.0, 0.0), (1.0, 100.0)]
    assert metrics["traffic_tx"].values == [(0.0, 0.0), (1.0, 0.0)]


def test_legacy_traffic_csv_preserves_uid_scoped_increments(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))

    def query(command):
        if command == "dumpsys package 'com.example.app'":
            return "userId=10123\n"
        assert command == "cat /proc/net/xt_qtaguid/stats"
        received = 1024 + int(clock[0]) * 102400
        return (
            f"2 wlan0 0x0 10123 0 {received} 1 2048 1\n"
            "3 wlan0 0x0 101234 0 999999 1 999999 1\n"
        )

    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 28, run_shell_cmd=query,
    )), ["com.example.app"], interval=1, timeout=2)
    collector._stop_event.wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    try:
        collector._collect_traffic_thread("unused-start")
    finally:
        RuntimeData.end_run()

    with (tmp_path / "traffics_uid.csv").open(encoding="utf-8", newline="") as stream:
        baseline, sample = list(csv.DictReader(stream))
    assert baseline["uid_total(KB)"] == "0.0"
    assert sample["uid"] == "10123"
    assert sample["uid_total(KB)"] == sample["rx(KB)"] == "100.0"
    assert sample["tx(KB)"] == "0.0"
