from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout
from gui.widgets.py_panel.log_panel import LogPanel
from gui.widgets.py_panel.left_panel import LeftPanel
from gui.widgets.py_menu_bar.custom_menu_bar import CustomMenuBar
from .widgets.style.base_styles import get_default_font


class MainFrame(QMainWindow):
    """精简主窗口，菜单功能已由CustomMenuBar实现"""
    
    DEFAULT_WIDTH = 1100
    DEFAULT_HEIGHT = 680

    def __init__(self):
        super().__init__()
        self._setup_window()
        self._init_panels()
        self._setup_menu()
        QTimer.singleShot(100, self.safe_refresh_devices)

    def _setup_window(self):
        """基础窗口设置"""
        self.setWindowTitle("ADB Manager GUI")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setFont(get_default_font())

    def _init_panels(self):
        """初始化主界面布局"""
        central_widget = QWidget()
        layout = QHBoxLayout(central_widget)
        
        self.left_panel = LeftPanel(self)
        self.log_panel = LogPanel()
        
        layout.addWidget(self.left_panel, stretch=1)
        layout.addWidget(self.log_panel, stretch=2)
        self.setCentralWidget(central_widget)

    def _setup_menu(self):
        """设置菜单栏（无需信号连接）"""
        self.menu_bar = CustomMenuBar(self)
        self.setMenuBar(self.menu_bar)
        # 连接菜单栏信号
        self._connect_menu_signals()
        
    def _connect_menu_signals(self):
        """连接菜单栏信号到主窗口方法"""
        self.menu_bar.restore_size_requested.connect(self.restore_default_size)
        self.menu_bar.minimize_requested.connect(self.showMinimized)
        self.menu_bar.clear_log_requested.connect(self.clear_log)
        self.menu_bar.exit_requested.connect(self.close)

    def safe_refresh_devices(self):
        """安全刷新设备列表"""
        try:
            if hasattr(self.left_panel, 'adb_controller'):
                self.left_panel.adb_controller.on_refresh_devices()
        except Exception as e:
            print(f"Refresh failed: {e}")

    def clear_log(self):
        """清空日志面板（被菜单栏直接调用）"""
        if hasattr(self, 'log_panel'):
            self.log_panel.clear()

    def restore_default_size(self):
        """恢复窗口尺寸（被菜单栏直接调用）"""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)