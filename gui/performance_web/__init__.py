"""Optional WebEngine performance dashboard widgets."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "WebPerformanceTimelineChart",
    "build_timeline_payload",
    "build_web_font",
    "build_web_palette",
    "is_web_timeline_available",
    "load_dashboard_css",
    "load_dashboard_html",
    "load_dashboard_js",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    dashboard = import_module(".dashboard", __name__)
    value = getattr(dashboard, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
