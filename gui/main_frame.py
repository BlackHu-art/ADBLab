"""组装主窗口、功能面板、设备扫描和应用级关闭流程。"""

import os
import shutil
import threading
import time

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from adblab.application.supervision import StopDisposition, ThreadedShutdownTask
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from controllers import ADBController
from core.dangerous_ops import DangerousOperationPolicy
from core.log_service import LogService
from core.settings_manager import AppSettings
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.lifecycle import configure_independent_secondary_window
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.settings_dialog import SettingsDialog
from gui.panels.log_panel import LogPanel
from gui.panels.side_panel import SidePanel
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.frameless_resize import FramelessResizeController
from gui.window_layout import (
    DEFAULT_PANEL_RATIO,
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    normalize_panel_ratio,
    normalize_window_size,
    ratio_from_sizes,
    split_sizes_for_ratio,
)
from models.base.command_runner import CommandRunner
from models.base.process_runner import CREATE_NEW_CONSOLE, ProcessRunner
from utils.resource_path import resource_path

from .styles import BaseStyles, FontRole


def _debug_log(owner, event: str, **fields) -> None:
    """输出不含敏感业务值的结构化开发诊断。"""
    log_service = getattr(owner, "log_service", None)
    if log_service is None:
        return
    details = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    message = event if not details else f"{event} {details}"
    log_service.log("DEBUG", message)


