"""用真实 Fluent 切换按钮验证结果切换替代组合的完整退出行为。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QSizePolicy, QWidget
from qfluentwidgets import TogglePushButton
import gui.dialogs.performance_launcher_form as form


class FluentViewToggle(QWidget):
    currentItemChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = {}
        self._current = None
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(self._on_clicked)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(8)

    def addItem(self, key, text):
        button = TogglePushButton(text, self)
        button.setProperty("routeKey", key)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.items[key] = button
        self._group.addButton(button)
        self._row.addWidget(button, 1)

    def setCurrentItem(self, key):
        if key == self._current:
            return
        self.items[key].setChecked(True)
        self._current = key
        self.currentItemChanged.emit(key)

    def _on_clicked(self, button):
        self.setCurrentItem(button.property("routeKey"))


form.SegmentedWidget = FluentViewToggle
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
