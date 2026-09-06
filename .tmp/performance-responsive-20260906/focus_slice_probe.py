"""只在诊断子进程中选择正式节点，按需在用例清理后定位 GC。"""
import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

start, end = (int(value) for value in sys.argv[1:3])
collect_each = "--gc-each" in sys.argv

if "--no-chart" in sys.argv:
    from PySide6.QtWidgets import QWidget
    import gui.widgets.perf_chart_view as charts

    class PlainChart(QWidget):
        def _sync_theme_state(self):
            pass

    charts.PerfChartView = PlainChart

if "--no-progress" in sys.argv:
    from PySide6.QtCore import QSize, Signal
    from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget
    import gui.dialogs.performance_launcher_form as form

    class PlainProgress(QWidget):
        geometry_changed = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self.ring = QProgressBar(self)
            self.status_label = QLabel("Idle", self)
            layout = QVBoxLayout(self)
            layout.addWidget(self.status_label)
            layout.addWidget(self.ring)

        def refresh(self, state, *, active):
            pass

        def refresh_geometry(self):
            pass

        def set_timing(self, elapsed, duration):
            pass

        def set_animation_enabled(self, enabled):
            pass

        def minimumSizeHint(self):
            return QSize(0, 60)

        def heightForWidth(self, width):
            return 60

    form.PerformanceProgress = PlainProgress


class Probe:
    def pytest_collection_modifyitems(self, config, items):
        selected = items[start:end]
        removed = items[:start] + items[end:]
        items[:] = selected
        config.hook.pytest_deselected(items=removed)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        yield
        if collect_each:
            print("GC_BEFORE", item.nodeid, flush=True)
            gc.collect()
            print("GC_AFTER", item.nodeid, flush=True)


raise SystemExit(pytest.main([
    "-q", "-s", "tests/test_performance_responsive.py",
    "tests/test_feature_typography.py::test_loaded_feature_pages_refresh_fonts_and_text_constraints",
    "tests/test_feature_typography.py::test_performance_large_font_keeps_bounded_scrollable_content",
], plugins=[Probe()]))
