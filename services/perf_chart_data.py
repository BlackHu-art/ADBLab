"""MobilePerf 静态结果 CSV 解析（纯 Python、无 Qt 依赖）。

兼容内核各 monitor 的真实 CSV 格式（列名/时间戳格式/采样节拍差异见 ADR 基线矩阵）：
- cpuinfo.csv：``datetime, device_cpu_rate%, user%, system%, idle%`` + 每包列
- meminfo.csv：``datatime, total_ram(MB), free_ram(MB)`` + 每包列（拼写 datatime）
- fps.csv：新格式 ``datetime, activity window, fps, jank`` 或旧格式 ``datetime, fps``
- traffic.csv：``datetime, device_total(KB), device_receive(KB), device_transport(KB)``

单个文件解析失败不抛出：返回空序列并记录原因，保证图表视图整体可用。
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

# 各指标的标准列名（存在即解析，缺失跳过）。
_DEVICE_CPU_KEYS = ("device_cpu_rate%", "user%", "system%", "idle%")
_MEM_TOTAL_KEY = "total_ram(MB)"
_MEM_FREE_KEY = "free_ram(MB)"
_FPS_KEY = "fps"
_JANK_KEY = "jank"
_TRAFFIC_TOTAL_KEY = "device_total(KB)"
_TRAFFIC_RX_KEY = "device_receive(KB)"
_TRAFFIC_TX_KEY = "device_transport(KB)"


@dataclass
class MetricSeries:
    """单条指标序列：样本时间（相对秒）与数值。"""

    name: str
    values: list[tuple[float, float]] = field(default_factory=list)
    error: str = ""

    def is_empty(self) -> bool:
        return not self.values


def _parse_float(text: str) -> float | None:
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


def _load_series(
    path: str,
    column: str,
    *,
    time_column: str | None = None,
    has_header: bool = True,
) -> MetricSeries:
    """读取单列 CSV 为 (相对秒, 值) 序列；坏行跳过。"""

    name = Path(path).stem
    series = MetricSeries(name=name)
    if not os.path.exists(path):
        series.error = "file missing"
        return series
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
    except OSError as exc:
        series.error = str(exc)
        return series
    if not rows:
        series.error = "empty file"
        return series
    header = [cell.strip() for cell in rows[0]]
    if column not in header:
        if has_header:
            series.error = f"column {column!r} not found"
            return series
        # 无表头兼容：直接按整列解析（仅支持首列为数值的退化场景）。
        for row in rows:
            value = _parse_float(row[0]) if row else None
            if value is not None:
                series.values.append((float(len(series.values)), value))
        return series
    column_index = header.index(column)
    time_index = header.index(time_column) if time_column and time_column in header else None
    base_time: float | None = None
    for row in rows[1:]:
        if column_index >= len(row):
            continue
        value = _parse_float(row[column_index])
        if value is None:
            continue
        if time_index is not None and time_index < len(row):
            compact = row[time_index].replace("-", "").replace(":", "").replace(" ", "")
            parsed_time = _parse_float(compact)
            timestamp = parsed_time if parsed_time is not None else float(len(series.values))
            if base_time is None:
                base_time = timestamp
            series.values.append((timestamp - base_time, value))
        else:
            series.values.append((float(len(series.values)), value))
    if not series.values:
        series.error = "no valid samples"
    return series


def parse_cpu_series(result_dir: str) -> dict[str, MetricSeries]:
    """解析 cpuinfo.csv 的整机 CPU 率序列。"""

    cpu = _load_series(os.path.join(result_dir, "cpuinfo.csv"), "device_cpu_rate%")
    return {"cpu": cpu}


def parse_memory_series(result_dir: str) -> dict[str, MetricSeries]:
    """解析 meminfo.csv 的整机内存序列（total/free）。"""

    total = _load_series(os.path.join(result_dir, "meminfo.csv"), _MEM_TOTAL_KEY)
    free = _load_series(os.path.join(result_dir, "meminfo.csv"), _MEM_FREE_KEY)
    return {"mem_total": total, "mem_free": free}


def parse_fps_series(result_dir: str) -> dict[str, MetricSeries]:
    """解析 fps.csv（兼容新旧列布局）。"""

    fps = _load_series(os.path.join(result_dir, "fps.csv"), _FPS_KEY)
    jank = _load_series(os.path.join(result_dir, "fps.csv"), _JANK_KEY)
    return {"fps": fps, "jank": jank}


def parse_traffic_series(result_dir: str) -> dict[str, MetricSeries]:
    """解析 traffic.csv 的整机流量序列。"""

    total = _load_series(os.path.join(result_dir, "traffic.csv"), _TRAFFIC_TOTAL_KEY)
    rx = _load_series(os.path.join(result_dir, "traffic.csv"), _TRAFFIC_RX_KEY)
    tx = _load_series(os.path.join(result_dir, "traffic.csv"), _TRAFFIC_TX_KEY)
    return {"traffic_total": total, "traffic_rx": rx, "traffic_tx": tx}


def load_result_metrics(result_dir: str) -> dict[str, MetricSeries]:
    """读取结果目录全部可用指标；目录不存在返回空字典。"""

    if not result_dir or not os.path.isdir(result_dir):
        return {}
    metrics: dict[str, MetricSeries] = {}
    for parser in (parse_cpu_series, parse_memory_series, parse_fps_series, parse_traffic_series):
        try:
            metrics.update(parser(result_dir))
        except Exception:  # 单文件异常不影响整体
            continue
    return {name: series for name, series in metrics.items() if not series.is_empty()}


__all__ = [
    "MetricSeries",
    "load_result_metrics",
    "parse_cpu_series",
    "parse_fps_series",
    "parse_memory_series",
    "parse_traffic_series",
]
