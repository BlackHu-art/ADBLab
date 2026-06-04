from unittest.mock import Mock, patch

from models.performance.parsers import (
    build_cpu_sample,
    enrich_startup_from_logcat,
    parse_am_start_output,
    parse_gfxinfo_output,
    parse_meminfo_output,
    parse_process_stat_cpu_ticks,
    parse_process_thread_count,
    parse_proc_stat_total,
    parse_process_stat_ticks,
)
from models.performance.dashboard import (
    axis_policy,
    build_metric_lanes,
    chart_points,
    frame_chart_values,
    marker_payload,
    metric_details,
    metric_summaries,
    monitor_control_state,
    refresh_metric_lane_colors,
    snapshot_chart_values,
    web_dashboard_context,
    web_timeline_payload,
)
from models.performance.presentation import build_report_summary, render_report_text
from models.performance.providers import PsutilHostProvider, provider_capabilities
from models.performance.sampling import PerformanceSamplingSchedule
from models.performance.service import (
    PerformanceService,
    _cpu_info,
    _cpu_snapshot_command,
    _gpu_type,
    _last_frame_completed_ns,
    _opengl_info,
    _parse_cpu_snapshot_output,
    _prop,
    _ram_size,
    _swap_size,
)
from models.performance.report_service import PerformanceReportService
from models.performance.session import PerformanceSession
from models.performance.types import CpuSample, FrameMetrics, MemorySample, PerformanceSnapshot, StartupMetrics
from models.performance.workers import PerformanceAnalyzeWorker, PerformanceSnapshotWorker


def test_parse_am_start_and_logcat_startup_metrics():
    output = """
Starting: Intent { cmp=com.example/.MainActivity }
Status: ok
Activity: com.example/.MainActivity
ThisTime: 321
TotalTime: 654
WaitTime: 700
Complete
"""
    logcat = """
06-01 10:00:00.000  100  100 I ActivityTaskManager: Displayed com.example/.MainActivity: +812ms
06-01 10:00:01.000  100  100 I ActivityTaskManager: Fully drawn com.example/.MainActivity: +1s250ms
"""

    metrics = parse_am_start_output(
        output,
        device_id="device-1",
        package_name="com.example",
        activity="com.example/.MainActivity",
    )
    enrich_startup_from_logcat(metrics, logcat)

    assert metrics.success is True
    assert metrics.this_time_ms == 321
    assert metrics.total_time_ms == 654
    assert metrics.wait_time_ms == 700
    assert metrics.displayed_ms == 812
    assert metrics.fully_drawn_ms == 1250


def test_parse_gfxinfo_prefers_profile_rows_over_cumulative_summary():
    output = """
Total frames rendered: 4
Janky frames: 1 (25.00%)
50th percentile: 8ms
90th percentile: 20ms
95th percentile: 4950ms
99th percentile: 30ms
Number Missed Vsync: 2
Number High input latency: 3
Number Slow UI thread: 4
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,2000000000,2000000000,0,0,0,0,0,0,0,0,0,0,2020000000,0,0,
---PROFILEDATA---
"""

    metrics = parse_gfxinfo_output(output)

    assert metrics.total_frames == 2
    assert metrics.janky_frames == 1
    assert metrics.jank_rate == 0.5
    assert metrics.p95_ms == 19.5
    assert metrics.slow_frames == 1
    assert metrics.slow_frame_rate == 0.5
    assert metrics.frozen_frame_rate == 0
    assert metrics.avg_frame_time_ms == 15
    assert metrics.max_frame_time_ms == 20
    assert metrics.estimated_fps == 1.0
    assert metrics.missed_vsync == 2
    assert metrics.high_input_latency == 3
    assert metrics.slow_ui_thread == 4


def test_parse_gfxinfo_filters_old_framestats_by_completed_timestamp():
    output = """
Total frames rendered: 20
Janky frames: 10 (50.00%)
95th percentile: 4950ms
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,2000000000,2000000000,0,0,0,0,0,0,0,0,0,0,2020000000,0,0,
0,3000000000,3000000000,0,0,0,0,0,0,0,0,0,0,3018000000,0,0,
---PROFILEDATA---
"""

    metrics = parse_gfxinfo_output(output, min_completed_ns=2020000000)
    empty = parse_gfxinfo_output(output, min_completed_ns=3018000000)

    assert metrics.total_frames == 1
    assert metrics.p95_ms == 18.0
    assert metrics.estimated_fps is None
    assert empty.total_frames == 0
    assert empty.p95_ms is None
    assert empty.slow_frames == 0


def test_parse_gfxinfo_estimates_fps_from_vsync_interval_not_completion_span():
    output = """
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,1016666667,1016666667,0,0,0,0,0,0,0,0,0,0,1026666667,0,0,
0,1033333334,1033333334,0,0,0,0,0,0,0,0,0,0,1043333334,0,0,
0,1050000001,1050000001,0,0,0,0,0,0,0,0,0,0,1060000001,0,0,
---PROFILEDATA---
"""

    metrics = parse_gfxinfo_output(output)

    assert metrics.estimated_fps == 60.0


