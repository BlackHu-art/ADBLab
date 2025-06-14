import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QProgressDialog
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
        """连接所有组件信号"""
        # ADB控制器 -> UI组件
        self.adb_controller.signals.devices_updated.connect(self.left_panel.update_device_list)
        self.adb_controller.signals.operation_completed.connect(self.log_panel._append_log)
        self.left_panel.signals.connect_requested.connect(self.adb_controller.connect_device)
        self.left_panel.signals.refresh_devices_requested.connect(self.adb_controller.refresh_devices)
        self.left_panel.signals.device_info_requested.connect(self.adb_controller.get_device_info)
        self.left_panel.signals.disconnect_requested.connect(self.adb_controller.disconnect_devices)
        self.left_panel.signals.restart_devices_requested.connect(self.adb_controller.restart_devices)
        self.left_panel.signals.restart_adb_requested.connect(self.adb_controller.restart_adb)
        self.left_panel.signals.screenshot_requested.connect(self.adb_controller.take_screenshot)
        self.left_panel.signals.retrieve_logs_requested.connect(self.adb_controller.retrieve_device_logs)
        self.left_panel.signals.cleanup_logs_requested.connect(self.adb_controller.cleanup_device_logs)
        self.left_panel.signals.send_text_requested.connect(self.adb_controller.input_text)
        # 生成临时邮箱信号处理和接收
        self.left_panel.signals.generate_email_requested.connect(self.adb_controller.get_random_email_and_code)
        self.adb_controller.signals.email_updated.connect(self.left_panel.update_email)
        self.adb_controller.signals.vercode_updated.connect(self.left_panel.update_vercode)
        self.adb_controller.signals.operation_completed.connect(self.left_panel._refresh_device_combobox())
        # 设备信息更新特殊处理
        self.adb_controller.signals.device_info_updated.connect(
            lambda ip, info: self.log_panel._append_log(
                "INFO", f"Device {ip} info:\n{json.dumps(info, indent=2)}")
        )
        # left_panel连接获取程序请求 adb_controller返回包名更新信号后在left_panel执行更新
        self.left_panel.signals.get_program_requested.connect(self.adb_controller.get_current_package)
        self.adb_controller.signals.current_package_received.connect(self.left_panel.update_current_package)
        # 连接安装
        self.left_panel.signals.install_app_requested.connect(self.adb_controller.install_apk)
        self.left_panel.signals.uninstall_app_requested.connect(self.adb_controller.uninstall_apk)
        self.left_panel.signals.clear_app_data_requested.connect(self.adb_controller.clear_app_data)
        self.left_panel.signals.restart_app_requested.connect(self.adb_controller.restart_app)
        self.left_panel.signals.print_activity_requested.connect(self.adb_controller.get_current_activity)
        self.left_panel.signals.parse_apk_info_requested.connect(self.adb_controller.parse_apk_info)
        self.left_panel.signals.start_monkey_requested.connect(self.adb_controller.run_monkey_test)
        self.left_panel.signals.kill_monkey_requested.connect(self.adb_controller.kill_monkey)
        self.left_panel.signals.list_installed_packages_requested.connect(self.adb_controller.list_installed_packages)
        self.left_panel.signals.capture_bugreport_requested.connect(self.adb_controller.capture_bugreport)
        self.left_panel.signals.pull_anr_file_requested.connect(self.adb_controller.pull_anr_files)
        
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
    
    
    