import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout
from controllers.adb_controller import ADBController
from gui.widgets.py_panel.log_panel import LogPanel
from gui.widgets.py_panel.left_panel import LeftPanel
from gui.widgets.py_menu_bar.custom_menu_bar import CustomMenuBar
from common.log_service import LogService
from gui.widgets.py_menu_bar.about_dialog import AboutDialog
from .widgets.style.base_styles import get_default_font


class MainFrame(QMainWindow):
    """主窗口框架，集成所有组件"""
    
    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 680

    def __init__(self):
        super().__init__()
        # 初始化服务
        self.log_service = LogService()
        self.log_panel = LogPanel()  # 保存日志面板引用
        self.left_panel = LeftPanel()
        self.adb_controller = ADBController(self.log_service)
        
        # 初始化UI
        self._setup_window()
        self._init_panels()
        self._setup_menu()
        
        # 延迟100ms刷新设备列表
        QTimer.singleShot(100, self._initial_refresh)

    def _setup_window(self):
        """基础窗口设置"""
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon("icon.ico"))
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setFont(get_default_font())

    def _init_panels(self):
        """初始化主界面布局"""
        central_widget = QWidget()
        layout = QHBoxLayout(central_widget)
        
        # 左侧面板和日志面板
        layout.addWidget(self.left_panel, stretch=1)
        layout.addWidget(self.log_panel, stretch=2)
        self.setCentralWidget(central_widget)
        
        # 连接所有信号
        self._connect_all_signals()

    def _connect_all_signals(self):
        LP = self.left_panel.signals
        CTL = self.adb_controller.signals
        AC = self.adb_controller

        # Controller → UI
        CTL.devices_updated.connect(self.left_panel.update_device_list)
        CTL.operation_completed.connect(self.log_panel._append_log)
        CTL.operation_completed.connect(lambda *args: self.left_panel._refresh_device_combobox())
        CTL.email_updated.connect(self.left_panel.update_email)
        CTL.vercode_updated.connect(self.left_panel.update_vercode)
        CTL.current_package_received.connect(self.left_panel.update_current_package)
        CTL.device_info_updated.connect(
            lambda ip, info: self.log_panel._append_log(
                "INFO", f"Device {ip} info:\n{json.dumps(info, indent=2)}")
        )

        # LeftPanel → Controller (table-driven one-to-one connections)
        for signal_, handler in [
            (LP.connect_requested,             AC.connect_device),
            (LP.refresh_devices_requested,     AC.refresh_devices),
            (LP.device_info_requested,         AC.get_device_info),
            (LP.disconnect_requested,          AC.disconnect_devices),
            (LP.restart_devices_requested,      AC.restart_devices),
            (LP.restart_adb_requested,         AC.restart_adb),
            (LP.screenshot_requested,          AC.take_screenshot),
            (LP.retrieve_logs_requested,        AC.retrieve_device_logs),
            (LP.cleanup_logs_requested,        AC.cleanup_device_logs),
            (LP.send_text_requested,           AC.input_text),
            (LP.generate_email_requested,      AC.get_random_email_and_code),
            (LP.get_program_requested,         AC.get_current_package),
            (LP.install_app_requested,         AC.install_apk),
            (LP.uninstall_app_requested,       AC.uninstall_apk),
            (LP.clear_app_data_requested,      AC.clear_app_data),
            (LP.restart_app_requested,         AC.restart_app),
            (LP.print_activity_requested,      AC.get_current_activity),
            (LP.parse_apk_info_requested,      AC.parse_apk_info),
            (LP.start_monkey_requested,        AC.run_monkey_test),
            (LP.kill_monkey_requested,         AC.kill_monkey),
            (LP.list_installed_packages_requested, AC.list_installed_packages),
            (LP.capture_bugreport_requested,   AC.capture_bugreport),
            (LP.pull_anr_file_requested,       AC.pull_anr_files),
        ]:
            signal_.connect(handler)
    def _setup_menu(self):
        """初始化菜单栏"""
        self.menu_bar = CustomMenuBar(self)
        self.setMenuBar(self.menu_bar)
        
        # 连接菜单栏信号
        self.menu_bar.restore_size_requested.connect(self.restore_default_size)
        self.menu_bar.minimize_requested.connect(self.showMinimized)
        self.menu_bar.clear_log_requested.connect(self.clear_log)
        self.menu_bar.exit_requested.connect(self.close)

    def _initial_refresh(self):
        """初始刷新设备列表"""
        try:
            self.adb_controller.refresh_devices()
        except Exception as e:
            self.log_panel._append_log("ERROR", f"Initial refresh failed: {str(e)}")

    def clear_log(self):
        """清空日志面板"""
        self.log_panel.clear()
        self.log_panel._append_log("INFO", "Log cleared")

    def restore_default_size(self):
        """恢复窗口默认尺寸"""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.log_panel._append_log("INFO", "Window size restored to default")

    def _show_about_dialog(self):
        """显示关于对话框"""
        dialog = AboutDialog(self)
        dialog.exec_()

    def closeEvent(self, event):
        """重写关闭事件"""
        self.log_panel._append_log("INFO", "Application shutting down...")
        super().closeEvent(event)
    
    
    