def test_last_frame_completed_ns_returns_latest_profile_row():
    output = """
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,2000000000,2000000000,0,0,0,0,0,0,0,0,0,0,2020000000,0,0,
---PROFILEDATA---
"""

    assert _last_frame_completed_ns(output) == 2020000000


def test_performance_service_frame_metrics_only_reports_new_framestats_rows():
    outputs = [
        """
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,2000000000,2000000000,0,0,0,0,0,0,0,0,0,0,2020000000,0,0,
---PROFILEDATA---
""",
        """
Total frames rendered: 20
95th percentile: 4950ms
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,2000000000,2000000000,0,0,0,0,0,0,0,0,0,0,2020000000,0,0,
0,3000000000,3000000000,0,0,0,0,0,0,0,0,0,0,3024000000,0,0,
---PROFILEDATA---
""",
        """
Total frames rendered: 20
95th percentile: 4950ms
---PROFILEDATA---
Flags,IntendedVsync,Vsync,OldestInputEvent,NewestInputEvent,HandleInputStart,AnimationStart,PerformTraversalsStart,DrawStart,SyncQueued,SyncStart,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,DequeueBufferDuration,QueueBufferDuration,
0,1000000000,1000000000,0,0,0,0,0,0,0,0,0,0,1010000000,0,0,
0,2000000000,2000000000,0,0,0,0,0,0,0,0,0,0,2020000000,0,0,
0,3000000000,3000000000,0,0,0,0,0,0,0,0,0,0,3024000000,0,0,
---PROFILEDATA---
""",
    ]
    service = PerformanceService("device-1")

    def fake_run(_cmd, timeout=30, shell=False):
        return Mock(success=True, output=outputs.pop(0), returncode=0, error="")

    with patch("models.performance.service.CommandRunner.run", side_effect=fake_run):
        first = service.frame_metrics("com.example")
        second = service.frame_metrics("com.example")
        third = service.frame_metrics("com.example")

    assert first.total_frames == 2
    assert second.total_frames == 1
    assert second.p95_ms == 24.0
    assert third.total_frames == 0
    assert third.p95_ms is None


def test_parse_meminfo_extracts_summary_and_object_counts():
    output = """
Applications Memory Usage (in Kilobytes):
                   Pss  Private  Private
                ------   ------   ------
        TOTAL    54132    34644     8212

 App Summary
                       Pss(KB)
                        ------
           Java Heap:     6760
         Native Heap:    26508
            Graphics:     1200
               Stack:      220
                Code:     3300
       Private Other:     4100
              System:     5100
               TOTAL:    54132
      TOTAL SWAP PSS:      256

 Objects
               Views:       98         ViewRootImpl:        1
         AppContexts:        4           Activities:        1
"""

    sample = parse_meminfo_output(output, timestamp_ms=123)

    assert sample.timestamp_ms == 123
    assert sample.total_pss_kb == 54132
    assert sample.java_heap_kb == 6760
    assert sample.native_heap_kb == 26508
    assert sample.graphics_kb == 1200
    assert sample.stack_kb == 220
    assert sample.code_kb == 3300
    assert sample.private_other_kb == 4100
    assert sample.system_kb == 5100
    assert sample.total_swap_pss_kb == 256
    assert sample.views == 98
    assert sample.view_roots == 1
    assert sample.app_contexts == 4
    assert sample.activities == 1


def test_parse_meminfo_falls_back_to_graphics_rows_and_swap_pss_column():
    output = """
Applications Memory Usage (in Kilobytes):
                   Pss  Private  Private  SwapPss  HeapSize  HeapAlloc  HeapFree
                ------   ------   ------   ------  --------  ---------  --------
       EGL mtrack    2048        0        0        0
        GL mtrack    1024        0        0        0
          Gfx dev     512        0        0        0
            TOTAL    8192     4096     2048      512     16384      12288      4096

 App Summary
                       Pss(KB)
                        ------
           Java Heap:     2048
         Native Heap:     1024
               TOTAL:     8192
"""

    sample = parse_meminfo_output(output, timestamp_ms=123)

    assert sample.total_pss_kb == 8192
    assert sample.graphics_kb == 3584
    assert sample.total_swap_pss_kb == 512


def test_parse_meminfo_handles_graphic_buffer_rows_and_heap_columns():
    output = """
Applications Memory Usage (in Kilobytes):
                   Pss  Private  Private  SwapPss  HeapSize  HeapAlloc  HeapFree
                ------   ------   ------   ------  --------  ---------  --------
 Graphic Buffer     768        0        0        0
    GPU private     256        0        0        0
            TOTAL    4096     2048     1024       64     32768      24576      8192

 App Summary
                       Pss(KB)
                        ------
           Java Heap:     1024
         Native Heap:      512
               TOTAL:     4096
"""

    sample = parse_meminfo_output(output, timestamp_ms=123)

    assert sample.total_pss_kb == 4096
    assert sample.graphics_kb == 1024
    assert sample.total_swap_pss_kb == 64


