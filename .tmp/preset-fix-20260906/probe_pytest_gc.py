"""仅在独立测试子进程观察夹具之后的 GC，不修改项目测试及业务。"""

import gc
import os
import sys
import weakref
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QObject
from shiboken6 import isValid

if "--no-ring-animation" in sys.argv:
    from qfluentwidgets import ProgressRing

    def direct_value(self, value):
        self._val = value
        self.ani.stop()

    ProgressRing._onValueChanged = direct_value
    ProgressRing.setUseAni = lambda self, enabled: setattr(self, "_useAni", False)

if "--no-ring-text" in sys.argv:
    from qfluentwidgets import ProgressRing
    ProgressRing._drawText = lambda self, painter, text: None

if "--no-chart" in sys.argv:
    from PySide6.QtWidgets import QWidget
    import gui.widgets.perf_chart_view as chart_module

    class ChartProbe(QWidget):
        def _sync_theme_state(self):
            pass

    chart_module.PerfChartView = ChartProbe

if "--no-enable-propagation" in sys.argv:
    from gui.dialogs.performance_launcher_form import PerformanceLauncherForm

    def lock_only(self, enabled):
        self._frame._configuration_locked = not enabled

    PerformanceLauncherForm._set_configuration_enabled = lock_only

if "--no-status-css" in sys.argv:
    from gui.dialogs.performance_launcher_run import PerformanceLauncherRun

    def refresh_without_status_css(self):
        self._frame.progress_display.refresh(
            self._frame._status_state,
            active=self._frame._configuration_locked and not self._frame._closing,
        )

    PerformanceLauncherRun._apply_status_style = refresh_without_status_css

if "--clear-controller-backrefs" in sys.argv:
    from gui.dialogs.performance_launcher import PerformancePage
    original_dispose = PerformancePage._poll_dispose_ready

    def dispose_then_clear(self):
        original_dispose(self)
        if self._dispose_ready_state:
            for name in ("_form_controller", "_run_controller", "_log_controller",
                         "_library_controller"):
                getattr(self, name)._frame = None

    PerformancePage._poll_dispose_ready = dispose_then_clear

if "--native-result-stack" in sys.argv:
    from PySide6.QtWidgets import QStackedWidget
    import gui.dialogs.performance_launcher_form as form_module
    form_module._PerformanceResultStack = QStackedWidget

if "--repolish-pivot-selection" in sys.argv:
    from qfluentwidgets.components.navigation.pivot import PivotItem

    def select_without_style_replacement(self, selected):
        if self.isSelected == selected:
            return
        self.isSelected = selected
        self.setProperty("isSelected", selected)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    PivotItem.setSelected = select_without_style_replacement

if "--disconnect-result-business" in sys.argv:
    from gui.dialogs.performance_launcher import PerformancePage
    original_begin_dispose = PerformancePage._begin_dispose

    def begin_dispose_without_result_callbacks(self):
        self._chart_toggle.currentItemChanged.disconnect()
        self._chart_stack.currentChanged.disconnect()
        original_begin_dispose(self)

    PerformancePage._begin_dispose = begin_dispose_without_result_callbacks


class CleanupProbe:
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        yield
        counts = Counter()
        for candidate in gc.get_objects():
            if isinstance(candidate, QObject):
                counts[(type(candidate).__name__, isValid(candidate))] += 1
                selected = "--finalizers" in sys.argv or (
                    "--finalizers-native" in sys.argv
                    and type(candidate).__module__.startswith("PySide6")
                ) or (
                    "--finalizers-custom" in sys.argv
                    and not type(candidate).__module__.startswith("PySide6")
                )
                if selected and not isValid(candidate):
                    weakref.finalize(candidate, print, "WRAPPER_FINAL", type(candidate).__name__,
                                     id(candidate), flush=True)
        counts = {str(key): count for key, count in counts.items()
                  if key[0] in {"PerformancePage", "PerformanceProgress", "_PerformanceActionCard",
                                "ProgressRing", "IconWidget", "QProxyStyle", "QCommonStyle"}}
        print("GC_BEFORE", item.name, counts, flush=True)
        collected = gc.collect()
        print("GC_AFTER", item.name, collected, flush=True)


code = pytest.main([
    "-q", "-s", "tests/test_performance_responsive.py", "-k",
    "cards_reflow_without or large_font_running_summary",
], plugins=[CleanupProbe()])
print("PYTEST_RETURNED", code, flush=True)
gc.collect()
print("FINAL_GC_DONE", flush=True)
sys.exit(code)
