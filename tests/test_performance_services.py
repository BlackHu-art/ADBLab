from models.performance.parsers import (
    build_cpu_sample,
    enrich_startup_from_logcat,
    parse_am_start_output,
    parse_gfxinfo_output,
    parse_meminfo_output,
    parse_proc_stat_total,
    parse_process_stat_ticks,
)
from models.performance.dashboard import (
    axis_policy,
    build_metric_lanes,
    chart_points,
    frame_chart_values,
    marker_payload,
    metric_summaries,
    monitor_control_state,
    refresh_metric_lane_colors,
    snapshot_chart_values,
    web_dashboard_context,
)
from models.performance.presentation import build_report_summary, render_report_text
from models.performance.sampling import PerformanceSamplingSchedule
from models.performance.service import _cpu_info, _gpu_type, _opengl_info, _prop, _ram_size, _swap_size
from models.performance.report_service import PerformanceReportService
from models.performance.session import PerformanceSession
from models.performance.types import CpuSample, FrameMetrics, MemorySample, PerformanceSnapshot, StartupMetrics
from models.performance.workers import PerformanceAnalyzeWorker


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


def test_parse_gfxinfo_summary_and_profile_rows():
    output = """
Total frames rendered: 4
Janky frames: 1 (25.00%)
50th percentile: 8ms
90th percentile: 20ms
95th percentile: 22ms
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

    assert metrics.total_frames == 4
    assert metrics.janky_frames == 1
    assert metrics.jank_rate == 0.25
    assert metrics.p95_ms == 22
    assert metrics.slow_frames == 1
    assert metrics.missed_vsync == 2
    assert metrics.high_input_latency == 3
    assert metrics.slow_ui_thread == 4


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
               TOTAL:    54132

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
    assert sample.views == 98
    assert sample.view_roots == 1
    assert sample.app_contexts == 4
    assert sample.activities == 1


def test_cpu_sample_uses_proc_tick_delta():
    process_stat = "1234 (com.example) S 1 2 3 4 5 6 7 8 9 10 120 30 0 0 20 0 1 0"
    total_stat = "cpu  100 20 30 850 0 0 0 0 0 0"

    process_ticks = parse_process_stat_ticks(process_stat)
    total_ticks = parse_proc_stat_total(total_stat)
    sample = build_cpu_sample(
        timestamp_ms=1000,
        pid=1234,
        process_ticks=process_ticks,
        total_ticks=total_ticks,
        previous_process_ticks=100,
        previous_total_ticks=900,
        is_foreground=True,
    )

    assert process_ticks == 150
    assert total_ticks == 1000
    assert sample.process_percent == 50.0
    assert sample.is_foreground is True


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
    }
    lanes = build_metric_lanes(roles.__getitem__)

    assert [lane["metric"] for lane in lanes] == ["fps", "cpu", "memory"]
    assert [series["metric"] for series in lanes[0]["series"]] == ["fps", "jank", "stutter"]
    assert [series["metric"] for series in lanes[1]["series"]] == ["cpu_fg", "cpu_bg"]
    assert [series["metric"] for series in lanes[2]["series"]] == [
        "memory_java",
        "memory_native",
        "memory_pss",
    ]
    assert lanes[0]["color"] == "#fps"
    assert lanes[1]["series"][0]["color"] == "#error"
    assert lanes[2]["series"][2]["color"] == "#success"

    refreshed = refresh_metric_lane_colors(lanes, lambda role: f"new-{role}")

    assert refreshed is lanes
    assert lanes[0]["series"][1]["color"] == "new-LOG_WARNING"
    assert lanes[2]["series"][0]["color"] == "new-LOG_INFO"


def test_dashboard_chart_value_helpers_normalize_snapshot_frame_and_session():
    frames = FrameMetrics(
        total_frames=120,
        jank_rate=0.125,
        estimated_fps=58.6,
        slow_frames=15,
        frozen_frames=2,
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
            activities=1,
            views=20,
            view_roots=2,
        ),
        cpu=CpuSample(timestamp_ms=1000, process_percent=37.5, is_foreground=False),
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
        "frames": 120,
        "slow": 15,
        "frozen": 2,
    }
    assert snapshot_values["online"] == 1
    assert snapshot_values["collecting"] == 1
    assert snapshot_values["cpu_fg"] == 0
    assert snapshot_values["cpu_bg"] == 37.5
    assert snapshot_values["memory_pss"] == 2.0
    assert snapshot_values["memory_java"] == 1.0
    assert snapshot_values["memory_native"] == 0.5
    assert snapshot_values["fps"] == 58.6
    assert chart_points(session, 1) == [{"_ts": 2000, "memory_pss": 120}]
    assert marker_payload(session) == [{"timestamp_ms": 1500, "label": "Login"}]


def test_dashboard_metric_summaries_and_axis_policy_are_stable_payloads():
    roles = {
        "BUTTON_ACCENT": "#fps",
        "LOG_WARNING": "#warn",
        "LOG_INFO": "#info",
        "LOG_ERROR": "#error",
        "LOG_SUCCESS": "#success",
    }
    session = PerformanceSession(device_id="device-1")
    session.add_point(1000, {"fps": 58, "jank": 3, "cpu_fg": 20, "memory_pss": 120})
    session.add_point(
        2000,
        {
            "fps": 60,
            "jank": 1,
            "cpu_fg": 30,
            "memory_pss": 140,
            "memory_java": 70,
            "memory_native": 45,
        },
    )

    summaries = metric_summaries(session, roles.__getitem__)
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
    assert summaries[3]["label"] == "PSS"
    assert summaries[4]["now"] == 70.0
    assert policy["fpsChart"] == {"min": 0, "max": 60, "padded": False}
    assert policy["cpuChart"] == {"min": 0, "max": 100, "padded": False}
    assert policy["memoryChart"] == {"min": 0, "max": 256, "padded": True}
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
        axis_policy=policy,
    )
    events.append("mutated")
    summary["status"] = "mutated"
    controls["start"] = False
    palette["background"] = "#fff"
    font["uiSize"] = 14
    device_info.append({"info": "OS", "value": "15"})
    summaries.append({"metric": "jank", "now": 5})
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
        "axis_policy": {"fpsChart": {"max": 60}},
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
            estimated_fps=58.7,
            p95_ms=22.4,
        ),
        "samples": [MemorySample(timestamp_ms=1, total_pss_kb=2048, native_heap_kb=512)],
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
    assert {"label": "PSS", "value": "2,048 KB"} in summary["metrics"]
    assert "Quick Check: WARN" in text
    assert "FPS: 58.7" in text
    assert "Native Heap: 512 KB" in text
    assert "- Jank rate: 8.00%" in text


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
        started_at=0,
    )
    emitted = []
    worker.result_ready.connect(emitted.append)

    worker.run()

    assert emitted
    assert emitted[0]["status"] == "warn"
    assert emitted[0]["findings"] == ["PSS grew by 12000 KB"]
