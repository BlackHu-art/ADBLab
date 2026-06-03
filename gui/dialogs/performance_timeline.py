from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from gui.styles import BaseStyles


class PerfDogTimelineChart(QWidget):
    """PerfDog-like shared timeline with one horizontal axis and multiple metric lanes."""

    def __init__(self, lanes: list[dict], parent=None):
        super().__init__(parent)
        self._lanes = lanes
        self._points: list[dict] = []
        self._markers: list[dict] = []
        self._max_points = 3600
        self.setMinimumHeight(360)

    @property
    def max_points(self) -> int:
        return self._max_points

    def set_points(self, points: list[dict], markers: list[dict] | None = None):
        self._points = points[-self._max_points:]
        self._markers = markers or []
        self.update()

    def set_lane_enabled(self, metric: str, enabled: bool):
        for lane in self._lanes:
            if lane["metric"] == metric:
                lane["enabled"] = enabled
                break
        self.update()

    def _sample_held_values(self, metric: str) -> list[float | None]:
        values = []
        last_value = None
        for point in self._points:
            value = point.get(metric)
            if value is not None:
                last_value = float(value)
            values.append(last_value)
        return values

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect().adjusted(8, 8, -8, -8))
        bg = QColor(BaseStyles.color("LOG_BACKGROUND"))
        border = QColor(BaseStyles.color("BORDER_COLOR"))
        text = QColor(BaseStyles.color("TEXT_PRIMARY"))
        muted = QColor(BaseStyles.color("TEXT_SECONDARY"))
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, BaseStyles.RADIUS_MD, BaseStyles.RADIUS_MD)

        painter.setPen(text)
        painter.drawText(rect.adjusted(12, 8, -12, -8), Qt.AlignTop | Qt.AlignLeft, "Realtime Timeline")

        enabled_lanes = [lane for lane in self._lanes if lane.get("enabled", True)]
        if not enabled_lanes:
            painter.setPen(muted)
            painter.drawText(rect, Qt.AlignCenter, "No metric selected")
            return

        plot = rect.adjusted(128, 34, -18, -28)
        lane_height = plot.height() / max(1, len(enabled_lanes))
        if not self._points:
            painter.setPen(muted)
            painter.drawText(plot, Qt.AlignCenter, "Waiting for samples")
            self._draw_timeline_axis(painter, plot, 0)
            return

        sample_count = len(self._points)
        for index, lane in enumerate(enabled_lanes):
            lane_rect = QRectF(plot.left(), plot.top() + lane_height * index, plot.width(), lane_height)
            self._draw_lane(painter, lane_rect, lane, sample_count)
        self._draw_markers(painter, plot)
        self._draw_timeline_axis(painter, plot, sample_count)

    def _draw_lane(self, painter: QPainter, lane_rect: QRectF, lane: dict, sample_count: int):
        border = QColor(BaseStyles.color("BORDER_COLOR"))
        text = QColor(BaseStyles.color("TEXT_PRIMARY"))
        muted = QColor(BaseStyles.color("TEXT_SECONDARY"))
        grid = QColor(border)
        grid.setAlpha(85)
        painter.setPen(QPen(grid, 1))
        painter.drawLine(lane_rect.left(), lane_rect.bottom(), lane_rect.right(), lane_rect.bottom())

        series_defs = lane.get("series") or [lane]
        series_values = [
            (series, self._sample_held_values(series["metric"]))
            for series in series_defs
        ]
        primary_values = [
            (series, values)
            for series, values in series_values
            if series.get("axis", "primary") != "overlay"
        ]
        numeric = _numeric_values(primary_values or series_values)
        overlay_axis_max = _axis_max(
            _numeric_values(
                (series, values)
                for series, values in series_values
                if series.get("axis") == "overlay"
            )
        )
        painter.setPen(text)
        label_rect = QRectF(lane_rect.left() - 122, lane_rect.top() + 4, 112, 20)
        painter.drawText(label_rect, Qt.AlignLeft | Qt.AlignVCenter, lane["label"])
        if not numeric:
            painter.setPen(muted)
            painter.drawText(lane_rect, Qt.AlignCenter, "--")
            return

        min_value = min(numeric)
        max_value = max(numeric)
        display_min = min_value
        display_max = max_value
        if min_value == max_value:
            max_value += 1
            min_value = max(0, min_value - 1)

        painter.setPen(muted)
        _draw_lane_value_rows(painter, lane_rect.left() - 122, lane_rect.top() + 32, lane, series_values)
        painter.drawText(
            QRectF(lane_rect.right() - 96, lane_rect.top() + 4, 92, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{_chart_value(display_max)} / {_chart_value(display_min)}",
        )
        mid_y = lane_rect.center().y()
        painter.setPen(QPen(grid, 1))
        painter.drawLine(lane_rect.left(), int(mid_y), lane_rect.right(), int(mid_y))

        lane_plot = lane_rect.adjusted(0, 8, 0, -8)
        for series, values in series_values:
            points = []
            scale_min = min_value
            scale_max = max_value
            if series.get("axis") == "overlay" and overlay_axis_max:
                scale_min = 0
                scale_max = overlay_axis_max
            for index, value in enumerate(values):
                if value is None:
                    points.append(None)
                    continue
                x = lane_plot.left() + lane_plot.width() * index / max(1, sample_count - 1)
                normalized = (float(value) - scale_min) / (scale_max - scale_min)
                y = lane_plot.bottom() - normalized * lane_plot.height()
                points.append(QPointF(x, y))

            color = QColor(series.get("color", lane["color"]))
            painter.setPen(QPen(color, 2))
            last = None
            for point in points:
                if point is None:
                    last = None
                    continue
                if last is not None:
                    painter.drawLine(last, point)
                last = point

    def _draw_timeline_axis(self, painter: QPainter, plot: QRectF, count: int):
        axis = QColor(BaseStyles.color("TEXT_SECONDARY"))
        grid = QColor(BaseStyles.color("BORDER_COLOR"))
        grid.setAlpha(80)
        painter.setPen(QPen(axis, 1))
        painter.drawLine(plot.left(), plot.bottom(), plot.right(), plot.bottom())
        labels = self._axis_labels(count)
        for ratio, label in labels:
            x = plot.left() + plot.width() * ratio
            painter.setPen(QPen(grid, 1))
            painter.drawLine(int(x), plot.top(), int(x), plot.bottom())
            painter.setPen(axis)
            painter.drawText(QRectF(x - 30, plot.bottom() + 5, 60, 18), Qt.AlignCenter, label)

    def _axis_labels(self, count: int) -> tuple[tuple[float, str], tuple[float, str], tuple[float, str]]:
        if len(self._points) >= 2:
            first = self._points[0].get("_ts")
            last = self._points[-1].get("_ts")
            if isinstance(first, (int, float)) and isinstance(last, (int, float)) and last >= first:
                span_seconds = max(0, int((last - first) / 1000))
                return (
                    (0, f"-{span_seconds}s"),
                    (0.5, f"-{span_seconds // 2}s"),
                    (1, "now"),
                )
        return ((0, f"-{max(count - 1, 0)}"), (0.5, "samples"), (1, "now"))

    def _draw_markers(self, painter: QPainter, plot: QRectF):
        if not self._markers or len(self._points) <= 1:
            return
        first = self._points[0].get("_ts")
        last = self._points[-1].get("_ts")
        if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
            return
        span = max(1, last - first)
        color = QColor(BaseStyles.color("LOG_WARNING"))
        painter.setPen(QPen(color, 1))
        for marker in self._markers[-20:]:
            timestamp = marker.get("timestamp_ms")
            if not isinstance(timestamp, (int, float)):
                continue
            ratio = (timestamp - first) / span
            if ratio < 0 or ratio > 1:
                continue
            x = plot.left() + plot.width() * max(0.0, min(1.0, ratio))
            painter.drawLine(int(x), plot.top(), int(x), plot.bottom())
            painter.drawText(QRectF(x + 4, plot.top() + 4, 92, 18), Qt.AlignLeft, marker.get("label", "Mark"))


def _draw_lane_value_rows(
    painter: QPainter,
    x: float,
    y: float,
    lane: dict,
    series_values: list[tuple[dict, list[float | None]]],
) -> None:
    muted = QColor(BaseStyles.color("TEXT_SECONDARY"))
    for series, values in series_values:
        current = next((value for value in reversed(values) if value is not None), None)
        color = QColor(series.get("color", lane.get("color", BaseStyles.color("BUTTON_ACCENT"))))
        painter.fillRect(QRectF(x, y + 4, 7, 7), color)
        painter.setPen(muted)
        painter.drawText(
            QRectF(x + 11, y - 2, 70, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            _series_label(series),
        )
        painter.drawText(
            QRectF(x + 78, y - 2, 42, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            _value_with_unit(current, series.get("unit", lane.get("unit", ""))),
        )
        y += 14


def _numeric_values(series_values) -> list[float]:
    return [
        float(value)
        for _series, values in series_values
        for value in values
        if value is not None
    ]


def _axis_max(values: list[float]) -> float | None:
    if not values:
        return None
    return max(max(values), 1)


def _series_label(series: dict) -> str:
    label = str(series.get("label", series.get("metric", "")))
    return f"{label}*" if series.get("axis") == "overlay" else label


def _value_with_unit(value: float | None, unit: str = "") -> str:
    text = _chart_value(value)
    return f"{text}{unit}" if unit and text != "--" else text


def _chart_value(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"
