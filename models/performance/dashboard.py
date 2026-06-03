from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy

from .session import PerformanceSession
from .types import FrameMetrics, PerformanceSnapshot

ColorGetter = Callable[[str], str]
MetricValue = float | int | None


_METRIC_LANE_TEMPLATES = [
    {
        "metric": "fps",
        "label": "FPS",
        "unit": "",
        "color": "",
        "enabled": True,
        "series": [
            {"metric": "fps", "label": "FPS", "unit": "", "color": ""},
            {"metric": "jank", "label": "Jank", "unit": "%", "color": ""},
            {"metric": "stutter_rate", "label": "Stutter", "unit": "%", "color": ""},
            {"metric": "frame_time_p95", "label": "P95", "unit": "ms", "color": ""},
        ],
    },
    {
        "metric": "cpu",
        "label": "CPU",
        "unit": "%",
        "color": "",
        "enabled": True,
        "series": [
            {"metric": "cpu_app", "label": "App", "unit": "%", "color": ""},
            {"metric": "cpu_user", "label": "User", "unit": "%", "color": ""},
            {"metric": "cpu_system", "label": "System", "unit": "%", "color": ""},
        ],
    },
    {
        "metric": "memory",
        "label": "Memory",
        "unit": "MB",
        "color": "",
        "enabled": True,
        "series": [
            {"metric": "memory_pss", "label": "PSS", "unit": "MB", "color": ""},
            {"metric": "memory_java", "label": "Java Heap", "unit": "MB", "color": ""},
            {"metric": "memory_native", "label": "Native", "unit": "MB", "color": ""},
            {"metric": "memory_graphics", "label": "Graphics", "unit": "MB", "color": ""},
            {"metric": "memory_swap", "label": "Swap", "unit": "MB", "color": ""},
        ],
    },
]

_METRIC_COLOR_ROLES = {
    "fps": "BUTTON_ACCENT",
    "jank": "LOG_WARNING",
    "stutter": "LOG_INFO",
    "stutter_rate": "LOG_INFO",
    "frame_time_p95": "TEXT_SECONDARY",
    "cpu": "LOG_ERROR",
    "cpu_app": "LOG_ERROR",
    "cpu_user": "LOG_WARNING",
    "cpu_system": "LOG_INFO",
    "cpu_fg": "LOG_ERROR",
    "cpu_bg": "LOG_WARNING",
    "memory": "LOG_SUCCESS",
    "memory_pss": "LOG_SUCCESS",
    "memory_java": "LOG_INFO",
    "memory_native": "LOG_WARNING",
    "memory_graphics": "BUTTON_ACCENT",
    "memory_stack": "TEXT_SECONDARY",
    "memory_code": "LOG_INFO",
    "memory_private_other": "TEXT_SECONDARY",
    "memory_system": "LOG_ERROR",
    "memory_swap": "LOG_WARNING",
}

_SUMMARY_METRICS = [
    {"metric": "fps", "label": "FPS", "unit": "", "digits": 1, "role": "BUTTON_ACCENT"},
    {"metric": "jank", "label": "Jank", "unit": "%", "digits": 1, "role": "LOG_WARNING"},
    {"metric": "stutter_rate", "label": "Stutter", "unit": "%", "digits": 1, "role": "LOG_INFO"},
    {"metric": "frame_time_p95", "label": "P95", "unit": "ms", "digits": 1, "role": "TEXT_SECONDARY"},
    {"metric": "cpu_app", "label": "CPU", "unit": "%", "digits": 1, "role": "LOG_ERROR"},
    {"metric": "cpu_user", "label": "User", "unit": "%", "digits": 1, "role": "LOG_WARNING"},
    {"metric": "cpu_system", "label": "System", "unit": "%", "digits": 1, "role": "LOG_INFO"},
    {"metric": "memory_pss", "label": "PSS", "unit": "MB", "digits": 1, "role": "LOG_SUCCESS"},
    {"metric": "memory_java", "label": "Java", "unit": "MB", "digits": 1, "role": "LOG_INFO"},
    {"metric": "memory_native", "label": "Native", "unit": "MB", "digits": 1, "role": "LOG_WARNING"},
    {"metric": "memory_graphics", "label": "Graphics", "unit": "MB", "digits": 1, "role": "BUTTON_ACCENT"},
    {"metric": "memory_swap", "label": "Swap", "unit": "MB", "digits": 1, "role": "LOG_WARNING"},
]

