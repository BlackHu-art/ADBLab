from __future__ import annotations

import csv
import re
from io import StringIO
from statistics import quantiles

from .types import CpuSample, FrameMetrics, MemorySample, StartupMetrics

_INT_RE = re.compile(r"(-?\d+)")
_DISPLAYED_RE = re.compile(r"\bDisplayed\s+\S+:\s+\+?([0-9sm.]+)")
_FULLY_DRAWN_RE = re.compile(r"\bFully drawn\s+\S+:\s+\+?([0-9sm.]+)")


def parse_duration_ms(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    total = 0
    match = re.fullmatch(r"(?:(\d+)s)?(?:(\d+)ms)?", value)
    if match:
        seconds, millis = match.groups()
        if seconds:
            total += int(seconds) * 1000
        if millis:
            total += int(millis)
        return total
    try:
        return int(float(value) * 1000)
    except ValueError:
        return None


def parse_am_start_output(
    output: str,
    *,
    device_id: str = "",
    package_name: str = "",
    activity: str = "",
) -> StartupMetrics:
    metrics = StartupMetrics(device_id=device_id, package_name=package_name, activity=activity)
    for line in output.splitlines():
        key, sep, raw_value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        raw_value = raw_value.strip()
        if key == "ThisTime":
            metrics.this_time_ms = parse_duration_ms(raw_value)
        elif key == "TotalTime":
            metrics.total_time_ms = parse_duration_ms(raw_value)
        elif key == "WaitTime":
            metrics.wait_time_ms = parse_duration_ms(raw_value)
        elif key == "Status":
            metrics.success = raw_value.lower() == "ok"
    if metrics.total_time_ms is not None or metrics.this_time_ms is not None:
        metrics.success = True
    metrics.message = "Startup measured" if metrics.success else output.strip()
    return metrics


def enrich_startup_from_logcat(metrics: StartupMetrics, logcat_output: str) -> StartupMetrics:
    displayed = _DISPLAYED_RE.search(logcat_output)
    fully_drawn = _FULLY_DRAWN_RE.search(logcat_output)
    if displayed:
        metrics.displayed_ms = parse_duration_ms(displayed.group(1))
    if fully_drawn:
        metrics.fully_drawn_ms = parse_duration_ms(fully_drawn.group(1))
    return metrics


def parse_gfxinfo_output(
    output: str,
    *,
    slow_frame_ms: float = 16.67,
    frozen_frame_ms: float = 700.0,
) -> FrameMetrics:
    metrics = FrameMetrics()
    total = _first_int_after(output, r"Total frames rendered:\s*")
    janky = _first_int_after(output, r"Janky frames:\s*")
    metrics.total_frames = total or 0
    metrics.janky_frames = janky or 0
    if metrics.total_frames:
        metrics.jank_rate = metrics.janky_frames / metrics.total_frames

    metrics.p50_ms = _first_float_after(output, r"50th percentile:\s*")
    metrics.p90_ms = _first_float_after(output, r"90th percentile:\s*")
    metrics.p95_ms = _first_float_after(output, r"95th percentile:\s*")
    metrics.p99_ms = _first_float_after(output, r"99th percentile:\s*")
    metrics.missed_vsync = _first_int_after(output, r"Number Missed Vsync:\s*") or 0
    metrics.high_input_latency = _first_int_after(output, r"Number High input latency:\s*") or 0
    metrics.slow_ui_thread = _first_int_after(output, r"Number Slow UI thread:\s*") or 0

    frame_durations = parse_framestats_durations(output)
    if frame_durations:
        metrics.slow_frames = sum(1 for value in frame_durations if value > slow_frame_ms)
        metrics.frozen_frames = sum(1 for value in frame_durations if value > frozen_frame_ms)
        metrics.total_frames = metrics.total_frames or len(frame_durations)
        if not metrics.janky_frames:
            metrics.janky_frames = metrics.slow_frames
            metrics.jank_rate = metrics.slow_frames / len(frame_durations)
        metrics.p50_ms = metrics.p50_ms if metrics.p50_ms is not None else _percentile(frame_durations, 50)
        metrics.p90_ms = metrics.p90_ms if metrics.p90_ms is not None else _percentile(frame_durations, 90)
        metrics.p95_ms = metrics.p95_ms if metrics.p95_ms is not None else _percentile(frame_durations, 95)
        metrics.p99_ms = metrics.p99_ms if metrics.p99_ms is not None else _percentile(frame_durations, 99)
        metrics.avg_frame_time_ms = round(sum(frame_durations) / len(frame_durations), 2)
        metrics.max_frame_time_ms = max(frame_durations)
        metrics.estimated_fps = _estimate_fps(output, len(frame_durations))
    else:
        metrics.slow_frames = metrics.janky_frames
        metrics.frozen_frames = _histogram_frozen_count(output, frozen_frame_ms)
    if metrics.total_frames:
        metrics.slow_frame_rate = metrics.slow_frames / metrics.total_frames
        metrics.frozen_frame_rate = metrics.frozen_frames / metrics.total_frames
    return metrics


def parse_framestats_durations(output: str) -> list[float]:
    rows = _profile_rows(output)
    if not rows:
        return []
    durations: list[float] = []
    for row in rows:
        try:
            intended = int(row.get("IntendedVsync", "0") or "0")
            completed = int(row.get("FrameCompleted", "0") or "0")
        except ValueError:
            continue
        if intended <= 0 or completed <= intended:
            continue
        durations.append((completed - intended) / 1_000_000)
    return durations


def parse_meminfo_output(output: str, *, timestamp_ms: int = 0) -> MemorySample:
    sample = MemorySample(timestamp_ms=timestamp_ms)
    in_app_summary = False
    graphics_fallback_kb = 0
    saw_swap_pss_column = False
    for line in output.splitlines():
        stripped = line.strip()
        if "SwapPss" in stripped:
            saw_swap_pss_column = True
        if stripped == "App Summary":
            in_app_summary = True
            continue
        if in_app_summary and not stripped:
            in_app_summary = False
            continue

        if re.match(r"^TOTAL\s+", stripped) and sample.total_pss_kb is None:
            sample.total_pss_kb = _first_int(stripped)
        if stripped.startswith("TOTAL SWAP PSS:"):
            sample.total_swap_pss_kb = _first_int(stripped)
        elif saw_swap_pss_column and stripped.startswith("TOTAL "):
            values = _all_ints(stripped)
            if values:
                sample.total_swap_pss_kb = values[-1]

        graphics_row = _graphics_row_pss(stripped)
        if graphics_row is not None:
            graphics_fallback_kb += graphics_row

        if in_app_summary:
            if stripped.startswith("Java Heap:"):
                sample.java_heap_kb = _first_int(stripped)
            elif stripped.startswith("Native Heap:"):
                sample.native_heap_kb = _first_int(stripped)
            elif stripped.startswith("Graphics:"):
                sample.graphics_kb = _first_int(stripped)
            elif stripped.startswith("Stack:"):
                sample.stack_kb = _first_int(stripped)
            elif stripped.startswith("Code:"):
                sample.code_kb = _first_int(stripped)
            elif stripped.startswith("Private Other:"):
                sample.private_other_kb = _first_int(stripped)
            elif stripped.startswith("System:"):
                sample.system_kb = _first_int(stripped)
            elif stripped.startswith("TOTAL SWAP PSS:"):
                sample.total_swap_pss_kb = _first_int(stripped)
            elif stripped.startswith("TOTAL:") and sample.total_pss_kb is None:
                sample.total_pss_kb = _first_int(stripped)

        for key, attr in (
            ("Views", "views"),
            ("ViewRootImpl", "view_roots"),
            ("AppContexts", "app_contexts"),
            ("Activities", "activities"),
        ):
            value = _object_value(stripped, key)
            if value is not None:
                setattr(sample, attr, value)
    if sample.graphics_kb is None and graphics_fallback_kb:
        sample.graphics_kb = graphics_fallback_kb
    return sample


def parse_proc_stat_total(output: str) -> int | None:
    first_line = output.splitlines()[0].strip() if output.splitlines() else ""
    if not first_line.startswith("cpu "):
        return None
    values = []
    for part in first_line.split()[1:]:
        try:
            values.append(int(part))
        except ValueError:
            return None
    return sum(values) if values else None


def parse_process_stat_ticks(output: str) -> int | None:
    ticks = parse_process_stat_cpu_ticks(output)
    return None if ticks is None else ticks[0] + ticks[1]


def parse_process_stat_cpu_ticks(output: str) -> tuple[int, int] | None:
    text = output.strip()
    if not text:
        return None
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 1:].strip().split()
    if len(fields) <= 12:
        return None
    try:
        # /proc/<pid>/stat fields after comm start at state, so utime/stime are indexes 11/12.
        return int(fields[11]), int(fields[12])
    except ValueError:
        return None


