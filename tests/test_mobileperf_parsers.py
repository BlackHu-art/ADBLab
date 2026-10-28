"""mobileperf 解析器对空/畸形输入的健壮性契约测试（对应 B1/B2/B4 修复）。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android.cpu_top import PckCpuinfo
from mobileperf.android.fps import SurfaceStatsCollector
from mobileperf.android.tools.androiddevice import ADB
from mobileperf.android.trafficstats import NetDevInfo, TrafficSnapshot


def test_traffic_snapshot_matches_uid_exactly_not_substring():
    source = (
        "2 wlan0 0x0 10123 0 100 10 200 20 0 0 0 0 0 0 0 0 0 0 0 0\n"
        "3 wlan0 0x0 101234 0 999 90 999 90 0 0 0 0 0 0 0 0 0 0 0 0\n"
        "4 rmnet0 0x0 10123 1 300 30 400 40 0 0 0 0 0 0 0 0 0 0 0 0\n"
    )
    snap = TrafficSnapshot(source, "com.example", "10123")

    # 仅 uid 完全等于 10123 的两行被统计，101234 行被排除。
    assert snap.rx_uid_bytes == 100 + 300
    assert snap.tx_uid_bytes == 200 + 400
    assert snap.total_uid_bytes == 1000
    # 第一行 cnt_set=0 记后台，第三行 cnt_set=1 记前台。
    assert snap.bg_bytes == 100 + 200
    assert snap.fg_bytes == 300 + 400


def test_traffic_snapshot_skips_short_malformed_lines():
    source = (
        "2 wlan0 0x0 10123 0 100 10 200\n"  # 列数不足 9
        "broken\n"
        "3 rmnet0 0x0 10123 0 50 5 60 6 0 0 0 0 0 0 0 0 0 0 0 0\n"
    )
    snap = TrafficSnapshot(source, "com.example", "10123")

    assert snap.rx_uid_bytes == 50
    assert snap.tx_uid_bytes == 60


def test_netdev_info_mobile_total_uses_mobile_counters():
    source = (
        "wlan0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n"
        "rmnet0: 300 0 0 0 0 0 0 0 400 0 0 0 0 0 0 0\n"
    )
    info = NetDevInfo(source)

    assert info.wifi_total == 100 + 200
    assert info.mobile_total == 300 + 400
    assert info.total == info.wifi_total + info.mobile_total


def test_pck_cpuinfo_short_line_without_cpu_column_does_not_crash():
    # 无 CPU% 表头时 get_cpucol_index 回退为默认 2，目标行不足 3 列导致 CPU 字段为空。
    source = "123 com.example.app\n"
    info = PckCpuinfo(["com.example.app"], source, sdkversion=26)

    assert info.pid == "123"
    assert info.total_pid_cpu == 0


def test_netdev_info_short_wlan0_line_does_not_crash():
    # wlan0 行字段不足 10 时跳过，不再 items[9] IndexError。
    info = NetDevInfo("wlan0: 100 0 0 0\n")

    assert info.wifi_total == 0
    assert info.total == 0


def test_meminfo_package_short_or_non_numeric_total_is_skipped():
    from mobileperf.android.meminfos import MemInfoPackage

    assert MemInfoPackage("TOTAL\n").totalAllocHeap == 0
    assert MemInfoPackage("TOTAL abc\n").totalAllocHeap == 0


@pytest.mark.parametrize("detail", [
    "Warning: Activity not started: intent delivered to existing instance",
    "Error: Permission Denial: cannot start activity",
    "Starting: Intent { cmp=com.example/.Main note=source: preview }",
])
def test_start_activity_preserves_values_containing_colon_separators(detail):
    adb = ADB.__new__(ADB)
    adb.run_shell_cmd = Mock(return_value=f"{detail}\nStatus: ok\nComplete\n")

    result = adb.start_activity("com.example/.Main")

    key, value = detail.split(": ", 1)
    assert result == {key: value, "Status": "ok"}
    assert adb.run_shell_cmd.call_args.kwargs["timeout"] == 30


def test_start_activity_keeps_empty_and_unstructured_output_compatible():
    adb = ADB.__new__(ADB)
    adb.run_shell_cmd = Mock(side_effect=["", "Starting an activity\nComplete"])

    assert adb.start_activity("com.example/.Main") == {}
    assert adb.start_activity("com.example/.Main", wait=False) == {}


@pytest.mark.parametrize("body", [
    "abc u0 com.example/.Main", "abc u10 com.example/.Main",
    "abc u123 com.example/.Main", "abc com.example/.Main",
    "abc   u10\tcom.example/.Main",
])
def test_focus_activity_extracts_component_with_optional_android_user(body):
    adb = ADB.__new__(ADB)
    adb.run_shell_cmd = Mock(return_value=f"  mCurrentFocus=Window{{{body}}}\n")

    assert adb.get_focus_activity() == "com.example/.Main"
    assert adb.get_foreground_process() == "com.example"


@pytest.mark.parametrize("output", [
    "", "   \n", "mCurrentFocus=null", "mCurrentFocus=Window{abc}",
    "mCurrentFocus=Window{abc u0}", "mCurrentFocus=Window{abc u10}",
    "mCurrentFocus=Window{abc u-1 com.example/.Main}",
    "mCurrentFocus=Window{abc ux com.example/.Main}",
    "mCurrentFocus=Window{abc u10 com.example/.Main", "mCurrentFocus=Window{",
])
def test_focus_activity_missing_or_malformed_window_is_unavailable(output):
    adb = ADB.__new__(ADB)
    adb.run_shell_cmd = Mock(return_value=output)

    assert adb.get_focus_activity() == ""
    assert adb.get_foreground_process() == ""


@pytest.mark.parametrize("user", ["u0", "u10"])
@pytest.mark.parametrize("has_target", [True, False])
def test_focus_component_drives_actual_gfxinfo_window_matching(user, has_target):
    def query(command):
        if command == "dumpsys window windows":
            return f"mCurrentFocus=Window{{abc {user} com.example/.Main}}"
        if command == "dumpsys SurfaceFlinger --latency 'com.example/.Main'":
            return "16666666\n"
        assert command == "dumpsys gfxinfo 'com.example' framestats"
        other = (
            "Window: com.example/.MainPopup\n---PROFILEDATA---\n"
            "Flags,IntendedVsync,Vsync,FrameCompleted\n"
            "0,2000000000,2001000000,2015000000\n---PROFILEDATA---\n"
        )
        target = (
            "Window: com.example/.Main\n---PROFILEDATA---\n"
            "Flags,IntendedVsync,Vsync,FrameCompleted\n"
            "0,1000000000,1001000000,1015000000\n---PROFILEDATA---\n"
        )
        return other + (target if has_target else "")

    adb = ADB.__new__(ADB)
    adb.run_shell_cmd = query
    adb.get_sdk_version = lambda: 34
    collector = SurfaceStatsCollector(SimpleNamespace(adb=adb), 1, "com.example", None, 166)
    collector.focus_window = collector.get_focus_activity()

    result = collector._get_surfaceflinger_frame_data()

    assert result == ((0.016666666, [[1.0, 1.001, 1.015]]) if has_target else (None, None))
