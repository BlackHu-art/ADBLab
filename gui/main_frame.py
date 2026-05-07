import json
from PySide6.QtCore import Qt, QTimer, QSize, QEvent
from PySide6.QtGui import QIcon, QMouseEvent, QCursor
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                                QPushButton, QLabel, QFrame, QSizePolicy)
from controllers.adb_controller import ADBController
from gui.panels.log_panel import LogPanel
from gui.panels.left_panel import LeftPanel
from core.log_service import LogService
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.settings_dialog import SettingsDialog
from utils.resource_path import resource_path
from .styles.base_styles import get_default_font, BaseStyles


class MainFrame(QMainWindow):

    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 700
    MIN_WIDTH = 860
    MIN_HEIGHT = 500

    def __init__(self):
        super().__init__()
        self.log_service = LogService()
        self.log_panel = LogPanel()
        self.left_panel = LeftPanel()
        self.adb_controller = ADBController(self.log_service)
        self._drag_pos = None
        self._resize_margin = 6

        self._setup_window()
        self._init_panels()

        QTimer.singleShot(100, self._initial_refresh)

    def _setup_window(self):
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        w = s.get("window_width", self.DEFAULT_WIDTH)
        h = s.get("window_height", self.DEFAULT_HEIGHT)
        self.resize(w, h)
        self.setFont(get_default_font())
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: transparent;
                border-radius: {BaseStyles.RADIUS_XL}px;
            }}
        """)

    def _init_panels(self):
        """构建中央控件：顶部工具栏 + 下方面板区域。"""
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color('WINDOW_BG')};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
            }}
        """)

        # 垂直布局: 全宽工具栏 + 水平面板区域
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._create_toolbar())

        # 水平面板区域
        panel_row = QHBoxLayout()
        panel_row.setContentsMargins(3, 1, 3, 3)
        panel_row.setSpacing(4)
        panel_row.addWidget(self.left_panel, stretch=1)
        panel_row.addWidget(self.log_panel, stretch=2)
        main_layout.addLayout(panel_row)

        self.setCentralWidget(central_widget)
        central_widget.installEventFilter(self)

        self._connect_all_signals()
        BaseStyles.theme_changed.connect(self._on_theme_changed)

        # USB 设备自动检测轮询（每 3 秒）
        self._usb_timer = QTimer(self)
        self._usb_timer.timeout.connect(self._check_new_devices)
        self._usb_timer.start(3000)
        self._known_device_count = 0

    def _check_new_devices(self):
        """轮询检测新 USB 设备，发现变化时自动刷新设备列表。"""
        import subprocess, sys
        try:
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                               creationflags=cf, timeout=5)
            devices = [l.split("\t")[0] for l in r.stdout.strip().splitlines()[1:]
                      if "device" in l and "offline" not in l]
            count = len(devices)
            if count != self._known_device_count:
                self._known_device_count = count
                self.adb_controller.refresh_devices()
        except Exception:
            pass

    # ── 顶部工具栏（全宽，替代菜单栏）──────────────────────────────────

    def _create_toolbar(self) -> QFrame:
        """创建全宽顶部工具栏，含标题、功能按钮、主题切换和窗口控制。"""
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)

        # 应用标题 + 功能按钮
        title = QLabel("ADBLab")
        layout.addWidget(title)
        self.tb_app_mgr = self._create_toolbar_btn("App Manager", "resources/icons/Install_app.svg")
        self.tb_app_mgr.setFixedSize(28, 24)
        self.tb_file_explorer = self._create_toolbar_btn("File Explorer", "resources/icons/Save_alt.svg")
        self.tb_file_explorer.setFixedSize(28, 24)
        self.tb_logcat = self._create_toolbar_btn("Live Logcat", "resources/icons/Print.svg")
        self.tb_logcat.setFixedSize(28, 24)
        self.tb_settings = self._create_toolbar_btn("Settings", "resources/icons/Settings.svg")
        self.tb_settings.setFixedSize(28, 24)
        layout.addWidget(self.tb_app_mgr)
        layout.addWidget(self.tb_file_explorer)
        layout.addWidget(self.tb_logcat)
        layout.addWidget(self.tb_settings)
        layout.addStretch()

        # 右侧工具按钮
        self.tb_clear = self._create_toolbar_btn("Clear Log", "resources/icons/Cleaning_services.svg")
        self.tb_about = self._create_toolbar_btn("About", "resources/icons/Info.svg")

        # 主题切换按钮（右侧倒数第二）
        self.theme_btn = QPushButton()
        self.theme_btn.setIcon(QIcon(resource_path("resources/icons/theme.svg")))
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.setToolTip("Toggle Light/Dark theme")
        self.theme_btn.setFixedSize(28, 24)
        self.theme_btn.setFlat(True)
        self.theme_btn.clicked.connect(lambda: BaseStyles.toggle_theme())

        self.tb_minimize = self._create_toolbar_btn("Minimize", "resources/icons/minimize.svg")
        self.tb_exit = self._create_toolbar_btn("Exit", "resources/icons/Close.svg")
        self.tb_exit.setObjectName("exit_btn")

        # 连接工具栏按钮动作
        self.tb_clear.clicked.connect(self.clear_log)
        self.tb_about.clicked.connect(self._show_about_dialog)
        self.tb_app_mgr.clicked.connect(self._show_app_manager)
        self.tb_file_explorer.clicked.connect(self._show_file_explorer)
        self.tb_logcat.clicked.connect(self._show_logcat)
        self.tb_settings.clicked.connect(self._show_settings)
        self.tb_minimize.clicked.connect(self.showMinimized)
        self.tb_exit.clicked.connect(self.close)

        for btn in (self.tb_clear, self.tb_about, self.theme_btn,
                    self.tb_minimize, self.tb_exit):
            btn.setFixedSize(28, 24)
            layout.addWidget(btn)

        return bar

    def _create_toolbar_btn(self, tooltip: str, icon_path: str) -> QPushButton:
        """创建扁平工具栏按钮（图标 + 提示）。"""
        btn = QPushButton()
        btn.setIcon(QIcon(resource_path(icon_path)))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setFlat(True)
        return btn

    def _on_theme_changed(self, _name: str):
        """主题切换时重新应用中央控件和工具栏样式。"""
        self.centralWidget().setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color('WINDOW_BG')};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
            }}
        """)
        # 刷新工具栏样式
        for bar in self.findChildren(QFrame, "toolbar"):
            bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())

    def _connect_all_signals(self):
        """连接左侧面板信号与 ADB 控制器信号。"""
        LP = self.left_panel.signals
        CTL = self.adb_controller.signals
        AC = self.adb_controller

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

        # Left panel → ADB controller signal mapping
        signal_map = [
            # 设备管理
            (LP.connect_requested,                AC.connect_device),
            (LP.refresh_devices_requested,        AC.refresh_devices),
            (LP.device_info_requested,            AC.get_device_info),
            (LP.disconnect_requested,             AC.disconnect_devices),
            (LP.restart_devices_requested,        AC.restart_devices),
            (LP.restart_adb_requested,            AC.restart_adb),
            (LP.reboot_mode_requested,            AC.reboot_mode),
            (LP.pair_device_requested,            AC.pair_device),
            (LP.tcpip_mode_requested,             AC.tcpip_mode),
            # 截图与录屏
            (LP.screenshot_requested,             AC.take_screenshot),
            (LP.screen_record_requested,          AC.start_screen_record),
            (LP.pull_recording_requested,         AC.pull_recordings),
            (LP.batch_install_requested,          AC.batch_install_apk),
            # 日志
            (LP.retrieve_logs_requested,          AC.retrieve_device_logs),
            (LP.cleanup_logs_requested,           AC.cleanup_device_logs),
            (LP.logcat_filtered_requested,        AC.logcat_filtered),
            # 输入
            (LP.send_text_requested,              AC.input_text),
            (LP.input_tap_requested,              AC.input_tap),
            (LP.input_swipe_requested,            AC.input_swipe),
            (LP.input_keyevent_requested,         AC.input_keyevent),
            # 邮箱
            (LP.generate_email_requested,         AC.get_random_email_and_code),
            # 应用管理
            (LP.get_program_requested,            AC.get_current_package),
            (LP.install_app_requested,            AC.install_apk),
            (LP.uninstall_app_requested,          AC.uninstall_apk),
            (LP.clear_app_data_requested,         AC.clear_app_data),
            (LP.restart_app_requested,            AC.restart_app),
            (LP.print_activity_requested,         AC.get_current_activity),
            (LP.parse_apk_info_requested,         AC.parse_apk_info),
            (LP.grant_permission_requested,       AC.grant_permission),
            (LP.revoke_permission_requested,      AC.revoke_permission),
            (LP.disable_app_requested,            AC.disable_app),
            (LP.enable_app_requested,             AC.enable_app),
            (LP.force_stop_requested,             AC.force_stop),
            (LP.send_broadcast_requested,         AC.send_broadcast),
            (LP.start_activity_requested,         AC.start_activity),
            (LP.open_deep_link_requested,         AC.open_deep_link),
            # 测试
            (LP.start_monkey_requested,           AC.run_monkey_test),
            (LP.kill_monkey_requested,            AC.kill_monkey),
            (LP.list_installed_packages_requested, AC.list_installed_packages),
            (LP.capture_bugreport_requested,      AC.capture_bugreport),
            (LP.pull_anr_file_requested,          AC.pull_anr_files),
            (LP.dumpsys_meminfo_requested,        AC.dumpsys_meminfo),
            (LP.dumpsys_cpuinfo_requested,        AC.dumpsys_cpuinfo),
            (LP.dumpsys_battery_requested,        AC.dumpsys_battery),
            # Shell 与文件
            (LP.shell_command_requested,          AC.run_shell_command),
            (LP.file_list_requested,              AC.file_list),
            (LP.file_push_requested,              AC.file_push),
            (LP.file_pull_requested,              AC.file_pull),
            # 网络与设置
            (LP.forward_port_requested,           AC.forward_port),
            (LP.list_forwards_requested,          AC.list_forwards),
            (LP.remove_forwards_requested,        AC.remove_forwards),
            (LP.reverse_port_requested,           AC.reverse_port),
            (LP.list_reverse_requested,           AC.list_reverse),
            (LP.remove_reverse_requested,         AC.remove_reverse),
            (LP.settings_list_requested,          AC.settings_list),
            (LP.settings_get_requested,           AC.settings_get),
            (LP.settings_put_requested,           AC.settings_put),
            (LP.content_query_requested,          AC.content_query),
            # 高级功能
            (LP.list_processes_requested,         AC.list_processes),
            (LP.kill_process_requested,           AC.kill_process),
            (LP.battery_set_requested,            AC.battery_set),
            (LP.battery_reset_requested,          AC.battery_reset),
            (LP.quick_setting_requested,          AC.quick_setting),
            (LP.ime_list_requested,               AC.ime_list),
            (LP.ime_set_requested,                AC.ime_set),
            (LP.pm_features_requested,            AC.pm_features),
            (LP.device_uptime_requested,          AC.device_uptime),
            (LP.emu_sms_requested,                AC.emu_sms),
            (LP.emu_call_requested,               AC.emu_call),
            (LP.emu_geo_requested,                AC.emu_geo),
        ]
        for signal_, handler in signal_map:
            signal_.connect(handler)

    def _initial_refresh(self):
        """UI 完全加载后执行初始设备列表刷新。"""
        try:
            self.adb_controller.refresh_devices()
            # 同步 USB 轮询器的设备计数
            import subprocess, sys
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                               creationflags=cf, timeout=5)
            self._known_device_count = len([l for l in r.stdout.strip().splitlines()[1:]
                                           if "device" in l and "offline" not in l])
        except Exception as e:
            self.log_panel._append_log("ERROR", f"Initial refresh failed: {str(e)}")

    def clear_log(self):
        """清空日志面板。"""
        self.log_panel.clear()
        self.log_panel._append_log("INFO", "Log cleared")

    def restore_default_size(self):
        """恢复窗口到默认尺寸。"""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.log_panel._append_log("INFO", "Window size restored to default")

    def _show_about_dialog(self):
        """显示关于对话框。"""
        dialog = AboutDialog(self)
        dialog.exec_()

    def _show_app_manager(self):
        """每台选中设备打开一个 App Manager 窗口"""
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "未选中设备")
            return
        for ip in devices:
            dlg = AppManagerDialog(self, ip); dlg.show()

    def _show_file_explorer(self):
        """每台选中设备打开一个 File Explorer 窗口"""
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "未选中设备")
            return
        for ip in devices:
            dlg = FileExplorerDialog(self, ip); dlg.show()

    def _show_logcat(self):
        """每台选中设备打开一个 Live Logcat 窗口"""
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "未选中设备")
            return
        for ip in devices:
            dlg = LiveLogcatDialog(self, ip); dlg.show()

    def _show_settings(self):
        """显示设置对话框。"""
        dialog = SettingsDialog(self)
        dialog.exec_()

    # ── 边缘拖拽调整窗口大小 ──────────────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.HoverMove:
            self._update_cursor(event.position().toPoint())
        elif event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edge = self._hit_edge(event.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                return True
            self._resize_edge = None
        return super().eventFilter(obj, event)

    def _hit_edge(self, pos):
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        m = self._resize_margin
        edges = 0
        if x < m:
            edges |= 1  # left
        if x > w - m:
            edges |= 2  # right
        if y < m:
            edges |= 4  # top
        if y > h - m:
            edges |= 8  # bottom
        return edges

    def _update_cursor(self, pos):
        edge = self._hit_edge(pos)
        if edge == 1 or edge == 2:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == 4 or edge == 8:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge in (1 | 4, 2 | 8):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in (2 | 4, 1 | 8):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # ── Window dragging & resizing ─────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            edge = self._hit_edge(pos)
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                event.accept()
                return
            if (self.childAt(event.pos()) and
                    self.childAt(event.pos()).objectName() == "toolbar" or
                    self.childAt(event.pos()).parent() and
                    self.childAt(event.pos()).parent().objectName() == "toolbar"):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if hasattr(self, '_resize_edge') and self._resize_edge and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geo = self._resize_start_geo
            e = self._resize_edge
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
            if e & 1:
                x = min(geo.x() + delta.x(), geo.x() + geo.width() - self.MIN_WIDTH)
                w = max(self.MIN_WIDTH, geo.width() - delta.x())
            if e & 2:
                w = max(self.MIN_WIDTH, geo.width() + delta.x())
            if e & 4:
                y = min(geo.y() + delta.y(), geo.y() + geo.height() - self.MIN_HEIGHT)
                h = max(self.MIN_HEIGHT, geo.height() - delta.y())
            if e & 8:
                h = max(self.MIN_HEIGHT, geo.height() + delta.y())
            self.setGeometry(x, y, w, h)
            event.accept()
            return
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        self._resize_edge = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        s.set("window_width", self.width())
        s.set("window_height", self.height())

    def closeEvent(self, event):
        self.log_panel._append_log("INFO", "Application shutting down...")
        super().closeEvent(event)