_AXIS_POLICY = {
    "fpsChart": {"min": 0, "max": 60, "padded": False},
    "cpuChart": {"min": 0, "max": 100, "padded": True, "dynamic": True},
    "memoryChart": {"min": 0, "max": 256, "padded": True, "dynamic": True},
}


def build_metric_lanes(color_for: ColorGetter) -> list[dict]:
    lanes = deepcopy(_METRIC_LANE_TEMPLATES)
    return refresh_metric_lane_colors(lanes, color_for)


def refresh_metric_lane_colors(lanes: list[dict], color_for: ColorGetter) -> list[dict]:
    for lane in lanes:
        _apply_metric_color(lane, color_for)
        for series in lane.get("series", []):
            _apply_metric_color(series, color_for)
    return lanes


def frame_chart_values(frames: FrameMetrics) -> dict[str, MetricValue]:
    jank_rate = frames.jank_rate if frames.jank_rate is not None else 0
    slow_rate = frames.slow_frame_rate if frames.slow_frame_rate is not None else 0
    frozen_rate = frames.frozen_frame_rate if frames.frozen_frame_rate is not None else 0
    stutter_rate = frozen_rate if frozen_rate else slow_rate
    stutter_frames = frames.frozen_frames if frames.frozen_frames else frames.slow_frames
    return {
        "fps": frames.estimated_fps,
        "jank": jank_rate * 100,
        "stutter": stutter_frames,
        "stutter_rate": stutter_rate * 100,
        "frames": frames.total_frames,
        "slow": frames.slow_frames,
        "frozen": frames.frozen_frames,
        "slow_rate": slow_rate * 100,
        "frozen_rate": frozen_rate * 100,
        "frame_time_avg": frames.avg_frame_time_ms,
        "frame_time_p50": frames.p50_ms,
        "frame_time_p95": frames.p95_ms,
        "frame_time_p99": frames.p99_ms,
        "frame_time_max": frames.max_frame_time_ms,
        "missed_vsync": frames.missed_vsync,
        "slow_ui_thread": frames.slow_ui_thread,
        "high_input_latency": frames.high_input_latency,
    }


def snapshot_chart_values(
    snapshot: PerformanceSnapshot,
    *,
    collecting: bool,
    latest_frame_values: Mapping[str, MetricValue] | None = None,
) -> dict[str, MetricValue]:
    values: dict[str, MetricValue] = {
        "online": 1 if snapshot.online else 0,
        "collecting": 1 if collecting else 0,
    }
    if snapshot.memory:
        values.update(
            {
                "memory_pss": _kb_to_mb(snapshot.memory.total_pss_kb) or 0,
                "memory_java": _kb_to_mb(snapshot.memory.java_heap_kb) or 0,
                "memory_native": _kb_to_mb(snapshot.memory.native_heap_kb) or 0,
                "memory_graphics": _kb_to_mb(snapshot.memory.graphics_kb) or 0,
                "memory_stack": _kb_to_mb(snapshot.memory.stack_kb) or 0,
                "memory_code": _kb_to_mb(snapshot.memory.code_kb) or 0,
                "memory_private_other": _kb_to_mb(snapshot.memory.private_other_kb) or 0,
                "memory_system": _kb_to_mb(snapshot.memory.system_kb) or 0,
                "memory_swap": _kb_to_mb(snapshot.memory.total_swap_pss_kb) or 0,
                "activities": snapshot.memory.activities,
                "views": snapshot.memory.views,
                "roots": snapshot.memory.view_roots,
                "app_contexts": snapshot.memory.app_contexts,
            }
        )
    if snapshot.cpu and snapshot.cpu.process_percent is not None:
        metric = "cpu_fg" if snapshot.cpu.is_foreground else "cpu_bg"
        values["cpu_fg"] = snapshot.cpu.process_percent if snapshot.cpu.is_foreground else 0
        values["cpu_bg"] = 0 if snapshot.cpu.is_foreground else snapshot.cpu.process_percent
        values[metric] = snapshot.cpu.process_percent
        values["cpu_app"] = snapshot.cpu.process_percent
        if snapshot.cpu.process_user_percent is not None:
            values["cpu_user"] = snapshot.cpu.process_user_percent
        if snapshot.cpu.process_system_percent is not None:
            values["cpu_system"] = snapshot.cpu.process_system_percent
        if snapshot.cpu.thread_count is not None:
            values["threads"] = snapshot.cpu.thread_count
        if snapshot.cpu.process_count is not None:
            values["processes"] = snapshot.cpu.process_count
    if latest_frame_values:
        values.update(latest_frame_values)
    return values


