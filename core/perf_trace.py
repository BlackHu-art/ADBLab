"""提供慢路径性能追踪所需的轻量辅助函数。"""

from time import perf_counter
from typing import Any

PERF_KEY = "_perf"
PAYLOAD_KEY = "_perf_payload"
DEFAULT_SLOW_THRESHOLD_MS = 300.0


def elapsed_ms(start: float, end: float | None = None) -> float:
    """根据单调时钟时间戳计算非负毫秒耗时。"""
    return max(0.0, ((perf_counter() if end is None else end) - start) * 1000.0)


def build_async_perf(
    method_name: str,
    queued_at: float,
    started_at: float,
    finished_at: float,
) -> dict[str, float | str]:
    """构建单个异步模型任务的阶段耗时数据。"""
    return {
        "method": method_name,
        "queued_at": queued_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "queue_ms": elapsed_ms(queued_at, started_at),
        "model_ms": elapsed_ms(started_at, finished_at),
    }


def attach_perf(result: Any, perf: dict[str, float | str]) -> Any:
    """附加性能数据，并保证 split_perf() 后仍可恢复原始载荷。"""
    if not isinstance(result, dict):
        return {PAYLOAD_KEY: result, PERF_KEY: perf}
    enriched = dict(result)
    enriched[PERF_KEY] = perf
    return enriched


def split_perf(result: Any) -> tuple[Any, dict[str, float | str] | None]:
    """在业务处理器消费结果前剥离内部性能数据。"""
    if not isinstance(result, dict) or PERF_KEY not in result:
        return result, None
    clean = dict(result)
    perf = clean.pop(PERF_KEY)
    if PAYLOAD_KEY in clean:
        payload = clean.pop(PAYLOAD_KEY)
        return payload, perf if isinstance(perf, dict) else None
    return clean, perf if isinstance(perf, dict) else None


def summarize_perf(
    perf: dict[str, float | str] | None,
    ui_started_at: float,
    ui_finished_at: float,
) -> dict[str, float]:
    """合并工作线程排队、模型执行和控制器界面处理耗时。"""
    ui_ms = elapsed_ms(ui_started_at, ui_finished_at)
    if not perf:
        return {"ui_ms": ui_ms, "total_ms": ui_ms}

    queued_at = _float(perf.get("queued_at"), ui_started_at)
    finished_at = _float(perf.get("finished_at"), ui_started_at)
    return {
        "queue_ms": _float(perf.get("queue_ms"), 0.0),
        "model_ms": _float(perf.get("model_ms"), 0.0),
        "signal_ms": elapsed_ms(finished_at, ui_started_at),
        "ui_ms": ui_ms,
        "total_ms": elapsed_ms(queued_at, ui_finished_at),
    }


def should_log_perf(summary: dict[str, float], threshold_ms: float) -> bool:
    """仅在任一阶段或总耗时达到阈值时记录性能日志。"""
    threshold = max(0.0, threshold_ms)
    return any(value >= threshold for value in summary.values())


def format_perf(op_type: str, summary: dict[str, float]) -> str:
    """将性能追踪数据格式化为紧凑的单行文本。"""
    ordered_keys = ("total_ms", "queue_ms", "model_ms", "signal_ms", "ui_ms")
    parts = [f"[PERF] {op_type}"]
    for key in ordered_keys:
        if key in summary:
            label = key.removesuffix("_ms")
            parts.append(f"{label}={summary[key]:.1f}ms")
    return " ".join(parts)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
