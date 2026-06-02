"""Optional WebEngine performance dashboard widgets."""

from .dashboard import (
    WebPerformanceTimelineChart,
    build_timeline_payload,
    build_web_font,
    build_web_palette,
    is_web_timeline_available,
    load_dashboard_css,
    load_dashboard_html,
    load_dashboard_js,
)

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