def test_cpu_sample_uses_proc_tick_delta():
    process_stat = "1234 (com.example) S 1 2 3 4 5 6 7 8 9 10 120 30 0 0 20 0 1 0"
    total_stat = "cpu  100 20 30 850 0 0 0 0 0 0"

    process_ticks = parse_process_stat_ticks(process_stat)
    process_cpu_ticks = parse_process_stat_cpu_ticks(process_stat)
    thread_count = parse_process_thread_count(process_stat)
    total_ticks = parse_proc_stat_total(total_stat)
    sample = build_cpu_sample(
        timestamp_ms=1000,
        pid=1234,
        process_ticks=process_ticks,
        total_ticks=total_ticks,
        previous_process_ticks=100,
        previous_total_ticks=900,
        is_foreground=True,
        user_ticks=process_cpu_ticks[0],
        system_ticks=process_cpu_ticks[1],
        previous_user_ticks=80,
        previous_system_ticks=20,
        thread_count=thread_count,
    )

    assert process_ticks == 150
    assert process_cpu_ticks == (120, 30)
    assert thread_count == 1
    assert total_ticks == 1000
    assert sample.process_percent == 50.0
    assert sample.process_user_percent == 40.0
    assert sample.process_system_percent == 10.0
    assert sample.thread_count == 1
    assert sample.is_foreground is True


def test_cpu_sample_scales_proc_tick_delta_by_cpu_core_count():
    sample = build_cpu_sample(
        timestamp_ms=1000,
        pid=1234,
        process_ticks=150,
        total_ticks=1000,
        previous_process_ticks=100,
        previous_total_ticks=900,
        is_foreground=True,
        user_ticks=120,
        system_ticks=30,
        previous_user_ticks=80,
        previous_system_ticks=20,
        cpu_count=8,
    )

    assert sample.process_percent == 400.0
    assert sample.process_user_percent == 320.0
    assert sample.process_system_percent == 80.0


def _proc_stat(pid: int, name: str, user_ticks: int, system_ticks: int, thread_count: int, start_time: int) -> str:
    fields = [
        "S",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        str(user_ticks),
        str(system_ticks),
        "0",
        "0",
        "20",
        "0",
        str(thread_count),
        "0",
        str(start_time),
    ]
    return f"{pid} ({name}) {' '.join(fields)}"


def test_cpu_snapshot_output_parses_all_matching_package_processes():
    output = "\n".join(
        [
            "cpu  100 0 100 800 0 0 0 0 0 0",
            "cpu0 50 0 50 400 0 0 0 0 0 0",
            "cpu1 50 0 50 400 0 0 0 0 0 0",
            f"ADBLAB_PROC\t1234\tcom.example\t{_proc_stat(1234, 'com.example', 120, 30, 8, 1000)}",
            f"ADBLAB_PROC\t1235\tcom.example:remote\t{_proc_stat(1235, 'example:remote', 40, 20, 4, 1001)}",
        ]
    )

    total_ticks, cpu_count, processes = _parse_cpu_snapshot_output(output)

    assert total_ticks == 1000
    assert cpu_count == 2
    assert [process.pid for process in processes] == [1234, 1235]
    assert [process.process_name for process in processes] == ["com.example", "com.example:remote"]
    assert [process.process_ticks for process in processes] == [150, 60]
    assert [process.thread_count for process in processes] == [8, 4]


def test_cpu_snapshot_command_matches_package_and_child_processes():
    command = _cpu_snapshot_command("com.example")

    assert "ADBLAB_PROC" in command
    assert "[ \"$cmd\" = 'com.example' ]" in command
    assert "case \"$cmd\" in 'com.example':*)" in command


def test_performance_service_cpu_sample_aggregates_stable_package_processes():
    snapshots = [
        "\n".join(
            [
                "cpu  100 0 100 800 0 0 0 0 0 0",
                "cpu0 50 0 50 400 0 0 0 0 0 0",
                "cpu1 50 0 50 400 0 0 0 0 0 0",
                f"ADBLAB_PROC\t1234\tcom.example\t{_proc_stat(1234, 'com.example', 100, 20, 8, 1000)}",
                f"ADBLAB_PROC\t1235\tcom.example:remote\t{_proc_stat(1235, 'example:remote', 40, 10, 4, 1001)}",
            ]
        ),
        "\n".join(
            [
                "cpu  120 0 140 940 0 0 0 0 0 0",
                "cpu0 60 0 70 470 0 0 0 0 0 0",
                "cpu1 60 0 70 470 0 0 0 0 0 0",
                f"ADBLAB_PROC\t1234\tcom.example\t{_proc_stat(1234, 'com.example', 130, 35, 9, 1000)}",
                f"ADBLAB_PROC\t1235\tcom.example:remote\t{_proc_stat(1235, 'example:remote', 50, 15, 5, 1001)}",
            ]
        ),
    ]
    service = PerformanceService("device-1")

    def fake_run(_cmd, timeout=30, shell=False):
        return Mock(success=True, output=snapshots.pop(0), returncode=0, error="")

    with patch("models.performance.service.CommandRunner.run", side_effect=fake_run):
        first = service.cpu_sample("com.example", current_package="com.example", timestamp_ms=1000)
        second = service.cpu_sample("com.example", current_package="com.example", timestamp_ms=2000)

    assert first.process_percent is None
    assert first.process_count == 2
    assert first.thread_count == 12
    assert second.pid == 1234
    assert second.process_count == 2
    assert second.thread_count == 14
    assert second.process_percent == 60.0
    assert second.process_user_percent == 40.0
    assert second.process_system_percent == 20.0