def chart_points(session: PerformanceSession, max_points: int) -> list[dict]:
    return [
        {"_ts": point.timestamp_ms, **point.values}
        for point in session.points[-max_points:]
    ]


def marker_payload(session: PerformanceSession) -> list[dict]:
    return [
        {
            "timestamp_ms": marker.timestamp_ms,
            "label": marker.label,
        }
        for marker in session.markers
    ]


def metric_summaries(session: PerformanceSession, color_for: ColorGetter) -> list[dict]:
    summaries = []
    for definition in _SUMMARY_METRICS:
        metric = definition["metric"]
        summary = session.summarize(metric)
        summaries.append(
            {
                "metric": metric,
                "label": definition["label"],
                "unit": definition["unit"],
                "digits": definition["digits"],
                "color": color_for(definition["role"]),
                "now": _round_metric(summary.last_value, definition["digits"]),
                "avg": _round_metric(summary.avg_value, definition["digits"]),
                "max": _round_metric(summary.max_value, definition["digits"]),
                "count": summary.count,
            }
        )
    return summaries


def metric_details(session: PerformanceSession) -> list[dict]:
    latest = session.latest_values()
    return [
        {
            "group": "Frame",
            "items": [
                _detail_item("FPS", latest.get("fps"), "", 1),
                _detail_item("Jank", latest.get("jank"), "%", 1),
                _detail_item("Stutter", latest.get("stutter_rate"), "%", 1),
                _detail_item("P95", latest.get("frame_time_p95"), "ms", 1),
                _detail_item("P99", latest.get("frame_time_p99"), "ms", 1),
                _detail_item("Slow", latest.get("slow"), "", 0),
                _detail_item("Frozen", latest.get("frozen"), "", 0),
            ],
        },
        {
            "group": "CPU",
            "items": [
                _detail_item("App", latest.get("cpu_app"), "%", 1),
                _detail_item("User", latest.get("cpu_user"), "%", 1),
                _detail_item("System", latest.get("cpu_system"), "%", 1),
                _detail_item("Foreground", latest.get("cpu_fg"), "%", 1),
                _detail_item("Background", latest.get("cpu_bg"), "%", 1),
                _detail_item("Processes", latest.get("processes"), "", 0),
                _detail_item("Threads", latest.get("threads"), "", 0),
            ],
        },
        {
            "group": "Memory",
            "items": [
                _detail_item("PSS", latest.get("memory_pss"), "MB", 1),
                _detail_item("Java", latest.get("memory_java"), "MB", 1),
                _detail_item("Native", latest.get("memory_native"), "MB", 1),
                _detail_item("Graphics", latest.get("memory_graphics"), "MB", 1),
                _detail_item("Stack", latest.get("memory_stack"), "MB", 1),
                _detail_item("Code", latest.get("memory_code"), "MB", 1),
                _detail_item("System", latest.get("memory_system"), "MB", 1),
                _detail_item("Swap", latest.get("memory_swap"), "MB", 1),
            ],
        },
        {
            "group": "Objects",
            "items": [
                _detail_item("Activities", latest.get("activities"), "", 0),
                _detail_item("Views", latest.get("views"), "", 0),
                _detail_item("Roots", latest.get("roots"), "", 0),
                _detail_item("Contexts", latest.get("app_contexts"), "", 0),
            ],
        },
    ]


