from PySide6.QtCore import Signal, QEvent
from PySide6.QtWidgets import QPushButton

class DoubleClickButton(QPushButton):
    """支持双击事件的自定义按钮"""
    doubleClicked = Signal()  # 新增双击信号
    
    def mouseDoubleClickEvent(self, event: QEvent):
        """重写双击事件处理"""
        self.doubleClicked.emit()  # 发射双击信号
        super().mouseDoubleClickEvent(event)
        event.accept()  # 阻止事件继续传播