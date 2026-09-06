"""诊断进程仅改变两个结果切换按钮的样式来源，保留正式测试与清理。"""
import gc
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from gui.styles import fluent

mode = sys.argv[1] if len(sys.argv) > 1 else "no-custom"

original_style = fluent._apply_button_custom_style


def omit_result_button_style(button, *, danger):
    if button.property("routeKey") not in ("log", "chart"):
        original_style(button, danger=danger)


if mode == "no-custom":
    fluent._apply_button_custom_style = omit_result_button_style
elif mode == "declared-slots":
    from PySide6.QtCore import Slot
    from PySide6.QtWidgets import QAbstractButton
    from gui.dialogs import performance_launcher_form as form

    class DeclaredViewToggle(form._PerformanceViewToggle):
        @Slot(QAbstractButton, bool)
        def _on_toggled(self, button, checked):
            super()._on_toggled(button, checked)

        @Slot(int)
        def setCurrentIndex(self, index):
            super().setCurrentIndex(index)

    form._PerformanceViewToggle = DeclaredViewToggle
elif mode == "no-helper":
    from gui.dialogs import performance_launcher_form as form
    original_configure = form.configure_button

    def omit_result_button_configure(button, **kwargs):
        if button.property("routeKey") in ("log", "chart"):
            button.setToolTip(kwargs["tooltip"])
            button.setProperty("functionalToolTip", kwargs["tooltip"])
            return button
        return original_configure(button, **kwargs)

    form.configure_button = omit_result_button_configure
elif mode == "no-controller-slot":
    from gui.dialogs import performance_launcher_form as form
    original_build = form.PerformanceLauncherForm._build_chart_toggle

    def build_without_controller_slot(self):
        toggle, stack = original_build(self)
        stack.currentChanged.disconnect(self.refresh_result_view_height)
        return toggle, stack

    form.PerformanceLauncherForm._build_chart_toggle = build_without_controller_slot
elif mode in ("progress-fluent-icon", "progress-native-svg", "progress-colored-fluent"):
    import inspect
    import textwrap
    from PySide6.QtGui import QIcon
    from gui.widgets import performance_progress as progress

    source = textwrap.dedent(inspect.getsource(progress.PerformanceProgress.refresh))
    original_call = "self.icon.setIcon(icon.icon(color=QColor(BaseStyles.color(color_key))))"
    replacements = {
        "progress-fluent-icon": "self.icon.setIcon(icon)",
        "progress-native-svg": "self.icon.setIcon(QIcon(icon.path()))",
        "progress-colored-fluent": "self.icon.setIcon(icon.colored(QColor(BaseStyles.color(color_key)), QColor(BaseStyles.color(color_key))))",
    }
    assert original_call in source
    source = source.replace(original_call, replacements[mode])
    namespace = dict(vars(progress), QIcon=QIcon)
    exec(compile(source, "<progress-icon-probe>", "exec"), namespace)
    progress.PerformanceProgress.refresh = namespace["refresh"]


class Probe:
    def pytest_collection_modifyitems(self, config, items):
        if "--first-two" in sys.argv:
            removed = items[2:]
            items[:] = items[:2]
            config.hook.pytest_deselected(items=removed)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        yield
        if "--gc-each" in sys.argv:
            print("GC_BEFORE", item.nodeid, flush=True)
            gc.collect()
            print("GC_AFTER", item.nodeid, flush=True)


raise SystemExit(pytest.main([
    "-q", "-s", "tests/test_performance_responsive.py",
    "tests/test_feature_typography.py::test_loaded_feature_pages_refresh_fonts_and_text_constraints",
    "tests/test_feature_typography.py::test_performance_large_font_keeps_bounded_scrollable_content",
], plugins=[Probe()]))