class _ScanThread(QThread):
    """以低频率轮询 ``adb devices`` 的长生命周期线程。"""

    devices_changed = Signal(list)

    def __init__(self, parent=None, interval_ms: int = 15000):
        super().__init__(parent)
        self._stop_flag = False
        self._interval_ms = max(3000, int(interval_ms))

    def stop(self):
        self._stop_flag = True

    def run(self):
        from models.adb_device import parse_connected_devices

        last_devices = None  # 首次轮询必须发布设备列表。
        while not self._stop_flag:
            try:
                if CommandRunner.active_count() == 0:
                    result = CommandRunner.run(["adb", "devices"], timeout=5)
                    devices = parse_connected_devices(result.output)
                    device_set = tuple(sorted(devices))
                    if device_set != last_devices:
                        last_devices = device_set
                        self.devices_changed.emit(devices)
            except Exception:
                pass
            # 将轮询间隔拆成短等待，使关闭请求能够及时中断线程。
            for _ in range(max(1, self._interval_ms // 100)):
                if self._stop_flag:
                    return
                self.msleep(100)


class MainFrame(QMainWindow):
    SHUTDOWN_DEADLINE_SECONDS = 6.0
    SHUTDOWN_FINALIZER_RESERVE_SECONDS = 1.0
    DEVICE_SCAN_DEBOUNCE_MS = 300
    SPLITTER_SAVE_DEBOUNCE_MS = 300
    WINDOW_SIZE_SAVE_DEBOUNCE_MS = 350
    _adb_bootstrap_finished = Signal()

    def __init__(self):
        super().__init__()
        self.log_service = LogService()
        self.log_panel = LogPanel()
        self.left_panel = SidePanel()
        self.adb_controller = ADBController(self.log_service)
        self.adb_controller.window_owner = self
        self.task_supervisor = QtTaskSupervisor()
        self.task_supervisor.application_stopped.connect(self._on_application_stopped)
        self.task_supervisor.application_finalized.connect(self._on_application_finalized)
        self._shutdown_owner_id = f"application-{id(self)}"
        self._shutdown_handles = []
        self._shutdown_results = ()
        self._shutdown_residual = ()
        self._shutdown_deadline_at = 0.0
        self._shutdown_finalizer_started = False
        self._close_started = False
        self._close_ready = False
        self._dangerous_policy = DangerousOperationPolicy()
        self._guarded_signal_handlers = []
        self._drag_pos = None
        self._layout_ready = False
        self._resize_controller = None
        self._normal_window_size = DEFAULT_WINDOW_SIZE
        self._active_dialogs = []
        self._scan_thread = None
        self._closing = False
        self._scan_refresh_timer = QTimer(self)
        self._scan_refresh_timer.setSingleShot(True)
        self._scan_refresh_timer.timeout.connect(self._publish_scanned_devices)
        self._pending_scanned_devices = []
        self._initial_refresh_timer = QTimer(self)
        self._initial_refresh_timer.setSingleShot(True)
        self._initial_refresh_timer.timeout.connect(self.adb_controller.refresh_devices)
        self._pending_panel_sizes = None
        self._panel_size_save_timer = QTimer(self)
        self._panel_size_save_timer.setSingleShot(True)
        self._panel_size_save_timer.timeout.connect(self._save_pending_panel_sizes)
        self._pending_window_size = None
        self._window_size_save_timer = QTimer(self)
        self._window_size_save_timer.setSingleShot(True)
        self._window_size_save_timer.timeout.connect(self._save_pending_window_size)
        self._responsive_layout_timer = QTimer(self)
        self._responsive_layout_timer.setSingleShot(True)
        self._responsive_layout_timer.timeout.connect(self._apply_panel_responsive_layout)
        self._adb_bootstrap_thread = None
        self._adb_bootstrap_finished.connect(self._start_device_discovery)
        self._always_on_top = False

        self._setup_window()
        self._init_panels()
        self._resize_controller = FramelessResizeController(self)
        self._layout_ready = True
        self._update_toolbar_path_display()
        self._responsive_layout_timer.start(0)
        self._bootstrap_adb_async()

    # ── 持续设备扫描 ────────────────────────────────────────────────────

    def _bootstrap_adb_async(self):
        """首帧绘制后再解析 ADB，避免文件系统和 PATH 检查阻塞启动界面。"""
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
        from core.settings_manager import AppSettings

        interval_ms = AppSettings.instance().get("device_scan_interval_ms", 15000)
        self._scan_thread = _ScanThread(interval_ms=interval_ms)
        self._scan_thread.devices_changed.connect(self._schedule_scan_refresh)
        self._scan_thread.start()

    def _stop_scan_thread(self, *, blocking: bool = False):
        initial_timer = getattr(self, "_initial_refresh_timer", None)
        if initial_timer and initial_timer.isActive():
            initial_timer.stop()
        timer = getattr(self, "_scan_refresh_timer", None)
        if timer and timer.isActive():
            timer.stop()
        thread = self._scan_thread
        if thread and thread.isRunning():
            thread.stop()
            wait_ms = 6000 if blocking else 150
            if thread.wait(wait_ms):
                self._scan_thread = None
            elif not blocking:
                threading.Thread(target=lambda: thread.wait(3000), daemon=True).start()
        elif thread:
            self._scan_thread = None

    def _schedule_scan_refresh(self, devices: list[str]):
        """合并扫描线程通知，更新界面时不再发起第二次 ADB 轮询。"""
        if getattr(self, "_closing", False):
            return
        self._pending_scanned_devices = list(devices)
        self._scan_refresh_timer.start(self.DEVICE_SCAN_DEBOUNCE_MS)

    def _publish_scanned_devices(self):
        if getattr(self, "_closing", False):
            return
        self.adb_controller.publish_detected_devices(list(self._pending_scanned_devices))

    def set_continuous_scan(self, enabled: bool):
        if enabled:
            self._start_scan_thread()
        else:
            self._stop_scan_thread()

    def _setup_window(self):
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)

        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        self._always_on_top = bool(s.get("always_on_top", False))
        self._apply_window_flags()
        screen = self.screen() or QApplication.primaryScreen()
        available_size = screen.availableGeometry().size() if screen is not None else None
        restored_size = normalize_window_size(
            s.get("window_width", DEFAULT_WINDOW_SIZE.width()),
            s.get("window_height", DEFAULT_WINDOW_SIZE.height()),
            available_size=available_size,
        )
        self._normal_window_size = restored_size
        self.resize(restored_size)
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: transparent;
                border-radius: {BaseStyles.RADIUS_XL}px;
            }}
        """)

    def _init_panels(self):
        """构建工具栏和左右功能面板。"""
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color('WINDOW_BG')};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
            }}
        """)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 工具栏只占用字体所需高度，窗口新增的纵向空间全部交给主内容区。
        main_layout.addWidget(self._create_toolbar(), stretch=0)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(1)
        dw = self.left_panel.device_widget
        dw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.log_panel.setMinimumHeight(120)
        left_col.addWidget(dw)
        left_col.addWidget(self.log_panel, stretch=1)

        left_wrapper = QWidget()
        left_wrapper.setObjectName("leftPanelWrapper")
        left_wrapper.setLayout(left_col)
        left_wrapper.setMinimumWidth(280)
        left_wrapper.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())

        panel_row = QHBoxLayout()
        panel_row.setContentsMargins(3, 3, 3, 3)
        panel_row.setSpacing(1)

        from core.settings_manager import AppSettings

        s2 = AppSettings.instance()
        lw = s2.get("left_panel_width", 400)
        rw = s2.get("right_panel_width", 600)
        stored_ratio = s2.get("panel_split_ratio", None)
        self._panel_ratio = (
            normalize_panel_ratio(stored_ratio)
            if stored_ratio is not None
            else ratio_from_sizes(lw, rw)
        )
        self._panel_splitter = QSplitter(Qt.Horizontal)
        self._panel_splitter.setHandleWidth(8)
        self._apply_splitter_style()
        self._panel_splitter.addWidget(left_wrapper)
        self._panel_splitter.addWidget(self.left_panel)
        left_size, right_size = split_sizes_for_ratio(1000, self._panel_ratio)
        self._panel_splitter.setSizes([left_size, right_size])
        self._panel_splitter.setStretchFactor(0, 1)
        self._panel_splitter.setStretchFactor(1, 1)
        self._panel_splitter.setChildrenCollapsible(False)
        self._panel_splitter.splitterMoved.connect(self._on_splitter_moved)
        panel_row.addWidget(self._panel_splitter)
        main_layout.addLayout(panel_row, stretch=1)

        self.setCentralWidget(central_widget)

        self._connect_all_signals()
        BaseStyles.theme_changed.connect(self._on_theme_changed)
        BaseStyles.ui_font_changed.connect(self._on_ui_font_changed)

    # ── 顶部工具栏 ──────────────────────────────────────────────────────

    def _create_toolbar(self) -> QFrame:
        """创建包含功能入口、主题切换和窗口控制的顶部工具栏。"""
        bar = QFrame()
        self._toolbar = bar
        bar.setObjectName("toolbar")
        bar.setMinimumHeight(BaseStyles.control_height(minimum=32, padding=8))
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)

        self._toolbar_title = QLabel("ADBLab")
        self._toolbar_title.setObjectName("toolbarTitle")
        layout.addWidget(self._toolbar_title)

        self.tb_app_mgr = self._create_toolbar_btn(
            "App Manager", "resources/icons/squares-four.svg"
        )
        self.tb_app_mgr.setFixedSize(28, 24)
        self.tb_file_explorer = self._create_toolbar_btn(
            "File Explorer", "resources/icons/folder-open.svg"
        )
        self.tb_file_explorer.setFixedSize(28, 24)
        self.tb_logcat = self._create_toolbar_btn("Live Logcat", "resources/icons/scroll.svg")
        self.tb_logcat.setFixedSize(28, 24)
        self.tb_performance = self._create_toolbar_btn(
            "Performance", "resources/icons/speedometer.svg"
        )
        self.tb_performance.setFixedSize(28, 24)
        self.tb_settings = self._create_toolbar_btn("Settings", "resources/icons/gear.svg")
        self.tb_settings.setFixedSize(28, 24)
        self.tb_cmd = self._create_toolbar_btn("CMD", "resources/icons/terminal-window.svg")
        self.tb_cmd.setFixedSize(28, 24)

        self._tb_save_btn = QPushButton()
        self._tb_save_btn.setIcon(get_themed_icon("folder.svg"))
        self._tb_save_btn.setIconSize(QSize(14, 14))
        self._tb_save_btn.setObjectName("savePathBtn")
        self._tb_save_btn.setToolTip("Change default save directory")
        self._tb_save_btn.setProperty("iconName", "folder.svg")
        self._tb_save_btn.setFlat(True)
        self._tb_save_btn.setCursor(Qt.PointingHandCursor)
        self._tb_save_btn.setFixedSize(28, 24)
        self._tb_save_btn.clicked.connect(self._on_save_path_clicked)

        self._save_path_label = QLabel()
        self._save_path_label.setObjectName("savePathLabel")
        self._save_path_label.setMinimumWidth(0)
        self._save_path_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
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

        self.tb_clear = self._create_toolbar_btn("Clear Log", "resources/icons/broom.svg")
        self.tb_about = self._create_toolbar_btn("About", "resources/icons/info.svg")

        self.theme_btn = QPushButton()
        self.theme_btn.setIcon(get_themed_icon("circle-half-tilt.svg"))
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.setToolTip("Toggle Light/Dark theme")
        self.theme_btn.setProperty("iconName", "circle-half-tilt.svg")
        self.theme_btn.setFixedSize(28, 24)
        self.theme_btn.setFlat(True)
        self.theme_btn.clicked.connect(self._toggle_theme)

        self.tb_minimize = self._create_toolbar_btn("Minimize", "resources/icons/minus.svg")
        self.tb_always_on_top = self._create_toolbar_btn(
            "Pin on top", "resources/icons/push-pin.svg"
        )
        self.tb_always_on_top.setCheckable(True)
        self.tb_always_on_top.setChecked(self._always_on_top)
        self._refresh_always_on_top_button()
        self.tb_exit = self._create_toolbar_btn("Exit", "resources/icons/x.svg")
        self.tb_exit.setObjectName("exit_btn")

        self.tb_clear.clicked.connect(self.clear_log)
        self.tb_about.clicked.connect(self._show_about_dialog)
        self.tb_app_mgr.clicked.connect(self._show_app_manager)
        self.tb_file_explorer.clicked.connect(self._show_file_explorer)
        self.tb_logcat.clicked.connect(self._show_logcat)
        self.tb_performance.clicked.connect(self._show_performance_monitor)
        self.tb_cmd.clicked.connect(self._open_cmd)
        self.tb_settings.clicked.connect(self._show_settings)
        self.tb_minimize.clicked.connect(self._minimize_window)
        self.tb_always_on_top.clicked.connect(self.set_always_on_top)
        self.tb_exit.clicked.connect(self._request_application_close)

        for btn in (
            self.tb_clear,
            self.tb_about,
            self.theme_btn,
            self.tb_minimize,
            self.tb_always_on_top,
            self.tb_exit,
        ):
            btn.setFixedSize(28, 24)
            layout.addWidget(btn)

        return bar

    def _create_toolbar_btn(self, tooltip: str, icon_path: str) -> QPushButton:
        """创建带图标和提示文本的扁平工具栏按钮。"""
        icon_name = icon_path.replace("resources/icons/", "")
        btn = QPushButton()
        btn.setIcon(get_themed_icon(icon_name))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setProperty("iconName", icon_name)
        btn.setFlat(True)
        return btn

    def _on_theme_changed(self, _name: str):
        """主题变化后刷新窗口样式和图标，并持久化主题选择。"""
        _debug_log(self, "ui.toolbar", action="theme", phase="applied", theme=_name)
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
        self._apply_splitter_style()
        # 左侧容器不属于 SidePanel 控件树，需要在此单独刷新分组框和设备列表。
        lw = self.findChild(QWidget, "leftPanelWrapper")
        if lw:
            lw.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
            for g in lw.findChildren(QGroupBox):
                g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
            self.left_panel.apply_device_theme()
        self._refresh_active_dialog_themes()

    def _on_ui_font_changed(self, _config) -> None:
        """应用新的界面字体并重新计算工具栏文字相关尺寸。"""

        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is not None:
            toolbar.setMinimumHeight(BaseStyles.control_height(minimum=32, padding=8))
            toolbar.updateGeometry()
        self._refresh_save_path()

    def _apply_splitter_style(self):
        """隐藏常驻分隔线，同时保留足够宽的透明拖动热区。"""

        splitter = getattr(self, "_panel_splitter", None)
        if splitter is None:
            return
        splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; border: none; }"
        )

    def _toggle_theme(self):
        """记录工具栏主题切换请求并交给主题服务执行。"""
        _debug_log(
            self,
            "ui.toolbar",
            action="theme",
            phase="requested",
            current_theme=BaseStyles.current_theme(),
        )
        BaseStyles.toggle_theme()

    def _minimize_window(self):
        """记录工具栏最小化动作。"""
        _debug_log(self, "ui.toolbar", action="minimize", phase="requested")
        self.showMinimized()

    def _request_application_close(self):
        """记录工具栏退出动作，实际资源清理由 closeEvent 接管。"""
        _debug_log(self, "ui.toolbar", action="exit", phase="requested")
        self.close()

    def _refresh_active_dialog_themes(self):
        survivors = []
        for dialog in list(getattr(self, "_active_dialogs", [])):
            try:
                if hasattr(dialog, "_sync_theme_state"):
                    dialog._sync_theme_state(force=True)
                elif hasattr(dialog, "_apply_theme"):
                    dialog._apply_theme(BaseStyles.current_theme())
                survivors.append(dialog)
            except RuntimeError:
                continue
        self._active_dialogs = survivors

    def _refresh_toolbar_icons(self):
        for button in self.findChildren(QPushButton):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(get_themed_icon(icon_name))
        self._refresh_always_on_top_button()

    def _connect_all_signals(self):
        """将左侧面板信号连接到 ADB Controller，并包装危险操作校验。"""
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
            guarded_handler = self._guard_dangerous_handler(handler)
            self._guarded_signal_handlers.append(guarded_handler)
            signal_.connect(guarded_handler)

    def _guard_dangerous_handler(self, handler):
        operation_key = getattr(handler, "__name__", "")

        def guarded(*args):
            target_count = len(args[0]) if args and isinstance(args[0], (list, tuple, set)) else 1
            decision = self._dangerous_policy.evaluate(
                operation_key,
                confirmation_enabled=bool(
                    AppSettings.instance().get("confirm_dangerous_ops", True)
                ),
                target_count=target_count,
            )
            if decision.requires_confirmation:
                answer = QMessageBox.question(
                    self,
                    "Confirm dangerous operation",
                    decision.message,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.log_service.log(
                        "WARNING",
                        f"Dangerous operation cancelled: {operation_key}",
                        flush_immediately=True,
                    )
                    return None
            return handler(*args)

        if (
            self._dangerous_policy.evaluate(
                operation_key,
                confirmation_enabled=True,
            ).operation
            is None
        ):
            return handler
        return guarded

    def _connect_controller_feedback(self, LP, CTL):
        CTL.devices_updated.connect(self._on_devices_updated)
        LP.log_message.connect(self.log_service.log)
        CTL.email_updated.connect(self.left_panel.update_email)
        CTL.vercode_updated.connect(self.left_panel.update_vercode)
        CTL.record_finished.connect(self.left_panel.on_recording_finished)
        CTL.operation_completed.connect(self.left_panel.on_operation_completed)
        CTL.current_package_received.connect(self.left_panel.update_current_package)
        CTL.device_info_updated.connect(
            lambda _ip, info: self.log_service.log(
                "INFO",
                f"Device information updated: field_count={len(info)}",
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
        """仅在设备列表变化后刷新设备界面。"""
        self.left_panel.update_device_list(devices)
        self.left_panel.refresh_device_choices()

    def clear_log(self):
        """清空用户日志面板并记录操作结果。"""
        _debug_log(self, "ui.toolbar", action="clear_log", phase="requested")
        self.log_panel.clear()
        self.log_service.log("INFO", "Log cleared")

    def _show_about_dialog(self):
        """显示关于对话框。"""
        _debug_log(self, "ui.toolbar", action="about", phase="requested")
        dialog = AboutDialog(self)
        dialog.installEventFilter(self)
        _debug_log(self, "ui.secondary_window", dialog="AboutDialog", phase="opened")
        result = dialog.exec_()
        _debug_log(
            self,
            "ui.secondary_window",
            dialog="AboutDialog",
            phase="closed",
            result=result,
        )

    def _show_app_manager(self):
        """为每个已选设备打开应用管理窗口。"""
        _debug_log(self, "ui.toolbar", action="app_manager", phase="requested")
        self._show_device_dialogs(AppManagerDialog)

    def _show_file_explorer(self):
        """为每个已选设备打开文件浏览窗口。"""
        _debug_log(self, "ui.toolbar", action="file_explorer", phase="requested")
        self._show_device_dialogs(FileExplorerDialog)

    def _show_logcat(self):
        """为每个已选设备打开实时 Logcat 窗口。"""
        _debug_log(self, "ui.toolbar", action="live_logcat", phase="requested")
        self._show_device_dialogs(
            LiveLogcatDialog,
            task_supervisor=self.task_supervisor,
            log_service=getattr(self, "log_service", None),
        )

    def _show_performance_monitor(self):
        """打开原生性能采集启动对话框。"""
        from gui.dialogs.performance_launcher import PerformanceLauncherDialog

        _debug_log(self, "ui.toolbar", action="performance", phase="requested")
        devices = self.left_panel.selected_devices
        if not devices:
            _debug_log(
                self,
                "ui.secondary_window",
                dialog="PerformanceLauncherDialog",
                phase="blocked",
                reason="no_device",
            )
            self.log_service.log("WARNING", "No device selected")
            return
        device_ip = devices[0]
        try:
            package_name = self.left_panel.current_package_text()
        except RuntimeError:
            package_name = ""
        dlg = self._find_active_dialog(PerformanceLauncherDialog, device_ip or "default")
        if dlg:
            _debug_log(
                self,
                "ui.secondary_window",
                dialog="PerformanceLauncherDialog",
                phase="reused",
            )
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = self._register_dialog(
            PerformanceLauncherDialog(
                device_ip=device_ip,
                package_name=package_name,
            ),
            PerformanceLauncherDialog,
            device_ip or "default",
        )
        dlg.show()

    def _show_device_dialogs(self, dialog_cls, **dialog_kwargs):
        """为选中设备创建由主窗口托管的非模态窗口。"""
        devices = self.left_panel.selected_devices
        if not devices:
            _debug_log(
                self,
                "ui.secondary_window",
                dialog=dialog_cls.__name__,
                phase="blocked",
                reason="no_device",
            )
            self.log_service.log("WARNING", "No device selected")
            return
        for ip in devices:
            dlg = self._find_active_dialog(dialog_cls, ip)
            if dlg:
                _debug_log(
                    self,
                    "ui.secondary_window",
                    dialog=dialog_cls.__name__,
                    phase="reused",
                )
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                continue
            dlg = self._register_dialog(
                dialog_cls(device_ip=ip, **dialog_kwargs),
                dialog_cls,
                ip,
            )
            dlg.show()

    def _register_dialog(self, dialog, dialog_cls=None, device_ip=None):
        configure_independent_secondary_window(dialog)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.installEventFilter(self)
        dialog_name = dialog_cls.__name__ if dialog_cls is not None else type(dialog).__name__
        if dialog_cls is not None:
            dialog.setProperty("dialog_class", dialog_name)
        if device_ip is not None:
            dialog.setProperty("device_ip", device_ip)
        self._active_dialogs.append(dialog)
        _debug_log(
            self,
            "ui.secondary_window",
            active_count=len(self._active_dialogs),
            dialog=dialog_name,
            phase="created",
        )
        dialog.destroyed.connect(
            lambda _obj=None, dlg=dialog, name=dialog_name: self._on_dialog_destroyed(
                dlg,
                name,
            )
        )
        return dialog

    def _find_active_dialog(self, dialog_cls, device_ip):
        survivors = []
        match = None
        for dialog in self._active_dialogs:
            try:
                if getattr(dialog, "_closing", False):
                    survivors.append(dialog)
                    continue
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

    def _on_dialog_destroyed(self, dialog, dialog_name: str):
        """移除已销毁窗口并记录二级窗口关闭完成。"""
        self._forget_dialog(dialog)
        _debug_log(
            self,
            "ui.secondary_window",
            active_count=len(self._active_dialogs),
            dialog=dialog_name,
            phase="closed",
        )

    def eventFilter(self, watched, event):
        """记录受主窗口托管的二级窗口关闭请求。"""
        if event.type() == QEvent.Type.Close:
            try:
                dialog_name = watched.property("dialog_class") or type(watched).__name__
            except RuntimeError:
                dialog_name = type(watched).__name__
            _debug_log(
                self,
                "ui.secondary_window",
                dialog=dialog_name,
                phase="close_requested",
            )
            return False
        return super().eventFilter(watched, event)

    def _show_settings(self):
        """显示设置对话框。"""
        _debug_log(self, "ui.toolbar", action="settings", phase="requested")
        dialog = SettingsDialog(self)
        dialog.installEventFilter(self)
        dialog.continuous_scan_toggled.connect(self.set_continuous_scan)
        _debug_log(self, "ui.secondary_window", dialog="SettingsDialog", phase="opened")
        result = dialog.exec_()
        self._refresh_save_path()
        _debug_log(
            self,
            "ui.secondary_window",
            dialog="SettingsDialog",
            phase="closed",
            result=result,
        )

    def _open_cmd(self):
        """在项目根目录打开系统终端。"""
        import platform

        _debug_log(self, "ui.toolbar", action="cmd", phase="requested")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system = platform.system()
        runner = ProcessRunner()
        if system == "Windows":
            runner.spawn(["cmd.exe", "/K", f'cd /d "{root}"'], creationflags=CREATE_NEW_CONSOLE)
            _debug_log(self, "ui.toolbar", action="cmd", backend="windows", phase="launched")
        elif system == "Darwin":
            runner.spawn(["open", "-a", "Terminal", root])
            _debug_log(self, "ui.toolbar", action="cmd", backend="macos", phase="launched")
        else:
            for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"]:
                if shutil.which(term):
                    runner.spawn([term], cwd=root)
                    _debug_log(
                        self,
                        "ui.toolbar",
                        action="cmd",
                        backend="linux",
                        phase="launched",
                    )
                    return
            _debug_log(
                self,
                "ui.toolbar",
                action="cmd",
                phase="blocked",
                reason="terminal_unavailable",
            )

    # ── 窗口和面板尺寸 ──────────────────────────────────────────────────

    def apply_window_size(self, w: int, h: int):
        screen = self.screen() or QApplication.primaryScreen()
        available_size = screen.availableGeometry().size() if screen is not None else None
        size = normalize_window_size(w, h, available_size=available_size)
        self._normal_window_size = size
        self.resize(size)

    def window_layout_snapshot(self) -> dict[str, object]:
        """返回设置页可展示的当前窗口和分栏状态。"""

        size = self._normal_window_size if self.isMaximized() else self.size()
        return {
            "width": int(size.width()),
            "height": int(size.height()),
            "panel_ratio": self.panel_split_ratio(),
        }

    def restore_default_window_size(self):
        """立即恢复默认窗口尺寸，并沿用正常的防抖持久化路径。"""

        if self.isMaximized() or self.isMinimized() or self.isFullScreen():
            self.showNormal()
        self.apply_window_size(DEFAULT_WINDOW_SIZE.width(), DEFAULT_WINDOW_SIZE.height())
        self._schedule_window_size_save(self.size())

    def reset_panel_split(self):
        """立即恢复默认分栏比例。"""

        self.apply_panel_ratio(DEFAULT_PANEL_RATIO)
        self._save_pending_panel_sizes()

    def _apply_window_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Window
        if self._always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _set_always_on_top_native(self, enabled: bool) -> bool:
        if os.name != "nt" or not self.isVisible():
            return False
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.winId())
            pointer_bits = ctypes.sizeof(ctypes.c_void_p) * 8
            hwnd_topmost = ctypes.c_void_p((1 << pointer_bits) - 1)
            hwnd_notopmost = ctypes.c_void_p((1 << pointer_bits) - 2)
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_noactivate = 0x0010
            flags = swp_nosize | swp_nomove | swp_noactivate
            set_window_pos = ctypes.windll.user32.SetWindowPos
            set_window_pos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            set_window_pos.restype = wintypes.BOOL
            return bool(
                set_window_pos(
                    ctypes.c_void_p(hwnd),
                    hwnd_topmost if enabled else hwnd_notopmost,
                    0,
                    0,
                    0,
                    0,
                    flags,
                )
            )
        except Exception:
            return False

    def set_always_on_top(self, enabled: bool):
        self._always_on_top = bool(enabled)
        native_applied = self._set_always_on_top_native(self._always_on_top)
        _debug_log(
            self,
            "ui.toolbar",
            action="always_on_top",
            enabled=self._always_on_top,
            native_applied=native_applied,
            phase="applied",
        )
        self._refresh_always_on_top_button()
        from core.settings_manager import AppSettings

        AppSettings.instance().set("always_on_top", self._always_on_top)

    def _refresh_always_on_top_button(self):
        button = getattr(self, "tb_always_on_top", None)
        if not button:
            return
        icon_name = "push-pin-slash.svg" if self._always_on_top else "push-pin.svg"
        button.setProperty("iconName", icon_name)
        button.setIcon(get_themed_icon(icon_name))
        button.setChecked(self._always_on_top)
        button.setToolTip("Unpin from top" if self._always_on_top else "Pin on top")

    def panel_sizes(self) -> list[int]:
        return self._panel_splitter.sizes() if self._panel_splitter else [400, 600]

    def panel_split_ratio(self) -> float:
        sizes = self.panel_sizes()
        if len(sizes) != 2:
            return DEFAULT_PANEL_RATIO
        return ratio_from_sizes(sizes[0], sizes[1])

    def apply_panel_sizes(self, left_w: int, right_w: int):
        if self._panel_splitter:
            self._panel_splitter.setSizes([left_w, right_w])

    def apply_panel_ratio(self, ratio: float):
        if not self._panel_splitter:
            return
        ratio = normalize_panel_ratio(ratio)
        total = max(1, sum(self._panel_splitter.sizes()))
        left_width, right_width = split_sizes_for_ratio(total, ratio)
        self._panel_ratio = ratio
        self._panel_splitter.setSizes([left_width, right_width])
        self._pending_panel_sizes = (left_width, right_width)
        responsive_timer = getattr(self, "_responsive_layout_timer", None)
        if responsive_timer is not None:
            responsive_timer.start(0)

    def _on_splitter_moved(self, _pos, _index):
        sizes = self._panel_splitter.sizes()
        if len(sizes) == 2:
            self._pending_panel_sizes = (sizes[0], sizes[1])
            self._panel_size_save_timer.start(self.SPLITTER_SAVE_DEBOUNCE_MS)
            self._responsive_layout_timer.start(0)

    def _apply_panel_responsive_layout(self):
        splitter = getattr(self, "_panel_splitter", None)
        panel = getattr(self, "left_panel", None)
        if splitter is None or panel is None:
            return
        sizes = splitter.sizes()
        if len(sizes) == 2:
            callback = getattr(panel, "apply_responsive_widths", None)
            if callable(callback):
                callback(int(sizes[0]), int(sizes[1]))

    def _save_pending_panel_sizes(self):
        if not self._pending_panel_sizes:
            return
        left_w, right_w = self._pending_panel_sizes
        self._pending_panel_sizes = None
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        ratio = ratio_from_sizes(left_w, right_w)
        self._panel_ratio = ratio
        MainFrame._update_settings(
            s,
            {
                "left_panel_width": int(left_w),
                "right_panel_width": int(right_w),
                "panel_split_ratio": ratio,
            },
        )

    @staticmethod
    def _update_settings(settings, values: dict[str, object]) -> None:
        """优先批量更新配置，并兼容尚未提供批量接口的设置对象。"""

        set_many = getattr(type(settings), "set_many", None)
        if callable(set_many):
            settings.set_many(values)
            return
        for key, value in values.items():
            settings.set(key, value)

    def _schedule_window_size_save(self, size: QSize) -> None:
        if (
            not getattr(self, "_layout_ready", False)
            or getattr(self, "_closing", False)
            or self.isMaximized()
            or self.isMinimized()
            or self.isFullScreen()
        ):
            return
        self._normal_window_size = QSize(size)
        self._pending_window_size = QSize(size)
        self._window_size_save_timer.start(self.WINDOW_SIZE_SAVE_DEBOUNCE_MS)

    def _save_pending_window_size(self) -> None:
        size = self._pending_window_size
        if size is None:
            return
        self._pending_window_size = None
        self._normal_window_size = QSize(size)
        settings = AppSettings.instance()
        MainFrame._update_settings(
            settings,
            {"window_width": int(size.width()), "window_height": int(size.height())},
        )

    def _flush_pending_layout_state(self) -> None:
        for timer, callback in (
            (getattr(self, "_window_size_save_timer", None), self._save_pending_window_size),
            (getattr(self, "_panel_size_save_timer", None), self._save_pending_panel_sizes),
        ):
            if timer is not None and timer.isActive():
                timer.stop()
                callback()

    # ── 全局保存路径 ────────────────────────────────────────────────────

    def _refresh_save_path(self):
        from core.settings_manager import AppSettings

        configured_path = AppSettings.instance().save_directory
        path = os.path.normpath(configured_path) if configured_path else ""
        if path:
            self._save_path_value = path
            self._save_path_label.setToolTip(path)
        else:
            self._save_path_value = ""
            self._save_path_label.setToolTip("")
        self._save_path_label.setStyleSheet(
            f"color: {BaseStyles.color('TEXT_SECONDARY')}; padding: 0 2px;"
        )
        self._save_path_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self._update_toolbar_path_display()

    def _update_toolbar_path_display(self):
        """按工具栏可用宽度显示、缩略或隐藏全局保存路径。"""

        label = getattr(self, "_save_path_label", None)
        if label is None:
            return
        path = getattr(self, "_save_path_value", "")
        window_width = self.width()
        if not path:
            label.clear()
            label.hide()
            return

        label.show()
        if window_width < 1040:
            tail = os.path.basename(os.path.normpath(path)) or path
            source_text = f"…{os.sep}{tail}"
            maximum_width = min(160, max(96, window_width - 760))
        else:
            maximum_width = min(420, max(160, window_width - 860))
            source_text = "GlobalSavePath: " + path
        text = label.fontMetrics().elidedText(
            source_text,
            Qt.TextElideMode.ElideMiddle,
            maximum_width,
        )
        label.setMaximumWidth(maximum_width)
        label.setText(text)
        label.updateGeometry()

    def _on_save_path_clicked(self):
        from core.settings_manager import AppSettings

        _debug_log(self, "ui.toolbar", action="save_path", phase="requested")
        s = AppSettings.instance()
        current = s.save_directory
        d = QFileDialog.getExistingDirectory(
            self, "Select Default Save Directory", current if os.path.isdir(current) else ""
        )
        if d:
            s.set("save_directory", d)
            self._refresh_save_path()
            _debug_log(self, "ui.toolbar", action="save_path", phase="updated")
        else:
            _debug_log(self, "ui.toolbar", action="save_path", phase="cancelled")

    # ── 拖动工具栏移动窗口 ──────────────────────────────────────────────

    def _is_toolbar_drag_target(self, position) -> bool:
        toolbar = getattr(self, "_toolbar", None)
        widget = self.childAt(position)
        while widget is not None:
            if isinstance(widget, QPushButton):
                return False
            if widget is toolbar:
                return True
            widget = widget.parentWidget()
        return False

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._is_toolbar_drag_target(
            event.position().toPoint()
        ):
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
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

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._is_toolbar_drag_target(
            event.position().toPoint()
        ):
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        controller = getattr(self, "_resize_controller", None)
        if controller is not None:
            controller.update_geometry()
        self._update_toolbar_path_display()
        responsive_timer = getattr(self, "_responsive_layout_timer", None)
        if responsive_timer is not None:
            responsive_timer.start(0)
        self._schedule_window_size_save(event.size())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            controller = getattr(self, "_resize_controller", None)
            if controller is not None:
                controller.update_geometry()

    def closeEvent(self, event):
        """启动异步关闭，只在资源停止和最终状态落盘完成后接受事件。"""
        if getattr(self, "_close_ready", False):
            event.accept()
            return
        event.ignore()
        if getattr(self, "_close_started", False):
            return
        self._flush_pending_layout_state()
        self._close_started = True
        self._closing = True
        self._shutdown_deadline_at = time.monotonic() + max(
            0.0,
            float(self.SHUTDOWN_DEADLINE_SECONDS),
        )
        self.log_service.log(
            "DEBUG",
            (
                "application shutdown requested: "
                f"deadline_seconds={float(self.SHUTDOWN_DEADLINE_SECONDS):.1f}"
            ),
        )
        self.setWindowTitle("ADBLab - Closing...")
        self.setEnabled(False)
        self.task_supervisor.begin_application_shutdown()
        self._register_application_shutdown_tasks()
        self._prepare_ui_for_shutdown()
        remaining = max(0.0, self._shutdown_deadline_at - time.monotonic())
        reserve = min(
            max(0.0, float(self.SHUTDOWN_FINALIZER_RESERVE_SECONDS)),
            remaining * 0.25,
        )
        self.task_supervisor.stop_all_async(deadline=max(0.0, remaining - reserve))

    def _register_application_shutdown_tasks(self):
        """按扫描、面板、对话框和 Controller 顺序注册应用级关闭资源。"""
        supervisor = self.task_supervisor.supervisor
        thread = self._scan_thread
        if thread is not None:

            def scan_running():
                try:
                    return thread.isRunning()
                except RuntimeError:
                    return False

            if scan_running():
                supervisor.register(
                    f"{self._shutdown_owner_id}-scan",
                    owner_id=self._shutdown_owner_id,
                    kind="device_scan",
                    request_stop=thread.stop,
                    wait=lambda timeout: thread.wait(max(0, int(timeout * 1000))),
                    is_running=scan_running,
                )

        register_panel_tasks = getattr(self.left_panel, "register_shutdown_tasks", None)
        if callable(register_panel_tasks):
            register_panel_tasks(
                supervisor,
                owner_id=self._shutdown_owner_id,
            )

        for index, dialog in enumerate(list(self._active_dialogs)):
            register_dialog_tasks = getattr(dialog, "register_shutdown_tasks", None)
            if not callable(register_dialog_tasks):
                continue
            try:
                register_dialog_tasks(
                    supervisor,
                    owner_id=self._shutdown_owner_id,
                    task_prefix=f"{self._shutdown_owner_id}-dialog-{index}",
                )
            except Exception as exc:
                self.log_service.log(
                    "ERROR",
                    f"Shutdown task registration failed: {type(exc).__name__}",
                    flush_immediately=True,
                )

        controller_shutdown = ThreadedShutdownTask(
            self.adb_controller.shutdown,
            name="adblab-controller-shutdown",
        )
        self._shutdown_handles.append(controller_shutdown)

        def controller_running():
            return (
                controller_shutdown.is_running()
                or ProcessRunner.tracked_active_count() > 0
            )

        def wait_for_controller(timeout: float):
            if not controller_shutdown.wait(timeout):
                return False
            return ProcessRunner.tracked_active_count() == 0

        supervisor.register(
            f"{self._shutdown_owner_id}-controller",
            owner_id=self._shutdown_owner_id,
            kind="controller_shutdown",
            request_stop=controller_shutdown.request_stop,
            wait=wait_for_controller,
            is_running=controller_running,
            force_stop=ProcessRunner.force_all_tracked,
            error_type=controller_shutdown.get_error_type,
        )

    def _prepare_ui_for_shutdown(self):
        """先停止界面定时器并断开生产者信号，再广播资源停止请求。"""
        if self._initial_refresh_timer.isActive():
            self._initial_refresh_timer.stop()
        if self._scan_refresh_timer.isActive():
            self._scan_refresh_timer.stop()
        if self._scan_thread is not None:
            self._scan_thread.stop()
            devices_changed = getattr(self._scan_thread, "devices_changed", None)
            try:
                if devices_changed is not None:
                    devices_changed.disconnect(self._schedule_scan_refresh)
            except (TypeError, RuntimeError, AttributeError):
                pass
        for dlg in list(self._active_dialogs):
            try:
                dlg.close()
            except Exception:
                pass
        # 独立窗口可能在后台资源停止前忽略关闭事件；保留强引用直到 destroyed 回调移除。
        for viewer in list(getattr(self.adb_controller, "_active_viewers", [])):
            try:
                viewer.close()
            except Exception:
                pass
        shutdown_left_panel = getattr(self.left_panel, "shutdown", None)
        if callable(shutdown_left_panel):
            shutdown_left_panel()

    def _on_application_stopped(self, results, residual):
        """汇总资源停止结果，再启动配置和日志收尾任务。"""
        if (
            not self._close_started
            or self._close_ready
            or getattr(self, "_shutdown_finalizer_started", False)
        ):
            return
        self._shutdown_finalizer_started = True
        self._shutdown_results = tuple(results)
        self._shutdown_residual = tuple(residual)
        self.log_service.log(
            "DEBUG",
            (
                "application producers stopped: "
                f"result_count={len(self._shutdown_results)} "
                f"residual_count={len(self._shutdown_residual)}"
            ),
        )
        failed = [
            result
            for result in self._shutdown_results
            if getattr(result, "disposition", None) == StopDisposition.FAILED
        ]
        if failed:
            error_types = sorted({result.error_type or "UnknownError" for result in failed})
            self.log_service.log(
                "ERROR",
                f"Shutdown task failures count={len(failed)} types={','.join(error_types)}",
                flush_immediately=True,
            )
        if self._shutdown_residual:
            kinds = sorted({item.kind for item in self._shutdown_residual})
            self.setWindowTitle(
                f"ADBLab - Closing ({len(self._shutdown_residual)} residual resources)"
            )
            self.log_service.log(
                "WARNING",
                (
                    f"Shutdown residual resources count={len(self._shutdown_residual)} "
                    f"kinds={','.join(kinds)}"
                ),
                flush_immediately=True,
            )
        if self._panel_size_save_timer.isActive():
            self._panel_size_save_timer.stop()
            self._save_pending_panel_sizes()

        # 最终用户日志必须在 GUI 线程刷新并冻结；后台 finalizer 只负责配置落盘。
        self.log_service.shutdown()
        finalizer = ThreadedShutdownTask(
            self._flush_shutdown_state,
            name="adblab-shutdown-finalizer",
        )
        self._shutdown_handles.append(finalizer)
        finalizer_task_id = f"{self._shutdown_owner_id}-finalizer"
        self.task_supervisor.supervisor.register(
            finalizer_task_id,
            owner_id=self._shutdown_owner_id,
            kind="shutdown_finalizer",
            request_stop=finalizer.request_stop,
            wait=finalizer.wait,
            is_running=finalizer.is_running,
            error_type=finalizer.get_error_type,
        )
        remaining = max(0.0, self._shutdown_deadline_at - time.monotonic())
        self.task_supervisor.stop_finalizer_async(
            finalizer_task_id,
            deadline=remaining,
        )

    def _flush_shutdown_state(self):
        """在后台原子保存待写配置；日志服务已在 GUI 线程提前关闭。"""
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        if s._save_timer:
            s._save_timer.cancel()
        s._save_atomic()

    def _on_application_finalized(self, result, residual):
        """记录收尾结果并重新触发关闭事件，使 Qt 最终销毁窗口。"""
        if not self._close_started or self._close_ready:
            return
        if result is not None:
            self._shutdown_results = (*self._shutdown_results, result)
        self._shutdown_residual = tuple(residual)
        finalizer_failed = (
            result is not None
            and result.disposition
            in {StopDisposition.FAILED, StopDisposition.TIMED_OUT}
        )
        if finalizer_failed:
            self.setWindowTitle(
                "ADBLab - Closing "
                f"(finalizer {result.disposition.value}, "
                f"{len(self._shutdown_residual)} residual resources)"
            )
        if self._shutdown_residual:
            self.setWindowTitle(
                f"ADBLab - Closing ({len(self._shutdown_residual)} residual resources)"
            )
        self._close_ready = True
        QTimer.singleShot(0, self.close)