def parse_process_thread_count(output: str) -> int | None:
    text = output.strip()
    if not text:
        return None
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 1:].strip().split()
    if len(fields) <= 17:
        return None
    try:
        return int(fields[17])
    except ValueError:
        return None


def build_cpu_sample(
    *,
    timestamp_ms: int,
    pid: int | None,
    process_ticks: int | None,
    total_ticks: int | None,
    previous_process_ticks: int | None,
    previous_total_ticks: int | None,
    is_foreground: bool,
    user_ticks: int | None = None,
    system_ticks: int | None = None,
    previous_user_ticks: int | None = None,
    previous_system_ticks: int | None = None,
    thread_count: int | None = None,
) -> CpuSample:
    percent = None
    user_percent = None
    system_percent = None
    if (
        process_ticks is not None
        and total_ticks is not None
        and previous_process_ticks is not None
        and previous_total_ticks is not None
    ):
        process_delta = process_ticks - previous_process_ticks
        total_delta = total_ticks - previous_total_ticks
        if process_delta >= 0 and total_delta > 0:
            percent = round((process_delta / total_delta) * 100, 2)
            if (
                user_ticks is not None
                and system_ticks is not None
                and previous_user_ticks is not None
                and previous_system_ticks is not None
            ):
                user_delta = user_ticks - previous_user_ticks
                system_delta = system_ticks - previous_system_ticks
                if user_delta >= 0 and system_delta >= 0:
                    user_percent = round((user_delta / total_delta) * 100, 2)
                    system_percent = round((system_delta / total_delta) * 100, 2)
    return CpuSample(
        timestamp_ms=timestamp_ms,
        process_percent=percent,
        process_user_percent=user_percent,
        process_system_percent=system_percent,
        is_foreground=is_foreground,
        pid=pid,
        thread_count=thread_count,
    )


