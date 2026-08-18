"""组装主窗口、功能面板、设备扫描和应用级关闭流程。"""

import os
import shutil
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QMouseEvent, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QToolButton,
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
from gui.dialogs.lifecycle import (
    configure_independent_secondary_window,
    fit_secondary_window_to_owner_screen,
)
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.settings_dialog import SettingsDialog
from gui.panels.log_panel import LogPanel
from gui.panels.side_panel import SidePanel
from gui.screen_adapter import QtScreenAdapter, ScreenAdapter
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.responsive_controller import ReflowReason
from gui.window_layout import (
    DEFAULT_DEVICE_LOG_RATIO,
    DEFAULT_PANEL_RATIO,
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    compute_workspace_constraints,
    normalize_panel_ratio,
    normalize_window_size,
    ratio_from_sizes,
    split_sizes_for_constraints,
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
    discovery_state_changed = Signal(str)

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
                    if not result.success:
                        self.discovery_state_changed.emit("unavailable")
                    else:
                        devices = parse_connected_devices(result.output)
                        device_set = tuple(sorted(devices))
                        if device_set != last_devices:
                            last_devices = device_set
                            self.devices_changed.emit(devices)
                        self.discovery_state_changed.emit("ready" if devices else "empty")
            except Exception:
                self.discovery_state_changed.emit("unavailable")
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
    WINDOW_SIZE_SAVE_POLL_MS = 50
    _adb_bootstrap_finished = Signal()

    def __init__(
        self,
        *,
        screen_adapter: ScreenAdapter | None = None,
        mouse_buttons_provider: Callable[[], Qt.MouseButton] | None = None,
    ):
        super().__init__()
        self._screen_adapter = screen_adapter or QtScreenAdapter()
        self._mouse_buttons_provider = mouse_buttons_provider or QApplication.mouseButtons
        self._window_screen_token = None
        self._screen_metric_tokens = []
        self._bound_window_handle = None
        self._bound_screen = None
        self._logical_dpi = 96.0
        self._preferred_window_size = QSize(DEFAULT_WINDOW_SIZE)
        self._effective_window_size = QSize(DEFAULT_WINDOW_SIZE)
        self._pending_user_window_size = None
        self._applying_workspace_constraints = False
        self._user_resize_transaction_active = False
        self._restricted_workspace = None
        self._device_layout_ready_for_constraints = False
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
        self._normal_window_size = QSize(DEFAULT_WINDOW_SIZE)
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
        self._pending_device_log_sizes = None
        self._device_log_size_save_timer = QTimer(self)
        self._device_log_size_save_timer.setSingleShot(True)
        self._device_log_size_save_timer.timeout.connect(self._save_pending_device_log_sizes)
        self._pending_window_size = None
        self._window_size_save_timer = QTimer(self)
        self._window_size_save_timer.setSingleShot(True)
        self._window_size_save_timer.timeout.connect(self._poll_user_resize_transaction)
        self._adb_bootstrap_thread = None
        self._adb_bootstrap_finished.connect(self._start_device_discovery)
        self._always_on_top = False

        self._setup_window()
        self._init_panels()
        self._sync_workspace_restriction(force=True)
        self._setup_shortcuts()
        self._resize_controller = FramelessResizeController(
            self,
            on_user_resize_started=self._begin_user_resize_transaction,
            on_user_resize_cancelled=self._cancel_user_resize_transaction,
        )
        self._layout_ready = True
        self._update_toolbar_path_display()
        self._request_side_panel_reflow(self, ReflowReason.EXPLICIT)
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
        left_panel = getattr(self, "left_panel", None)
        set_discovery_state = getattr(left_panel, "set_device_discovery_state", None)
        if callable(set_discovery_state):
            set_discovery_state("scanning")
        self._scan_thread = _ScanThread(interval_ms=interval_ms)
        self._scan_thread.devices_changed.connect(self._schedule_scan_refresh)
        discovery_state_changed = getattr(
            self._scan_thread,
            "discovery_state_changed",
            None,
        )
        if discovery_state_changed is not None and callable(set_discovery_state):
            discovery_state_changed.connect(set_discovery_state)
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
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        self._always_on_top = bool(s.get("always_on_top", False))
        self._apply_window_flags()
        configured_width = s.get("window_width", DEFAULT_WINDOW_SIZE.width())
        configured_height = s.get("window_height", DEFAULT_WINDOW_SIZE.height())
        configured_size = normalize_window_size(configured_width, configured_height)
        self._preferred_window_size = QSize(configured_size)
        self._normal_window_size = QSize(configured_size)
        self._apply_workspace_constraints(
            self._screen_adapter.window_screen(self),
            request_reflow=False,
        )
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: transparent;
                border-radius: {BaseStyles.RADIUS_XL}px;
            }}
        """)

    def _bind_window_screen(self) -> None:
        """在 window handle 可用后绑定窗口与当前屏幕的变化信号。"""

        handle = self.windowHandle()
        rebound_window = handle is not None and (
            handle is not self._bound_window_handle or self._window_screen_token is None
        )
        if rebound_window:
            self._disconnect_screen_token(self._window_screen_token)
            self._window_screen_token = self._screen_adapter.connect_window_screen_changed(
                self,
                self._on_window_screen_changed,
            )
            self._bound_window_handle = handle

        screen = self._screen_adapter.window_screen(self)
        rebound_screen = self._bind_screen_metrics(screen)
        self._apply_workspace_constraints(screen, request_reflow=False)
        if rebound_window or rebound_screen:
            self._request_side_panel_reflow(self, ReflowReason.SCREEN)

    def _bind_screen_metrics(self, screen) -> bool:
        if screen is self._bound_screen and len(self._screen_metric_tokens) == 2:
            return False
        for token in self._screen_metric_tokens:
            self._disconnect_screen_token(token)
        self._screen_metric_tokens = []
        self._bound_screen = screen
        if screen is None:
            return True
        for token in (
            self._screen_adapter.connect_available_geometry_changed(
                screen,
                self._on_screen_available_geometry_changed,
            ),
            self._screen_adapter.connect_logical_dpi_changed(
                screen,
                self._on_screen_logical_dpi_changed,
            ),
        ):
            if token is not None:
                self._screen_metric_tokens.append(token)
        return True

    def _disconnect_screen_token(self, token) -> None:
        if token is None:
            return
        try:
            self._screen_adapter.disconnect(token)
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _unbind_window_screen(self) -> None:
        """断开全部屏幕 token，使关闭后的信号不再访问 MainFrame。"""

        self._disconnect_screen_token(getattr(self, "_window_screen_token", None))
        self._window_screen_token = None
        for token in getattr(self, "_screen_metric_tokens", ()):
            self._disconnect_screen_token(token)
        self._screen_metric_tokens = []
        self._bound_window_handle = None
        self._bound_screen = None

    def _on_window_screen_changed(self, screen=None) -> None:
        if screen is None:
            screen = self._screen_adapter.window_screen(self)
        self._bind_screen_metrics(screen)
        self._apply_workspace_constraints(
            screen,
            request_reflow=True,
            reason=ReflowReason.SCREEN,
        )

    def _on_screen_available_geometry_changed(self, _geometry=None) -> None:
        self._apply_workspace_constraints(
            self._bound_screen,
            request_reflow=True,
            reason=ReflowReason.SCREEN,
        )

    def _on_screen_logical_dpi_changed(self, _dpi=None) -> None:
        self._apply_workspace_constraints(
            self._bound_screen,
            request_reflow=True,
            reason=ReflowReason.DPI,
        )

    def _apply_workspace_constraints(
        self,
        screen=None,
        *,
        request_reflow: bool = True,
        reason: ReflowReason = ReflowReason.SCREEN,
        restore_preferred_size: bool = True,
    ):
        """应用当前屏幕约束，同时保留独立的用户首选尺寸。"""

        if screen is None:
            screen = self._screen_adapter.window_screen(self)
        available_size = self._screen_adapter.available_size(screen)
        design_minimum = self._workspace_design_minimum()
        constraints = compute_workspace_constraints(
            available_size,
            self._preferred_window_size,
            design_minimum=design_minimum,
            allow_vertical_overflow=(design_minimum.height() > MINIMUM_WINDOW_SIZE.height()),
        )
        previous_restricted = self._restricted_workspace
        self._restricted_workspace = constraints.restricted
        if restore_preferred_size:
            self._effective_window_size = QSize(constraints.effective_window_size)
        self._logical_dpi = self._screen_adapter.logical_dpi(screen)
        self._applying_workspace_constraints = True
        try:
            if self.minimumSize() != constraints.minimum_window_size:
                self.setMinimumSize(constraints.minimum_window_size)
            if restore_preferred_size and self.size() != constraints.effective_window_size:
                self.resize(constraints.effective_window_size)
        finally:
            self._applying_workspace_constraints = False
        if previous_restricted != constraints.restricted:
            self._sync_workspace_restriction(force=True)
        if request_reflow:
            self._request_side_panel_reflow(self, reason)
        return constraints

    @staticmethod
    def _log_soft_minimum_height(log_panel) -> int:
        """返回可显示一行日志的字体感知软下限。"""

        if log_panel is None:
            return 32
        output = getattr(log_panel, "text_output", None)
        if output is None:
            minimum_height = getattr(log_panel, "minimumHeight", None)
            return max(32, int(minimum_height())) if callable(minimum_height) else 32
        return max(
            32,
            int(output.fontMetrics().height()) + 2 * max(0, int(output.frameWidth())),
        )

    def _apply_log_soft_minimum(self) -> int:
        """应用 Log 的非折叠软下限，并允许 splitter 在极限位置折叠它。"""

        log_panel = getattr(self, "log_panel", None)
        soft_minimum = MainFrame._log_soft_minimum_height(log_panel)
        if log_panel is None:
            return soft_minimum
        policy = log_panel.sizePolicy()
        if policy.verticalPolicy() != QSizePolicy.Policy.Ignored:
            policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
            log_panel.setSizePolicy(policy)
        if log_panel.minimumHeight() != soft_minimum:
            log_panel.setMinimumHeight(soft_minimum)
        return soft_minimum

    def _workspace_vertical_chrome_height(self) -> int:
        """返回 splitter 之外由 toolbar 与布局 margins 占用的真实高度。"""

        splitter = getattr(self, "_device_log_splitter", None)
        if self.isVisible() and splitter is not None and splitter.height() > 0:
            return max(0, self.height() - splitter.height())
        toolbar = getattr(self, "_toolbar", None)
        toolbar_height = 0
        if toolbar is not None:
            toolbar_height = max(toolbar.minimumHeight(), toolbar.minimumSizeHint().height())
        panel_layout = getattr(self, "_panel_row_layout", None)
        panel_margins = panel_layout.contentsMargins() if panel_layout is not None else None
        return toolbar_height + (
            panel_margins.top() + panel_margins.bottom() if panel_margins is not None else 0
        )

    def _workspace_design_minimum(self) -> QSize:
        """以完整 Devices、splitter handle 和一行 Log 推导主窗口最小高度。"""

        minimum = QSize(MINIMUM_WINDOW_SIZE)
        if not getattr(self, "_device_layout_ready_for_constraints", False):
            return minimum
        splitter = getattr(self, "_device_log_splitter", None)
        device_panel = getattr(getattr(self, "left_panel", None), "device_widget", None)
        if splitter is None or device_panel is None:
            return minimum
        device_minimum = MainFrame._minimum_splitter_height(device_panel)
        log_minimum = self._apply_log_soft_minimum()
        required_height = (
            self._workspace_vertical_chrome_height()
            + device_minimum
            + max(0, splitter.handleWidth())
            + log_minimum
        )
        minimum.setHeight(max(minimum.height(), required_height))
        return minimum

    def _on_side_panel_responsive_layout_settled(self, _generation: int) -> None:
        """在 Devices 计划稳定后更新字体感知窗口边界。"""

        self._device_layout_ready_for_constraints = True
        self._apply_workspace_constraints(
            self._bound_screen,
            request_reflow=False,
            restore_preferred_size=False,
        )

    def _sync_workspace_restriction(self, *, force: bool = False) -> None:
        del force
        restricted = bool(self._restricted_workspace)
        wrapper = getattr(self, "_left_panel_wrapper", None)
        if wrapper is not None:
            minimum_width = 120 if restricted else 280
            if wrapper.minimumWidth() != minimum_width:
                wrapper.setMinimumWidth(minimum_width)
        panel = getattr(self, "left_panel", None)
        setter = getattr(panel, "set_restricted_width_mode", None)
        if callable(setter):
            setter(restricted)

    def _init_panels(self):
        """构建工具栏和左右功能面板。"""
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color("WINDOW_BG")};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color("BORDER_COLOR")};
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
        # Devices 的安全下限由当前字体下的一行列表和全部动作行动态度量。
        dw.setMinimumHeight(0)
        self._apply_log_soft_minimum()

        left_wrapper = QWidget()
        left_wrapper.setObjectName("leftPanelWrapper")
        left_wrapper.setLayout(left_col)
        left_wrapper.setMinimumWidth(120 if self._restricted_workspace else 280)
        self._left_panel_wrapper = left_wrapper
        left_wrapper.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())

        panel_row = QHBoxLayout()
        panel_row.setContentsMargins(3, 3, 3, 3)
        panel_row.setSpacing(1)
        self._panel_row_layout = panel_row

        from core.settings_manager import AppSettings

        s2 = AppSettings.instance()
        stored_device_log_ratio = s2.get("device_log_split_ratio", None)
        self._device_log_ratio = normalize_panel_ratio(
            stored_device_log_ratio,
            fallback=DEFAULT_DEVICE_LOG_RATIO,
        )
        self._device_log_splitter = QSplitter(Qt.Vertical)
        self._device_log_splitter.setObjectName("deviceLogSplitter")
        self._device_log_splitter.setAccessibleName("Devices and operation log splitter")
        self._device_log_splitter.setHandleWidth(8)
        self._device_log_splitter.addWidget(dw)
        self._device_log_splitter.addWidget(self.log_panel)
        device_height, log_height = split_sizes_for_constraints(
            1000,
            self._device_log_ratio,
            left_minimum=MainFrame._minimum_splitter_height(dw),
            right_minimum=MainFrame._minimum_splitter_height(self.log_panel),
        )
        self._device_log_splitter.setSizes([device_height, log_height])
        # 两侧使用相同伸缩因子，窗口缩放时保持用户保存的实际比例。
        self._device_log_splitter.setStretchFactor(0, 1)
        self._device_log_splitter.setStretchFactor(1, 1)
        self._device_log_splitter.setChildrenCollapsible(True)
        self._device_log_splitter.setCollapsible(0, False)
        self._device_log_splitter.setCollapsible(1, True)
        self._device_log_splitter.splitterMoved.connect(self._on_device_log_splitter_moved)
        left_col.addWidget(self._device_log_splitter)

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
        left_size, right_size = split_sizes_for_constraints(
            1000,
            self._panel_ratio,
            left_minimum=left_wrapper.minimumWidth(),
            right_minimum=self.left_panel.minimumWidth(),
        )
        self._panel_splitter.setSizes([left_size, right_size])
        self._panel_splitter.setStretchFactor(0, 1)
        self._panel_splitter.setStretchFactor(1, 1)
        self._panel_splitter.setChildrenCollapsible(False)
        self._panel_splitter.splitterMoved.connect(self._on_splitter_moved)
        panel_row.addWidget(self._panel_splitter)
        main_layout.addLayout(panel_row, stretch=1)

        self.setCentralWidget(central_widget)

        self._connect_all_signals()
        self.left_panel.responsive_layout_settled.connect(
            self._on_side_panel_responsive_layout_settled
        )
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

        self._toolbar_actions = {}
        self._toolbar_action_buttons = {}
        action_specs = (
            (
                "app_mgr",
                "App Manager",
                "squares-four.svg",
                "Manage apps on the selected device",
                self._show_app_manager,
                False,
            ),
            (
                "file_explorer",
                "File Explorer",
                "folder-open.svg",
                "Browse files on the selected device",
                self._show_file_explorer,
                False,
            ),
            (
                "logcat",
                "Live Logcat",
                "scroll.svg",
                "View live logs from the selected device",
                self._show_logcat,
                False,
            ),
            (
                "performance",
                "Performance",
                "speedometer.svg",
                "Configure and start performance monitoring",
                self._show_performance_monitor,
                False,
            ),
            (
                "settings",
                "Settings",
                "gear.svg",
                "Configure application preferences",
                self._show_settings,
                False,
            ),
            (
                "cmd",
                "CMD",
                "terminal-window.svg",
                "Open a command prompt in the ADB tools folder",
                self._open_cmd,
                False,
            ),
            (
                "save_path",
                "Change default save directory",
                "folder.svg",
                "Choose the default output directory",
                self._on_save_path_clicked,
                False,
            ),
            (
                "clear",
                "Clear Log",
                "broom.svg",
                "Remove all messages from the operation log",
                self.clear_log,
                False,
            ),
            (
                "about",
                "About",
                "info.svg",
                "Show application version and project information",
                self._show_about_dialog,
                False,
            ),
            (
                "theme",
                "Toggle Light/Dark theme",
                "circle-half-tilt.svg",
                "Switch between light and dark themes",
                self._toggle_theme,
                False,
            ),
            (
                "always_on_top",
                "Pin on top",
                "push-pin.svg",
                "Keep the main window above other windows",
                self.set_always_on_top,
                True,
            ),
            (
                "minimize",
                "Minimize",
                "minus.svg",
                "Hide the main window in the taskbar",
                self._minimize_window,
                False,
            ),
            (
                "maximize",
                "Maximize",
                "square.svg",
                "Expand the main window to fill the screen",
                self._toggle_maximize_restore,
                False,
            ),
            ("exit", "Exit", "x.svg", "Close ADBLab", self._request_application_close, False),
        )
        for key, label, icon_name, tooltip, callback, checkable in action_specs:
            self._create_toolbar_action(
                key,
                label,
                icon_name,
                callback,
                tooltip=tooltip,
                checkable=checkable,
                checked=self._always_on_top if key == "always_on_top" else False,
            )

        self.tb_app_mgr = self._create_toolbar_action_button("app_mgr")
        self.tb_file_explorer = self._create_toolbar_action_button("file_explorer")
        self.tb_logcat = self._create_toolbar_action_button("logcat")
        self.tb_performance = self._create_toolbar_action_button("performance")
        self.tb_settings = self._create_toolbar_action_button("settings")
        self.tb_cmd = self._create_toolbar_action_button("cmd")
        self._tb_save_btn = self._create_toolbar_action_button("save_path")
        self._tb_save_btn.setObjectName("savePathBtn")
        self._tb_save_btn.setCursor(Qt.PointingHandCursor)

        self._save_path_label = QLabel()
        self._save_path_label.setObjectName("savePathLabel")
        self._save_path_label.setMinimumWidth(0)
        self._save_path_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        layout.addWidget(self.tb_app_mgr)
        layout.addWidget(self.tb_file_explorer)
        layout.addWidget(self.tb_logcat)
        layout.addWidget(self.tb_performance)
        layout.addWidget(self.tb_settings)
        layout.addWidget(self.tb_cmd)
        layout.addWidget(self._tb_save_btn)
        layout.addWidget(self._save_path_label)
        layout.addStretch()

        self.tb_clear = self._create_toolbar_action_button("clear")
        self.tb_about = self._create_toolbar_action_button("about")
        self.theme_btn = self._create_toolbar_action_button("theme", icon_size=QSize(16, 16))
        self.tb_always_on_top = self._create_toolbar_action_button("always_on_top")
        self._refresh_always_on_top_button()
        self.tb_minimize = self._create_toolbar_action_button("minimize")
        self.tb_maximize = self._create_toolbar_action_button("maximize")
        self.tb_exit = self._create_toolbar_action_button("exit")
        self.tb_exit.setObjectName("exit_btn")

        for btn in (
            self.tb_clear,
            self.tb_about,
            self.theme_btn,
            self.tb_always_on_top,
        ):
            layout.addWidget(btn)

        layout.addWidget(self.tb_minimize)
        layout.addWidget(self.tb_maximize)
        layout.addWidget(self.tb_exit)

        self._refresh_toolbar_metrics()
        self._refresh_save_path()

        return bar

    def _create_toolbar_action(
        self,
        key: str,
        label: str,
        icon_name: str,
        callback: Callable,
        *,
        tooltip: str,
        checkable: bool = False,
        checked: bool = False,
    ) -> QAction:
        """创建业务入口唯一持有的 QAction。"""

        action = QAction(get_themed_icon(icon_name), label, self)
        action.setToolTip(tooltip)
        action.setProperty("functionalToolTip", tooltip)
        action.setProperty("iconName", icon_name)
        action.setProperty("accessibleName", label)
        action.setProperty("accessibleDescription", tooltip)
        action.setCheckable(checkable)
        action.setChecked(checked)
        if checkable:
            action.triggered.connect(callback)
        else:
            action.triggered.connect(lambda _checked=False, handler=callback: handler())
        action.changed.connect(lambda key=key: self._sync_toolbar_action_button(key))
        self._toolbar_actions[key] = action
        return action

    def _create_toolbar_action_button(
        self,
        key: str,
        *,
        icon_size: QSize = QSize(14, 14),
    ) -> QToolButton:
        action = self._toolbar_actions[key]
        button = self._create_toolbar_btn(action.toolTip(), "", action=action)
        button.setIconSize(icon_size)
        self._toolbar_action_buttons[key] = button
        self._sync_toolbar_action_button(key)
        return button

    def _create_toolbar_btn(
        self,
        tooltip: str,
        icon_path: str,
        *,
        action: QAction | None = None,
    ) -> QToolButton:
        """创建带图标和提示文本的扁平工具栏按钮。"""
        icon_name = icon_path.replace("resources/icons/", "")
        btn = QToolButton()
        if action is not None:
            btn.setDefaultAction(action)
            icon_name = str(action.property("iconName") or "")
        elif icon_name:
            btn.setIcon(get_themed_icon(icon_name))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setProperty("iconName", icon_name)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setAutoRaise(True)
        return btn

    def _sync_toolbar_action_button(self, key: str) -> None:
        """把 QAction 的展示状态投射到兼容 QToolButton。"""

        action = getattr(self, "_toolbar_actions", {}).get(key)
        button = getattr(self, "_toolbar_action_buttons", {}).get(key)
        if action is None or button is None:
            return
        button.setEnabled(action.isEnabled())
        button.setCheckable(action.isCheckable())
        button.setChecked(action.isChecked())
        button.setIcon(action.icon())
        button.setToolTip(action.toolTip())
        button.setAccessibleName(str(action.property("accessibleName") or action.text()))
        button.setAccessibleDescription(str(action.property("accessibleDescription") or ""))
        button.setProperty("iconName", action.property("iconName"))

    def _set_toolbar_action_state(
        self,
        key: str,
        button_name: str,
        *,
        enabled: bool | None = None,
        checked: bool | None = None,
        tooltip: str | None = None,
        accessible_name: str | None = None,
        icon_name: str | None = None,
    ) -> None:
        """优先写 canonical QAction，并兼容只构造旧按钮的轻量调用方。"""

        action = getattr(self, "_toolbar_actions", {}).get(key)
        target = action or getattr(self, button_name, None)
        if target is None:
            return
        if enabled is not None:
            target.setEnabled(enabled)
        if checked is not None:
            target.setChecked(checked)
        if tooltip is not None:
            target.setToolTip(tooltip)
        if accessible_name is not None:
            if action is not None:
                action.setText(accessible_name)
                action.setProperty("accessibleName", accessible_name)
            else:
                target.setAccessibleName(accessible_name)
        if icon_name is not None:
            target.setProperty("iconName", icon_name)
            target.setIcon(get_themed_icon(icon_name))
        if action is not None:
            self._sync_toolbar_action_button(key)

    def _setup_shortcuts(self) -> None:
        """注册不占用 Remote 启停组合键的主窗口快捷操作。"""

        bindings = (
            ("F5", self._request_device_refresh),
            ("Ctrl+,", self._show_settings),
            ("Ctrl+Shift+L", self.clear_log),
        )
        self._main_shortcuts = []
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._main_shortcuts.append(shortcut)

    def _request_device_refresh(self) -> None:
        """先公开扫描状态，再通过既有信号请求刷新。"""

        self.left_panel.set_device_discovery_state("scanning")
        self.left_panel.signals.refresh_devices_requested.emit()

    def _refresh_toolbar_metrics(self) -> None:
        """按当前界面字体更新工具栏高度和图标按钮点击区域。"""

        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None:
            return
        toolbar_height = BaseStyles.control_height(minimum=32, padding=8)
        requested_button_height = BaseStyles.control_height(minimum=24, padding=4)
        button_height = min(requested_button_height, max(24, toolbar_height - 2))
        size = QSize(max(28, button_height), button_height)
        toolbar.setMinimumHeight(toolbar_height)
        for button in toolbar.findChildren(QAbstractButton):
            button.setFixedSize(size)
        toolbar.updateGeometry()

    def _on_theme_changed(self, _name: str):
        """主题变化后刷新窗口样式和图标，并持久化主题选择。"""
        _debug_log(self, "ui.toolbar", action="theme", phase="applied", theme=_name)
        from core.settings_manager import AppSettings

        AppSettings.instance().set("theme", _name)

        self.centralWidget().setStyleSheet(f"""
            #centralWidget {{
                background-color: {BaseStyles.color("WINDOW_BG")};
                border-radius: {BaseStyles.RADIUS_XL}px;
                border: 1px solid {BaseStyles.color("BORDER_COLOR")};
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
        self._refresh_toolbar_metrics()
        self._refresh_save_path()

    def _apply_splitter_style(self):
        """隐藏常驻分隔线，同时保留足够宽的透明拖动热区。"""

        for splitter in (
            getattr(self, "_panel_splitter", None),
            getattr(self, "_device_log_splitter", None),
        ):
            if splitter is not None:
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

    def _toggle_maximize_restore(self):
        """切换最大化状态，并同步窗口控制按钮的图标和说明。"""

        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._refresh_maximize_button()

    def _refresh_maximize_button(self) -> None:
        maximized = self.isMaximized()
        label = "Restore" if maximized else "Maximize"
        tooltip = (
            "Restore the main window to its previous size"
            if maximized
            else "Expand the main window to fill the screen"
        )
        icon_name = "corners-in.svg" if maximized else "square.svg"
        MainFrame._set_toolbar_action_state(
            self,
            "maximize",
            "tb_maximize",
            tooltip=tooltip,
            accessible_name=label,
            icon_name=icon_name,
        )

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
        actions = tuple(getattr(self, "_toolbar_actions", {}).values())
        for action in actions:
            icon_name = action.property("iconName")
            if icon_name:
                action.setIcon(get_themed_icon(icon_name))
        for button in self.findChildren(QAbstractButton):
            icon_name = button.property("iconName")
            default_action = button.defaultAction() if isinstance(button, QToolButton) else None
            if icon_name and default_action not in actions:
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
        self.left_panel.selected_devices_changed.connect(self._update_device_toolbar_actions)
        self._update_device_toolbar_actions()

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
        CTL.record_target_finished.connect(self.left_panel.on_recording_target_finished)
        CTL.monkey_target_finished.connect(self.left_panel.on_monkey_target_finished)
        operation_handler = getattr(
            self,
            "_on_operation_completed",
            self.left_panel.on_operation_completed,
        )
        CTL.operation_completed.connect(operation_handler)
        CTL.current_package_received.connect(self.left_panel.update_current_package)
        CTL.device_info_updated.connect(
            lambda _ip, info: self.log_service.log(
                "INFO",
                f"Device information updated: field_count={len(info)}",
            )
        )

    def _on_operation_completed(self, operation: str, success: bool, message: str) -> None:
        """转发操作结果，并将刷新失败映射为明确的 ADB 不可用状态。"""

        self.left_panel.on_operation_completed(operation, success, message)
        if operation == "refresh" and not success:
            QTimer.singleShot(
                0,
                lambda: self.left_panel.set_device_discovery_state("unavailable"),
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
            (LP.screen_record_batch_requested, AC.start_screen_record),
            (LP.stop_screen_record_requested, AC.stop_screen_record),
            (LP.stop_screen_record_batch_requested, AC.stop_screen_record),
            (LP.batch_install_requested, AC.batch_install_apk),
            (LP.retrieve_logs_requested, AC.retrieve_device_logs),
            (LP.cleanup_logs_requested, AC.cleanup_device_logs),
            (LP.send_text_requested, AC.input_text),
            (LP.input_tap_requested, AC.input_tap),
            (LP.input_swipe_requested, AC.input_swipe),
            (LP.input_keyevent_requested, AC.input_keyevent),
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
            (LP.disable_app_for_user_requested, AC.disable_app_for_user),
            (LP.enable_app_requested, AC.enable_app),
            (LP.force_stop_requested, AC.force_stop),
            (LP.send_broadcast_requested, AC.send_broadcast),
            (LP.start_activity_requested, AC.start_activity),
            (LP.open_deep_link_requested, AC.open_deep_link),
        ]

    def _testing_signal_map(self, LP, AC):
        return [
            (LP.start_monkey_requested, AC.run_monkey_test),
            (LP.start_monkey_batch_requested, AC.run_monkey_test),
            (LP.kill_monkey_requested, AC.kill_monkey),
            (LP.kill_monkey_batch_requested, AC.kill_monkey),
            (LP.capture_bugreport_requested, AC.capture_bugreport),
            (LP.pull_anr_file_requested, AC.pull_anr_files),
            (LP.dumpsys_meminfo_requested, AC.dumpsys_meminfo),
            (LP.dumpsys_cpuinfo_requested, AC.dumpsys_cpuinfo),
            (LP.dumpsys_battery_requested, AC.dumpsys_battery),
            (LP.top_snapshot_requested, AC.top_snapshot),
            (LP.gfxinfo_requested, AC.gfxinfo),
            (LP.wakelocks_requested, AC.wakelocks),
            (LP.netstats_detail_requested, AC.netstats_detail),
        ]

    def _system_signal_map(self, LP, AC):
        return [
            (LP.shell_command_requested, AC.run_shell_command),
            (LP.dumpsys_service_requested, AC.dumpsys_service),
            (LP.kernel_version_requested, AC.kernel_version),
            (LP.cpu_info_requested, AC.cpu_info),
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
        self._update_device_toolbar_actions()

    def _update_device_toolbar_actions(self, _devices=None) -> None:
        """让所有顶部设备入口跟随当前复选设备集合。"""

        selected_count = len(self.left_panel.selected_devices)
        has_selection = selected_count > 0
        for key, button_name, label, description in (
            (
                "app_mgr",
                "tb_app_mgr",
                "App Manager",
                "Manage apps on the selected device",
            ),
            (
                "file_explorer",
                "tb_file_explorer",
                "File Explorer",
                "Browse files on the selected device",
            ),
            (
                "logcat",
                "tb_logcat",
                "Live Logcat",
                "View live logs from the selected device",
            ),
        ):
            MainFrame._set_toolbar_action_state(
                self,
                key,
                button_name,
                enabled=has_selection,
                tooltip=description if has_selection else "Select a device first",
                accessible_name=label,
            )

        if selected_count == 1:
            performance_tooltip = "Configure and start performance monitoring"
        elif selected_count > 1:
            performance_tooltip = "Performance requires exactly one selected device"
        else:
            performance_tooltip = "Select a device first"
        MainFrame._set_toolbar_action_state(
            self,
            "performance",
            "tb_performance",
            enabled=selected_count == 1,
            tooltip=performance_tooltip,
            accessible_name="Performance",
        )

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
        if len(devices) != 1:
            _debug_log(
                self,
                "ui.secondary_window",
                dialog="PerformanceLauncherDialog",
                phase="blocked",
                reason="ambiguous_device_selection",
            )
            self.log_service.log(
                "WARNING",
                "Performance requires exactly one selected device",
            )
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
            MainFrame._show_fitted_dialog(self, dlg)
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
                MainFrame._show_fitted_dialog(self, dlg)
                continue
            dlg = self._register_dialog(
                dialog_cls(device_ip=ip, **dialog_kwargs),
                dialog_cls,
                ip,
            )
            dlg.show()

    def _register_dialog(self, dialog, dialog_cls=None, device_ip=None):
        configure_independent_secondary_window(dialog)
        fit_secondary_window_to_owner_screen(dialog, self)
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

    def _show_fitted_dialog(self, dialog) -> None:
        """复用二级窗口前重新限制几何，并将其激活。"""

        try:
            fit_secondary_window_to_owner_screen(dialog, self)
        except (AttributeError, RuntimeError, TypeError):
            pass
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
        """显示或激活非模态的单实例设置窗口。"""
        _debug_log(self, "ui.toolbar", action="settings", phase="requested")
        dialog = self._find_active_dialog(SettingsDialog, "global")
        if dialog:
            MainFrame._show_fitted_dialog(self, dialog)
            return
        dialog = self._register_dialog(SettingsDialog(self), SettingsDialog, "global")
        dialog.continuous_scan_toggled.connect(self.set_continuous_scan)
        dialog.log_max_lines_changed.connect(self.log_panel.set_max_lines)
        dialog.save_directory_changed.connect(lambda _path: self._refresh_save_path())
        dialog.settings_applied.connect(self._refresh_live_settings)
        _debug_log(self, "ui.secondary_window", dialog="SettingsDialog", phase="opened")
        dialog.show()

    def _refresh_live_settings(self) -> None:
        """让主窗口和已加载页签重新读取可即时生效的设置。"""

        settings = AppSettings.instance()
        always_on_top = bool(settings.get("always_on_top", False))
        if always_on_top != self._always_on_top:
            self.set_always_on_top(always_on_top)
        else:
            self._refresh_always_on_top_button()
        self.log_panel.set_max_lines(settings.get("log_max_lines", 2000))
        refresh_panels = getattr(self.left_panel, "refresh_from_settings", None)
        if callable(refresh_panels):
            refresh_panels()
        self._refresh_save_path()

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
        self._cancel_user_resize_transaction()
        preferred = normalize_window_size(w, h)
        self._preferred_window_size = QSize(preferred)
        self._normal_window_size = QSize(preferred)
        self._apply_workspace_constraints(self._bound_screen, request_reflow=True)
        self._persist_window_size(preferred)

    def window_layout_snapshot(self) -> dict[str, object]:
        """返回设置页可展示的当前窗口和分栏状态。"""

        size = (
            self._pending_user_window_size
            or self._preferred_window_size
            or self._normal_window_size
        )
        return {
            "width": int(size.width()),
            "height": int(size.height()),
            "panel_ratio": self.panel_split_ratio(),
            "device_log_ratio": self.device_log_split_ratio(),
        }

    def restore_default_window_size(self):
        """立即恢复并持久化默认窗口尺寸。"""

        if self.isMaximized() or self.isMinimized() or self.isFullScreen():
            self.showNormal()
        self.apply_window_size(DEFAULT_WINDOW_SIZE.width(), DEFAULT_WINDOW_SIZE.height())

    def reset_panel_split(self):
        """立即恢复水平分栏和设备/日志纵向分栏的默认比例。"""

        for timer in (
            getattr(self, "_panel_size_save_timer", None),
            getattr(self, "_device_log_size_save_timer", None),
        ):
            if timer is not None and timer.isActive():
                timer.stop()
        self.apply_panel_ratio(DEFAULT_PANEL_RATIO)
        self.apply_device_log_ratio(DEFAULT_DEVICE_LOG_RATIO)
        self._save_pending_panel_sizes()
        self._save_pending_device_log_sizes()

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
        action = getattr(self, "_toolbar_actions", {}).get("always_on_top")
        button = getattr(self, "tb_always_on_top", None)
        if action is None and button is None:
            return
        icon_name = "push-pin-slash.svg" if self._always_on_top else "push-pin.svg"
        label = "Unpin from top" if self._always_on_top else "Pin on top"
        tooltip = (
            "Allow other windows above the main window"
            if self._always_on_top
            else "Keep the main window above other windows"
        )
        MainFrame._set_toolbar_action_state(
            self,
            "always_on_top",
            "tb_always_on_top",
            checked=self._always_on_top,
            tooltip=tooltip,
            accessible_name=label,
            icon_name=icon_name,
        )

    def panel_sizes(self) -> list[int]:
        return self._panel_splitter.sizes() if self._panel_splitter else [400, 600]

    def device_log_split_ratio(self) -> float:
        """返回左侧设备区域在设备/日志纵向分栏中的实际比例。"""

        splitter = getattr(self, "_device_log_splitter", None)
        sizes = splitter.sizes() if splitter is not None else []
        if len(sizes) != 2 or sum(sizes) <= 0:
            return DEFAULT_DEVICE_LOG_RATIO
        return normalize_panel_ratio(
            sizes[0] / sum(sizes),
            fallback=DEFAULT_DEVICE_LOG_RATIO,
        )

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
        left_panel = self._panel_splitter.widget(0)
        right_panel = self._panel_splitter.widget(1)
        left_width, right_width = split_sizes_for_constraints(
            total,
            ratio,
            left_minimum=left_panel.minimumWidth() if left_panel is not None else 0,
            right_minimum=right_panel.minimumWidth() if right_panel is not None else 0,
        )
        self._panel_splitter.setSizes([left_width, right_width])
        actual_sizes = self._panel_splitter.sizes()
        if len(actual_sizes) == 2 and sum(actual_sizes) > 0:
            left_width, right_width = map(int, actual_sizes)
        self._panel_ratio = ratio_from_sizes(left_width, right_width)
        self._pending_panel_sizes = (left_width, right_width)
        MainFrame._request_side_panel_reflow(self, ReflowReason.SPLITTER)

    def apply_device_log_ratio(self, ratio: float) -> None:
        """按约束应用设备/日志纵向比例，并准备统一持久化。"""

        splitter = getattr(self, "_device_log_splitter", None)
        if splitter is None:
            return
        ratio = normalize_panel_ratio(ratio, fallback=DEFAULT_DEVICE_LOG_RATIO)
        total = max(1, sum(splitter.sizes()))
        device_panel = splitter.widget(0)
        log_panel = splitter.widget(1)
        device_height, log_height = MainFrame._device_log_split_sizes(
            total,
            ratio,
            device_minimum=MainFrame._minimum_splitter_height(device_panel),
            log_minimum=MainFrame._log_soft_minimum_height(log_panel),
        )
        splitter.setSizes([device_height, log_height])
        actual_sizes = splitter.sizes()
        if len(actual_sizes) == 2 and sum(actual_sizes) > 0:
            device_height, log_height = map(int, actual_sizes)
        self._device_log_ratio = normalize_panel_ratio(
            device_height / max(1, device_height + log_height),
            fallback=DEFAULT_DEVICE_LOG_RATIO,
        )
        self._pending_device_log_sizes = (device_height, log_height)
        MainFrame._request_side_panel_reflow(self, ReflowReason.SPLITTER)

    def _on_splitter_moved(self, _pos, _index):
        sizes = self._panel_splitter.sizes()
        if len(sizes) == 2:
            total = max(0, int(sizes[0]) + int(sizes[1]))
            left_panel = self._panel_splitter.widget(0)
            right_panel = self._panel_splitter.widget(1)
            corrected_sizes = split_sizes_for_constraints(
                total,
                sizes[0] / total if total else DEFAULT_PANEL_RATIO,
                left_minimum=left_panel.minimumWidth() if left_panel is not None else 0,
                right_minimum=right_panel.minimumWidth() if right_panel is not None else 0,
            )
            if tuple(map(int, sizes)) != corrected_sizes:
                self._panel_splitter.setSizes(list(corrected_sizes))
            self._pending_panel_sizes = corrected_sizes
            self._panel_size_save_timer.start(self.SPLITTER_SAVE_DEBOUNCE_MS)
            MainFrame._request_side_panel_reflow(self, ReflowReason.SPLITTER)

    @staticmethod
    def _request_side_panel_reflow(owner, reason: ReflowReason) -> None:
        """以兼容 mock/精简壳对象的方式请求 SidePanel 响应式重排。"""

        panel = getattr(owner, "left_panel", None)
        callback = getattr(panel, "request_responsive_reflow", None)
        if callable(callback):
            callback(reason)

    def _save_pending_panel_sizes(self):
        if not self._pending_panel_sizes:
            return
        left_w, right_w = self._pending_panel_sizes
        splitter = getattr(self, "_panel_splitter", None)
        actual_sizes = splitter.sizes() if splitter is not None else []
        if len(actual_sizes) == 2 and sum(actual_sizes) > 0:
            left_w, right_w = map(int, actual_sizes)
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

    def _on_device_log_splitter_moved(self, _pos, _index) -> None:
        """限制设备/日志区域最小高度，并防抖保存最终比例。"""

        splitter = self._device_log_splitter
        sizes = splitter.sizes()
        if len(sizes) != 2:
            return
        total = max(0, int(sizes[0]) + int(sizes[1]))
        if total <= 0:
            return
        device_panel = splitter.widget(0)
        log_panel = splitter.widget(1)
        corrected_sizes = MainFrame._device_log_split_sizes(
            total,
            sizes[0] / total,
            device_minimum=MainFrame._minimum_splitter_height(device_panel),
            log_minimum=MainFrame._log_soft_minimum_height(log_panel),
            log_collapsed=int(sizes[1]) <= 0,
        )
        if tuple(map(int, sizes)) != corrected_sizes:
            splitter.setSizes(list(corrected_sizes))
        self._pending_device_log_sizes = corrected_sizes
        self._device_log_ratio = normalize_panel_ratio(
            corrected_sizes[0] / max(1, sum(corrected_sizes)),
            fallback=DEFAULT_DEVICE_LOG_RATIO,
        )
        self._device_log_size_save_timer.start(self.SPLITTER_SAVE_DEBOUNCE_MS)
        MainFrame._request_side_panel_reflow(self, ReflowReason.SPLITTER)

    @staticmethod
    def _minimum_splitter_height(widget) -> int:
        """返回可避免内容相交的纵向分栏最小高度。"""

        if widget is None:
            return 0
        minimum = max(0, int(widget.minimumHeight()))
        size_hint = getattr(widget, "minimumSizeHint", None)
        if not callable(size_hint):
            return minimum
        try:
            return max(minimum, int(size_hint().height()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return minimum

    @staticmethod
    def _device_log_split_sizes(
        total: int,
        ratio: float,
        *,
        device_minimum: int,
        log_minimum: int,
        log_collapsed: bool = False,
    ) -> tuple[int, int]:
        """优先满足 Devices；空间不足或用户越过软下限时折叠 Log。"""

        total = max(0, int(total))
        device_minimum = max(0, int(device_minimum))
        log_minimum = max(0, int(log_minimum))
        if total <= 0:
            return 0, 0
        if log_collapsed or total < device_minimum + log_minimum:
            return total, 0
        return split_sizes_for_constraints(
            total,
            ratio,
            left_minimum=device_minimum,
            right_minimum=log_minimum,
        )

    def _save_pending_device_log_sizes(self) -> None:
        """持久化 Qt 实际采用的设备/日志高度比例。"""

        if not self._pending_device_log_sizes:
            return
        device_height, log_height = self._pending_device_log_sizes
        splitter = getattr(self, "_device_log_splitter", None)
        actual_sizes = splitter.sizes() if splitter is not None else []
        if len(actual_sizes) == 2 and sum(actual_sizes) > 0:
            device_height, log_height = map(int, actual_sizes)
        self._pending_device_log_sizes = None
        total = max(1, device_height + log_height)
        ratio = normalize_panel_ratio(
            device_height / total,
            fallback=DEFAULT_DEVICE_LOG_RATIO,
        )
        self._device_log_ratio = ratio
        MainFrame._update_settings(
            AppSettings.instance(),
            {"device_log_split_ratio": ratio},
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
            not getattr(self, "_user_resize_transaction_active", False)
            or not getattr(self, "_layout_ready", False)
            or getattr(self, "_closing", False)
            or getattr(self, "_applying_workspace_constraints", False)
            or self.isMaximized()
            or self.isMinimized()
            or self.isFullScreen()
        ):
            return
        self._normal_window_size = QSize(size)
        self._effective_window_size = QSize(size)
        self._pending_user_window_size = QSize(size)
        self._window_size_save_timer.start(self.WINDOW_SIZE_SAVE_DEBOUNCE_MS)

    def _save_pending_window_size(self) -> None:
        size = getattr(self, "_pending_user_window_size", None)
        if size is None:
            size = getattr(self, "_pending_window_size", None)
        if size is None:
            self._user_resize_transaction_active = False
            return
        self._pending_user_window_size = None
        self._pending_window_size = None
        self._normal_window_size = QSize(size)
        self._preferred_window_size = QSize(size)
        self._user_resize_transaction_active = False
        self._persist_window_size(size)

    def _poll_user_resize_transaction(self) -> None:
        if not getattr(self, "_user_resize_transaction_active", False):
            return
        if self._mouse_buttons_provider() & Qt.MouseButton.LeftButton:
            self._window_size_save_timer.start(self.WINDOW_SIZE_SAVE_POLL_MS)
            return
        self._finish_user_resize_transaction()

    def _persist_window_size(self, size: QSize) -> None:
        settings = AppSettings.instance()
        MainFrame._update_settings(
            settings,
            {"window_width": int(size.width()), "window_height": int(size.height())},
        )

    def _begin_user_resize_transaction(self) -> None:
        """只为成功启动的原生边缘缩放开启可持久化事务。"""

        self._discard_pending_user_resize()
        self._user_resize_transaction_active = True
        self._window_size_save_timer.start(self.WINDOW_SIZE_SAVE_DEBOUNCE_MS)

    def _finish_user_resize_transaction(self) -> None:
        if getattr(self, "_pending_user_window_size", None) is None:
            self._cancel_user_resize_transaction()
            return
        timer = getattr(self, "_window_size_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._save_pending_window_size()

    def _cancel_user_resize_transaction(self) -> None:
        self._user_resize_transaction_active = False
        self._discard_pending_user_resize()

    def _discard_pending_user_resize(self) -> None:
        timer = getattr(self, "_window_size_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._pending_user_window_size = None
        self._pending_window_size = None

    def _flush_pending_layout_state(self) -> None:
        for timer, callback in (
            (getattr(self, "_window_size_save_timer", None), MainFrame._save_pending_window_size),
            (getattr(self, "_panel_size_save_timer", None), MainFrame._save_pending_panel_sizes),
            (
                getattr(self, "_device_log_size_save_timer", None),
                MainFrame._save_pending_device_log_sizes,
            ),
        ):
            if timer is not None and timer.isActive():
                timer.stop()
                callback(self)

    # ── 全局保存路径 ────────────────────────────────────────────────────

    def _sync_save_path_action(self, path: str) -> None:
        """让默认按钮公开当前完整保存路径。"""

        action = getattr(self, "_toolbar_actions", {}).get("save_path")
        if action is None:
            return
        label = "Change default save directory"
        if path:
            current_path = f"Current save directory: {path}"
            action.setText(f"{label} — {path.replace('&', '&&')}")
            action.setToolTip(f"Choose a different default output directory\n{current_path}")
            action.setStatusTip(current_path)
            action.setProperty("accessibleDescription", current_path)
        else:
            action.setText(label)
            action.setToolTip("Choose the default output directory")
            action.setStatusTip("")
            action.setProperty("accessibleDescription", "")
        action.setProperty("accessibleName", label)
        MainFrame._sync_toolbar_action_button(self, "save_path")

    def _refresh_save_path(self):
        from core.settings_manager import AppSettings

        configured_path = AppSettings.instance().save_directory
        path = os.path.normpath(configured_path) if configured_path else ""
        MainFrame._sync_save_path_action(self, path)
        if path:
            self._save_path_value = path
            self._save_path_label.setToolTip(path)
            self._save_path_label.setAccessibleName("Global save path")
            self._save_path_label.setAccessibleDescription(path)
        else:
            self._save_path_value = ""
            self._save_path_label.setToolTip("")
            self._save_path_label.setAccessibleDescription("")
        self._save_path_label.setStyleSheet(
            f"color: {BaseStyles.color('TEXT_SECONDARY')}; padding: 0 2px;"
        )
        self._save_path_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self._update_toolbar_path_display()

    def _update_toolbar_path_display(self):
        """按工具栏扣除其余控件后的真实剩余宽度省略保存路径。"""

        label = getattr(self, "_save_path_label", None)
        if label is None:
            return
        path = getattr(self, "_save_path_value", "")
        if not path:
            label.clear()
            label.hide()
            return

        save_button = getattr(self, "_tb_save_btn", None)
        if save_button is not None and save_button.isHidden():
            label.hide()
            return

        toolbar = getattr(self, "_toolbar", None)
        layout = toolbar.layout() if toolbar is not None else None
        if toolbar is None or layout is None:
            return
        margins = layout.contentsMargins()
        active_items = []
        required_width = 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is not None and widget is not label and widget.isHidden():
                continue
            active_items.append(item)
            if widget is None or widget is label:
                continue
            if widget.minimumWidth() == widget.maximumWidth():
                required_width += widget.minimumWidth()
            else:
                required_width += max(widget.minimumWidth(), widget.sizeHint().width())
        spacing_width = max(0, len(active_items) - 1) * max(0, layout.spacing())
        maximum_width = max(
            0,
            min(
                420,
                toolbar.width() - margins.left() - margins.right() - required_width - spacing_width,
            ),
        )
        label.setVisible(maximum_width > 0)
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
            if isinstance(widget, QAbstractButton):
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
            self._toggle_maximize_restore()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        controller = getattr(self, "_resize_controller", None)
        if controller is not None:
            controller.update_geometry()
        self._update_toolbar_path_display()
        self._schedule_window_size_save(event.size())

    def showEvent(self, event):
        super().showEvent(event)
        self._bind_window_screen()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._finish_user_resize_transaction()
            controller = getattr(self, "_resize_controller", None)
            if controller is not None:
                controller.update_geometry()
            self._refresh_maximize_button()

    def closeEvent(self, event):
        """启动异步关闭，只在资源停止和最终状态落盘完成后接受事件。"""
        self._unbind_window_screen()
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
            return controller_shutdown.is_running() or ProcessRunner.tracked_active_count() > 0

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
            discovery_state_changed = getattr(
                self._scan_thread,
                "discovery_state_changed",
                None,
            )
            try:
                if devices_changed is not None:
                    devices_changed.disconnect(self._schedule_scan_refresh)
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                if discovery_state_changed is not None:
                    discovery_state_changed.disconnect(self.left_panel.set_device_discovery_state)
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
        finalizer_failed = result is not None and result.disposition in {
            StopDisposition.FAILED,
            StopDisposition.TIMED_OUT,
        }
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