def test_performance_service_cpu_sample_ignores_new_or_restarted_process_delta_until_next_sample():
    snapshots = [
        "\n".join(
            [
                "cpu  100 0 100 800 0 0 0 0 0 0",
                "cpu0 50 0 50 400 0 0 0 0 0 0",
                "cpu1 50 0 50 400 0 0 0 0 0 0",
                f"ADBLAB_PROC\t1234\tcom.example\t{_proc_stat(1234, 'com.example', 100, 20, 8, 1000)}",
            ]
        ),
        "\n".join(
            [
                "cpu  120 0 140 940 0 0 0 0 0 0",
                "cpu0 60 0 70 470 0 0 0 0 0 0",
                "cpu1 60 0 70 470 0 0 0 0 0 0",
                f"ADBLAB_PROC\t1234\tcom.example\t{_proc_stat(1234, 'com.example', 130, 35, 8, 1000)}",
                f"ADBLAB_PROC\t2234\tcom.example:remote\t{_proc_stat(2234, 'example:remote', 500, 300, 3, 2000)}",
            ]
        ),
    ]
    service = PerformanceService("device-1")

    def fake_run(_cmd, timeout=30, shell=False):
        return Mock(success=True, output=snapshots.pop(0), returncode=0, error="")

    with patch("models.performance.service.CommandRunner.run", side_effect=fake_run):
        service.cpu_sample("com.example", current_package="com.example", timestamp_ms=1000)
        second = service.cpu_sample("com.example", current_package="com.example", timestamp_ms=2000)

    assert second.process_count == 2
    assert second.thread_count == 11
    assert second.process_percent == 45.0
    assert second.process_user_percent == 30.0
    assert second.process_system_percent == 15.0


def test_device_info_helpers_parse_system_outputs():
    props = """
[ro.product.model]: [Pixel Test]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.build.version.release]: [15]
[ro.hardware]: [tensor]
"""
    cpuinfo = """
Processor   : AArch64 Processor rev 1
Hardware    : Google Tensor G3
"""
    meminfo = """
MemTotal:       12582912 kB
SwapTotal:       2097152 kB
"""
    surfaceflinger = """
GLES: ARM, Mali-G715, OpenGL ES 3.2 build
"""

    assert _prop(props, "ro.product.model") == "Pixel Test"
    assert _cpu_info(cpuinfo, props) == "Google Tensor G3"
    assert _gpu_type(surfaceflinger) == "GLES: ARM, Mali-G715, OpenGL ES 3.2 build"
    assert _opengl_info(surfaceflinger) == "GLES: ARM, Mali-G715, OpenGL ES 3.2 build"
    assert _ram_size(meminfo) == "12.0 GB"
    assert _swap_size(meminfo) == "2048 MB"


def test_provider_capabilities_separate_host_and_android_backends():
    capabilities = {capability.name: capability for capability in provider_capabilities()}

    assert capabilities["psutil-host"].host is True
    assert capabilities["psutil-host"].android is False
    assert capabilities["android-agent"].realtime is True
    assert capabilities["android-agent"].android is True
    assert capabilities["perfetto-android"].android is True
    assert capabilities["adb-compat"].realtime is False


def test_psutil_host_provider_samples_current_process():
    provider = PsutilHostProvider()

    provider.start()
    snapshot = provider.sample()

    assert provider.available is True
    assert snapshot.device_id == "host"
    assert snapshot.online is True
    assert snapshot.cpu is not None
    assert snapshot.cpu.pid
    assert snapshot.cpu.process_count == 1
    assert snapshot.memory is not None
    assert snapshot.memory.total_pss_kb and snapshot.memory.total_pss_kb > 0
    provider.stop()


def test_psutil_host_provider_rejects_non_pid_target():
    provider = PsutilHostProvider()

    try:
        provider.start("com.example.android")
    except ValueError as exc:
        assert "local process id" in str(exc)
    else:
        raise AssertionError("non-pid psutil-host target should fail")


def test_report_service_writes_expected_artifacts(tmp_path):
    service = PerformanceReportService(save_root=str(tmp_path))
    report_dir = service.create_report_dir("device-1", "com.example")

    artifacts = service.write_report(
        report_dir,
        device_id="device-1",
        package_name="com.example",
        startup=StartupMetrics(
            device_id="device-1",
            package_name="com.example",
            success=True,
            total_time_ms=500,
        ),
        frames=FrameMetrics(total_frames=10, janky_frames=1, jank_rate=0.1),
        samples=[MemorySample(timestamp_ms=1, total_pss_kb=1000)],
        findings=["demo finding"],
        status="warn",
    )

    assert (tmp_path / "performance").exists()
    assert set(artifacts) == {"summary", "metrics", "report"}
    for path in artifacts.values():
        assert path.startswith(report_dir)


