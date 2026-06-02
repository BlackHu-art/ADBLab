from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report_text(result: Mapping[str, Any], title: str) -> str:
    startup = result.get("startup")
    frames = result.get("frames")
    samples = list(result.get("samples") or [])
    cpu_samples = list(result.get("cpu_samples") or [])
    lines = [f"{title}: {str(result.get('status', 'unknown')).upper()}"]
    if startup:
        lines.append(f"Startup TotalTime: {_ms(startup.total_time_ms)}")
        lines.append(f"Displayed: {_ms(startup.displayed_ms)}")
    if frames:
        lines.append(f"Frames: {frames.total_frames}")
        lines.append(f"Jank: {_percent(frames.jank_rate)}")
        if frames.estimated_fps is not None:
            lines.append(f"FPS: {frames.estimated_fps:.1f}")
        lines.append(f"P95: {_ms(frames.p95_ms)}")
        lines.append(f"Stutter: {_percent(_stutter_rate(frames))}")
    if cpu_samples:
        last_cpu = cpu_samples[-1]
        lines.append(f"CPU App: {_percent_value(last_cpu.process_percent)}")
        lines.append(f"CPU User: {_percent_value(last_cpu.process_user_percent)}")
        lines.append(f"CPU System: {_percent_value(last_cpu.process_system_percent)}")
        if last_cpu.thread_count is not None:
            lines.append(f"Threads: {last_cpu.thread_count}")
    if samples:
        last = samples[-1]
        lines.append(f"PSS: {kb(last.total_pss_kb)}")
        lines.append(f"Java Heap: {kb(last.java_heap_kb)}")
        lines.append(f"Native Heap: {kb(last.native_heap_kb)}")
        lines.append(f"Graphics: {kb(last.graphics_kb)}")
        lines.append(f"Swap PSS: {kb(last.total_swap_pss_kb)}")
    findings = _findings(result)
    if findings:
        lines.append("Findings:")
        lines.extend(f"- {item}" for item in findings)
    lines.append(f"Report: {result.get('report_dir', '')}")
    return "\n".join(lines)


def build_report_summary(result: Mapping[str, Any], title: str) -> dict:
    metrics = []
    startup = result.get("startup")
    frames = result.get("frames")
    samples = list(result.get("samples") or [])
    cpu_samples = list(result.get("cpu_samples") or [])
    if startup:
        metrics.append({"label": "Startup", "value": _ms(startup.total_time_ms)})
        metrics.append({"label": "Displayed", "value": _ms(startup.displayed_ms)})
    if frames:
        metrics.append({"label": "FPS", "value": _compact_value(frames.estimated_fps)})
        metrics.append({"label": "Jank", "value": _percent(frames.jank_rate)})
        metrics.append({"label": "Stutter", "value": _percent(_stutter_rate(frames))})
        metrics.append({"label": "P95", "value": _ms(frames.p95_ms)})
    if cpu_samples:
        last_cpu = cpu_samples[-1]
        metrics.append({"label": "CPU", "value": _percent_value(last_cpu.process_percent)})
        metrics.append({"label": "User", "value": _percent_value(last_cpu.process_user_percent)})
        metrics.append({"label": "System", "value": _percent_value(last_cpu.process_system_percent)})
    if samples:
        last = samples[-1]
        metrics.append({"label": "PSS", "value": kb(last.total_pss_kb)})
        metrics.append({"label": "Native", "value": kb(last.native_heap_kb)})
        metrics.append({"label": "Graphics", "value": kb(last.graphics_kb)})
        metrics.append({"label": "Swap", "value": kb(last.total_swap_pss_kb)})
    return {
        "title": title,
        "status": result.get("status", "unknown"),
        "metrics": metrics,
        "findings": _findings(result),
        "reportDir": result.get("report_dir", ""),
    }


def kb(value: int | None) -> str:
    return "--" if value is None else f"{value:,} KB"


def _findings(result: Mapping[str, Any]) -> list[str]:
    values = result.get("findings") or []
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        return [str(item) for item in values]
    return [str(values)]


def _ms(value: float | int | None) -> str:
    if value is None:
        return "--"
    if float(value).is_integer():
        return f"{int(value)} ms"
    return f"{value:.1f} ms"


def _percent(value: float | None) -> str:
    return "--" if value is None else f"{value:.2%}"


def _stutter_rate(frames: Any) -> float | None:
    frozen_rate = frames.frozen_frame_rate
    if frozen_rate is not None and frozen_rate > 0:
        return frozen_rate
    slow_rate = frames.slow_frame_rate
    if slow_rate is not None:
        return slow_rate
    return frozen_rate


def _percent_value(value: float | int | None) -> str:
    return "--" if value is None else f"{float(value):.1f}%"


def _compact_value(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"
