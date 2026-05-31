"""Small helpers for slow-path performance tracing."""

from time import perf_counter
from typing import Any


PERF_KEY = "_perf"
PAYLOAD_KEY = "_perf_payload"
DEFAULT_SLOW_THRESHOLD_MS = 300.0


def elapsed_ms(start: float, end: float | None = None) -> float:
    """Return elapsed milliseconds from monotonic timestamps."""
    return max(0.0, ((perf_counter() if end is None else end) - start) * 1000.0)


def build_async_perf(
    method_name: str,
    queued_at: float,
    started_at: float,
    finished_at: float,
) -> dict[str, float | str]:
    """Build timing data for one async model task."""
    return {
        "method": method_name,
        "queued_at": queued_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "queue_ms": elapsed_ms(queued_at, started_at),
        "model_ms": elapsed_ms(started_at, finished_at),
    }


def attach_perf(result: Any, perf: dict[str, float | str]) -> Any:
    """Attach performance data while preserving payload after split_perf()."""
    if not isinstance(result, dict):
        return {PAYLOAD_KEY: result, PERF_KEY: perf}
    enriched = dict(result)
    enriched[PERF_KEY] = perf
    return enriched


def split_perf(result: Any) -> tuple[Any, dict[str, float | str] | None]:
    """Remove internal performance data before business handlers see the result."""
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
    """Combine worker queue/model timings with controller-side UI handling time."""
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
    """Only log when at least one stage or the whole operation crosses threshold."""
    threshold = max(0.0, threshold_ms)
    return any(value >= threshold for value in summary.values())


def format_perf(op_type: str, summary: dict[str, float]) -> str:
    """Format a compact single-line performance trace."""
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
