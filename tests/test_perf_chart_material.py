"""图表的合成背景跟随实际宿主，同时保留曲线与坐标轴。"""

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.styles import BaseStyles
from gui.widgets.perf_chart_view import PerfChartView
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class _PaintedHost(QWidget):
    def __init__(self):
        super().__init__()
        self.backdrop = QColor("#6388ad")
        QVBoxLayout(self)
        self.resize(900, 500)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.backdrop)


class _MaterialHost(_PaintedHost):
    def __init__(self, mica):
        super().__init__()
        self.mica = mica

    def isMicaEffectEnabled(self):
        return self.mica

    def setMicaEffectEnabled(self, enabled):
        self.mica = enabled
        self.update()


def _background(host, view):
    image = host.grab().toImage()
    point = view._chart_view.viewport().mapTo(host, QPoint(12, 12))
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


def _show(host, view, application):
    host.layout().addWidget(view)
    host.show()
    view.show()
    application.processEvents()


def _chart_contents(view):
    return (
        tuple((series.name(), tuple((point.x(), point.y()) for point in series.points()))
              for series in view._chart.series()),
        tuple((axis.titleText(), axis.min(), axis.max()) for axis in view._chart.axes()),
    )


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_chart_mica_round_trip_composites_every_background_layer(qt_application, theme):
    BaseStyles.switch_theme(theme)
    host = _MaterialHost(True)
    view = PerfChartView(host)
    view.set_series({"cpu": [(0, 25), (5, 75)], "mem_total": [(0, 1000), (5, 1200)]})
    _show(host, view, qt_application)
    contents = _chart_contents(view)
    axes = tuple(view._chart.axes())

    for backdrop in ("#6388ad", "#906742"):
        host.backdrop = QColor(backdrop)
        host.update()
        wait_until(qt_application, lambda: _background(host, view) == host.backdrop)

    for next_theme in ("Dark" if theme == "Light" else "Light", theme):
        BaseStyles.switch_theme(next_theme)
        view._sync_theme_state()
        wait_until(qt_application, lambda: _background(host, view) == host.backdrop)
        host.setMicaEffectEnabled(False)
        expected = QColor(BaseStyles.color("WINDOW_BG"))
        wait_until(qt_application, lambda: _background(host, view) == expected)
        assert view._chart_view.viewport().palette().color(QPalette.ColorRole.Base) == expected
        assert not view._chart_view.viewport().autoFillBackground()
        host.setMicaEffectEnabled(True)
        wait_until(qt_application, lambda: _background(host, view) == host.backdrop)
        assert tuple(view._chart.axes()) == axes
        assert _chart_contents(view) == contents


def test_chart_late_reparenting_and_series_reload_follow_actual_host(qt_application):
    view = PerfChartView()
    hosts = (_MaterialHost(True), _MaterialHost(False), _MaterialHost(True))
    for index, host in enumerate(hosts, start=1):
        view.setParent(host)
        _show(host, view, qt_application)
        points = [(0, index * 10), (5, index * 20)]
        view.set_series({"cpu": points})
        expected = host.backdrop if host.mica else QColor(BaseStyles.color("WINDOW_BG"))
        wait_until(qt_application, lambda: _background(host, view) == expected)
        assert len(view._chart.series()) == 1
        series = view._chart.series()[0]
        assert [(point.x(), point.y()) for point in series.points()] == points
        assert len(view._chart.axes()) == 2
        assert all(axis.titleText() for axis in view._chart.axes())


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_chart_without_mica_capability_keeps_plain_surface(qt_application, theme):
    BaseStyles.switch_theme(theme)
    host = _PaintedHost()
    view = PerfChartView(host)
    _show(host, view, qt_application)
    expected = QColor(BaseStyles.color("WINDOW_BG"))
    assert _background(host, view) == expected
    assert view._chart_view.viewport().palette().color(QPalette.ColorRole.Base) == expected
    assert not view._chart_view.viewport().autoFillBackground()
    assert not view.has_data()
