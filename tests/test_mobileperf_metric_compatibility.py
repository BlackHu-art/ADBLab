"""覆盖 Android 指标输出变体与历史 CSV 的真实解析边界。"""

import csv
import datetime
import queue
import time
from types import SimpleNamespace

import pytest

from mobileperf.android import trafficstats
from mobileperf.android.fps import SurfaceStatsCollector
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.trafficstats import NetDevInfo, TrafficCollecor
from mobileperf.common import utils
from services.perf_chart_data import load_result_metrics, parse_fps_series

OLD_HEADER = (
    "Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,"
    "AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,"
    "IssueDrawCommandsStart,SwapBuffers,FrameCompleted,"
)
NEW_HEADER = (
    "Flags,FrameTimelineVsyncId,IntendedVsync,Vsync,InputEventId,HandleInputStart,"
    "AnimationStart,PerformTraversalsStart,DrawStart,FrameDeadline,FrameStartTime,"
    "FrameInterval,WorkloadTarget,SyncQueued,SyncStart,IssueDrawCommandsStart,"
    "SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,"
    "GpuCompleted,SwapBuffersCompleted,DisplayPresentTime,CommandSubmissionCompleted,"
)
OLD_ROW = "0,1000000000,1001000000,0,0,0,0,0,0,0,0,0,1009000000,1015000000,"
NEW_ROW = (
    "0,77,1000000000,1001000000,0,0,0,0,0,1016666666,1000000000,16666666,0,"
    "1005000000,1006000000,1007000000,1009000000,1015000000,0,0,0,0,0,0,"
)


def _window(header, row, name="com.example/.Main"):
    return f"Window: {name}\n---PROFILEDATA---\n{header}\n{row}\n---PROFILEDATA---\n"


def _frames(output):
    def query(command):
        if command == "dumpsys SurfaceFlinger --latency 'com.example/.Main'":
            return "16666666\n"
        assert command == "dumpsys gfxinfo 'com.example' framestats"
        return output

    collector = SurfaceStatsCollector(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34, run_shell_cmd=query,
    )), 1, "com.example", None, 166)
    collector.focus_window = "com.example/.Main"
    return collector._get_surfaceflinger_frame_data()


@pytest.mark.parametrize("header,row", [(OLD_HEADER, OLD_ROW), (NEW_HEADER, NEW_ROW)],
                         ids=["legacy", "frame-timeline"])
def test_gfxinfo_columns_follow_field_names_across_android_versions(header, row):
    period, frames = _frames(_window(header, row))

    assert period == 0.016666666
    assert frames == [[1.0, 1.001, 1.015]]


def test_gfxinfo_matches_whole_window_and_never_combines_other_windows():
    output = _window(OLD_HEADER, OLD_ROW.replace("1001000000", "1002000000"),
                     "com.example/.MainPopup")
    output += _window(NEW_HEADER, NEW_ROW)
    output += _window(OLD_HEADER, OLD_ROW, "com.example/.Other")

    assert _frames(output)[1] == [[1.0, 1.001, 1.015]]


@pytest.mark.parametrize("output", [
    _window(OLD_HEADER, OLD_ROW, "com.example/.MainPopup"),
    _window("", OLD_ROW),
    _window(OLD_HEADER.replace("FrameCompleted", "UnsupportedCompleted"), OLD_ROW),
    "Window: com.example/.Main\n" + _window(OLD_HEADER, OLD_ROW, "com.example/.Other"),
], ids=["prefix-window", "no-header", "missing-column", "next-window"])
def test_gfxinfo_missing_target_or_required_header_is_unavailable(output):
    assert _frames(output) == (None, None)


@pytest.mark.parametrize("invalid_row", [
    OLD_ROW.replace("1015000000", "9223372036854775807"),
    OLD_ROW.replace("1001000000", "9223372036854775807"),
    OLD_ROW.replace("1015000000", "0"),
    OLD_ROW.replace("1015000000", "999000000"),
    OLD_ROW.replace("1001000000", "not-ready"),
    "0,1000000000,1001000000,",
    OLD_ROW.replace("0,1000000000", "1,1000000000", 1),
], ids=["pending-completed", "pending-vsync", "zero-completed", "reverse-time",
        "non-numeric", "short-row", "flagged"])
def test_gfxinfo_skips_incomplete_and_malformed_frames_without_losing_valid_rows(invalid_row):
    assert _frames(_window(OLD_HEADER, invalid_row + "\n" + OLD_ROW))[1] == [[1.0, 1.001, 1.015]]


def test_gfxinfo_empty_valid_profile_remains_an_empty_sample():
    assert _frames(_window(NEW_HEADER, "")) == (0.016666666, [])


@pytest.mark.parametrize("row", [
    "0,1000000000,1001000000,",
    OLD_ROW.replace("1001000000", "not-ready"),
], ids=["truncated", "non-numeric"])
def test_gfxinfo_only_malformed_rows_are_unavailable_instead_of_zero_fps(row):
    assert _frames(_window(OLD_HEADER, row)) == (None, None)


