"""用普通 Qt 布局隔离状态卡自定义重排，保留真实进度与字段。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import CardWidget
import gui.dialogs.performance_launcher_form as form


class StaticActionCard(CardWidget):
    def __init__(self, progress, stop, start):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(progress)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(stop)
        actions.addWidget(start)
        layout.addLayout(actions)


form._PerformanceActionCard = StaticActionCard
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