def _profile_rows(output: str) -> list[dict[str, str]]:
    lines = output.splitlines()
    header_index = next((i for i, line in enumerate(lines) if line.startswith("Flags,")), -1)
    if header_index < 0:
        return []
    csv_lines = [lines[header_index]]
    for line in lines[header_index + 1:]:
        if not line.strip() or line.startswith("---PROFILEDATA---"):
            break
        if "," not in line:
            break
        csv_lines.append(line)
    try:
        return list(csv.DictReader(StringIO("\n".join(csv_lines))))
    except csv.Error:
        return []


def _estimate_fps(output: str, frame_count: int) -> float | None:
    rows = _profile_rows(output)
    if len(rows) < 2 or frame_count < 2:
        return None
    vsync_times: list[int] = []
    for row in rows:
        try:
            intended = int(row.get("IntendedVsync", "0") or "0")
            completed = int(row.get("FrameCompleted", "0") or "0")
        except ValueError:
            continue
        if intended > 0 and completed > intended:
            vsync_times.append(intended)
    if len(vsync_times) >= 2:
        elapsed_seconds = (vsync_times[-1] - vsync_times[0]) / 1_000_000_000
        if elapsed_seconds > 0:
            return round((len(vsync_times) - 1) / elapsed_seconds, 2)
    try:
        first = int(rows[0].get("IntendedVsync", "0") or "0")
        last = int(rows[-1].get("FrameCompleted", "0") or "0")
    except ValueError:
        return None
    elapsed_seconds = (last - first) / 1_000_000_000
    if elapsed_seconds <= 0:
        return None
    return round(frame_count / elapsed_seconds, 2)


def _first_int_after(output: str, pattern: str) -> int | None:
    match = re.search(pattern + r"(-?\d+)", output)
    return int(match.group(1)) if match else None


def _first_float_after(output: str, pattern: str) -> float | None:
    match = re.search(pattern + r"(-?\d+(?:\.\d+)?)ms", output)
    return float(match.group(1)) if match else None


def _first_int(text: str) -> int | None:
    match = _INT_RE.search(text)
    return int(match.group(1)) if match else None


def _all_ints(text: str) -> list[int]:
    return [int(match) for match in _INT_RE.findall(text)]


def _graphics_row_pss(text: str) -> int | None:
    if not re.match(r"^(?:EGL\s+mtrack|GL\s+mtrack|Gfx\s+dev)\b", text):
        return None
    return _first_int(text)


def _object_value(line: str, key: str) -> int | None:
    match = re.search(rf"\b{re.escape(key)}:\s*(-?\d+)", line)
    return int(match.group(1)) if match else None


def _histogram_frozen_count(output: str, threshold_ms: float) -> int:
    match = re.search(r"HISTOGRAM:\s*(.+)", output)
    if not match:
        return 0
    count = 0
    for bucket in match.group(1).split():
        time_part, sep, value_part = bucket.partition("=")
        if not sep:
            continue
        try:
            if float(time_part.removesuffix("ms")) >= threshold_ms:
                count += int(value_part)
        except ValueError:
            continue
    return count


def _percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    if percent == 50:
        ordered = sorted(values)
        return ordered[len(ordered) // 2]
    qs = quantiles(values, n=100, method="inclusive")
    return qs[min(max(percent, 1), 99) - 1]
