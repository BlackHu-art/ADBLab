"""保留原分段控件并显式保有动画目标，隔离 Python 包装的释放顺序。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from qfluentwidgets import SegmentedWidget

original_init = SegmentedWidget.__init__


def retain_target(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    self._retained_scale_target = self.slideAni.targetObject()


SegmentedWidget.__init__ = retain_target
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
