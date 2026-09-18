"""services.perf_chart_data 与 PerfChartView 的契约测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from services.perf_chart_data import (
    MetricSeries,
    load_result_metrics,
    parse_cpu_series,
    parse_fps_series,
    parse_memory_series,
)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def result_dir(tmp_path):
    _write(
        tmp_path / "cpuinfo.csv",
        "datetime,device_cpu_rate%,user%,system%,idle%\n"
        "2026-08-28 10-00-00,10.5,4.0,3.0,93.0\n"
        "2026-08-28 10-00-01,20.5,8.0,6.0,86.0\n",
    )
    _write(
        tmp_path / "meminfo.csv",
        "datatime,total_ram(MB),free_ram(MB)\n"
        "2026-08-28 10-00-00,2048,1024\n"
        "2026-08-28 10-00-01,2048,900\n",
    )
    _write(
        tmp_path / "fps.csv",
        "datetime,activity window,fps,jank\n"
        "2026-08-28 10-00-00,com.example,60,0\n"
        "2026-08-28 10-00-01,com.example,55,2\n",
    )
    _write(
        tmp_path / "traffic.csv",
        "datetime,device_total(KB),device_receive(KB),device_transport(KB)\n"
        "2026-08-28 10-00-00,100,60,40\n",
    )
    return tmp_path


def test_load_result_metrics_reads_all_sources(result_dir):
    metrics = load_result_metrics(str(result_dir))
    assert "cpu" in metrics
    assert metrics["cpu"].values == [(0.0, 10.5), (1.0, 20.5)]
    assert metrics["mem_total"].values == [(0.0, 2048.0), (1.0, 2048.0)]
    assert metrics["mem_free"].values == [(0.0, 1024.0), (1.0, 900.0)]
    assert metrics["fps"].values == [(0.0, 60.0), (1.0, 55.0)]
    assert metrics["traffic_total"].values == [(0.0, 100.0)]


def test_missing_directory_returns_empty():
    assert load_result_metrics(str(os.path.join("no", "such", "dir"))) == {}


def test_bad_rows_skipped(tmp_path):
    _write(
        tmp_path / "cpuinfo.csv",
        "datetime,device_cpu_rate%,user%,system%,idle%\n"
        "2026-08-28 10-00-00,abc,4,3,93\n"
        "2026-08-28 10-00-01,20.5,8,6,86\n",
    )
    cpu = parse_cpu_series(str(tmp_path))
    assert cpu["cpu"].values == [(0.0, 20.5)]


def test_fps_legacy_two_column_format(tmp_path):
    _write(tmp_path / "fps.csv", "datetime,fps\n2026-08-28 10-00-00,60\n2026-08-28 10-00-01,59\n")
    fps = parse_fps_series(str(tmp_path))
    assert fps["fps"].values == [(0.0, 60.0), (1.0, 59.0)]
    assert fps["jank"].is_empty()
    assert fps["jank"].error == "column 'jank' not found"


def test_missing_jank_column_never_treats_numeric_timestamps_as_jank(tmp_path):
    _write(tmp_path / "fps.csv", "datetime,fps\n1000,60\n1001,59\n")

    fps = parse_fps_series(str(tmp_path))

    assert fps["fps"].values == [(0.0, 60.0), (1.0, 59.0)]
    assert fps["jank"].values == []
    assert fps["jank"].error == "column 'jank' not found"


def test_missing_file_reports_error(tmp_path):
    series = parse_memory_series(str(tmp_path))
    assert series["mem_total"].is_empty()
    assert series["mem_total"].error == "file missing"


def test_metric_series_empty_contract():
    series = MetricSeries(name="x")
    assert series.is_empty()


def test_metrics_share_real_elapsed_time_across_midnight_and_missing_samples(tmp_path):
    _write(tmp_path / "cpuinfo.csv", "datetime,device_cpu_rate%\n"
           "2026-09-13 23:59:55,10\n2026-09-14 00:00:00,20\n2026-09-14 00:00:15,30\n")
    _write(tmp_path / "fps.csv", "datetime,fps\n2026-09-14 00:00:00,60\n")
    metrics = load_result_metrics(str(tmp_path))
    assert metrics["cpu"].values == [(0, 10), (5, 20), (20, 30)]
    assert metrics["fps"].values == [(5, 60)]


def test_chart_reduction_preserves_short_peak_valley_and_endpoints():
    from gui.widgets.perf_chart_view import _decimate
    points = [(float(i), 100.0 if i == 1 else -100.0 if i == 3 else 0.0)
              for i in range(2001)]
    reduced = _decimate(points, 2000)
    assert points[1] in reduced and points[3] in reduced
    assert reduced[0] == points[0] and reduced[-1] == points[-1]
    assert len(reduced) <= 2000


def test_streaming_metrics_open_each_csv_once_and_bound_summary_memory(result_dir, monkeypatch):
    from pathlib import Path

    from services import perf_chart_data as module
    real_open = Path.open
    opened = []
    sizes = []
    real_reduce = module.reduce_extrema
    _write(result_dir / "traffic.csv", "datetime,device_total(KB),device_receive(KB),"
           "device_transport(KB)\n" + "".join(f"{i},{i},1,2\n" for i in range(20000)))

    def open_file(path, *args, **kwargs):
        opened.append(path.name)
        return real_open(path, *args, **kwargs)

    def reduce(points, limit):
        sizes.append(len(points))
        return real_reduce(points, limit)

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(module, "reduce_extrema", reduce)
    metrics = load_result_metrics(str(result_dir))
    assert sorted(opened) == ["cpuinfo.csv", "fps.csv", "meminfo.csv", "traffic.csv"]
    assert max(sizes) <= module.MAX_METRIC_POINTS * 2
    assert all(len(series.values) <= module.MAX_METRIC_POINTS for series in metrics.values())


def test_cancelled_streaming_load_does_not_publish_partial_metrics(result_dir):
    calls = [0]
    def cancelled():
        calls[0] += 1
        return calls[0] > 3
    assert load_result_metrics(str(result_dir), cancelled=cancelled) == {}


def test_missing_time_column_reports_error_instead_of_inventing_seconds(tmp_path):
    _write(tmp_path / "cpuinfo.csv", "device_cpu_rate%\n10\n20\n")
    series = parse_cpu_series(str(tmp_path))["cpu"]
    assert series.values == []
    assert series.error == "time column missing"
    assert load_result_metrics(str(tmp_path)) == {}


@pytest.mark.ui
def test_chart_axes_cover_each_unit_and_all_time_values(qt_application):
    from PySide6.QtCore import Qt

    from gui.widgets.perf_chart_view import PerfChartView
    view = PerfChartView()
    view.set_series({"cpu": [(0, 50), (5, 80)], "mem_total": [(10, 10000), (20, 12000)]})
    for series in view._chart.series():
        axes = view._chart.axes(Qt.Orientation.Vertical, series)
        assert len(axes) == 1
        assert axes[0].titleText()
        assert all(axes[0].min() <= point.y() <= axes[0].max() for point in series.points())
    horizontal = view._chart.axes(Qt.Orientation.Horizontal)
    assert len(horizontal) == 1 and horizontal[0].max() >= 20
    assert len(view._chart.axes(Qt.Orientation.Vertical)) == 2
    view.deleteLater()


@pytest.mark.ui
@pytest.mark.parametrize("initial_theme", ["Light", "Dark"])
def test_chart_axis_titles_follow_theme_round_trip(qt_application, initial_theme):
    from PySide6.QtGui import QColor

    from gui.styles import BaseStyles
    from gui.widgets.perf_chart_view import PerfChartView

    BaseStyles.switch_theme(initial_theme)
    view = PerfChartView()
    view.set_series({"cpu": [(0, 50), (5, 80)], "mem_total": [(0, 10000), (5, 12000)]})
    other_theme = "Dark" if initial_theme == "Light" else "Light"
    try:
        for theme_name in (other_theme, initial_theme, other_theme):
            BaseStyles.switch_theme(theme_name)
            view._sync_theme_state()
            qt_application.processEvents()

            axes = view._chart.axes()
            assert len(axes) == 3
            expected = QColor(BaseStyles.color("TEXT_SECONDARY"))
            assert all(axis.titleText() for axis in axes)
            assert all(axis.titleBrush().color() == expected for axis in axes)
    finally:
        view.deleteLater()


@pytest.mark.ui
def test_narrow_large_font_chart_keeps_all_units_accessible(monkeypatch, qt_application):
    from PySide6.QtCore import Qt

    from gui.styles import BaseStyles
    from gui.widgets.perf_chart_view import PerfChartView

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    view = PerfChartView()
    view.set_series({
        "cpu": [(0, 50), (20, 80)], "mem_total": [(0, 10000), (20, 12000)],
        "mem_free": [(0, 5000), (20, 4000)], "fps": [(0, 60), (20, 55)],
        "jank": [(0, 0), (20, 3)], "traffic_total": [(0, 100), (20, 300)],
        "traffic_rx": [(0, 60), (20, 200)], "traffic_tx": [(0, 40), (20, 100)],
    })
    view.resize(500, 420)
    view.show()
    qt_application.processEvents()
    try:
        assert view.width() == 500
        assert len(view._chart.axes(Qt.Orientation.Vertical)) == 5
        assert len(view._chart.series()) == 8
        assert view._chart.plotArea().width() >= 240
        scroll = view._chart_scroll.horizontalScrollBar()
        assert scroll.maximum() > 0
        scroll.setValue(scroll.maximum())
        assert scroll.value() == scroll.maximum()
        assert all(marker.label() for marker in view._chart.legend().markers())
        assert not any(axis.labelsTruncated() for axis in view._chart.axes())
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.ui
def test_perf_chart_view_set_clear_and_reload(app_holder=None):
    application = QApplication.instance() or QApplication([])
    from gui.widgets.perf_chart_view import PerfChartView

    view = PerfChartView()
    view.set_series({"cpu": [(0.0, 10.0), (1.0, 20.0)], "fps": [(0.0, 60.0)]})
    assert view.has_data() is True
    first_count = len(view._chart.series())
    # 重复加载不累积旧序列
    view.set_series({"cpu": [(0.0, 5.0)]})
    assert len(view._chart.series()) == 1
    assert first_count == 2
    view.clear()
    assert view.has_data() is False
    assert len(view._chart.series()) == 0
    view.deleteLater()
    application.processEvents()
