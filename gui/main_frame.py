import json
import os
import shutil
import threading

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QFileDialog,
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
from gui.styles.icon_loader import get_themed_icon
from models.base.command_runner import CommandRunner
from models.base.process_runner import CREATE_NEW_CONSOLE, ProcessRunner
from utils.resource_path import resource_path

from .styles import BaseStyles, get_default_font


class _ScanThread(QThread):
    """Long-running thread: polls `adb devices` every 3 s, emits on count change."""

    devices_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        from models.adb_device import parse_connected_devices

        last_count = None  # always emit on first poll
        while not self._stop_flag:
            try:
                result = CommandRunner.run(["adb", "devices"], timeout=5)
                devices = parse_connected_devices(result.output)
                count = len(devices)
                if count != last_count:
                    last_count = count
                    self.devices_changed.emit()
            except Exception:
                pass
            # Sleep 3 s between polls (breakable for clean shutdown)
            for _ in range(30):
                if self._stop_flag:
                    return
                self.msleep(100)


class MainFrame(QMainWindow):
    DEVICE_SCAN_DEBOUNCE_MS = 300
    SPLITTER_SAVE_DEBOUNCE_MS = 300
    _adb_bootstrap_finished = Signal()

    def __init__(self):
        super().__init__()
        self.log_service = LogService()
        self.log_panel = LogPanel()
        self.left_panel = SidePanel()
        self.adb_controller = ADBController(self.log_service)
        self._drag_pos = None
        self._active_dialogs = []
        self._scan_thread = None
        self._closing = False
        self._scan_refresh_timer = QTimer(self)
        self._scan_refresh_timer.setSingleShot(True)
        self._scan_refresh_timer.timeout.connect(self.adb_controller.refresh_devices)
        self._initial_refresh_timer = QTimer(self)
        self._initial_refresh_timer.setSingleShot(True)
        self._initial_refresh_timer.timeout.connect(self.adb_controller.refresh_devices)
        self._pending_panel_sizes = None
        self._panel_size_save_timer = QTimer(self)
        self._panel_size_save_timer.setSingleShot(True)
        self._panel_size_save_timer.timeout.connect(self._save_pending_panel_sizes)
        self._adb_bootstrap_thread = None
        self._adb_bootstrap_finished.connect(self._start_device_discovery)

        self._setup_window()
        self._init_panels()
        self._bootstrap_adb_async()

    # ── continuous scan ───────────────────────────────────────────────

    def _bootstrap_adb_async(self):
        """Resolve ADB after first paint so startup is not held by filesystem/PATH checks."""
        from utils.adb_resolver import resolve_adb_path

        def _bootstrap():
            try:
                resolve_adb_path()
            finally:
                try:
                    self._adb_bootstrap_finished.emit()
                except RuntimeError:
                    pass

        self._adb_bootstrap_thread = threading.Thread(
            target=_bootstrap,
            name="adblab-adb-bootstrap",
            daemon=True,
        )
        self._adb_bootstrap_thread.start()

    def _start_device_discovery(self):
        if getattr(self, "_closing", False):
            return
        from core.settings_manager import AppSettings
        if AppSettings.instance().get("continuous_device_scan", True):
            self._start_scan_thread()
        else:
            self._initial_refresh_timer.start(0)

    def _start_scan_thread(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self._scan_thread = _ScanThread(self)
        self._scan_thread.devices_changed.connect(self._schedule_scan_refresh)
        self._scan_thread.start()

    def _stop_scan_thread(self):
        initial_timer = getattr(self, "_initial_refresh_timer", None)
        if initial_timer and initial_timer.isActive():
            initial_timer.stop()
        timer = getattr(self, "_scan_refresh_timer", None)
        if timer and timer.isActive():
            timer.stop()
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.stop()
            if not self._scan_thread.wait(150):
                thread = self._scan_thread
                threading.Thread(target=lambda: thread.wait(3000), daemon=True).start()

    def _schedule_scan_refresh(self):
        """Debounce scan-thread device change notifications."""
        self._scan_refresh_timer.start(self.DEVICE_SCAN_DEBOUNCE_MS)

    def set_continuous_scan(self, enabled: bool):
        if enabled:
            self._start_scan_thread()
        else:
            self._stop_scan_thread()

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

        # App title
        title = QLabel("ADBLab")
        layout.addWidget(title)

        # Function buttons
        self.tb_app_mgr = self._create_toolbar_btn("App Manager", "resources/icons/squares-four.svg")
        self.tb_app_mgr.setFixedSize(28, 24)
        self.tb_file_explorer = self._create_toolbar_btn(
            "File Explorer", "resources/icons/folder-open.svg"
        )
        self.tb_file_explorer.setFixedSize(28, 24)
        self.tb_logcat = self._create_toolbar_btn("Live Logcat", "resources/icons/scroll.svg")
        self.tb_logcat.setFixedSize(28, 24)
        self.tb_performance = self._create_toolbar_btn(
            "Performance Monitor", "resources/icons/speedometer.svg"
        )
        self.tb_performance.setFixedSize(28, 24)
        self.tb_settings = self._create_toolbar_btn("Settings", "resources/icons/gear.svg")
        self.tb_settings.setFixedSize(28, 24)
        self.tb_cmd = self._create_toolbar_btn("CMD", "resources/icons/terminal-window.svg")
        self.tb_cmd.setFixedSize(28, 24)

        # Save path indicator + change button
        self._tb_save_btn = QPushButton()
        self._tb_save_btn.setIcon(get_themed_icon("folder.svg"))
        self._tb_save_btn.setIconSize(QSize(14, 14))
        self._tb_save_btn.setObjectName("savePathBtn")
        self._tb_save_btn.setToolTip("Change default save directory")
        self._tb_save_btn.setProperty("iconName", "folder.svg")
        self._tb_save_btn.setFlat(True)
        self._tb_save_btn.setCursor(Qt.PointingHandCursor)
        self._tb_save_btn.clicked.connect(self._on_save_path_clicked)

        # Save path indicator + change button
        self._save_path_label = QLabel()
        self._save_path_label.setObjectName("savePathLabel")
        self._refresh_save_path()

        layout.addWidget(self.tb_app_mgr)
        layout.addWidget(self.tb_file_explorer)
        layout.addWidget(self.tb_logcat)
        layout.addWidget(self.tb_performance)
        layout.addWidget(self.tb_settings)
        layout.addWidget(self.tb_cmd)
        layout.addWidget(self._tb_save_btn)
        layout.addWidget(self._save_path_label)
        layout.addStretch()

        # Right-side tool buttons
        self.tb_clear = self._create_toolbar_btn(
            "Clear Log", "resources/icons/broom.svg"
        )
        self.tb_about = self._create_toolbar_btn("About", "resources/icons/info.svg")

        # Theme toggle button
        self.theme_btn = QPushButton()
        self.theme_btn.setIcon(get_themed_icon("circle-half-tilt.svg"))
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.setToolTip("Toggle Light/Dark theme")
        self.theme_btn.setProperty("iconName", "circle-half-tilt.svg")
        self.theme_btn.setFixedSize(28, 24)
        self.theme_btn.setFlat(True)
        self.theme_btn.clicked.connect(lambda: BaseStyles.toggle_theme())

        self.tb_minimize = self._create_toolbar_btn("Minimize", "resources/icons/minus.svg")
        self.tb_exit = self._create_toolbar_btn("Exit", "resources/icons/x.svg")
        self.tb_exit.setObjectName("exit_btn")

        # Connect toolbar button actions
        self.tb_clear.clicked.connect(self.clear_log)
        self.tb_about.clicked.connect(self._show_about_dialog)
        self.tb_app_mgr.clicked.connect(self._show_app_manager)
        self.tb_file_explorer.clicked.connect(self._show_file_explorer)
        self.tb_logcat.clicked.connect(self._show_logcat)
        self.tb_performance.clicked.connect(self._show_performance_monitor)
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
        icon_name = icon_path.replace("resources/icons/", "")
        btn = QPushButton()
        btn.setIcon(get_themed_icon(icon_name))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setProperty("iconName", icon_name)
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
        self._refresh_toolbar_icons()
        self._refresh_save_path()
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

    def _refresh_toolbar_icons(self):
        for button in self.findChildren(QPushButton):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(get_themed_icon(icon_name))

    def _connect_all_signals(self):
        """Connect left panel signals to ADB controller signals."""
        LP = self.left_panel.signals
        CTL = self.adb_controller.signals
        AC = self.adb_controller

        self._connect_controller_feedback(LP, CTL)
        signal_map = (
            self._device_signal_map(LP, AC)
            + self._app_signal_map(LP, AC)
            + self._testing_signal_map(LP, AC)
            + self._system_signal_map(LP, AC)
        )
        for signal_, handler in signal_map:
            signal_.connect(handler)

    def _connect_controller_feedback(self, LP, CTL):
        CTL.devices_updated.connect(self._on_devices_updated)
        LP.log_message.connect(self.log_panel._append_log)
        CTL.email_updated.connect(self.left_panel.update_email)
        CTL.vercode_updated.connect(self.left_panel.update_vercode)
        CTL.record_finished.connect(self.left_panel.on_recording_finished)
        CTL.current_package_received.connect(self.left_panel.update_current_package)
        CTL.device_info_updated.connect(
            lambda ip, info: self.log_panel._append_log(
                "INFO", f"Device {ip} info:\n{json.dumps(info, indent=2)}"
            )
        )

    def _device_signal_map(self, LP, AC):
        return [
            (LP.connect_requested, AC.connect_device),
            (LP.refresh_devices_requested, AC.refresh_devices),
            (LP.device_info_requested, AC.get_device_info),
            (LP.disconnect_requested, AC.disconnect_devices),
            (LP.restart_devices_requested, AC.restart_devices),
            (LP.restart_adb_requested, AC.restart_adb),
            (LP.reboot_mode_requested, AC.reboot_mode),
            (LP.tcpip_mode_requested, AC.tcpip_mode),
            (LP.screenshot_requested, AC.take_screenshot),
            (LP.screen_record_requested, AC.start_screen_record),
            (LP.stop_screen_record_requested, AC.stop_screen_record),
            (LP.batch_install_requested, AC.batch_install_apk),
            (LP.retrieve_logs_requested, AC.retrieve_device_logs),
            (LP.cleanup_logs_requested, AC.cleanup_device_logs),
            (LP.send_text_requested, AC.input_text),
            (LP.input_tap_requested, AC.input_tap),
            (LP.input_swipe_requested, AC.input_swipe),
            (LP.input_keyevent_requested, AC.input_keyevent),
            (LP.generate_email_requested, AC.start_random_email_task),
        ]

    def _app_signal_map(self, LP, AC):
        return [
            (LP.get_program_requested, AC.get_current_package),
            (LP.uninstall_app_requested, AC.uninstall_apk),
            (LP.clear_app_data_requested, AC.clear_app_data),
            (LP.restart_app_requested, AC.restart_app),
            (LP.print_activity_requested, AC.get_current_activity),
            (LP.parse_apk_info_requested, AC.parse_apk_info),
            (LP.disable_app_requested, AC.disable_app),
            (LP.enable_app_requested, AC.enable_app),
            (LP.force_stop_requested, AC.force_stop),
            (LP.send_broadcast_requested, AC.send_broadcast),
            (LP.start_activity_requested, AC.start_activity),
            (LP.open_deep_link_requested, AC.open_deep_link),
        ]

    def _testing_signal_map(self, LP, AC):
        return [
            (LP.start_monkey_requested, AC.run_monkey_test),
            (LP.kill_monkey_requested, AC.kill_monkey),
            (LP.capture_bugreport_requested, AC.capture_bugreport),
            (LP.pull_anr_file_requested, AC.pull_anr_files),
            (LP.dumpsys_meminfo_requested, AC.dumpsys_meminfo),
            (LP.dumpsys_cpuinfo_requested, AC.dumpsys_cpuinfo),
            (LP.dumpsys_battery_requested, AC.dumpsys_battery),
        ]

    def _system_signal_map(self, LP, AC):
        return [
            (LP.shell_command_requested, AC.run_shell_command),
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

    def _on_devices_updated(self, devices: list[str]):
        """Refresh device UI only when the device list changes."""
        self.left_panel.update_device_list(devices)
        self.left_panel._refresh_device_combobox()

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
        self._show_device_dialogs(AppManagerDialog)

    def _show_file_explorer(self):
        """Open a File Explorer window for each selected device."""
        self._show_device_dialogs(FileExplorerDialog)

    def _show_logcat(self):
        """Open a Live Logcat window for each selected device."""
        self._show_device_dialogs(LiveLogcatDialog)

    def _show_performance_monitor(self):
        """Open a Performance Monitor window for each selected device."""
        from gui.dialogs.performance_monitor import PerformanceMonitorDialog

        self._show_device_dialogs(PerformanceMonitorDialog)

    def _show_device_dialogs(self, dialog_cls):
        devices = self.left_panel.selected_devices
        if not devices:
            self.log_panel._append_log("WARNING", "No device selected")
            return
        for ip in devices:
            dlg = self._find_active_dialog(dialog_cls, ip)
            if dlg:
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                continue
            dlg = self._register_dialog(dialog_cls(device_ip=ip), dialog_cls, ip)
            dlg.show()

    def _register_dialog(self, dialog, dialog_cls=None, device_ip=None):
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if dialog_cls is not None:
            dialog.setProperty("dialog_class", dialog_cls.__name__)
        if device_ip is not None:
            dialog.setProperty("device_ip", device_ip)
        self._active_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _obj=None, dlg=dialog: self._forget_dialog(dlg))
        return dialog

    def _find_active_dialog(self, dialog_cls, device_ip):
        survivors = []
        match = None
        for dialog in self._active_dialogs:
            try:
                same_dialog = (
                    dialog.property("dialog_class") == dialog_cls.__name__
                    and dialog.property("device_ip") == device_ip
                )
            except RuntimeError:
                continue
            survivors.append(dialog)
            if same_dialog and match is None:
                match = dialog
        self._active_dialogs = survivors
        return match

    def _forget_dialog(self, dialog):
        try:
            self._active_dialogs.remove(dialog)
        except ValueError:
            pass

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self)
        dialog.continuous_scan_toggled.connect(self.set_continuous_scan)
        dialog.exec_()

    def _open_cmd(self):
        """Open system terminal at project root."""
        import platform
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system = platform.system()
        runner = ProcessRunner()
        if system == "Windows":
            runner.spawn(["cmd.exe", "/K", f'cd /d "{root}"'], creationflags=CREATE_NEW_CONSOLE)
        elif system == "Darwin":
            runner.spawn(["open", "-a", "Terminal", root])
        else:
            for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"]:
                if shutil.which(term):
                    runner.spawn([term], cwd=root)
                    return


    # -- Window and panel sizing ----------------------------------------

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
            self._pending_panel_sizes = (sizes[0], sizes[1])
            self._panel_size_save_timer.start(self.SPLITTER_SAVE_DEBOUNCE_MS)

    def _save_pending_panel_sizes(self):
        if not self._pending_panel_sizes:
            return
        left_w, right_w = self._pending_panel_sizes
        self._pending_panel_sizes = None
        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        s.set("left_panel_width", left_w)
        s.set("right_panel_width", right_w)

    # ── Save path (toolbar top-left) ──────────────────────────────────

    def _refresh_save_path(self):
        from core.settings_manager import AppSettings
        path = AppSettings.instance().save_directory
        if path and os.path.isdir(path):
            short = path if len(path) <= 36 else "..." + path[-33:]
            self._save_path_label.setText("GlobalSavePath: " + short)
            self._save_path_label.setToolTip(path)
        else:
            self._save_path_label.setText("")
        self._save_path_label.setStyleSheet(
            f"color: {BaseStyles.color('TEXT_SECONDARY')}; font-size: 10px; padding: 0 2px;"
        )

    def _on_save_path_clicked(self):
        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        current = s.save_directory
        d = QFileDialog.getExistingDirectory(self, "Select Default Save Directory",
            current if os.path.isdir(current) else "")
        if d:
            s.set("save_directory", d)
            self._refresh_save_path()

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
        self._closing = True
        self._stop_scan_thread()
        if self._panel_size_save_timer.isActive():
            self._panel_size_save_timer.stop()
            self._save_pending_panel_sizes()
        # Flush pending settings save before exit
        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        if s._save_timer:
            s._save_timer.cancel()
        s._save_atomic()
        for dlg in list(self._active_dialogs):
            try:
                dlg.close()
            except Exception:
                pass
        self._active_dialogs.clear()
        for viewer in list(getattr(self.adb_controller, "_active_viewers", [])):
            try:
                viewer.close()
            except Exception:
                pass
        self.adb_controller.shutdown()
        event.accept()
