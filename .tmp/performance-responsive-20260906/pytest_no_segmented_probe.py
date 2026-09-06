"""仅隔离结果分段控件，保留页面和结果栈的真实对象。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
import gui.dialogs.performance_launcher_form as form


class PlainSegmented(QWidget):
    currentItemChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = {}
        self.row = QHBoxLayout(self)

    def addItem(self, key, text):
        button = QPushButton(text, self)
        self.items[key] = button
        self.row.addWidget(button)

    def setCurrentItem(self, key):
        self.currentItemChanged.emit(key)


form.SegmentedWidget = PlainSegmented
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
