"""MobilePerf 静态结果图表视图（PySide6.QtCharts，D1）。

契约：``set_series({名称: [(x, y), ...]})`` 全量替换曲线；重复加载不累积旧序列；
主题切换经 ``_sync_theme_state()`` 重刷配色；仅 GUI 主线程使用。
"""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.tokens import RAW_PALETTE
from services.perf_chart_data import METRIC_UNITS, reduce_extrema

# 单序列点数上限：超出按峰谷抽稀，避免万点级曲线卡顿并保留异常尖峰。
MAX_POINTS_PER_SERIES = 2000


def _decimate(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    return reduce_extrema(points, limit)


class PerfChartView(QWidget):
    """QtCharts 折线图：CPU/内存/FPS/流量多曲线 + 图例 + 空态。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("perfChartView")
        self._chart = QChart()
        self._chart.legend().setVisible(True)
        self._chart_view = QChartView(self._chart, self)
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._chart_scroll = QScrollArea(self)
        self._chart_scroll.setWidgetResizable(True)
        self._chart_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._chart_scroll.setWidget(self._chart_view)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._chart_scroll)
        self._series_names: list[str] = []
        self._sync_theme_state()

    def set_series(self, metrics: dict[str, list[tuple[float, float]]]) -> None:
        """全量替换曲线：先移除旧序列再按 metrics 添加（重复加载不累积）。"""

        self._chart.removeAllSeries()
        axes = self._chart.axes()
        for axis in axes:
            self._chart.removeAxis(axis)
            axis.deleteLater()
        self._series_names = []
        palette = RAW_PALETTE["CHART_SERIES"]
        for index, (name, points) in enumerate(metrics.items()):
            if not points:
                continue
            series = QLineSeries(self._chart)
            series.setName(name)
            for x_value, y_value in _decimate(points, MAX_POINTS_PER_SERIES):
                series.append(float(x_value), float(y_value))
            series.setColor(palette[index % len(palette)])
            self._chart.addSeries(series)
            self._series_names.append(name)
        if self._series_names:
            self._attach_axes()
        self._sync_theme_state()

    def _attach_axes(self) -> None:
        """统一时间范围，按物理单位分轴并显式计算范围，防止后加曲线被裁掉。"""
        axis_x = QValueAxis(self._chart)
        axis_x.setTitleText(tr("Elapsed time (s)"))
        axis_x.setLabelFormat("%.0f")
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        unit_axes = {}
        time_values = []
        unit_values = {}
        for series in self._chart.series():
            if not isinstance(series, QLineSeries):
                continue
            unit = METRIC_UNITS.get(series.name(), series.name())
            if unit not in unit_axes:
                axis = QValueAxis(self._chart)
                axis.setTitleText(tr("Count") if unit == "count" else unit)
                axis.setLabelFormat("%.1f")
                side = Qt.AlignmentFlag.AlignLeft if not unit_axes else Qt.AlignmentFlag.AlignRight
                self._chart.addAxis(axis, side)
                unit_axes[unit] = axis
                unit_values[unit] = []
            series.attachAxis(axis_x)
            series.attachAxis(unit_axes[unit])
            time_values.extend(point.x() for point in series.points())
            unit_values[unit].extend(point.y() for point in series.points())
        axis_x.setRange(min(time_values), max(time_values) if len(set(time_values)) > 1
                        else min(time_values) + 1)
        axis_x.applyNiceNumbers()
        for unit, values in unit_values.items():
            low, high = min(values), max(values)
            margin = max(abs(low) * 0.05, 1) if low == high else (high - low) * 0.05
            unit_axes[unit].setRange(low - margin, high + margin)
            unit_axes[unit].applyNiceNumbers()

    def clear(self) -> None:
        self.set_series({})

    def has_data(self) -> bool:
        return bool(self._series_names)

    def _sync_theme_state(self) -> None:
        """同步背景、图例与坐标轴，确保新建轴和深色主题使用相同文字语义。"""

        window = BaseStyles.color("WINDOW_BG")
        text = BaseStyles.color("TEXT_PRIMARY")
        self._chart.setBackgroundBrush(self._chart_view.palette().brush(self._chart_view.backgroundRole()))
        self._chart.setTitleBrush(Qt.GlobalColor.transparent)
        self._chart.legend().setLabelColor(text)
        self._chart.legend().setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        for axis in self._chart.axes():
            axis.setTitleBrush(QColor(BaseStyles.color("TEXT_SECONDARY")))
            axis.setLabelsColor(BaseStyles.color("TEXT_SECONDARY"))
            axis.setLabelsFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
            axis.setLinePenColor(BaseStyles.color("BORDER_COLOR"))
            axis.setGridLineColor(BaseStyles.color("BORDER_COLOR"))
        self._chart.setBackgroundVisible(False)
        self._chart_view.setStyleSheet(
            f"QChartView {{ background: {window}; color: {text}; border: none; }}"
        )
        self._update_readable_width()

    def _update_readable_width(self) -> None:
        """按真实字体预留轴和图例宽度，窄宿主通过滚动访问全部指标而不缩小文字。"""
        font = QFontMetricsF(self._chart.legend().font())
        axis_width = 0.0
        for axis in self._chart.axes(Qt.Orientation.Vertical):
            if not isinstance(axis, QValueAxis):
                continue
            labels = QFontMetricsF(axis.labelsFont())
            longest = max(labels.horizontalAdvance(f"{value:.1f}")
                          for value in (axis.min(), axis.max()))
            title = QFontMetricsF(axis.titleFont()).height() if axis.titleText() else 0
            axis_width += longest + title + 32
        legend_width = sum(font.horizontalAdvance(name) + 48 for name in self._series_names)
        width = max(320 + axis_width, legend_width + 64) if self._series_names else 0
        self._chart_view.setMinimumWidth(int(width))


__all__ = ["PerfChartView"]
