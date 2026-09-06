"""仅用于区分工作区重挂载和运行绘制的隔离诊断。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from gui.features.performance import PerformancePage

PerformancePage.prepare_for_workspace = lambda self: None
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
