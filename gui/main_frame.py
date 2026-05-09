import json
import os
import subprocess

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from controllers import ADBController
from core.log_service import LogService
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.settings_dialog import SettingsDialog
from gui.panels.log_panel import LogPanel
from gui.panels.side_panel import SidePanel
from utils.resource_path import resource_path

from .styles.base_styles import BaseStyles, get_default_font


class MainFrame(QMainWindow):

    def __init__(self):
        super().__init__()
        self.log_service = LogService()
        self.log_panel = LogPanel()
        self.left_panel = SidePanel()
        self.adb_controller = ADBController(self.log_service)
        self._drag_pos = None
        self._active_dialogs = []

        self._setup_window()
        self._init_panels()

        from utils.adb_resolver import resolve_adb_path

        QTimer.singleShot(200, lambda: resolve_adb_path())
        QTimer.singleShot(100, self._initial_refresh)

    def _setup_window(self):
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(860, 500)

        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        w = s.get("window_width", 1200)
        h = s.get("window_height", 650)
        self.resize(w, h)
        self.setFont(get_default_font())
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: transparent;
                border-radius: {BaseStyles.RADIUS_XL}px;
            }}
        """)

    def _init_panels(self):
        """Build central widget: toolbar + panel area."""
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color('WINDOW_BG')};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
            }}
        """)

        # Vertical layout: full-width toolbar + horizontal panel area
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._create_toolbar())

        # Left column: device manager + log
        # Right column: function tabs
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(1)
        dw = self.left_panel._device_widget
        dw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        left_col.addWidget(dw)
        left_col.addWidget(self.log_panel, stretch=1)

        left_wrapper = QWidget()
        left_wrapper.setObjectName("leftPanelWrapper")
        left_wrapper.setLayout(left_col)
        left_wrapper.setMinimumWidth(200)
        left_wrapper.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())

        panel_row = QHBoxLayout()
        panel_row.setContentsMargins(3, 3, 3, 3)
        panel_row.setSpacing(1)

        from core.settings_manager import AppSettings
        s2 = AppSettings.instance()
        lw = s2.get("left_panel_width", 595)
        rw = s2.get("right_panel_width", 592)
        self._panel_splitter = QSplitter(Qt.Horizontal)
        self._panel_splitter.setHandleWidth(5)
        self._panel_splitter.setStyleSheet(
            f"QSplitter::handle {{ background-color: {BaseStyles.color('BORDER_COLOR')}; }}"
        )
        self._panel_splitter.addWidget(left_wrapper)
        self._panel_splitter.addWidget(self.left_panel)
        self._panel_splitter.setSizes([lw, rw])
        self._panel_splitter.setStretchFactor(0, 0)
        self._panel_splitter.setStretchFactor(1, 1)
        self._panel_splitter.setChildrenCollapsible(False)
        self._panel_splitter.splitterMoved.connect(self._on_splitter_moved)
        panel_row.addWidget(self._panel_splitter)
        main_layout.addLayout(panel_row)

        self.setCentralWidget(central_widget)

        self._connect_all_signals()
        BaseStyles.theme_changed.connect(self._on_theme_changed)

        # USB device auto-detection poll (every 3s)
        self._usb_timer = QTimer(self)
        self._usb_timer.timeout.connect(self._check_new_devices)
        self._usb_timer.start(3000)
        self._known_device_count = 0

    def _check_new_devices(self):
        """Poll for new USB devices and auto-refresh the device list on change."""
        import subprocess
        import sys

        try:
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            from utils.adb_resolver import adb_path
            r = subprocess.run(
                [adb_path(), "devices"], capture_output=True, text=True, creationflags=cf, timeout=5
            )
            devices = [
                line.split("\t")[0]
                for line in r.stdout.strip().splitlines()[1:]
                if "device" in line and "offline" not in line
            ]
            count = len(devices)
            if count != self._known_device_count:
                self._known_device_count = count
                self.adb_controller.refresh_devices()
        except Exception:
            pass

    # ── Top toolbar (full-width, replaces menu bar) ───────────────────

    def _create_toolbar(self) -> QFrame:
        """Create full-width top toolbar with title, function buttons, theme toggle and window controls."""
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)

        # App title + function buttons
        title = QLabel("ADBLab")
        layout.addWidget(title)
        self.tb_app_mgr = self._create_toolbar_btn("App Manager", "resources/icons/Install_app.svg")
        self.tb_app_mgr.setFixedSize(28, 24)
        self.tb_file_explorer = self._create_toolbar_btn(
            "File Explorer", "resources/icons/Save_alt.svg"
        )
        self.tb_file_explorer.setFixedSize(28, 24)
        self.tb_logcat = self._create_toolbar_btn("Live Logcat", "resources/icons/Print.svg")
        self.tb_logcat.setFixedSize(28, 24)
        self.tb_settings = self._create_toolbar_btn("Settings", "resources/icons/Settings.svg")
        self.tb_settings.setFixedSize(28, 24)
        self.tb_cmd = self._create_toolbar_btn("CMD", "resources/icons/Input.svg")
        self.tb_cmd.setFixedSize(28, 24)
        layout.addWidget(self.tb_app_mgr)
        layout.addWidget(self.tb_file_explorer)
        layout.addWidget(self.tb_logcat)
        layout.addWidget(self.tb_settings)
        layout.addWidget(self.tb_cmd)
        layout.addStretch()

        # Right-side tool buttons
        self.tb_clear = self._create_toolbar_btn(
            "Clear Log", "resources/icons/Cleaning_services.svg"
        )
        self.tb_about = self._create_toolbar_btn("About", "resources/icons/Info.svg")

        # Theme toggle button
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

        # Connect toolbar button actions
        self.tb_clear.clicked.connect(self.clear_log)
        self.tb_about.clicked.connect(self._show_about_dialog)
        self.tb_app_mgr.clicked.connect(self._show_app_manager)
        self.tb_file_explorer.clicked.connect(self._show_file_explorer)
        self.tb_logcat.clicked.connect(self._show_logcat)
        self.tb_cmd.clicked.connect(self._open_cmd)
        self.tb_settings.clicked.connect(self._show_settings)
        self.tb_minimize.clicked.connect(self.showMinimized)
        self.tb_exit.clicked.connect(self.close)

        for btn in (self.tb_clear, self.tb_about, self.theme_btn, self.tb_minimize, self.tb_exit):
            btn.setFixedSize(28, 24)
            layout.addWidget(btn)

        return bar

    def _create_toolbar_btn(self, tooltip: str, icon_path: str) -> QPushButton:
        """Create flat toolbar button (icon + tooltip)."""
        btn = QPushButton()
        btn.setIcon(QIcon(resource_path(icon_path)))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setFlat(True)
        return btn

    def _on_theme_changed(self, _name: str):
        """Re-apply central widget and toolbar styles on theme change, and persist theme."""
        from core.settings_manager import AppSettings
        AppSettings.instance().set("theme", _name)

        self.centralWidget().setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color('WINDOW_BG')};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
            }}
        """)
        for bar in self.findChildren(QFrame, "toolbar"):
            bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())
        # Splitter handle theme
        self._panel_splitter.setStyleSheet(
            f"QSplitter::handle {{ background-color: {BaseStyles.color('BORDER_COLOR')}; }}"
        )
        # Left panel theme update (including inner GroupBoxes and device list)
        lw = self.findChild(QWidget, "leftPanelWrapper")
        if lw:
            lw.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
            for g in lw.findChildren(QGroupBox):
                g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
            self.left_panel._devices_tab._apply_device_list_style()

    def _connect_all_signals(self):
        """Connect left panel signals to ADB controller signals."""
        LP = self.left_panel.signals
        CTL = self.adb_controller.signals
        AC = self.adb_controller

        CTL.devices_updated.connect(self.left_panel.update_device_list)
        CTL.operation_completed.connect(self.log_panel._append_log)
        CTL.operation_completed.connect(lambda *args: self.left_panel._refresh_device_combobox())
        LP.log_message.connect(self.log_panel._append_log)
        CTL.email_updated.connect(self.left_panel.update_email)
        CTL.vercode_updated.connect(self.left_panel.update_vercode)
        CTL.current_package_received.connect(self.left_panel.update_current_package)
        CTL.device_info_updated.connect(
            lambda ip, info: self.log_panel._append_log(
                "INFO", f"Device {ip} info:\n{json.dumps(info, indent=2)}"
            )
        )

        # Left panel → ADB controller signal mapping
        signal_map = [
            # Device management
            (LP.connect_requested, AC.connect_device),
            (LP.refresh_devices_requested, AC.refresh_devices),
            (LP.device_info_requested, AC.get_device_info),
            (LP.disconnect_requested, AC.disconnect_devices),
            (LP.restart_devices_requested, AC.restart_devices),
            (LP.restart_adb_requested, AC.restart_adb),
            (LP.reboot_mode_requested, AC.reboot_mode),
            (LP.pair_device_requested, AC.pair_device),
            (LP.tcpip_mode_requested, AC.tcpip_mode),
            # Screenshot & screen recording
            (LP.screenshot_requested, AC.take_screenshot),
            (LP.screen_record_requested, AC.start_screen_record),
            (LP.pull_recording_requested, AC.pull_recordings),
            (LP.batch_install_requested, AC.batch_install_apk),
            # Logging
            (LP.retrieve_logs_requested, AC.retrieve_device_logs),
            (LP.cleanup_logs_requested, AC.cleanup_device_logs),
            (LP.logcat_filtered_requested, AC.logcat_filtered),
            # Input
            (LP.send_text_requested, AC.input_text),
            (LP.input_tap_requested, AC.input_tap),
            (LP.input_swipe_requested, AC.input_swipe),
            (LP.input_keyevent_requested, AC.input_keyevent),
            # Email
            (LP.generate_email_requested, AC.get_random_email_and_code),
            # App management
            (LP.get_program_requested, AC.get_current_package),
            (LP.install_app_requested, AC.install_apk),
            (LP.uninstall_app_requested, AC.uninstall_apk),
            (LP.clear_app_data_requested, AC.clear_app_data),
            (LP.restart_app_requested, AC.restart_app),
            (LP.print_activity_requested, AC.get_current_activity),
            (LP.parse_apk_info_requested, AC.parse_apk_info),
            (LP.grant_permission_requested, AC.grant_permission),
            (LP.revoke_permission_requested, AC.revoke_permission),
            (LP.disable_app_requested, AC.disable_app),
            (LP.enable_app_requested, AC.enable_app),
            (LP.force_stop_requested, AC.force_stop),
            (LP.send_broadcast_requested, AC.send_broadcast),
            (LP.start_activity_requested, AC.start_activity),
            (LP.open_deep_link_requested, AC.open_deep_link),
            # Testing
            (LP.start_monkey_requested, AC.run_monkey_test),
            (LP.kill_monkey_requested, AC.kill_monkey),
            (LP.list_installed_packages_requested, AC.list_installed_packages),
            (LP.capture_bugreport_requested, AC.capture_bugreport),
            (LP.pull_anr_file_requested, AC.pull_anr_files),
            (LP.dumpsys_meminfo_requested, AC.dumpsys_meminfo),
            (LP.dumpsys_cpuinfo_requested, AC.dumpsys_cpuinfo),
            (LP.dumpsys_battery_requested, AC.dumpsys_battery),
            # Shell & file
            (LP.shell_command_requested, AC.run_shell_command),
            (LP.file_list_requested, AC.file_list),
            (LP.file_push_requested, AC.file_push),
            (LP.file_pull_requested, AC.file_pull),
            # Network & settings
            (LP.forward_port_requested, AC.forward_port),
            (LP.list_forwards_requested, AC.list_forwards),
            (LP.remove_forwards_requested, AC.remove_forwards),
            (LP.reverse_port_requested, AC.reverse_port),
            (LP.list_reverse_requested, AC.list_reverse),
            (LP.remove_reverse_requested, AC.remove_reverse),
            (LP.settings_list_requested, AC.settings_list),
            (LP.settings_get_requested, AC.settings_get),
            (LP.settings_put_requested, AC.settings_put),
            (LP.content_query_requested, AC.content_query),
            # Advanced
            (LP.list_processes_requested, AC.list_processes),
            (LP.kill_process_requested, AC.kill_process),
            (LP.battery_set_requested, AC.battery_set),
            (LP.battery_reset_requested, AC.battery_reset),
            (LP.quick_setting_requested, AC.quick_setting),
            (LP.ime_list_requested, AC.ime_list),
            (LP.ime_set_requested, AC.ime_set),
            (LP.pm_features_requested, AC.pm_features),
            (LP.device_uptime_requested, AC.device_uptime),
            (LP.emu_sms_requested, AC.emu_sms),
            (LP.emu_call_requested, AC.emu_call),
            (LP.emu_geo_requested, AC.emu_geo),
        ]
        for signal_, handler in signal_map:
            signal_.connect(handler)

    def _initial_refresh(self):
        """Perform initial device list refresh after UI is fully loaded."""
        try:
            self.adb_controller.refresh_devices()
            # Sync USB poller device count
            import subprocess
            import sys

            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            from utils.adb_resolver import adb_path
            r = subprocess.run(
                [adb_path(), "devices"], capture_output=True, text=True, creationflags=cf, timeout=5
            )
            self._known_device_count = len(
                [
                    line
                    for line in r.stdout.strip().splitlines()[1:]
                    if "device" in line and "offline" not in line
                ]
            )
        except Exception as e:
            self.log_panel._append_log("ERROR", f"Initial refresh failed: {str(e)}")

    def clear_log(self):
        """Clear log panel."""
        self.log_panel.clear()
        self.log_panel._append_log("INFO", "Log cleared")

    def _show_about_dialog(self):
        """Show about dialog."""
        dialog = AboutDialog(self)
        dialog.exec_()

    def _show_app_manager(self):
        """Open an App Manager window for each selected device."""
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "No device selected")
            return
        for ip in devices:
            dlg = AppManagerDialog(device_ip=ip)
            dlg.show()
            self._active_dialogs.append(dlg)

    def _show_file_explorer(self):
        """Open a File Explorer window for each selected device."""
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "No device selected")
            return
        for ip in devices:
            dlg = FileExplorerDialog(device_ip=ip)
            dlg.show()
            self._active_dialogs.append(dlg)

    def _show_logcat(self):
        """Open a Live Logcat window for each selected device."""
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "No device selected")
            return
        for ip in devices:
            dlg = LiveLogcatDialog(device_ip=ip)
            dlg.show()
            self._active_dialogs.append(dlg)

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self)
        dialog.exec_()

    def _open_cmd(self):
        """Open local command window (cmd.exe) with working directory at project root."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.Popen(
            ["cmd.exe", "/K", f'cd /d "{project_root}"'],
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )


    # ── 窗口与面板尺寸调整 ──────────────────────────────────────────

    def apply_window_size(self, w: int, h: int):
        self.resize(w, h)

    def panel_sizes(self) -> list[int]:
        return self._panel_splitter.sizes() if self._panel_splitter else [400, 600]

    def apply_panel_sizes(self, left_w: int, right_w: int):
        if self._panel_splitter:
            self._panel_splitter.setSizes([left_w, right_w])

    def _on_splitter_moved(self, _pos, _index):
        sizes = self._panel_splitter.sizes()
        if len(sizes) == 2:
            from core.settings_manager import AppSettings
            s = AppSettings.instance()
            s.set("left_panel_width", sizes[0])
            s.set("right_panel_width", sizes[1])

    # ── Toolbar drag-to-move window ──────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            widget = self.childAt(event.pos())
            if widget and (
                widget.objectName() == "toolbar"
                or (widget.parent() and widget.parent().objectName() == "toolbar")
            ):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        self.log_panel._append_log("INFO", "Application shutting down...")
        super().closeEvent(event)
