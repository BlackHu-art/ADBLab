import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon, IconWidget
from qfluentwidgets.common.icon import SvgIconEngine, writeSvg
from shiboken6 import ownedByPython, isValid

app = QApplication([])
svg = writeSvg(FluentIcon.HISTORY.path(), fill='#888888')
engine = SvgIconEngine(svg)
print('before icon', ownedByPython(engine), isValid(engine), flush=True)
icon = QIcon(engine)
print('after icon', ownedByPython(engine), isValid(engine), flush=True)
copy = QIcon(icon)
copy.setIsMask(True)
print('after copy/detach', ownedByPython(engine), isValid(engine), flush=True)
del copy, icon
gc.collect()
print('after icon deleted', ownedByPython(engine), isValid(engine), flush=True)
del engine
gc.collect()
for step in range(150):
    widget = IconWidget()
    widget.resize(24, 24)
    widget.show()
    for key in (FluentIcon.HISTORY, FluentIcon.COMPLETED, FluentIcon.INFO, FluentIcon.CANCEL):
        widget.setIcon(key.icon(color=QColor('#336699')))
        app.processEvents()
        widget.grab()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del widget
    gc.collect()
print('150 icon cycles complete', flush=True)
