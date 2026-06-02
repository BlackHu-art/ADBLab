from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot

from gui.styles import BaseStyles

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - depends on optional Qt package availability.
    QWebChannel = None
    QWebEngineView = None


def is_web_timeline_available() -> bool:
    """Return whether the WebEngine timeline can be used in the current process."""

    if QWebEngineView is None or QWebChannel is None:
        return False
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        return False
    if getattr(sys, "frozen", False) and os.environ.get("ADBLAB_ENABLE_WEB_DASHBOARD") != "1":
        return False
    return all(path.exists() for path in DASHBOARD_ASSET_PATHS)


def build_timeline_payload(
    points: list[dict],
    markers: list[dict],
    lanes: list[dict],
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
        "points": points,
        "markers": markers,
        "lanes": lanes,
        "events": events or [],
        "report": report,
        "reportSummary": report_summary or {},
        "state": state,
        "currentPackage": current_package,
        "packageName": package_name,
        "activity": activity,
        "controls": controls or {},
        "theme": theme,
        "palette": palette or {},
        "font": font or {},
        "deviceInfo": device_info or [],
        "metricSummaries": metric_summaries or [],
        "metricDetails": metric_details or [],
        "axisPolicy": axis_policy or {},
    }


def build_web_palette() -> dict:
    """Expose the active Qt palette to the embedded dashboard as CSS variables."""

    return {
        "background": BaseStyles.color("WINDOW_BG"),
        "surface": BaseStyles.color("PANEL_BG"),
        "surfaceSoft": BaseStyles.color("BUTTON_BG"),
        "field": BaseStyles.color("INPUT_BG"),
        "button": BaseStyles.color("BUTTON_BG"),
        "buttonHover": BaseStyles.color("BUTTON_HOVER"),
        "disabledBackground": BaseStyles.color("INPUT_BG"),
        "disabledText": BaseStyles.color("TEXT_DISABLED"),
        "border": BaseStyles.color("BORDER_COLOR"),
        "borderStrong": BaseStyles.color("BORDER_COLOR"),
        "text": BaseStyles.color("TEXT_PRIMARY"),
        "title": BaseStyles.color("TITLE_COLOR"),
        "muted": BaseStyles.color("TEXT_SECONDARY"),
        "subtle": BaseStyles.color("LOG_TEXT_COLOR"),
        "accent": BaseStyles.color("BUTTON_ACCENT"),
        "accentContrast": "#ffffff",
        "info": BaseStyles.color("LOG_INFO"),
        "success": BaseStyles.color("LOG_SUCCESS"),
        "warning": BaseStyles.color("LOG_WARNING"),
        "danger": BaseStyles.color("LOG_ERROR"),
    }


def build_web_font() -> dict:
    """Expose the active global UI font settings to the embedded dashboard."""

    return {
        "family": BaseStyles.DEFAULT_FONT_FAMILY,
        "uiSize": BaseStyles.DEFAULT_FONT_SIZE,
        "labelSize": max(8, BaseStyles.DEFAULT_FONT_SIZE - 1),
        "headerSize": BaseStyles.DEFAULT_FONT_SIZE,
    }


class WebDashboardBridge(QObject):
    action_requested = Signal(str, dict)

    @Slot(str, str)
    def requestAction(self, action: str, payload: str = "{}"):
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            data = {}
        self.action_requested.emit(action, data)