def test_performance_session_summarizes_series_and_markers():
    session = PerformanceSession(device_id="device-1", package_name="com.example", started_at_ms=1000)

    session.add_point(1000, {"fps": 55, "pss": 100})
    session.add_point(2000, {"fps": 60, "pss": 120})
    session.add_marker(1500, "Login")

    fps = session.summarize("fps")

    assert fps.count == 2
    assert fps.min_value == 55
    assert fps.max_value == 60
    assert fps.avg_value == 57.5
    assert fps.last_value == 60
    assert session.latest_values()["pss"] == 120
    assert session.duration_ms() == 1000
    assert session.to_dict()["markers"][0]["label"] == "Login"


def test_dashboard_metric_lanes_define_perfdog_series_and_theme_colors():
    roles = {
        "BUTTON_ACCENT": "#fps",
        "LOG_WARNING": "#warn",
        "LOG_INFO": "#info",
        "LOG_ERROR": "#error",
        "LOG_SUCCESS": "#success",
        "TEXT_SECONDARY": "#muted",
    }
    lanes = build_metric_lanes(roles.__getitem__)

    assert [lane["metric"] for lane in lanes] == ["fps", "cpu", "memory"]
    assert [series["metric"] for series in lanes[0]["series"]] == [
        "fps",
        "jank",
        "stutter_rate",
        "frame_time_p95",
    ]
    assert [series["metric"] for series in lanes[1]["series"]] == ["cpu_app", "cpu_user", "cpu_system"]
    assert [series["metric"] for series in lanes[2]["series"]] == [
        "memory_pss",
        "memory_java",
        "memory_native",
        "memory_graphics",
        "memory_swap",
    ]
    assert lanes[0]["color"] == "#fps"
    assert lanes[1]["series"][0]["color"] == "#error"
    assert lanes[2]["series"][0]["color"] == "#success"

    refreshed = refresh_metric_lane_colors(lanes, lambda role: f"new-{role}")

    assert refreshed is lanes
    assert lanes[0]["series"][1]["color"] == "new-LOG_WARNING"
    assert lanes[2]["series"][1]["color"] == "new-LOG_INFO"


def test_dashboard_chart_value_helpers_normalize_snapshot_frame_and_session():
    frames = FrameMetrics(
        total_frames=120,
        jank_rate=0.125,
        estimated_fps=58.6,
        slow_frames=15,
        frozen_frames=2,
        slow_frame_rate=0.125,
        frozen_frame_rate=0.0167,
        p50_ms=12.1,
        p95_ms=24.2,
        p99_ms=48.5,
        avg_frame_time_ms=14.7,
        max_frame_time_ms=55.0,
        missed_vsync=3,
        slow_ui_thread=4,
        high_input_latency=5,
    )
    snapshot = PerformanceSnapshot(
        device_id="device-1",
        online=True,
        current_package="com.example",
        memory=MemorySample(
            timestamp_ms=1000,
            total_pss_kb=2048,
            java_heap_kb=1024,
            native_heap_kb=512,
            graphics_kb=256,
            stack_kb=128,
            code_kb=64,
            private_other_kb=32,
            system_kb=16,
            total_swap_pss_kb=8,
            activities=1,
            views=20,
            view_roots=2,
            app_contexts=3,
        ),
        cpu=CpuSample(
            timestamp_ms=1000,
            process_percent=37.5,
            process_user_percent=28.0,
            process_system_percent=9.5,
            is_foreground=False,
            thread_count=42,
        ),
    )
    session = PerformanceSession(device_id="device-1")
    session.add_point(1000, {"fps": 55})
    session.add_point(2000, {"memory_pss": 120})
    session.add_marker(1500, "Login")

    frame_values = frame_chart_values(frames)
    snapshot_values = snapshot_chart_values(
        snapshot,
        collecting=True,
        latest_frame_values=frame_values,
    )

    assert frame_values == {
        "fps": 58.6,
        "jank": 12.5,
        "stutter": 2,
        "stutter_rate": 1.67,
        "frames": 120,
        "slow": 15,
        "frozen": 2,
        "slow_rate": 12.5,
        "frozen_rate": 1.67,
        "frame_time_avg": 14.7,
        "frame_time_p50": 12.1,
        "frame_time_p95": 24.2,
        "frame_time_p99": 48.5,
        "frame_time_max": 55.0,
        "missed_vsync": 3,
        "slow_ui_thread": 4,
        "high_input_latency": 5,
    }
    assert snapshot_values["online"] == 1
    assert snapshot_values["collecting"] == 1
    assert snapshot_values["cpu_fg"] == 0
    assert snapshot_values["cpu_bg"] == 37.5
    assert snapshot_values["cpu_app"] == 37.5
    assert snapshot_values["cpu_user"] == 28.0
    assert snapshot_values["cpu_system"] == 9.5
    assert snapshot_values["threads"] == 42
    assert snapshot_values["memory_pss"] == 2.0
    assert snapshot_values["memory_java"] == 1.0
    assert snapshot_values["memory_native"] == 0.5
    assert snapshot_values["memory_graphics"] == 0.25
    assert snapshot_values["memory_stack"] == 0.12
    assert snapshot_values["memory_code"] == 0.06
    assert snapshot_values["memory_private_other"] == 0.03
    assert snapshot_values["memory_system"] == 0.02
    assert snapshot_values["memory_swap"] == 0.01
    assert snapshot_values["fps"] == 58.6
    assert chart_points(session, 1) == [{"_ts": 2000, "memory_pss": 120}]
    assert marker_payload(session) == [{"timestamp_ms": 1500, "label": "Login"}]


