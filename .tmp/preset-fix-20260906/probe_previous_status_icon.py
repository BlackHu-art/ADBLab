"""单次验证新回归能捕获旧图标引擎释放错误，不修改正式代码。"""
import inspect
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from gui.widgets import performance_progress as progress

source = textwrap.dedent(inspect.getsource(progress.PerformanceProgress.refresh))
fixed = "self.icon.setIcon(icon.colored(color, color))"
assert fixed in source
source = source.replace(fixed, "self.icon.setIcon(icon.icon(color=color))")
namespace = dict(vars(progress))
exec(compile(source, "<previous-status-icon-probe>", "exec"), namespace)
progress.PerformanceProgress.refresh = namespace["refresh"]

raise SystemExit(pytest.main([
    "-q", "-s",
    "tests/test_performance_progress.py::test_status_icon_qt_value_can_be_copied_and_released_after_rendering",
]))
