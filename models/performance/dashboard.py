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
            {"metric": "stutter", "label": "Stutter", "unit": "", "color": ""},
        ],
    },
    {
        "metric": "cpu",
        "label": "CPU",
        "unit": "%",
        "color": "",
        "enabled": True,
        "series": [
            {"metric": "cpu_fg", "label": "Foreground", "unit": "%", "color": ""},
            {"metric": "cpu_bg", "label": "Background", "unit": "%", "color": ""},
        ],
    },
    {
        "metric": "memory",
        "label": "Memory",
        "unit": "MB",
        "color": "",
        "enabled": True,
        "series": [
            {"metric": "memory_java", "label": "Java Heap", "unit": "MB", "color": ""},
            {"metric": "memory_native", "label": "Native", "unit": "MB", "color": ""},
            {"metric": "memory_pss", "label": "PSS", "unit": "MB", "color": ""},
        ],
    },
]

_METRIC_COLOR_ROLES = {
    "fps": "BUTTON_ACCENT",
    "jank": "LOG_WARNING",
    "stutter": "LOG_INFO",
    "cpu": "LOG_ERROR",
    "cpu_fg": "LOG_ERROR",
    "cpu_bg": "LOG_WARNING",
    "memory": "LOG_SUCCESS",
    "memory_java": "LOG_INFO",
    "memory_native": "LOG_WARNING",
    "memory_pss": "LOG_SUCCESS",
}

_SUMMARY_METRICS = [
    {"metric": "fps", "label": "FPS", "unit": "", "digits": 1, "role": "BUTTON_ACCENT"},
    {"metric": "jank", "label": "Jank", "unit": "%", "digits": 1, "role": "LOG_WARNING"},
    {"metric": "cpu_fg", "label": "CPU", "unit": "%", "digits": 1, "role": "LOG_ERROR"},
    {"metric": "memory_pss", "label": "PSS", "unit": "MB", "digits": 1, "role": "LOG_SUCCESS"},
    {"metric": "memory_java", "label": "Java", "unit": "MB", "digits": 1, "role": "LOG_INFO"},
    {"metric": "memory_native", "label": "Native", "unit": "MB", "digits": 1, "role": "LOG_WARNING"},
]

_AXIS_POLICY = {
    "fpsChart": {"min": 0, "max": 60, "padded": False},
    "cpuChart": {"min": 0, "max": 100, "padded": False},
    "memoryChart": {"min": 0, "max": 256, "padded": True},
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
    return {
        "fps": frames.estimated_fps,
        "jank": jank_rate * 100,
        "stutter": frames.frozen_frames,
        "frames": frames.total_frames,
        "slow": frames.slow_frames,
        "frozen": frames.frozen_frames,
    }


def snapshot_chart_values(
    snapshot: PerformanceSnapshot,
    *,
    collecting: bool,
    latest_frame_values: Mapping[str, MetricValue] | None = None,
) -> dict[str, MetricValue]:
    values: dict[str, MetricValue] = {
        "online": 1 if snapshot.online else 0,
        "cpu_fg": 0,
        "cpu_bg": 0,
        "collecting": 1 if collecting else 0,
    }
    if snapshot.memory:
        values.update(
            {
                "memory_pss": _kb_to_mb(snapshot.memory.total_pss_kb) or 0,
                "memory_java": _kb_to_mb(snapshot.memory.java_heap_kb) or 0,
                "memory_native": _kb_to_mb(snapshot.memory.native_heap_kb) or 0,
                "activities": snapshot.memory.activities,
                "views": snapshot.memory.views,
                "roots": snapshot.memory.view_roots,
            }
        )
    if snapshot.cpu and snapshot.cpu.process_percent is not None:
        metric = "cpu_fg" if snapshot.cpu.is_foreground else "cpu_bg"
        values[metric] = snapshot.cpu.process_percent
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
        "axis_policy": dict(axis_policy or {}),
    }


def _apply_metric_color(metric: dict, color_for: ColorGetter) -> None:
    role = _METRIC_COLOR_ROLES.get(str(metric.get("metric", "")))
    if role:
        metric["color"] = color_for(role)


def _kb_to_mb(value: int | None) -> float | None:
    return None if value is None else round(value / 1024, 2)


def _round_metric(value: float | int | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)
