"""MobilePerf 静态结果图表视图（PySide6.QtCharts，D1）。

契约：``set_series({名称: [(x, y), ...]})`` 全量替换曲线；重复加载不累积旧序列；
主题切换经 ``_sync_theme_state()`` 重刷配色；仅 GUI 主线程使用。
"""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.styles import BaseStyles, FontRole
from gui.styles.tokens import RAW_PALETTE

# 单序列点数上限：超出按步长抽稀，避免万点级曲线卡顿（评审要求 decimation）。
MAX_POINTS_PER_SERIES = 2000


def _decimate(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    if len(points) <= limit:
        return points
    step = (len(points) + limit - 1) // limit
    return points[::step]


class PerfChartView(QWidget):
    """QtCharts 折线图：CPU/内存/FPS/流量多曲线 + 图例 + 空态。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("perfChartView")
        self._chart = QChart()
        self._chart.legend().setVisible(True)
        self._chart_view = QChartView(self._chart, self)
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._chart_view)
        self._series_names: list[str] = []
        self._sync_theme_state()

    def set_series(self, metrics: dict[str, list[tuple[float, float]]]) -> None:
        """全量替换曲线：先移除旧序列再按 metrics 添加（重复加载不累积）。"""

        self._chart.removeAllSeries()
        axes = self._chart.axes()
        for axis in axes:
            self._chart.removeAxis(axis)
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
        axis_x = QValueAxis(self._chart)
        axis_y = QValueAxis(self._chart)
        axis_x.setLabelFormat("%.0f")
        axis_y.setLabelFormat("%.1f")
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for series in self._chart.series():
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)
        axis_x.applyNiceNumbers()
        axis_y.applyNiceNumbers()

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
            axis.setLabelsColor(BaseStyles.color("TEXT_SECONDARY"))
            axis.setLabelsFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
            axis.setLinePenColor(BaseStyles.color("BORDER_COLOR"))
            axis.setGridLineColor(BaseStyles.color("BORDER_COLOR"))
        self._chart.setBackgroundVisible(False)
        self._chart_view.setStyleSheet(
            f"QChartView {{ background: {window}; color: {text}; border: none; }}"
        )


__all__ = ["PerfChartView"]