def test_snapshot_chart_values_does_not_emit_cpu_zero_without_delta():
    snapshot = PerformanceSnapshot(
        device_id="device-1",
        online=True,
        current_package="com.example",
        cpu=CpuSample(timestamp_ms=1000, process_percent=None, is_foreground=True),
    )

    values = snapshot_chart_values(snapshot, collecting=True)

    assert values == {
        "online": 1,
        "collecting": 1,
    }


def test_frame_chart_values_uses_slow_rate_as_stutter_fallback():
    frames = FrameMetrics(
        total_frames=100,
        slow_frames=8,
        frozen_frames=0,
        slow_frame_rate=0.08,
        frozen_frame_rate=0,
    )

    values = frame_chart_values(frames)

    assert values["stutter"] == 8
    assert values["stutter_rate"] == 8.0
    assert values["frozen_rate"] == 0


def test_dashboard_metric_summaries_and_axis_policy_are_stable_payloads():
    roles = {
        "BUTTON_ACCENT": "#fps",
        "LOG_WARNING": "#warn",
        "LOG_INFO": "#info",
        "LOG_ERROR": "#error",
        "LOG_SUCCESS": "#success",
        "TEXT_SECONDARY": "#muted",
    }
    session = PerformanceSession(device_id="device-1")
    session.add_point(
        1000,
        {
            "fps": 58,
            "jank": 3,
            "stutter_rate": 1,
            "frame_time_p95": 20,
            "cpu_app": 20,
            "cpu_user": 15,
            "cpu_system": 5,
            "memory_pss": 120,
            "memory_graphics": 10,
        },
    )
    session.add_point(
        2000,
        {
            "fps": 60,
            "jank": 1,
            "stutter_rate": 0,
            "frame_time_p95": 18,
            "cpu_app": 30,
            "cpu_user": 22,
            "cpu_system": 8,
            "memory_pss": 140,
            "memory_java": 70,
            "memory_native": 45,
            "memory_graphics": 12,
            "memory_swap": 2,
            "activities": 1,
            "views": 10,
            "roots": 1,
        },
    )

    summaries = metric_summaries(session, roles.__getitem__)
    details = metric_details(session)
    policy = axis_policy()

    assert summaries[0] == {
        "metric": "fps",
        "label": "FPS",
        "unit": "",
        "digits": 1,
        "color": "#fps",
        "now": 60.0,
        "avg": 59.0,
        "max": 60.0,
        "count": 2,
    }
    assert summaries[1]["metric"] == "jank"
    assert summaries[1]["color"] == "#warn"
    assert summaries[2]["metric"] == "stutter_rate"
    assert summaries[4]["metric"] == "cpu_app"
    assert summaries[7]["label"] == "PSS"
    assert summaries[8]["now"] == 70.0
    assert details[0]["group"] == "Frame"
    assert {"label": "P95", "value": "18.0", "unit": "ms"} in details[0]["items"]
    assert {"label": "User", "value": "22.0", "unit": "%"} in details[1]["items"]
    assert {"label": "Graphics", "value": "12.0", "unit": "MB"} in details[2]["items"]
    assert {"label": "Views", "value": "10", "unit": ""} in details[3]["items"]
    assert policy["fpsChart"] == {"min": 0, "max": 60, "padded": False}
    assert policy["cpuChart"] == {"min": 0, "max": 100, "padded": True, "dynamic": True}
    assert policy["memoryChart"] == {"min": 0, "max": 256, "padded": True, "dynamic": True}
    policy["fpsChart"]["max"] = 120
    assert axis_policy()["fpsChart"]["max"] == 60


def test_monitor_control_state_matches_collection_lifecycle():
    idle = monitor_control_state(
        monitoring=False,
        quick_running=False,
        analyzing=False,
        has_report=False,
    )
    quick = monitor_control_state(
        monitoring=False,
        quick_running=True,
        analyzing=False,
        has_report=False,
    )
    collecting = monitor_control_state(
        monitoring=True,
        quick_running=False,
        analyzing=False,
        has_report=True,
    )
    analyzing = monitor_control_state(
        monitoring=False,
        quick_running=False,
        analyzing=True,
        has_report=True,
    )

    assert idle == {
        "current": True,
        "quick": True,
        "start": True,
        "stop": False,
        "mark": False,
        "openReport": False,
        "export": False,
    }
    assert quick["quick"] is False
    assert quick["start"] is False
    assert quick["stop"] is False
    assert collecting["quick"] is False
    assert collecting["start"] is False
    assert collecting["stop"] is True
    assert collecting["mark"] is True
    assert collecting["openReport"] is True
    assert analyzing["current"] is False
    assert analyzing["quick"] is False
    assert analyzing["start"] is False
    assert analyzing["stop"] is False
    assert analyzing["openReport"] is True


