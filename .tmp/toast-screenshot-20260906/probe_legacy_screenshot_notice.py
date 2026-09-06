"""仅用本机 Fluent 控件复现旧截图通知在大字号下的宽度。"""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import InfoBar, InfoBarPosition, PushButton

app = QApplication([])
owner = QWidget()
owner.resize(860, 700)
owner.show()
notice = InfoBar.success(
    title="截图已完成", content="结果已加入“截图结果”页面。", duration=-1,
    position=InfoBarPosition.TOP_RIGHT, parent=owner,
)
button = PushButton("查看结果", notice)
notice.addWidget(button)
for control in (notice.titleLabel, notice.contentLabel, button):
    control.setFont(QFont("Microsoft YaHei UI", 22))
notice.show()
for _ in range(8):
    app.processEvents()
print(json.dumps({
    "parent_width": owner.width(), "notice_width": notice.width(),
    "notice_x": notice.x(), "content": notice.contentLabel.text(),
    "content_width": notice.contentLabel.width(),
    "content_text_width": notice.contentLabel.fontMetrics().horizontalAdvance(
        notice.contentLabel.text()),
}, ensure_ascii=False))
owner.grab().save(str(Path(__file__).with_name("legacy-screenshot-notice-font22.png")))
notice.close()
owner.close()
owner.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