def axis_policy() -> dict[str, dict[str, float | int | bool]]:
    return {
        chart_id: dict(policy)
        for chart_id, policy in _AXIS_POLICY.items()
    }


def monitor_control_state(
    *,
    monitoring: bool,
    quick_running: bool,
    analyzing: bool,
    has_report: bool,
) -> dict[str, bool]:
    busy = quick_running or analyzing
    return {
        "current": not busy and not monitoring,
        "quick": not busy and not monitoring,
        "start": not busy and not monitoring,
        "stop": monitoring and not busy,
        "mark": monitoring and not busy,
        "openReport": has_report,
        "export": has_report,
    }


def web_dashboard_context(
    *,
    events: list[str] | None = None,
    report: str = "",
    report_summary: dict | None = None,
    state: str = "",
    current_package: str = "",
    package_name: str = "",
    activity: str = "",
    controls: dict | None = None,
    theme: str = "",
    palette: dict | None = None,
    font: dict | None = None,
    device_info: list[dict] | None = None,
    metric_summaries: list[dict] | None = None,
    metric_details: list[dict] | None = None,
    axis_policy: dict | None = None,
) -> dict:
    return {
        "events": list(events or []),
        "report": report,
        "report_summary": dict(report_summary or {}),
        "state": state,
        "current_package": current_package,
        "package_name": package_name,
        "activity": activity,
        "controls": dict(controls or {}),
        "theme": theme,
        "palette": dict(palette or {}),
        "font": dict(font or {}),
        "device_info": list(device_info or []),
        "metric_summaries": list(metric_summaries or []),
        "metric_details": list(metric_details or []),
        "axis_policy": dict(axis_policy or {}),
    }


def web_timeline_payload(
    points: list[dict],
    markers: list[dict],
    lanes: list[dict],
    *,
    events: list[str] | None = None,
    report: str = "",
    report_summary: dict | None = None,
    state: str = "",
    current_package: str = "",
    package_name: str = "",
    activity: str = "",
    controls: dict | None = None,
    theme: str = "",
    palette: dict | None = None,
    font: dict | None = None,
    device_info: list[dict] | None = None,
    metric_summaries: list[dict] | None = None,
    metric_details: list[dict] | None = None,
    axis_policy: dict | None = None,
) -> dict:
    """Build the browser-facing WebEngine timeline payload."""

    context = web_dashboard_context(
        events=events,
        report=report,
        report_summary=report_summary,
        state=state,
        current_package=current_package,
        package_name=package_name,
        activity=activity,
        controls=controls,
        theme=theme,
        palette=palette,
        font=font,
        device_info=device_info,
        metric_summaries=metric_summaries,
        metric_details=metric_details,
        axis_policy=axis_policy,
    )
    return {
        "points": list(points),
        "markers": list(markers),
        "lanes": list(lanes),
        "events": context["events"],
        "report": context["report"],
        "reportSummary": context["report_summary"],
        "state": context["state"],
        "currentPackage": context["current_package"],
        "packageName": context["package_name"],
        "activity": context["activity"],
        "controls": context["controls"],
        "theme": context["theme"],
        "palette": context["palette"],
        "font": context["font"],
        "deviceInfo": context["device_info"],
        "metricSummaries": context["metric_summaries"],
        "metricDetails": context["metric_details"],
        "axisPolicy": context["axis_policy"],
    }


def _apply_metric_color(metric: dict, color_for: ColorGetter) -> None:
    role = _METRIC_COLOR_ROLES.get(str(metric.get("metric", "")))
    if role:
        metric["color"] = color_for(role)


def _kb_to_mb(value: int | None) -> float | None:
    return None if value is None else round(value / 1024, 2)


def _round_metric(value: float | int | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _detail_item(label: str, value: MetricValue, unit: str, digits: int) -> dict[str, str]:
    return {
        "label": label,
        "value": _format_detail_value(value, digits),
        "unit": unit,
    }


def _format_detail_value(value: MetricValue, digits: int) -> str:
    if value is None:
        return "--"
    number = float(value)
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"