def test_web_dashboard_context_normalizes_set_context_payload():
    events = ["12:00:00 Monitor started"]
    summary = {"status": "pass"}
    controls = {"start": True}
    palette = {"background": "#000"}
    font = {"uiSize": 12}
    device_info = [{"info": "Device Name", "value": "Pixel"}]
    summaries = [{"metric": "fps", "now": 60}]
    details = [{"group": "Frame", "items": [{"label": "FPS", "value": "60"}]}]
    policy = {"fpsChart": {"max": 60}}

    context = web_dashboard_context(
        events=events,
        report="Quick Check: PASS",
        report_summary=summary,
        state="Ready",
        current_package="com.example",
        package_name="com.example.target",
        activity=".MainActivity",
        controls=controls,
        theme="Dark",
        palette=palette,
        font=font,
        device_info=device_info,
        metric_summaries=summaries,
        metric_details=details,
        axis_policy=policy,
    )
    events.append("mutated")
    summary["status"] = "mutated"
    controls["start"] = False
    palette["background"] = "#fff"
    font["uiSize"] = 14
    device_info.append({"info": "OS", "value": "15"})
    summaries.append({"metric": "jank", "now": 5})
    details.append({"group": "CPU", "items": []})
    policy["cpuChart"] = {"max": 100}

    assert context == {
        "events": ["12:00:00 Monitor started"],
        "report": "Quick Check: PASS",
        "report_summary": {"status": "pass"},
        "state": "Ready",
        "current_package": "com.example",
        "package_name": "com.example.target",
        "activity": ".MainActivity",
        "controls": {"start": True},
        "theme": "Dark",
        "palette": {"background": "#000"},
        "font": {"uiSize": 12},
        "device_info": [{"info": "Device Name", "value": "Pixel"}],
        "metric_summaries": [{"metric": "fps", "now": 60}],
        "metric_details": [{"group": "Frame", "items": [{"label": "FPS", "value": "60"}]}],
        "axis_policy": {"fpsChart": {"max": 60}},
    }


def test_web_timeline_payload_normalizes_browser_facing_keys():
    points = [{"_ts": 1000, "fps": 60}]
    markers = [{"timestamp_ms": 1000, "label": "Mark 1"}]
    lanes = [{"metric": "fps", "label": "FPS", "enabled": True}]
    report_summary = {"status": "pass"}
    controls = {"quick": True}
    palette = {"background": "#101217"}
    font = {"uiSize": 12}
    device_info = [{"info": "Model", "value": "Pixel"}]
    summaries = [{"metric": "fps", "now": 60}]
    details = [{"group": "Frame", "items": [{"label": "FPS", "value": "60"}]}]
    policy = {"fpsChart": {"max": 60}}

    payload = web_timeline_payload(
        points,
        markers,
        lanes,
        events=["12:00:00 Monitor started"],
        report="Quick Check: PASS",
        report_summary=report_summary,
        state="Ready",
        current_package="com.example",
        package_name="com.example.target",
        activity=".MainActivity",
        controls=controls,
        theme="Dark",
        palette=palette,
        font=font,
        device_info=device_info,
        metric_summaries=summaries,
        metric_details=details,
        axis_policy=policy,
    )
    points.append({"_ts": 2000, "fps": 59})
    markers.append({"timestamp_ms": 2000, "label": "Mark 2"})
    lanes.append({"metric": "cpu", "label": "CPU", "enabled": True})
    report_summary["status"] = "mutated"
    controls["quick"] = False
    palette["background"] = "#fff"
    font["uiSize"] = 14
    device_info.append({"info": "OS", "value": "15"})
    summaries.append({"metric": "jank", "now": 5})
    details.append({"group": "CPU", "items": []})
    policy["cpuChart"] = {"max": 100}

    assert payload == {
        "points": [{"_ts": 1000, "fps": 60}],
        "markers": [{"timestamp_ms": 1000, "label": "Mark 1"}],
        "lanes": [{"metric": "fps", "label": "FPS", "enabled": True}],
        "events": ["12:00:00 Monitor started"],
        "report": "Quick Check: PASS",
        "reportSummary": {"status": "pass"},
        "state": "Ready",
        "currentPackage": "com.example",
        "packageName": "com.example.target",
        "activity": ".MainActivity",
        "controls": {"quick": True},
        "theme": "Dark",
        "palette": {"background": "#101217"},
        "font": {"uiSize": 12},
        "deviceInfo": [{"info": "Model", "value": "Pixel"}],
        "metricSummaries": [{"metric": "fps", "now": 60}],
        "metricDetails": [{"group": "Frame", "items": [{"label": "FPS", "value": "60"}]}],
        "axisPolicy": {"fpsChart": {"max": 60}},
    }


