# menu_bar_creator.py
from PySide6.QtWidgets import QMenuBar, QPushButton, QHBoxLayout, QWidget
from PySide6.QtGui import QCursor, QAction
from PySide6.QtCore import Qt, QPoint


class CustomMenuBar(QMenuBar):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._drag_pos = None
        self._create_menu()

    def _create_menu(self):
        """ 创建自定义菜单栏 """
        # File 菜单
        file_menu = self.addMenu("File")
        restore_action = QAction("Restore Default Size", self.parent)
        restore_action.triggered.connect(self.parent.restore_default_size)
        file_menu.addAction(restore_action)

        # Help 菜单
        help_menu = self.addMenu("Help")
        about_action = QAction("About", self.parent)
        about_action.triggered.connect(self.parent.show_about_dialog)
        help_menu.addAction(about_action)
        
        # 最小化按钮（与 File、Help、Exit 同级）
        minimize_action = QAction("Minimize", self.parent)
        minimize_action.triggered.connect(self.parent.showMinimized)
        self.addAction(minimize_action)  # 直接添加到菜单栏
        
        # 退出按钮（与 File、Help 同级）
        exit_action = QAction("Exit", self.parent)
        exit_action.triggered.connect(self.parent.close)
        self.addAction(exit_action)  # 直接添加到菜单栏

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

class MenuBarCreator:
    def __init__(self, parent):
        self.parent = parent
        self.menu_bar = CustomMenuBar(parent)

    def get_menu_bar(self):
        return self.menu_bar