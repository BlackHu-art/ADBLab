from PySide6.QtWidgets import QMenuBar
from PySide6.QtCore import Qt

class CustomMenuBar(QMenuBar):
    """
    自定义菜单栏：允许在空白区域拖动窗口移动，
    而对点击在菜单项上的操作保持默认响应。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None  # 用于存储拖动起始位置的偏移量

    def mousePressEvent(self, event):
        # 仅处理鼠标左键点击事件
        if event.button() == Qt.LeftButton:
            # 如果点击位置上没有菜单项，则认为点击在空白区域
            if self.actionAt(event.pos()) is None:
                # 计算鼠标点击位置与窗口左上角的偏移量（全局坐标）
                self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
                event.accept()
                return  # 直接返回，不调用父类方法，防止干扰拖动
        # 如果点击在菜单项上，交由父类处理
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 如果正在拖动（左键按下且_drag_pos不为空），则移动窗口
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return  # 拖动事件已处理，不再传递
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # 鼠标释放时，重置拖动状态
        self._drag_pos = None
        super().mouseReleaseEvent(event)
