"""在独立 offscreen Qt 进程中输出一次 DPI 几何快照。"""

from __future__ import annotations

import argparse
import json

_APP = None


def main() -> int:
    """创建固定逻辑尺寸窗口，并以单个 JSON 对象报告抓图像素尺寸。"""

    global _APP
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-scale")
    args = parser.parse_args()
    if args.app_scale is not None:
        from main import _configure_gui_scaling

        _configure_gui_scaling(json.loads(args.app_scale))

    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
    from PySide6.QtWidgets import QApplication, QWidget

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
        "logical_height": widget.height(),
        "pixmap_height": pixmap.height(),
    }
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
