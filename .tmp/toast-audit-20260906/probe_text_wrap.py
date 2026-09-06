"""比较长通知正文的实际排版范围，不改变正文、不隐藏溢出诊断。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFontDatabase, QTextOption
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTextEdit, QWidget
from qfluentwidgets import PlainTextEdit, TextEdit

from gui.notifications import show_toast
from gui.styles import BaseStyles, FontRole

app = QApplication([])
if not QFontDatabase.families():
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / filename))
content = "A long diagnostic line with selectable details. " * 120 + "\n" + "x" * 1200


def inspect_edit(label, editor):
    document = editor.document()
    block = document.begin()
    maxima = []
    while block.isValid():
        layout = block.layout()
        lines = [layout.lineAt(index) for index in range(layout.lineCount())]
        bounds = [(line.naturalTextRect().right(), line.width(), line.horizontalAdvance(), line.textLength()) for line in lines]
        maxima.append(max(bounds, default=(0,0,0,0)))
        block = block.next()
    print(label, "edit",editor.size().toTuple(), "view",editor.viewport().size().toTuple(), "doc",document.size().toTuple(), "textWidth",document.textWidth(),"hmax",editor.horizontalScrollBar().maximum(),"vmax",editor.verticalScrollBar().maximum(), "margin",document.documentMargin(),"bounds",maxima, flush=True)


owner = QWidget()
owner.resize(640, 468)
owner.show()
toast = show_toast(owner,"Long message",content,level="error",duration=-1)
app.processEvents()
inspect_edit("REAL_TOAST",toast.content_edit)

font = BaseStyles.font_for_role(FontRole.UI)
for cls in (QPlainTextEdit, PlainTextEdit, QTextEdit, TextEdit):
    for margin in (0,4):
        for mode in (QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere,QTextOption.WrapMode.WrapAnywhere):
            editor=cls()
            editor.setReadOnly(True)
            editor.setFont(font)
            editor.document().setDefaultFont(font)
            editor.setStyleSheet(f"{cls.__name__} {{ border: none; padding: 0; font-family: '{font.family()}'; font-size:{font.pointSizeF()}pt; }}")
            editor.setLineWrapMode(cls.LineWrapMode.WidgetWidth)
            editor.setWordWrapMode(mode)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            editor.document().setDocumentMargin(margin)
            editor.setPlainText(content)
            editor.resize(422,230)
            editor.show()
            app.processEvents()
            inspect_edit(f"{cls.__name__} {mode.name}",editor)
            editor.close()
            editor.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
toast.close()
owner.close()
owner.deleteLater()
QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
