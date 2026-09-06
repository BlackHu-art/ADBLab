"""比较实际 Toast 在窄宽窗口、大字号下的文档边距，不修改公共实现。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from gui.notifications import show_toast

app = QApplication([])
if not QFontDatabase.families():
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / filename))
content = "A long diagnostic line with selectable details. " * 120 + "\n" + "x" * 1200
for width in (420,640,900):
    for point in (12,22):
        for margin in (0,4):
            owner=QWidget()
            owner.resize(width,468)
            owner.show()
            toast=show_toast(owner,"Long message",content,level="error",duration=-1)
            editor=toast.content_edit
            font=QFont(editor.font())
            font.setPointSize(point)
            editor.setFont(font)
            editor.document().setDefaultFont(font)
            editor.setStyleSheet(f"PlainTextEdit {{ border: none; padding: 0; font-family: '{font.family()}'; font-size: {point}pt; }}")
            editor.document().setDocumentMargin(margin)
            toast._adjustText()
            app.processEvents()
            editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())
            app.processEvents()
            rights=[]
            block=editor.document().begin()
            while block.isValid():
                layout=block.layout()
                rights.extend(layout.lineAt(i).naturalTextRect().right() for i in range(layout.lineCount()))
                block=block.next()
            print('width',width,'point',point,'margin',margin,'view',editor.viewport().width(),'doc',editor.document().size().width(),'hmax',editor.horizontalScrollBar().maximum(),'naturalRight',max(rights,default=0),'textMatches',editor.toPlainText()==content,flush=True)
            toast.close()
            owner.close()
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
