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