@pytest.mark.parametrize("first,second", [
    ("2026-09-29 12:00:59", "2026-09-29 12:01:00"),
    ("2026-09-29 23:59:59", "2026-09-30 00:00:00"),
    ("2026-12-31 23:59:59", "2027-01-01 00:00:00"),
], ids=["minute", "midnight", "year"])
def test_legacy_fps_writer_dates_share_real_seconds_with_other_metrics(
    monkeypatch, tmp_path, first, second,
):
    moments = [datetime.datetime.fromisoformat(value) for value in (first, second)]
    written_times = iter(moment.timestamp() for moment in moments)
    monkeypatch.setattr(utils, "time", SimpleNamespace(
        time=lambda: next(written_times), localtime=time.localtime, strftime=time.strftime,
    ))
    collector = SurfaceStatsCollector(None, 0, "com.example", None, 166, use_legacy=True)
    collector.surface_before = {"timestamp": moments[0] - datetime.timedelta(seconds=1),
                                "page_flip_count": 0}
    collector.data_queue = queue.Queue()
    for index, moment in enumerate(moments, 1):
        collector.data_queue.put({"timestamp": moment, "page_flip_count": index * 60})
    collector.data_queue.put("Stop")
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    try:
        collector._calculator_thread("unused-start")
    finally:
        RuntimeData.end_run()
    (tmp_path / "cpuinfo.csv").write_text(
        f"datetime,device_cpu_rate%\n{first},10\n{second},20\n", encoding="utf-8",
    )

    assert parse_fps_series(str(tmp_path))["fps"].values == [(0.0, 60.0), (1.0, 60.0)]
    metrics = load_result_metrics(str(tmp_path))
    assert metrics["fps"].values == [(0.0, 60.0), (1.0, 60.0)]
    assert metrics["cpu"].values == [(0.0, 10.0), (1.0, 20.0)]


def test_invalid_underscore_date_is_not_reinterpreted_as_numeric_timestamp(tmp_path):
    (tmp_path / "fps.csv").write_text(
        "datetime,fps\n2026_13_01_00_00_00,10\n2026_09_29_12_00_00,60\n",
        encoding="utf-8",
    )

    assert parse_fps_series(str(tmp_path))["fps"].values == [(0.0, 60.0)]


def _interface(name, rx, tx):
    return f"{name}:{rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0\n"


def test_netdev_counts_supported_physical_interfaces_without_virtual_duplicates():
    source = _interface("wlan0", 100, 200) + _interface("wlan1", 10, 20)
    source += _interface("rmnet0", 1, 2) + _interface("rmnet_data0", 300, 400)
    source += _interface("rmnet_data1", 30, 40)
    for name in ("lo", "tun0", "v4-rmnet_data0", "dummy0", "rmnet_ipa0", "unknown0"):
        source += _interface(name, 99999, 99999)

    info = NetDevInfo(source)

    assert (info.wifi_rx, info.wifi_tx, info.wifi_total) == (110, 220, 330)
    assert (info.mobile_rx, info.mobile_tx, info.mobile_total) == (331, 442, 773)
    assert (info.rx, info.tx, info.total) == (441, 662, 1103)


@pytest.mark.parametrize("unavailable", [
    _interface("unknown0", 1024, 2048),
    _interface("tun0", 1024, 2048),
    "wlan0: 100 0 0 0\n",
    _interface("wlan0", "invalid", 100),
    _interface("wlan0", -1, 100),
    _interface("wlan0", 0, 0) + _interface("rmnet_data0", "invalid", 2048),
    _interface("rmnet_data0", "invalid", 2048) + _interface("wlan0", 0, 0),
], ids=["unknown", "vpn", "short-row", "non-numeric", "negative",
        "partial-mobile-after-wifi", "partial-mobile-before-wifi"])
def test_device_traffic_unavailable_interfaces_do_not_write_false_zero_baseline(
    monkeypatch, tmp_path, unavailable,
):
    clock = [0.0]
    monkeypatch.setattr(trafficstats, "time", SimpleNamespace(time=lambda: clock[0]))
    responses = iter([unavailable, _interface("rmnet_data0", 1024, 2048),
                      _interface("rmnet_data0", 3072, 3072)])
    collector = TrafficCollecor(SimpleNamespace(adb=SimpleNamespace(
        get_sdk_version=lambda: 34, run_shell_cmd=lambda _command: next(responses),
    )), [], interval=1, timeout=3)
    collector._stop_event.wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    try:
        collector.get_traffic_with_dev()
    finally:
        RuntimeData.end_run()

    with (tmp_path / "traffic.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 3
    assert rows[1][1:] == ["0.0", "0.0", "0.0"]
    assert rows[2][1:] == ["3.0", "2.0", "1.0"]
