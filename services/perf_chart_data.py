"""按文件单次流式读取性能指标，以共同时间起点和有界峰谷摘要交付图表。"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAX_METRIC_POINTS = 2000
METRIC_UNITS = {
    "cpu": "%", "mem_total": "MB", "mem_free": "MB", "fps": "FPS",
    "jank": "count", "traffic_total": "KB", "traffic_rx": "KB", "traffic_tx": "KB",
}
_SOURCES = {
    "cpuinfo.csv": {"cpu": "device_cpu_rate%"},
    "meminfo.csv": {"mem_total": "total_ram(MB)", "mem_free": "free_ram(MB)"},
    "fps.csv": {"fps": "fps", "jank": "jank"},
    "traffic.csv": {"traffic_total": "device_total(KB)", "traffic_rx": "device_receive(KB)",
                    "traffic_tx": "device_transport(KB)"},
}


@dataclass
class MetricSeries:
    """单条指标的共同相对秒时间和值；未知时间不会假装成采样秒数。"""

    name: str
    values: list[tuple[float, float]] = field(default_factory=list)
    error: str = ""

    def is_empty(self) -> bool:
        return not self.values


def reduce_extrema(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    """有界分桶保留首末点及每桶峰谷，保持原时间顺序。"""
    if len(points) <= limit:
        return points
    if limit < 4:
        return points[:1] + points[-1:] if limit >= 2 else points[:limit]
    buckets = max(1, (limit - 2) // 2)
    width = math.ceil((len(points) - 2) / buckets)
    result = [points[0]]
    for start in range(1, len(points) - 1, width):
        end = min(len(points) - 1, start + width)
        low = min(range(start, end), key=lambda i: points[i][1])
        high = max(range(start, end), key=lambda i: points[i][1])
        result.extend(points[i] for i in sorted({low, high}))
    result.append(points[-1])
    return result


def _number(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: str) -> float | None:
    text = value.strip()
    numeric = _number(text)
    if numeric is not None:
        return numeric
    # 旧版 MobilePerf 时间部分使用横线，日期与时区仍按日期时间解析。
    if len(text) >= 19 and text[13] == "-" and text[16] == "-":
        text = text[:11] + text[11:19].replace("-", ":") + text[19:]
    try:
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except (ValueError, OverflowError):
        return None


def _read_file(path: Path, columns: dict[str, str], cancelled: Callable[[], bool]):
    """每个 CSV 只遍历一次，多列同时提取；缓存从不超过每序列两倍绘制预算。"""
    result = {name: MetricSeries(name) for name in columns}
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as stream:
            reader = csv.reader(stream)
            header = [cell.strip() for cell in next(reader, [])]
            time_index = next((header.index(key) for key in ("datetime", "datatime")
                               if key in header), None)
            indices = {}
            for name, column in columns.items():
                if column in header:
                    indices[name] = header.index(column)
                else:
                    result[name].error = f"column {column!r} not found"
            if time_index is None:
                for series in result.values():
                    series.error = series.error or "time column missing"
                return result
            for row in reader:
                if cancelled():
                    return {}
                if time_index >= len(row):
                    continue
                stamp = _timestamp(row[time_index])
                if stamp is None:
                    continue
                for name, index in indices.items():
                    value = _number(row[index]) if index < len(row) else None
                    if value is None:
                        continue
                    values = result[name].values
                    values.append((stamp, value))
                    if len(values) >= MAX_METRIC_POINTS * 2:
                        result[name].values = reduce_extrema(values, MAX_METRIC_POINTS)
    except FileNotFoundError:
        for series in result.values():
            series.error = "file missing"
    except (OSError, csv.Error) as exc:
        for series in result.values():
            series.error = type(exc).__name__
    for series in result.values():
        if not series.values:
            series.error = series.error or "no valid samples"
        series.values = reduce_extrema(series.values, MAX_METRIC_POINTS)
    return result


def _relative(metrics: dict[str, MetricSeries]) -> dict[str, MetricSeries]:
    origin = min((x for series in metrics.values() for x, _ in series.values), default=0)
    for series in metrics.values():
        series.values = [(x - origin, y) for x, y in series.values]
    return metrics


def _parse_source(result_dir: str, filename: str) -> dict[str, MetricSeries]:
    return _relative(_read_file(Path(result_dir) / filename, _SOURCES[filename], lambda: False))


def parse_cpu_series(result_dir: str) -> dict[str, MetricSeries]:
    """读取整机 CPU，独立调用时以该文件首个有效点为起点。"""
    return _parse_source(result_dir, "cpuinfo.csv")


def parse_memory_series(result_dir: str) -> dict[str, MetricSeries]:
    """单次读取内存总量与可用量。"""
    return _parse_source(result_dir, "meminfo.csv")


def parse_fps_series(result_dir: str) -> dict[str, MetricSeries]:
    """单次读取 FPS 与可选 jank 列。"""
    return _parse_source(result_dir, "fps.csv")


def parse_traffic_series(result_dir: str) -> dict[str, MetricSeries]:
    """单次读取流量总量、接收与发送列。"""
    return _parse_source(result_dir, "traffic.csv")


def load_result_metrics(
    result_dir: str, *, cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, MetricSeries]:
    """读取本次结果，所有指标使用共同起点；取消后不交付部分曲线。"""
    if not result_dir:
        return {}
    metrics = {}
    for filename, columns in _SOURCES.items():
        if cancelled():
            return {}
        metrics.update(_read_file(Path(result_dir) / filename, columns, cancelled))
    if cancelled():
        return {}
    return _relative({name: series for name, series in metrics.items() if not series.is_empty()})
