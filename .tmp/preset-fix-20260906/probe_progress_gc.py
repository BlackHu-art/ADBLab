"""独立验证进度组件构造、主题刷新和 Qt/Python 清理，不访问设备或用户库。"""

import argparse
import gc
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, IconWidget, IndeterminateProgressRing, ProgressRing
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.widgets.performance_progress import PerformanceProgress

parser = argparse.ArgumentParser()
parser.add_argument("kind", choices=("raw", "progress"))
parser.add_argument("--count", type=int, default=80)
parser.add_argument("--gc-each", action="store_true")
args = parser.parse_args()
app = QApplication([])
if not QFontDatabase.families():
    for filename in ("msyh.ttc", "segoeui.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / filename))
initial_theme = BaseStyles.current_theme()
initial_font = QFont(app.font())
destroyed = []


def iteration(index):
    initial_windows = set(app.topLevelWidgets())
    owner = QWidget()
    owner.destroyed.connect(lambda: destroyed.append(index))
    layout = QVBoxLayout(owner)
    if args.kind == "progress":
        progress = PerformanceProgress(owner)
        layout.addWidget(progress)
        ring, busy, icon = progress.ring, progress.busy_ring, progress.icon
    else:
        body = QWidget(owner)
        row = QHBoxLayout(body)
        ring, busy = ProgressRing(body), IndeterminateProgressRing(body, start=False)
        icon = IconWidget(FluentIcon.HISTORY, body)
        for item in (ring, busy, icon):
            row.addWidget(item)
        layout.addWidget(body)
        progress = None
    owner.resize(420 if index % 2 else 764, 600)
    owner.show()
    for theme, size in (("Light", 12), ("Dark", 22), ("Light", 22)):
        BaseStyles.switch_theme(theme)
        owner.setFont(QFont(initial_font.family(), size))
        ring.setValue(index % 100)
        icon.setIcon(FluentIcon.COMPLETED.icon(color=QColor("#005a9e")))
        if progress is not None:
            progress.refresh("running", active=True)
            progress.set_timing(120, 100)
        else:
            busy.start()
        app.processEvents()
    if progress is not None:
        progress.set_animation_enabled(False)
    else:
        busy.stop()
        ring.ani.stop()
    owner.close()
    for window in set(app.topLevelWidgets()) - initial_windows:
        if not isValid(window):
            continue
        for timer in window.findChildren(QTimer):
            timer.stop()
        if window.isVisible():
            window.close()
        if isValid(window):
            window.deleteLater()
    BaseStyles.switch_theme(initial_theme)
    app.setFont(initial_font)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


for index in range(args.count):
    iteration(index)
    if args.gc_each:
        gc.collect()
    if index % 10 == 9:
        print("iteration", index + 1, "destroyed", len(destroyed), flush=True)
print("before_final_gc", args.kind, len(destroyed), flush=True)
gc.collect()
print("after_final_gc", args.kind, len(destroyed), flush=True)
assert len(destroyed) == args.count
