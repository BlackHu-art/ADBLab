"""仅隔离确定环绘制与其余页面对象的诊断，不用于功能验收。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from qfluentwidgets import ProgressRing

ProgressRing.paintEvent = lambda self, event: None
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
