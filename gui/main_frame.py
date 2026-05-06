import json
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                                QPushButton, QLabel, QFrame, QSizePolicy)
from controllers.adb_controller import ADBController
from gui.panels.log_panel import LogPanel
from gui.panels.left_panel import LeftPanel
from core.log_service import LogService
from gui.dialogs.about_dialog import AboutDialog
from .styles.base_styles import get_default_font, BaseStyles


class MainFrame(QMainWindow):

    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 680

    def __init__(self):
        super().__init__()
        self.log_service = LogService()
        self.log_panel = LogPanel()
        self.left_panel = LeftPanel()
        self.adb_controller = ADBController(self.log_service)
        self._drag_pos = None  # window drag tracking

        self._setup_window()
        self._init_panels()

        QTimer.singleShot(100, self._initial_refresh)

    def _setup_window(self):
        """Frameless translucent window with rounded corners."""
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon("icon.ico"))
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setFont(get_default_font())
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: transparent;
                border-radius: {BaseStyles.RADIUS_XL}px;
            }}
        """)

    def _init_panels(self):
        """Build central widget: toolbar on top, panels below."""
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

        # Horizontal panel area
        panel_row = QHBoxLayout()
        panel_row.setContentsMargins(6, 2, 6, 6)
        panel_row.setSpacing(4)
        panel_row.addWidget(self.left_panel, stretch=1)
        panel_row.addWidget(self.log_panel, stretch=2)
        main_layout.addLayout(panel_row)

        self.setCentralWidget(central_widget)

        self._connect_all_signals()
        BaseStyles.theme_changed.connect(self._on_theme_changed)

    # ── Top toolbar (full-width, replaces menu bar) ────────────────────

    def _create_toolbar(self) -> QFrame:
        """Full-width top toolbar with app title, theme toggle, and window controls."""
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

        # Theme toggle button
        self.theme_btn = QPushButton()
        self.theme_btn.setIcon(QIcon("resources/icons/theme.svg"))
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.setToolTip("Toggle Light/Dark theme")
        self.theme_btn.setFixedSize(28, 24)
        self.theme_btn.clicked.connect(lambda: BaseStyles.toggle_theme())
        layout.addWidget(self.theme_btn)

        layout.addStretch()

        # Window action buttons
        self.tb_clear = self._create_toolbar_btn("Clear Log", "resources/icons/Cleaning_services.svg")
        self.tb_about = self._create_toolbar_btn("About", "resources/icons/Info.svg")
        self.tb_minimize = self._create_toolbar_btn("Minimize", "resources/icons/minimize.svg")
        self.tb_exit = self._create_toolbar_btn("Exit", "resources/icons/Close.svg")
        self.tb_exit.setObjectName("exit_btn")

        # Connect toolbar button actions
        self.tb_clear.clicked.connect(self.clear_log)
        self.tb_about.clicked.connect(self._show_about_dialog)
        self.tb_minimize.clicked.connect(self.showMinimized)
        self.tb_exit.clicked.connect(self.close)

        for btn in (self.tb_clear, self.tb_about, self.tb_minimize, self.tb_exit):
            btn.setFixedSize(28, 24)
            layout.addWidget(btn)

        return bar

    def _create_toolbar_btn(self, tooltip: str, icon_path: str) -> QPushButton:
        """Create a flat toolbar button with icon and tooltip."""
        btn = QPushButton()
        btn.setIcon(QIcon(icon_path))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setFlat(True)
        return btn

    def _on_theme_changed(self, _name: str):
        """Re-apply central widget and toolbar styles on theme switch."""
        self.centralWidget().setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color('WINDOW_BG')};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
            }}
        """)
        # Refresh toolbar style
        for bar in self.findChildren(QFrame, "toolbar"):
            bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())

    def _connect_all_signals(self):
        """Wire left_panel signals and controller signals."""
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

    def _initial_refresh(self):
        """Initial device list refresh after UI is fully loaded."""
        try:
            self.adb_controller.refresh_devices()
        except Exception as e:
            self.log_panel._append_log("ERROR", f"Initial refresh failed: {str(e)}")

    def clear_log(self):
        """Clear the log panel."""
        self.log_panel.clear()
        self.log_panel._append_log("INFO", "Log cleared")

    def restore_default_size(self):
        """Restore the window to its default size."""
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.log_panel._append_log("INFO", "Window size restored to default")

    def _show_about_dialog(self):
        """Show the About dialog."""
        dialog = AboutDialog(self)
        dialog.exec_()

    # ── Window dragging (via toolbar) ─────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.childAt(event.pos()) is self.findChild(QFrame, "toolbar"):
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        self.log_panel._append_log("INFO", "Application shutting down...")
        super().closeEvent(event)
