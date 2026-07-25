"""提供能够区分双击操作的按钮控件。"""

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QPushButton


class DoubleClickButton(QPushButton):
    """在标准按钮行为之外发布双击信号。"""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event: QEvent):
        """发布双击信号，并由当前控件消费该事件。"""
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)
        event.accept()