class WebPerformanceTimelineChart(QWebEngineView if QWebEngineView is not None else object):
    """Canvas-based timeline surface used when QtWebEngine is available."""

    uses_embedded_controls = True

    def __init__(self, lanes: list[dict], parent=None):
        if QWebEngineView is None or QWebChannel is None:
            raise RuntimeError("QtWebEngine/QtWebChannel is not available")
        super().__init__(parent)
        self._lanes = lanes
        self._points: list[dict] = []
        self._markers: list[dict] = []
        self._events: list[str] = []
        self._report = ""
        self._report_summary: dict = {}
        self._state = ""
        self._current_package = ""
        self._package_name = ""
        self._activity = ""
        self._controls: dict = {}
        self._theme = ""
        self._palette: dict = {}
        self._font: dict = {}
        self._device_info: list[dict] = []
        self._metric_summaries: list[dict] = []
        self._metric_details: list[dict] = []
        self._axis_policy: dict = {}
        self._max_points = 3600
        self._ready = False
        self._pending_payload: dict | None = None
        self._render_queued = False
        self.bridge = WebDashboardBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("performanceBridge", self.bridge)
        self.page().setWebChannel(self._channel)
        self.setMinimumHeight(360)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.loadFinished.connect(self._on_load_finished)
        self.load(QUrl.fromLocalFile(str(DASHBOARD_HTML_PATH)))

    @property
    def max_points(self) -> int:
        return self._max_points

    def set_points(self, points: list[dict], markers: list[dict] | None = None):
        self._points = points[-self._max_points:]
        self._markers = markers or []
        self._schedule_render_current_payload()

    def set_context(
        self,
        *,
        events: list[str] | None = None,
        report: str | None = None,
        report_summary: dict | None = None,
        state: str | None = None,
        current_package: str | None = None,
        package_name: str | None = None,
        activity: str | None = None,
        controls: dict | None = None,
        theme: str | None = None,
        palette: dict | None = None,
        font: dict | None = None,
        device_info: list[dict] | None = None,
        metric_summaries: list[dict] | None = None,
        metric_details: list[dict] | None = None,
        axis_policy: dict | None = None,
    ):
        if events is not None:
            self._events = events[-160:]
        if report is not None:
            self._report = report
        if report_summary is not None:
            self._report_summary = report_summary
        if state is not None:
            self._state = state
        if current_package is not None:
            self._current_package = current_package
        if package_name is not None:
            self._package_name = package_name
        if activity is not None:
            self._activity = activity
        if controls is not None:
            self._controls = controls
        if theme is not None:
            self._theme = theme
        if palette is not None:
            self._palette = palette
        if font is not None:
            self._font = font
        if device_info is not None:
            self._device_info = device_info
        if metric_summaries is not None:
            self._metric_summaries = metric_summaries
        if metric_details is not None:
            self._metric_details = metric_details
        if axis_policy is not None:
            self._axis_policy = axis_policy
        self._schedule_render_current_payload()

    def set_lane_enabled(self, metric: str, enabled: bool):
        for lane in self._lanes:
            if lane["metric"] == metric:
                lane["enabled"] = enabled
                break
        self._schedule_render_current_payload()

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        if ok and self._pending_payload is not None:
            payload = self._pending_payload
            self._pending_payload = None
            self._render_payload(payload)

    def _render_payload(self, payload: dict):
        if not self._ready:
            self._pending_payload = payload
            return
        script = f"window.renderPerformanceTimeline({json.dumps(payload, ensure_ascii=False)});"
        self.page().runJavaScript(script)

    def _schedule_render_current_payload(self):
        if self._render_queued:
            return
        self._render_queued = True
        QTimer.singleShot(0, self._flush_render_current_payload)

    def _flush_render_current_payload(self):
        self._render_queued = False
        self._render_current_payload()

    def _render_current_payload(self):
        payload = build_timeline_payload(
            self._points,
            self._markers,
            self._lanes,
            events=self._events,
            report=self._report,
            report_summary=self._report_summary,
            state=self._state,
            current_package=self._current_package,
            package_name=self._package_name,
            activity=self._activity,
            controls=self._controls,
            theme=self._theme,
            palette=self._palette,
            font=self._font,
            device_info=self._device_info,
            metric_summaries=self._metric_summaries,
            metric_details=self._metric_details,
            axis_policy=self._axis_policy,
        )
        self._render_payload(payload)

_ASSET_DIR = Path(__file__).with_name("assets")
DASHBOARD_HTML_PATH = _ASSET_DIR / "index.html"
DASHBOARD_CSS_PATH = _ASSET_DIR / "style.css"
DASHBOARD_JS_PATH = _ASSET_DIR / "app.js"
DASHBOARD_ASSET_PATHS = (DASHBOARD_HTML_PATH, DASHBOARD_CSS_PATH, DASHBOARD_JS_PATH)


def load_dashboard_asset(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_dashboard_html() -> str:
    return load_dashboard_asset(DASHBOARD_HTML_PATH)


def load_dashboard_css() -> str:
    return load_dashboard_asset(DASHBOARD_CSS_PATH)


def load_dashboard_js() -> str:
    return load_dashboard_asset(DASHBOARD_JS_PATH)
