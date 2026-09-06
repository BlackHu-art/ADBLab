"""直接调用同组 UI 操作与清理夹具，区分 pytest 收尾和 Qt 生命周期。"""

import gc
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from tests import conftest
from tests import test_performance_responsive as cases

app_generator = conftest.qt_application.__wrapped__()
app = next(app_generator)


def execute(name, **values):
    patch = pytest.MonkeyPatch()
    state = conftest.isolated_ui_state.__wrapped__(app, {"assertions": [], "cleanup": {}})
    next(state)
    with tempfile.TemporaryDirectory(prefix="adblab-gc-probe-") as temporary:
        cases.isolated_performance_settings.__wrapped__(patch, Path(temporary))
        try:
            getattr(cases, name)(app, patch, **values)
        finally:
            try:
                next(state)
            except StopIteration:
                pass
            patch.undo()
    print("CASE_DONE", name, values, flush=True)


for width in (420, 640):
    for size in (12, 22):
        for theme in ("Light", "Dark"):
            execute("test_performance_cards_reflow_without_horizontal_scroll_or_clipped_controls",
                    width=width, font_size=size, theme=theme)
            gc.collect()
            print("GC_DONE", flush=True)
for width in (420, 764, 1200):
    execute("test_performance_large_font_running_summary_and_actions_remain_readable", width=width)
    gc.collect()
    print("GC_DONE", flush=True)
print("PROBE_COMPLETE", flush=True)
