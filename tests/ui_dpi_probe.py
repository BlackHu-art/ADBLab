"""在独立 offscreen Qt 进程中输出一次 DPI 几何快照。"""

from __future__ import annotations

import json

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication, QWidget

_APP = None


def main() -> int:
    """创建固定逻辑尺寸窗口，并以单个 JSON 对象报告抓图像素尺寸。"""

    global _APP
    _APP = QApplication.instance() or QApplication([])
    widget = QWidget()
    widget.resize(200, 120)
    widget.show()
    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    pixmap = widget.grab()
    payload = {
        "dpr": pixmap.devicePixelRatio(),
        "logical_width": widget.width(),
        "pixmap_width": pixmap.width(),
    }
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
