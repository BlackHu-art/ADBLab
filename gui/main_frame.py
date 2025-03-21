# main_frame.py
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QComboBox, QPushButton, QListWidget, QLineEdit, QLabel, QMessageBox
from PySide6.QtGui import QCursor
from PySide6.QtCore import Qt, QPoint
from gui.widgets.py_panel.log_panel import LogPanel
from gui.widgets.py_panel.left_panel import LeftPanel
from .styles import Styles, get_default_font
from controllers.adb_controller import ADBController
from controllers.email_controller import EmailController
from controllers.log_controller import LogController
from gui.widgets.py_menu_bar.custom_menu_bar import MenuBarCreator


class MainFrame(QMainWindow):
    DEFAULT_WIDTH = 1100  # 默认窗口宽度
    DEFAULT_HEIGHT = 800  # 默认窗口高度
    MARGIN = 5  # 窗口边缘检测范围

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADB Manager GUI")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        
        # 添加字体配置
        default_font = get_default_font()  # 修改为可靠字体
        self.setFont(default_font)

        self._drag_pos = None
        self._resizing = False
        self._resize_direction = None

        self._setup_ui()
        self._create_menu()

    def _create_menu(self):
        """创建自定义菜单栏"""
        menu_bar_creator = MenuBarCreator(self)
        self.setMenuBar(menu_bar_creator.get_menu_bar())

    def show_about_dialog(self):
        QMessageBox.about(self, "About", "ADB Manager GUI\nVersion 1.0\nPySide6 Example")

    def restore_default_size(self):
        """一键恢复初始窗口大小"""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def _setup_ui(self):
        """设置 UI 布局"""
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # 左侧面板
        self.left_panel = LeftPanel(self)  # 将主窗口实例传递给 LeftPanel
        main_layout.addWidget(self.left_panel)

        # 右侧日志面板
        self.log_panel = LogPanel()
        main_layout.addWidget(self.log_panel)

    def log_message(self, level, message):
        self.log_panel.log_message(level, message)

    def clear_log(self):
        self.log_panel.clear()

    # ---------------- Window Drag & Resize ----------------

    def mousePressEvent(self, event):
        """处理窗口拖拽和调整大小"""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._resizing = self._is_near_edge(event.pos())
            event.accept()

    def mouseMoveEvent(self, event):
        """处理鼠标移动：更新光标或调整窗口大小"""
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            if self._resizing:
                self._resize_window(event.globalPosition().toPoint())
            else:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            self._update_cursor(event.pos())

    def mouseReleaseEvent(self, event):
        """清除拖拽和调整状态"""
        self._drag_pos = None
        self._resizing = False

    def _update_cursor(self, pos):
        """根据鼠标位置更新光标形状"""
        resize_direction = self._get_resize_direction(pos)
        self.setCursor(QCursor(resize_direction) if resize_direction else QCursor(Qt.ArrowCursor))

    def _get_resize_direction(self, pos):
        """判断鼠标是否靠近窗口边缘以调整大小"""
        rect = self.rect()
        if pos.x() < self.MARGIN or pos.x() > rect.width() - self.MARGIN:
            return Qt.SizeHorCursor
        elif pos.y() < self.MARGIN or pos.y() > rect.height() - self.MARGIN:
            return Qt.SizeVerCursor
        return None

    def _is_near_edge(self, pos):
        """判断鼠标是否靠近窗口边缘"""
        return self._get_resize_direction(pos) is not None

    def _resize_window(self, global_pos):
        """根据鼠标移动调整窗口大小"""
        delta = global_pos - self.pos()
        self.resize(delta.x(), delta.y())