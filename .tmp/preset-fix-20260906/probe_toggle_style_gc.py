"""只在独立进程验证样式注册、按钮选择和延迟销毁，不访问设备或用户数据。"""
import argparse
import gc
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QButtonGroup, QHBoxLayout, QWidget
from qfluentwidgets import TogglePushButton, setCustomStyleSheet
from qfluentwidgets.common.style_sheet import styleSheetManager
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.styles.fluent import configure_button

parser = argparse.ArgumentParser()
parser.add_argument("kind", choices=("bare", "custom", "configured"))
parser.add_argument("--count", type=int, default=80)
args = parser.parse_args()
app = QApplication([])
initial_theme = BaseStyles.current_theme()
initial_font = QFont(app.font())
destroyed = []


def iteration(index):
    host = QWidget()
    host.destroyed.connect(lambda: destroyed.append(index))
    row = QHBoxLayout(host)
    group = QButtonGroup(host)
    group.setExclusive(True)
    buttons = [TogglePushButton(text, host) for text in ("日志", "图表")]
    for button in buttons:
        group.addButton(button)
        row.addWidget(button)
        if args.kind == "configured":
            configure_button(button, text=button.text(), tooltip="Show run logs")
        elif args.kind == "custom":
            setCustomStyleSheet(button, "ToggleButton:focus { border: 2px solid #0078d4; }", "ToggleButton:focus { border: 2px solid #60cdff; }")
    buttons[0].setChecked(True)
    host.resize(420, 100)
    host.show()
    for theme, size in (("Light", 12), ("Dark", 22), ("Light", 22)):
        BaseStyles.switch_theme(theme)
        host.setFont(QFont(initial_font.family(), size))
        for button in buttons:
            button.setChecked(True)
            button.setFocus(Qt.FocusReason.TabFocusReason)
            app.processEvents()
    host.close()
    host.deleteLater()
    BaseStyles.switch_theme(initial_theme)
    app.setFont(initial_font)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(host) and not any(isValid(b) for b in buttons)


for index in range(args.count):
    iteration(index)
    if index % 10 == 9:
        print("iteration", index + 1, "destroyed", len(destroyed), "registered", len(styleSheetManager.widgets), flush=True)
        gc.collect()
print("before_final_gc", args.kind, flush=True)
gc.collect()
print("after_final_gc", args.kind, len(destroyed), "registered", len(styleSheetManager.widgets), flush=True)