def test_performance_report_presentation_builds_summary_and_plain_text():
    result = {
        "status": "warn",
        "report_dir": "C:/reports/perf",
        "startup": StartupMetrics(
            device_id="device-1",
            package_name="com.example",
            total_time_ms=1234,
            displayed_ms=900,
        ),
        "frames": FrameMetrics(
            total_frames=100,
            janky_frames=8,
            jank_rate=0.08,
            frozen_frame_rate=0.01,
            estimated_fps=58.7,
            p95_ms=22.4,
        ),
        "samples": [
            MemorySample(
                timestamp_ms=1,
                total_pss_kb=2048,
                native_heap_kb=512,
                graphics_kb=256,
                total_swap_pss_kb=128,
            )
        ],
        "cpu_samples": [
            CpuSample(
                timestamp_ms=1,
                process_percent=22.5,
                process_user_percent=18.0,
                process_system_percent=4.5,
                thread_count=12,
            )
        ],
        "findings": ["Jank rate: 8.00%"],
    }

    summary = build_report_summary(result, "Quick Check")
    text = render_report_text(result, "Quick Check")

    assert summary["title"] == "Quick Check"
    assert summary["status"] == "warn"
    assert summary["reportDir"] == "C:/reports/perf"
    assert summary["findings"] == ["Jank rate: 8.00%"]
    assert {"label": "Startup", "value": "1234 ms"} in summary["metrics"]
    assert {"label": "Jank", "value": "8.00%"} in summary["metrics"]
    assert {"label": "Stutter", "value": "1.00%"} in summary["metrics"]
    assert {"label": "CPU", "value": "22.5%"} in summary["metrics"]
    assert {"label": "PSS", "value": "2,048 KB"} in summary["metrics"]
    assert {"label": "Graphics", "value": "256 KB"} in summary["metrics"]
    assert "Quick Check: WARN" in text
    assert "FPS: 58.7" in text
    assert "CPU User: 18.0%" in text
    assert "Native Heap: 512 KB" in text
    assert "Swap PSS: 128 KB" in text
    assert "- Jank rate: 8.00%" in text


def test_performance_report_presentation_falls_back_to_slow_stutter_rate():
    result = {
        "status": "warn",
        "frames": FrameMetrics(
            total_frames=100,
            slow_frames=8,
            frozen_frames=0,
            slow_frame_rate=0.08,
            frozen_frame_rate=0.0,
            estimated_fps=55.0,
        ),
        "samples": [
            MemorySample(
                timestamp_ms=1,
                total_pss_kb=4096,
                graphics_kb=3584,
            )
        ],
    }

    summary = build_report_summary(result, "Monitor")
    text = render_report_text(result, "Monitor")

    assert {"label": "Stutter", "value": "8.00%"} in summary["metrics"]
    assert {"label": "Graphics", "value": "3,584 KB"} in summary["metrics"]
    assert "Stutter: 8.00%" in text
    assert "Graphics: 3,584 KB" in text


def test_sampling_schedule_respects_frame_interval_and_force_refresh():
    schedule = PerformanceSamplingSchedule(frame_interval_ms=1000)

    assert schedule.should_refresh_frame(10.0) is True
    schedule.mark_frame_refresh(10.0)

    assert schedule.should_refresh_frame(10.5) is False
    assert schedule.should_refresh_frame(11.0) is True
    assert schedule.should_refresh_frame(10.2, force=True) is True

    schedule.reset()

    assert schedule.last_frame_refresh_at == 0.0
    assert schedule.should_refresh_frame(10.1) is True


def test_analyze_worker_flags_memory_growth_and_writes_report():
    service = type("FakeService", (), {})()
    service.device_id = "device-1"
    service.frame_metrics = lambda package_name: FrameMetrics(total_frames=100, jank_rate=0.01)
    service.report_service = type(
        "FakeReportService",
        (),
        {
            "create_report_dir": lambda self, device_id, package_name: "C:/reports/perf",
            "write_report": lambda self, *args, **kwargs: {"summary": "summary.json"},
        },
    )()
    worker = PerformanceAnalyzeWorker(
        service,
        "com.example",
        [
            MemorySample(timestamp_ms=1, total_pss_kb=1000),
            MemorySample(timestamp_ms=2, total_pss_kb=13000),
        ],
        [],
        started_at=0,
    )
    emitted = []
    worker.result_ready.connect(emitted.append)

    worker.run()

    assert emitted
    assert emitted[0]["status"] == "warn"
    assert emitted[0]["findings"] == ["PSS grew by 12000 KB"]


def test_snapshot_worker_skips_heavy_device_info_by_default():
    service = Mock()
    service.snapshot.return_value = PerformanceSnapshot(
        device_id="device-1",
        online=True,
        target_package="com.example",
        status="Ready",
    )
    worker = PerformanceSnapshotWorker(service, "com.example")
    emitted = []
    worker.snapshot_ready.connect(emitted.append)

    worker.run()

    service.device_info.assert_not_called()
    service.snapshot.assert_called_once_with("com.example")
    assert emitted == [service.snapshot.return_value]


def test_snapshot_worker_collects_device_info_only_when_requested():
    device_info = Mock()
    device_info.rows.return_value = [{"info": "Model", "value": "Pixel"}]
    service = Mock()
    service.device_info.return_value = device_info
    service.snapshot.return_value = PerformanceSnapshot(
        device_id="device-1",
        online=True,
        target_package="com.example",
        status="Ready",
    )
    worker = PerformanceSnapshotWorker(
        service,
        "com.example",
        include_device_info=True,
        refresh_device_info=True,
    )
    device_rows = []
    snapshots = []
    worker.device_info_ready.connect(device_rows.append)
    worker.snapshot_ready.connect(snapshots.append)

    worker.run()

    service.device_info.assert_called_once_with(refresh=True)
    service.snapshot.assert_called_once_with("com.example")
    assert device_rows == [[{"info": "Model", "value": "Pixel"}]]
    assert snapshots == [service.snapshot.return_value]
