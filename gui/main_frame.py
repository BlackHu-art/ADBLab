# main_frame.py
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QMessageBox
from gui.widgets.py_panel.log_panel import LogPanel
from gui.widgets.py_panel.left_panel import LeftPanel
from .styles import get_default_font
from gui.widgets.py_menu_bar.custom_menu_bar import MenuBarCreator


class MainFrame(QMainWindow):
    """主窗口类，实现无边框可拖拽的GUI界面"""
    DEFAULT_WIDTH = 1100
    DEFAULT_HEIGHT = 680

    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        self._setup_window_properties()
        self._init_ui_components()
        self._setup_ui()
        self._create_menu()
        # 延迟操作前添加存在性检查
        if hasattr(self, 'left_panel') and hasattr(self.left_panel, 'adb_controller'):
            QTimer.singleShot(100, self.safe_refresh_devices)

    def safe_refresh_devices(self):
        try:
            self.left_panel.adb_controller.on_refresh_devices()
        except AttributeError as e:
            print(f"Controller not initialized: {e}")


    def _setup_window_properties(self):
        """配置窗口基本属性"""
        self.setWindowTitle("ADB Manager GUI")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setFont(get_default_font())

    def _init_ui_components(self):
        """初始化UI组件状态"""
        self._drag_pos: QPoint | None = None
        self.left_panel: LeftPanel | None = None
        self.log_panel: LogPanel | None = None

    def _create_menu(self):
        """创建自定义菜单栏"""
        menu_bar_creator = MenuBarCreator(self)
        self.setMenuBar(menu_bar_creator.get_menu_bar())

    def _setup_ui(self):
        """设置主界面布局"""
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # 左侧功能面板
        self.left_panel = LeftPanel(self)
        main_layout.addWidget(self.left_panel, stretch=1)

        # 右侧日志面板
        self.log_panel = LogPanel()
        main_layout.addWidget(self.log_panel, stretch=2)

    # 在MainFrame中统一处理错误
    # def log_message(self, level: str, message: str):
    #     # 添加崩溃防护
    #     try:
    #         self.log_panel.log_message(level, message)
    #     except RuntimeError as e:
    #         print(f"UI Already Destroyed: {e}")

    def clear_log(self):
        """清空日志面板"""
        self.log_panel.clear()

    def restore_default_size(self):
        """恢复窗口默认尺寸"""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    # region 窗口操作事件处理
    def mousePressEvent(self, event: QMouseEvent):
        """处理鼠标按下事件（仅拖拽）"""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        """处理鼠标移动事件（仅拖拽）"""
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """处理鼠标释放事件"""
        self._drag_pos = None

    def show_about_dialog(self):
        """显示关于对话框"""
        QMessageBox.about(self, "About", 
            "ADB Manager GUI\nVersion 1.0\nPySide6 Example")