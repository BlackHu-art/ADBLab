"""组装主窗口、功能面板、设备扫描和应用级关闭流程。"""

import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QRect,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QFocusEvent, QIcon, QRegion, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    FluentStyleSheet,
    FluentTitleBar,
    FluentWindow,
    MessageBox,
    NavigationDisplayMode,
    NavigationItemPosition,
    NavigationPanel,
    SmoothScrollArea,
    setCustomStyleSheet,
)
from shiboken6 import isValid

from controllers import ADBController
from controllers.action_catalog import ACTION_SIGNALS
from core.exec import (
    CREATE_NEW_CONSOLE,
    ProcessRunner,
)
from core.log_service import LogService
from core.settings_manager import AppSettings, set_error_sink
from core.startup_diagnostics import StartupDiagnostics
from core.tasks.qt_supervisor import QtTaskSupervisor
from core.tasks.supervision import TaskStopResult
from gui.action_feedback import ActionFeedbackPresenter
from gui.adapters.apk_file_picker import QtApkFilePicker
from gui.adapters.app_update import QtAppUpdate
from gui.adapters.device_connection_lifecycle import QtDeviceConnectionLifecycle
from gui.adapters.installer_handoff import QtInstallerHandoff
from gui.close_controller import CloseController
from gui.dialogs.fluent_dialog import _apply_role_font as apply_dialog_font_role
from gui.i18n import tr
from gui.main_frame_actions import MainFrameActions
from gui.notifications import show_toast
from gui.pages.device_hub import DeviceHubPage, _connection_kind, _device_name, _metadata_text
from gui.pages.fluent_pages import (
    GalleryPage,
    HomePage,
    SettingsPage,
    WorkspaceAreaPage,
    WorkspaceSectionPage,
)
from gui.pages.tasks_page import TaskCenterPage, _operation_label
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute
from gui.panels.side_panel import SidePanel
from gui.run_library import RunLibraryController
from gui.screen_adapter import QtScreenAdapter, ScreenAdapter
from gui.startup_stages import WindowStartupStage
from gui.styles.icon_loader import DEVICE_ICON
from gui.widgets.device_context_bar import DeviceContextBar
from gui.widgets.frame_animation import FrameAnimation
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.layout_settle import settle_responsive_layout
from gui.widgets.navigation_theme import NavigationThemeToggle
from gui.widgets.page_transition import PageTransition
from gui.widgets.responsive_controller import ReflowReason
from gui.window_layout import (
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    compute_workspace_constraints,
    normalize_window_size,
)
from gui.workers.device_discovery import _ScanDiscoveryState as _ScanDiscoveryState
from gui.workers.device_discovery import _ScannedDevices as _ScannedDevices
from gui.workers.device_discovery import _ScanThread as _ScanThread
from models.device_store import DeviceStore
from services.run_library import RunLibrary, RunRecord
from services.task_history import TaskHistoryStore
from utils.resource_path import resource_path

from .styles import BaseStyles, FontRole
from .styles.fluent import (
    apply_label_role,
    font_qss,
    refresh_fluent_widget_style,
    set_fluent_font_rule,
    use_smooth_scroll,
)
from .styles.theme import apply_dark_title_bar

if TYPE_CHECKING:
    from core.installer_handoff import InstallerHandoff
    from gui.adapters.installer_update import QtInstallerUpdate
    from services.app_update import InstallerAsset


def _debug_log(owner, event: str, **fields) -> None:
    """输出不含敏感业务值的结构化开发诊断。"""
    log_service = getattr(owner, "log_service", None)
    if log_service is None:
        return
    details = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    message = event if not details else f"{event} {details}"
    log_service.log("DEBUG", message)


class MainFrame(FluentWindow):
    startup_aborted = Signal()
    SHUTDOWN_DEADLINE_SECONDS = 6.0
    SHUTDOWN_FINALIZER_RESERVE_SECONDS = 1.0
    DEVICE_SCAN_DEBOUNCE_MS = 300
    WINDOW_SIZE_SAVE_DEBOUNCE_MS = 350
    WINDOW_SIZE_SAVE_POLL_MS = 50
    NAVIGATION_EXPAND_BREAKPOINT = 1120
    NAVIGATION_LAYOUT_DEBOUNCE_MS = 60
    _QFLUENT_DEFAULT_EXPAND_WIDTH = 322
    _CONTENT_CORNER_RADIUS = 10

    def __init__(
        self,
        *,
        screen_adapter: ScreenAdapter | None = None,
        mouse_buttons_provider: Callable[[], Qt.MouseButton] | None = None,
        deferred_startup: bool = False,
        device_history_loaded: bool = False,
        handoff: "InstallerHandoff | None" = None,
    ):
        super().__init__()
        self._deferred_startup = deferred_startup
        self.startup_diagnostics: StartupDiagnostics | None = None
        # 仅 GUI 启动门禁完成后跳过重复读取；直接构造保留原有同步初始化契约。
        self._device_history_loaded = device_history_loaded
        # 安装资格仅由根入口注入；源码和便携版不能通过页面状态自行授予资格。
        self._handoff = handoff
        self._installer_update: QtInstallerUpdate | None = None
        self._installer_handoff: QtInstallerHandoff | None = None
        self._installer_close_requested = False
        self._installer_confirmation_pending = False
        self._installer_requested_asset: InstallerAsset | None = None
        self._startup_complete = False
        self._startup_aborting = False
        self._startup_abort_reported = False
        self._startup_services_started = False
        self._startup_failed = False
        self._sync_material_surface_styles()
        self._screen_adapter = screen_adapter or QtScreenAdapter()
        self._mouse_buttons_provider = mouse_buttons_provider or QApplication.mouseButtons
        self._window_screen_token = None
        self._screen_metric_tokens = []
        self._bound_window_handle = None
        self._bound_screen = None
        self._preferred_window_size = QSize(DEFAULT_WINDOW_SIZE)
        self._effective_window_size = QSize(DEFAULT_WINDOW_SIZE)
        self._pending_user_window_size = None
        self._applying_workspace_constraints = False
        self._user_resize_transaction_active = False
        self._restricted_workspace = None
        self._workspace_forced_size = None
        self._last_workspace_minimum_size = QSize(MINIMUM_WINDOW_SIZE)
        self._workspace_constraint_refresh_timer = QTimer(self)
        self._workspace_constraint_refresh_timer.setSingleShot(True)
        self._workspace_constraint_refresh_timer.timeout.connect(
            self._refresh_workspace_after_responsive_layout
        )
        self._navigation_wide_state: bool | None = None
        self._navigation_history: list[str | WorkspaceRoute] = []
        self._current_navigation_location: str | WorkspaceRoute | None = None
        self._workspace_navigation_in_progress = False
        self._navigation_reopen_after_collapse = False
        self._navigation_reopen_requires_wide = False
        self._pending_navigation_scroll_key = ""
        self._navigation_layout_timer = QTimer(self)
        self._navigation_layout_timer.setSingleShot(True)
        self._navigation_layout_timer.setInterval(
            self.NAVIGATION_LAYOUT_DEBOUNCE_MS
        )
        self._navigation_layout_timer.timeout.connect(
            self._sync_navigation_width_mode
        )
        self._navigation_reflow_timer = QTimer(self)
        self._navigation_reflow_timer.setSingleShot(True)
        self._navigation_reflow_timer.timeout.connect(
            self._settle_navigation_content_layout
        )
        self._navigation_scroll_timer = QTimer(self)
        self._navigation_scroll_timer.setSingleShot(True)
        self._navigation_scroll_timer.timeout.connect(
            self._ensure_current_navigation_item_visible
        )
        self._device_scroll_vertical_maximum = 0
        self._device_metadata: dict[str, dict[str, str]] = {}
        self._pending_package_device = ""
        self._package_query_invalidated = False
        self.task_supervisor = QtTaskSupervisor()
        self.task_supervisor.setParent(self)
        QtTaskSupervisor.bind_shared(self.task_supervisor)
        self.task_supervisor.application_stopped.connect(self._on_application_stopped)
        self.task_supervisor.application_finalized.connect(self._on_application_finalized)
        self._adb_pairing = None
        self._connection_panel = None
        self._connection_transition_active = False
        self._device_details_transition_active = False
        self._selector_transition_active = False
        self._actions = MainFrameActions(self)
        self._close_controller = CloseController(self)
        self._shutdown_owner_id = f"application-{id(self)}"
        self._shutdown_handles = []
        self._shutdown_results = ()
        self._shutdown_residual = ()
        self._shutdown_had_residual = False
        self._shutdown_deadline_at = 0.0
        self._shutdown_finalizer_started = False
        self._close_started = False
        self._close_ready = False
        self._layout_ready = False
        self._resize_controller = None
        self._scan_thread = None
        self._continuous_scan_enabled = False
        self._closing = False
        self._accent_revision = 0
        self._scan_refresh_timer = QTimer(self)
        self._scan_refresh_timer.setSingleShot(True)
        self._scan_refresh_timer.timeout.connect(self._publish_scanned_devices)
        self._pending_scanned_devices: list[str] | None = None
        self._pending_scan_token: tuple[int, int] | None = None
        self._initial_refresh_timer = QTimer(self)
        self._initial_refresh_timer.setSingleShot(True)
        self._pending_window_size = None
        self._window_size_save_timer = QTimer(self)
        self._window_size_save_timer.setSingleShot(True)
        self._window_size_save_timer.timeout.connect(self._poll_user_resize_transaction)
        self._always_on_top = False
        self.navigationInterface.setEnabled(False)
        self._startup_iterator: Iterator[int] | None = self._startup_steps()
        if not deferred_startup:
            try:
                while self.advance_startup() is not None:
                    pass
            except BaseException:
                self.abort_startup()
                raise

    def advance_startup(self) -> int | None:
        """在 GUI 线程推进一个完整阶段；调用之间由外部事件循环交还绘制机会。

        默认构造同步消费同一序列。失败保留原异常，由协调器调用 abort_startup
        并等待 startup_aborted；就绪、失败或中止后不重复构建和连接信号。
        """
        if self._startup_iterator is None or self._startup_failed or self._startup_aborting:
            return None
        try:
            return next(self._startup_iterator)
        except StopIteration:
            self._startup_iterator = None
            return None
        except BaseException:
            self._startup_failed = True
            raise

    def _startup_steps(self) -> Iterator[int]:
        """按资源归属分段构建隐藏主窗，最后才开放导航和后台启动入口。"""
        self.log_service = LogService()
        set_error_sink(self.log_service.log)
        started_at = time.perf_counter()
        # 隐藏协调器随主窗销毁，不能在工作区释放后继续接收全局样式信号。
        self.left_panel = SidePanel(self)
        self.left_panel.hide()
        self._record_startup_stage("side-panel", started_at)
        # 页面尚未挂入工作区时也必须有 Qt 父对象，阶段中止不能留下独立顶层滚动区。
        for widget in (
            self.left_panel.device_widget,
            *getattr(self.left_panel, "_tab_scroll_areas", {}).values(),
        ):
            if widget.parent() is None:
                widget.setParent(self.left_panel)
        started_at = time.perf_counter()
        apk_picker = QtApkFilePicker(lambda: self)
        device_lifecycle = QtDeviceConnectionLifecycle(lambda: self.adb_controller.window_owner)
        if self._device_history_loaded:
            self.adb_controller = ADBController(
                self.log_service, load_device_history=False, apk_picker=apk_picker,
                device_lifecycle=device_lifecycle,
            )
        else:
            self.adb_controller = ADBController(
                self.log_service, apk_picker=apk_picker, device_lifecycle=device_lifecycle,
            )
        setattr(self.adb_controller, "window_owner", self)
        self._initial_refresh_timer.timeout.connect(self.adb_controller.refresh_devices)
        self._record_startup_stage("adb-controller", started_at)

        started_at = time.perf_counter()
        self._setup_window()
        self._record_startup_stage("window-layout", started_at)
        yield WindowStartupStage.WINDOW_BASE
        yield from self._init_panels_steps()
        self._sync_workspace_restriction(force=True)
        self._setup_shortcuts()
        # FluentWindow 提供窗口外观与导航；该控制器只负责把原生缩放手势映射到
        # ADBLab 的窗口尺寸持久化事务，不参与页面视觉实现。
        self._resize_controller = FramelessResizeController(
            self,
            on_user_resize_started=self._begin_user_resize_transaction,
            on_user_resize_cancelled=self._cancel_user_resize_transaction,
        )
        self._layout_ready = True
        self._refresh_save_path()
        attach_top_level = getattr(self.left_panel, "attach_responsive_top_level", None)
        if callable(attach_top_level):
            attach_top_level(self)
        self._request_side_panel_reflow(self, ReflowReason.EXPLICIT)
        self._startup_complete = True
        self.navigationInterface.setEnabled(True)
        if not self._deferred_startup:
            self._start_startup_services()
        yield WindowStartupStage.NAVIGATION

    def _record_startup_stage(self, name: str, started_at: float) -> None:
        if self.startup_diagnostics is not None:
            self.startup_diagnostics.record(
                name, elapsed_ms=(time.perf_counter() - started_at) * 1000,
            )

    def _start_startup_services(self) -> None:
        """完成构建后只安排一次设备检测；分步启动在首次显示时才开放此入口。"""
        if not self._startup_complete or self._closing or self._startup_services_started:
            return
        self._startup_services_started = True
        self._settings_page.start_startup_detection()
        self._bootstrap_adb_async()

    def abort_startup(self) -> None:
        """幂等中止启动并异步收口已创建资源；完成信号之后才可退出事件循环。"""
        if self._startup_aborting:
            return
        self._startup_aborting = True
        self._closing = True
        iterator, self._startup_iterator = self._startup_iterator, None
        close_iterator = getattr(iterator, "close", None)
        if callable(close_iterator):
            close_iterator()
        self.hide()
        self.setEnabled(False)
        self._unbind_window_screen()
        for timer in self.findChildren(QTimer):
            timer.stop()
        if not hasattr(self, "adb_controller"):
            self._close_ready = True
            self._finish_startup_abort()
            return
        # RunLibrary 构造会启动本地读取，沿用应用关闭屏障在后台等待实际收尾。
        # closeEvent 内再次调用 close 会被 Qt 的重入保护忽略，直接交给同一屏障。
        self._close_controller.handle_close_event(QCloseEvent())
        if self._close_ready:
            self._finish_startup_abort()

    def _finish_startup_abort(self) -> None:
        """关闭屏障完成后停止剩余 UI 动画并安排 Qt 对象树释放。"""
        if self._startup_abort_reported:
            return
        self._startup_abort_reported = True
        for timer in self.findChildren(QTimer):
            timer.stop()
        for animation in self.findChildren(QAbstractAnimation):
            animation.stop()
        for animation in self.findChildren(FrameAnimation):
            animation.stop()
        self.deleteLater()
        self.startup_aborted.emit()

    # ── 持续设备扫描 ────────────────────────────────────────────────────

    def _bootstrap_adb_async(self):
        """安排后台环境检查；服务可用即开始发现，不等待原生性能基准。"""
        from gui.adapters.adb_runtime import QtAdbRuntime

        self._adb_environment = QtAdbRuntime(self)
        self._adb_environment.ready.connect(self._start_device_discovery)
        self._adb_environment.changed.connect(self._update_adb_environment)
        self._adb_environment.diagnostic.connect(self._log_adb_environment)
        self._update_adb_environment(self._adb_environment.snapshot())
        self._adb_environment.schedule()

    def _log_adb_environment(self, message: str) -> None:
        """后台诊断经主线程进入诊断记录，源码与打包环境均保留能力和耗时。"""
        if not self._closing:
            self.log_service.record_runtime_diagnostic(message)

    def _update_adb_environment(self, snapshot) -> None:
        """显示执行范围与检测状态，不把性能策略当作设备在线状态。"""
        if not self._closing:
            self._settings_page.update_adb_environment(snapshot)

    def recheck_adb_environment(self) -> None:
        """重新检测不重启 ADB 服务，也不重复提交用户命令。"""
        self.invalidate_wireless_pairing("environment_recheck")
        environment = getattr(self, "_adb_environment", None)
        if environment is not None and not self._closing:
            panel = getattr(getattr(self, "left_panel", None), "_scrcpy_tab", None)
            if panel is not None:
                panel.invalidate_adb_input_sessions()
            environment.recheck()

    def invalidate_wireless_pairing(self, reason: str) -> None:
        """改变客户端环境前撤销配对与续连资格，普通发现和性能模式不调用。"""
        pairing = getattr(self, "_adb_pairing", None)
        if pairing is not None and not self._closing:
            pairing.invalidate(reason)

    def note_adb_server_restarted(self) -> None:
        """本机 ADB 服务重启成功后作废运行时能力与扫描快照。

        重启会切断既有 socket，旧的能力状态与拓扑不再可信；这里先失效并重测，
        延迟设备列表刷新仍由 Controller 安排，避免后续命令先撞一次连接被拒。
        """
        environment = getattr(self, "_adb_environment", None)
        if environment is not None and not self._closing:
            environment.note_server_restart()
        thread = getattr(self, "_scan_thread", None)
        invalidate = getattr(thread, "invalidate_snapshot", None)
        if callable(invalidate):
            invalidate()

    def set_adb_selection_mode(self, mode: str) -> None:
        """切换执行模式（auto/fast/native）；只影响后续命令，不重放在途请求。"""
        environment = getattr(self, "_adb_environment", None)
        if environment is not None and not self._closing:
            environment.set_selection_mode(mode)

    def set_adb_native_only(self, enabled: bool) -> None:
        """临时兼容选项只影响后续操作。"""
        environment = getattr(self, "_adb_environment", None)
        if environment is not None and not self._closing:
            environment.set_native_only(enabled)

    def _start_device_discovery(self):
        if getattr(self, "_closing", False):
            return
        from core.settings_manager import AppSettings

        enabled = bool(AppSettings.instance().get("continuous_device_scan", True))
        self._continuous_scan_enabled = enabled
        if enabled:
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
        scan_thread = self._scan_thread
        scan_thread.discovery_token = self.adb_controller.device_discovery_token
        scan_thread.devices_changed.connect(self._schedule_scan_refresh)
        discovery_state_changed = getattr(
            scan_thread,
            "discovery_state_changed",
            None,
        )
        if discovery_state_changed is not None and callable(set_discovery_state):
            discovery_state_changed.connect(self._on_scan_discovery_state)
        finished = getattr(scan_thread, "finished", None)
        if finished is not None:
            finished.connect(lambda: self._on_scan_thread_finished(scan_thread))
        scan_thread.start()

    def _on_scan_thread_finished(self, scan_thread: _ScanThread) -> None:
        """收口旧扫描线程，并兑现快速关闭后重新开启的用户意图。"""

        if self._scan_thread is not scan_thread:
            return
        self._scan_thread = None
        if self._continuous_scan_enabled and not self._closing:
            self._start_scan_thread()

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

    def _on_scan_discovery_state(self, state: str) -> None:
        """错误状态也经过发现准入，避免过期失败撤销刚完成的手动刷新。"""
        if self._closing:
            return
        token = getattr(state, "discovery_token", None)
        if token is not None:
            current = self.adb_controller.device_discovery_token()
            if token != current or current[1]:
                return
        self.left_panel.set_device_discovery_state(str(state))

    def _schedule_scan_refresh(self, devices: list[str]):
        """合并扫描线程通知，更新界面时不再发起第二次 ADB 轮询。"""
        if getattr(self, "_closing", False):
            return
        self._pending_scanned_devices = list(devices)
        self._pending_scan_token = getattr(devices, "discovery_token", None)
        self._scan_refresh_timer.start(self.DEVICE_SCAN_DEBOUNCE_MS)

    def _publish_scanned_devices(self):
        if getattr(self, "_closing", False) or self._pending_scanned_devices is None:
            return
        devices = self._pending_scanned_devices
        self._pending_scanned_devices = None
        token = getattr(self, "_pending_scan_token", None)
        if token is None:
            self.adb_controller.publish_detected_devices(devices)
        else:
            self.adb_controller.publish_detected_devices(devices, discovery_token=token)

    def set_continuous_scan(self, enabled: bool):
        self._continuous_scan_enabled = bool(enabled)
        if self._continuous_scan_enabled:
            self._start_scan_thread()
        else:
            self._stop_scan_thread()
            panel = getattr(self, "left_panel", None)
            if panel is not None:
                context = panel.device_context_snapshot()
                if context.discovery_state == "scanning":
                    panel.set_device_discovery_state(
                        "ready" if context.connected_devices else "empty"
                    )

    def _setup_window(self):
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        # 复用系统标题标签，名称处的鼠标操作仍交给标题栏处理拖动和双击。
        label = cast(FluentTitleBar, self.titleBar).titleLabel
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.show()
        getattr(self.titleBar, "iconLabel").hide()
        self._sync_title_bar_typography()
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        BaseStyles.set_accent_color(str(s.get("accent_color", "#0F6CBD")))
        self.setMicaEffectEnabled(bool(s.get("mica_enabled", True)))
        self.navigationInterface.setExpandWidth(220)
        self.navigationInterface.setMinimumExpandWidth(
            self.NAVIGATION_EXPAND_BREAKPOINT
        )
        self._always_on_top = bool(s.get("always_on_top", False))
        if self._always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        configured_width = s.get("window_width", DEFAULT_WINDOW_SIZE.width())
        configured_height = s.get("window_height", DEFAULT_WINDOW_SIZE.height())
        configured_size = normalize_window_size(configured_width, configured_height)
        self._preferred_window_size = QSize(configured_size)
        self._apply_workspace_constraints(
            self._screen_adapter.window_screen(self),
            request_reflow=False,
        )
        self.setFont(BaseStyles.font_for_role(FontRole.UI))

    def _screen_is_valid(self, screen) -> bool:
        """通过适配器判断 QScreen 底层对象是否仍然存活。"""

        if screen is None:
            return False
        validator = getattr(self._screen_adapter, "is_valid_screen", None)
        if not callable(validator):
            # 测试替身和第三方适配器没有 Qt 包装器生命周期，非空即视为有效。
            return True
        try:
            return bool(validator(screen))
        except (AttributeError, RuntimeError, TypeError):
            return False

    def _resolve_window_screen(self, screen=None):
        """返回仍存活的候选屏幕；失效缓存必须重新查询当前窗口。"""

        if self._screen_is_valid(screen):
            return screen
        try:
            current = self._screen_adapter.window_screen(self)
        except (AttributeError, RuntimeError, TypeError):
            current = None
        return current if self._screen_is_valid(current) else None

    def _bind_window_screen(self) -> None:
        """在 window handle 可用后绑定窗口与当前屏幕的变化信号。"""

        if getattr(self, "_closing", False):
            return
        handle = self.windowHandle()
        rebound_window = handle is not None and (
            handle is not self._bound_window_handle or self._window_screen_token is None
        )
        if rebound_window:
            previous_handle = self._bound_window_handle
            if previous_handle is not None and isValid(previous_handle):
                previous_handle.removeEventFilter(self)
            self._disconnect_screen_token(self._window_screen_token)
            self._window_screen_token = self._screen_adapter.connect_window_screen_changed(
                self,
                self._on_window_screen_changed,
            )
            self._bound_window_handle = handle
            handle.installEventFilter(self)

        screen = self._resolve_window_screen()
        rebound_screen = self._bind_screen_metrics(screen)
        self._apply_workspace_constraints(screen, request_reflow=False)
        if rebound_window or rebound_screen:
            self._request_side_panel_reflow(self, ReflowReason.SCREEN)

    def _bind_screen_metrics(self, screen) -> bool:
        screen = self._resolve_window_screen(screen)
        if screen is self._bound_screen and (
            (screen is None and not self._screen_metric_tokens)
            or (self._screen_is_valid(screen) and len(self._screen_metric_tokens) == 2)
        ):
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

        refresh_timer = getattr(self, "_workspace_constraint_refresh_timer", None)
        if refresh_timer is not None and refresh_timer.isActive():
            refresh_timer.stop()
        window_token = getattr(self, "_window_screen_token", None)
        metric_tokens = tuple(getattr(self, "_screen_metric_tokens", ()))
        self._window_screen_token = None
        self._screen_metric_tokens = []
        handle = getattr(self, "_bound_window_handle", None)
        if handle is not None and isValid(handle):
            handle.removeEventFilter(self)
        self._bound_window_handle = None
        self._bound_screen = None
        self._disconnect_screen_token(window_token)
        for token in metric_tokens:
            self._disconnect_screen_token(token)

    def _on_window_screen_changed(self, _screen=None) -> None:
        if getattr(self, "_closing", False):
            return
        # queued screenChanged 可能携带已过期的旧 wrapper，以窗口当前值为准。
        screen = self._resolve_window_screen()
        self._bind_screen_metrics(screen)
        self._apply_workspace_constraints(
            self._bound_screen,
            request_reflow=True,
            reason=ReflowReason.SCREEN,
        )

    def _on_screen_available_geometry_changed(self, _geometry=None) -> None:
        if getattr(self, "_closing", False):
            return
        self._bind_screen_metrics(self._resolve_window_screen())
        self._apply_workspace_constraints(
            self._bound_screen,
            request_reflow=True,
            reason=ReflowReason.SCREEN,
        )

    def _on_screen_logical_dpi_changed(self, _dpi=None) -> None:
        if getattr(self, "_closing", False):
            return
        self._bind_screen_metrics(self._resolve_window_screen())
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

        requested_screen = screen
        screen = self._resolve_window_screen(screen)
        if (
            requested_screen is not None
            and requested_screen is self._bound_screen
            and screen is not requested_screen
        ):
            self._bind_screen_metrics(screen)
            screen = self._bound_screen
        available_size = self._screen_adapter.available_size(screen)
        design_minimum = self._workspace_design_minimum()
        constraints = compute_workspace_constraints(
            available_size,
            self._preferred_window_size,
            design_minimum=design_minimum,
        )
        previous_minimum = QSize(self._last_workspace_minimum_size)
        forced_size = self._workspace_forced_size
        minimum_relaxed = (
            constraints.minimum_window_size.width() < previous_minimum.width()
            or constraints.minimum_window_size.height() < previous_minimum.height()
        )
        restore_relaxed_minimum = bool(
            not restore_preferred_size
            and forced_size is not None
            and self.size() == forced_size
            and minimum_relaxed
            and (
                constraints.effective_window_size.width() < forced_size.width()
                or constraints.effective_window_size.height() < forced_size.height()
            )
        )
        apply_effective_size = restore_preferred_size or restore_relaxed_minimum
        size_before_constraints = QSize(self.size())
        minimum_forced_size = QSize(
            max(size_before_constraints.width(), constraints.minimum_window_size.width()),
            max(size_before_constraints.height(), constraints.minimum_window_size.height()),
        )
        previous_restricted = self._restricted_workspace
        self._restricted_workspace = constraints.restricted
        device_scroll = getattr(self, "_device_scroll_area", None)
        if device_scroll is not None:
            # Devices 已位于工作区宿主的可变高度内容区内。滚动容器若继续继承
            # 设备内容高度，短窗口会先把内层页面撑出外层 viewport，导致底部动作
            # 即使在内层滚到底也不可见；内容本身的 minimumHeight 足以生成滚动范围。
            device_scroll.setProperty("preserveDeviceContentHeight", False)
            if device_scroll.minimumHeight() != 0:
                device_scroll.setMinimumHeight(0)
        if apply_effective_size:
            self._effective_window_size = QSize(constraints.effective_window_size)
        elif minimum_forced_size != size_before_constraints:
            self._effective_window_size = QSize(minimum_forced_size)
        self._applying_workspace_constraints = True
        try:
            if self.minimumSize() != constraints.minimum_window_size:
                self.setMinimumSize(constraints.minimum_window_size)
            if apply_effective_size and self.size() != constraints.effective_window_size:
                self.resize(constraints.effective_window_size)
        finally:
            self._applying_workspace_constraints = False
        applied_size = (
            QSize(constraints.effective_window_size)
            if apply_effective_size
            else QSize(minimum_forced_size)
        )
        preferred = self._preferred_window_size
        forced_by_design = bool(
            apply_effective_size
            and (
                applied_size.width() > preferred.width()
                or applied_size.height() > preferred.height()
            )
        )
        forced_by_new_minimum = bool(
            not apply_effective_size and minimum_forced_size != size_before_constraints
        )
        if forced_by_design or forced_by_new_minimum:
            self._workspace_forced_size = QSize(applied_size)
        elif apply_effective_size or size_before_constraints != forced_size:
            self._workspace_forced_size = None
        self._last_workspace_minimum_size = QSize(constraints.minimum_window_size)
        if previous_restricted != constraints.restricted:
            self._sync_workspace_restriction(force=True)
        if request_reflow:
            self._request_side_panel_reflow(self, reason)
        return constraints

    def _workspace_design_minimum(self) -> QSize:
        """返回 FluentWindow 页面体系的设计下限。"""

        return QSize(MINIMUM_WINDOW_SIZE)

    def _on_side_panel_responsive_layout_settled(self, _generation: int) -> None:
        """在 Devices 计划稳定后更新字体感知窗口边界。"""

        if getattr(self, "_closing", False):
            return
        self._workspace_constraint_refresh_timer.start(0)

    def _refresh_workspace_after_responsive_layout(self) -> None:
        """等待 Qt 提交布局提示后，再同步 Devices 滚动高度和窗口边界。"""

        if getattr(self, "_closing", False):
            return
        self._bind_screen_metrics(self._resolve_window_screen())
        self._sync_device_scroll_content_minimum()
        self._apply_workspace_constraints(
            self._bound_screen,
            request_reflow=False,
            restore_preferred_size=False,
        )

    def _sync_device_scroll_content_minimum(self) -> int:
        """同步 Devices 当前计划的完整高度，让短屏由局部滚动承接。"""

        device_panel = getattr(self, "_device_hub", None)
        if device_panel is None:
            device_panel = getattr(getattr(self, "left_panel", None), "device_widget", None)
        if device_panel is None:
            return 0
        layout = device_panel.layout()
        layout_height = max(0, layout.minimumSize().height()) if layout is not None else 0
        content_height = max(layout_height, device_panel.minimumSizeHint().height())
        minimum_changed = device_panel.minimumHeight() != content_height
        if minimum_changed:
            device_panel.setMinimumHeight(content_height)
        scroll = getattr(self, "_device_scroll_area", None)
        if scroll is not None and minimum_changed:
            scroll.updateGeometry()
        return content_height

    def _on_device_scroll_range_changed(
        self,
        _minimum: int,
        maximum: int,
    ) -> None:
        """内容在滚动底部继续增长时，保持最末动作仍在视口内。"""

        scroll = getattr(self, "_device_scroll_area", None)
        if scroll is None:
            return
        bar = scroll.verticalScrollBar()
        previous = self._device_scroll_vertical_maximum
        followed_previous_bottom = previous > 0 and bar.value() >= previous - 2
        self._device_scroll_vertical_maximum = maximum
        if self._connection_transition_active or self._device_details_transition_active:
            # 连接区和详情展开只推移后续内容，不逐帧跟底拖动阅读位置。
            return
        if maximum > previous and followed_previous_bottom:
            bar.setValue(maximum)

    def _on_connection_transition_changed(self, active: bool) -> None:
        """连接区与同页详情可同时展开，结束一处不能提前恢复整个工作区布局。"""
        self._connection_transition_active = active
        self._sync_viewport_transition_gate()

    def _on_device_details_transition_changed(self, active: bool) -> None:
        self._device_details_transition_active = active
        self._sync_viewport_transition_gate()

    def _on_selector_transition_changed(self, active: bool) -> None:
        self._selector_transition_active = active
        self._sync_viewport_transition_gate()

    def _sync_viewport_transition_gate(self) -> None:
        """等最后一个活动过渡结束，涵盖跨页时仍在收尾的旧页面。"""
        self.left_panel.set_viewport_transition_active(
            self._connection_transition_active or self._device_details_transition_active
            or self._selector_transition_active
        )

    def _sync_device_reveal_geometry(self) -> None:
        """逐帧只同步概览的滚动高度，响应式网格仍在过渡结束后统一收敛。"""
        self._sync_device_scroll_content_minimum()
        layout = self._device_hub.layout()
        if layout is not None:
            layout.activate()

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
        """构建按任务领域拆分的 Fluent 主导航页面。"""
        for _position in self._init_panels_steps():
            pass

    def _init_panels_steps(self) -> Iterator[int]:
        """页面先完成归属再交还事件循环，局部宿主引用由生成器保存。"""

        from gui.features.app_manager import AppManagerPage
        from gui.features.file_explorer import FileExplorerPage
        from gui.features.logcat import LiveLogcatPage
        from gui.features.media import ScreenshotPage
        from gui.features.performance import PerformancePage

        self._central_widget = self.stackedWidget
        self.run_library = RunLibraryController(RunLibrary.for_user(), self)
        self.run_library.error.connect(self._on_run_library_error)

        self._global_device_bar = DeviceContextBar(self)
        self._global_device_bar.selector_transition_changed.connect(
            self._on_selector_transition_changed,
        )
        self.widgetLayout.removeWidget(self.stackedWidget)
        # 设备栏与页面共用一个材质面，避免两次半透明合成或接缝处出现色带。
        self._content_surface = QWidget(self)
        self._content_surface.setObjectName("workspaceSurface")
        self._content_surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._content_surface.installEventFilter(self)
        FluentStyleSheet.FLUENT_WINDOW.apply(self._content_surface)
        self._content_layout = QVBoxLayout(self._content_surface)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._content_layout.addWidget(self._global_device_bar)
        # 滚动区铺满材质面；阅读留白由滚动内容承担，避免覆盖滚动条随正文内缩。
        self.stackedWidget.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self.stackedWidget, 1)
        self.widgetLayout.addWidget(self._content_surface, 1)
        # 页面几何由布局独占；视觉过渡只作用于透明内容，不移动或淡出共享材质。
        self.stackedWidget.setAnimationEnabled(False)
        self._page_transition = PageTransition(self._content_surface, self.stackedWidget)
        self._sync_material_surface_styles()
        self._device_hub = DeviceHubPage(self)
        self._device_hub.details_transition_changed.connect(
            self._on_device_details_transition_changed,
        )
        self._device_hub.details_geometry_changed.connect(self._sync_device_reveal_geometry)
        # 旧设备视图作为兼容状态源保留在协调器下；不拆走仍被响应式绑定引用的控件。
        self.left_panel.device_widget.setParent(self.left_panel)
        self.left_panel.device_widget.hide()

        device_scroll = use_smooth_scroll(SmoothScrollArea(self))
        device_scroll.setObjectName("deviceScrollArea")
        device_scroll.setWidgetResizable(True)
        device_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        device_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        device_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._device_scroll_area = device_scroll
        device_scroll.verticalScrollBar().rangeChanged.connect(
            self._on_device_scroll_range_changed
        )

        devices_overview = WorkspaceSectionPage(
            "devicesOverviewPage",
            self._device_hub,
            scroll_area=device_scroll,
            parent=self,
        )

        def build_overview(
            index: int,
            route: str,
        ) -> WorkspaceSectionPage:
            scroll, content = self.left_panel.take_overview_content(index)
            if content is None:
                content = QWidget()
            return WorkspaceSectionPage(
                f"{route}OverviewPage",
                content,
                scroll_area=scroll,
                parent=self,
            )

        apps_overview = build_overview(0, "apps")
        yield WindowStartupStage.APPS_OVERVIEW
        system_overview = build_overview(1, "system")
        yield WindowStartupStage.SYSTEM_OVERVIEW
        remote_overview = build_overview(2, "remote")
        yield WindowStartupStage.REMOTE_OVERVIEW

        apps_panel = self.left_panel.app_panel
        system_panel = self.left_panel.system_panel
        remote_panel = self.left_panel.remote_panel
        if apps_panel is None or system_panel is None or remote_panel is None:
            raise RuntimeError("workspace overview panel was not initialized")
        for panel in (apps_panel, system_panel, remote_panel):
            panel.panel_header.hide()
            panel.category_stack.set_navigation_visible(False)

        devices_host = WorkspaceFeatureHost(
            "devices",
            tr("设备概览"),
            devices_overview,
            self,
        )
        devices_host.configure_overview_category(
            "overview",
            icon=DEVICE_ICON,
        )
        devices_host.register_feature(
            "files",
            tr("文件管理"),
            FluentIcon.FOLDER,
            lambda key: FileExplorerPage(
                device_ip=key.device_id, task_supervisor=self.task_supervisor,
            ),
            close_label=tr("关闭文件管理"),
        )
        devices_host.register_overview_category(
            "remote",
            tr("远程控制"),
            FluentIcon.PROJECTOR,
            page=remote_overview,
            requires_device=False,
            activate=lambda device_id: self._activate_remote_workspace(
                "mirroring",
                device_id,
            ),
        )
        devices_host.register_alias("remote-control", "remote")
        yield WindowStartupStage.DEVICES_HOST

        apps_host = WorkspaceFeatureHost(
            "apps",
            tr("应用与诊断"),
            apps_overview,
            self,
        )
        apps_host.configure_overview_category(
            "overview",
            icon=FluentIcon.CODE,
            activate=lambda _device_id: apps_panel.category_stack.set_current("daily"),
        )
        apps_host.register_feature(
            "manager",
            tr("应用管理"),
            FluentIcon.APPLICATION,
            lambda key: AppManagerPage(device_ip=key.device_id),
            close_label=tr("关闭应用管理"),
        )
        apps_host.register_alias("packages", "manager")
        apps_host.register_alias("monkey", "overview")
        apps_host.register_alias("diagnostics", "overview")

        def create_screenshot_page(_key):
            page = ScreenshotPage()
            page.set_device_tools(
                apps_panel.text_screen_tools, apps_panel.text_screen_tools_parking,
            )
            page.back_requested.connect(apps_host.show_overview)
            return page

        apps_host.register_feature(
            "media",
            tr("截图与屏幕"),
            FluentIcon.CAMERA,
            create_screenshot_page,
            requires_device=False,
            defer_payload_while_disposing=True,
            close_label=tr("清除截图结果"),
        )
        yield WindowStartupStage.APPS_HOST

        system_host = WorkspaceFeatureHost(
            "system",
            tr("系统工具"),
            system_overview,
            self,
        )
        system_host.configure_overview_category(
            "overview",
            icon=FluentIcon.COMMAND_PROMPT,
            activate=lambda _device_id: system_panel.category_stack.set_current(
                "commands"
            ),
        )
        system_host.register_alias("connectivity", "overview")
        system_host.register_alias("settings", "overview")
        system_host.register_alias("device", "overview")
        system_host.register_feature(
            "logcat",
            tr("实时 Logcat"),
            FluentIcon.SCROLL,
            lambda key: LiveLogcatPage(
                device_ip=key.device_id,
                task_supervisor=self.task_supervisor,
                log_service=self.log_service,
            ),
            close_label=tr("关闭日志会话"),
        )

        def create_performance_page(key):
            try:
                package_name = self.left_panel.current_package_text()
            except RuntimeError:
                package_name = ""
            page = PerformancePage(
                device_ip=key.device_id,
                package_name=package_name,
            )
            page.setProperty(
                "run_device_label", self._global_device_bar.device_label(key.device_id),
            )
            page.set_run_library(self.run_library)
            return page

        system_host.register_feature(
            "performance",
            tr("性能采集"),
            FluentIcon.SPEED_HIGH,
            create_performance_page,
            show_close_action=False,
        )

        self._workspace_feature_hosts = {
            "devices": devices_host,
            "apps": apps_host,
            "system": system_host,
        }
        for host in self._workspace_feature_hosts.values():
            host.feature_selector.set_navigation_visible(False)
            host.set_external_device_controls(True)
            host.controls_changed.connect(self._sync_global_session_controls)
            host.route_requested.connect(self._on_nav_requested)
            host.choose_device_requested.connect(
                self._global_device_bar.open_picker
            )

        bar = self._global_device_bar
        bar.selection_requested.connect(self._select_operation_devices)
        bar.connect_requested.connect(self.left_panel.signals.connect_requested)
        self._device_hub.disconnect_requested.connect(
            lambda: self.left_panel.signals.disconnect_requested.emit(
                self.left_panel.selected_devices
            )
        )
        bar.session_requested.connect(self._choose_global_session)
        bar.close_session_requested.connect(self._close_global_session)
        bar.device_operation_requested.connect(self._request_remote_device_operation)
        remote_panel.device_selection_requested.connect(self._show_remote_device_selector)
        remote_panel.device_operations_changed.connect(self._sync_global_session_controls)
        self._device_hub.choose_requested.connect(bar.open_picker)
        self._device_hub.connect_requested.connect(self._show_global_connection)
        self._device_hub.refresh_requested.connect(self._request_device_refresh)
        self._device_hub.selection_requested.connect(
            self.left_panel.set_selected_devices
        )
        self._device_hub.device_action_requested.connect(self._open_device_tool)

        self._devices_page = WorkspaceAreaPage(
            "devicesPage",
            "devices",
            tr("设备概览"),
            tr("双击设备行选择或取消操作目标，右侧按钮打开该设备工具"),
            devices_host,
            feature_host=devices_host,
            parent=self,
        )
        self._apps_page = WorkspaceAreaPage(
            "appsPage",
            "apps",
            tr("应用与诊断"),
            tr("应用包操作、Monkey 测试与诊断报告"),
            apps_host,
            feature_host=apps_host,
            parent=self,
        )
        self._system_page = WorkspaceAreaPage(
            "systemPage",
            "system",
            tr("系统工具"),
            tr("系统命令、设备配置、网络与模拟器操作"),
            system_host,
            feature_host=system_host,
            parent=self,
        )
        for host in (devices_host, apps_host, system_host):
            host_layout = host.layout()
            assert host_layout is not None
            host_layout.setContentsMargins(0, 8, 0, 0)
            for state in (host.no_device_page, host.closing_page):
                state_layout = state.layout()
                assert state_layout is not None
                # 等待和关闭状态的卡片也属于正文，不能随滚动外壳贴到窗口边缘。
                state_layout.setContentsMargins(32, 0, 32, 24)
            sessions_layout = host.performance_sessions.layout()
            assert sessions_layout is not None
            # 固定会话控件不属于下方滚动内容，单独与正文阅读边界对齐。
            sessions_layout.setContentsMargins(32, 0, 32, 0)
            host.manage_devices_requested.connect(lambda: self._on_nav_requested("devices"))
        self._workspace_pages = {
            "devices": self._devices_page,
            "apps": self._apps_page,
            "system": self._system_page,
        }
        yield WindowStartupStage.WORKSPACE

        self._task_history = TaskHistoryStore()
        self._task_page = TaskCenterPage(
            self.adb_controller.operation_manager,
            history_store=self._task_history,
            stop_hook=self._stop_operation_from_task_center,
            run_library=self.run_library,
            parent=self,
        )
        assert self._task_page.run_results is not None
        self._task_page.run_results.reuse_requested.connect(self._reuse_test_run)
        yield WindowStartupStage.TASK_CENTER

        self._tasks_page = GalleryPage(
            "tasksPage",
            tr("任务中心"),
            tr("查看任务进度、测试归档与本次操作结果"),
            self._task_page,
            scroll=False,
            parent=self,
        )
        yield WindowStartupStage.TASKS_PAGE

        self._settings_page = SettingsPage(self, self, defer_startup_detection=True)
        self._app_update = QtAppUpdate(self)
        self._settings_page.about_panel.updateRequested.connect(self._app_update.check)
        self._app_update.changed.connect(self._settings_page.about_panel.set_update_snapshot)
        self._wire_installer_update()
        yield WindowStartupStage.SETTINGS_PAGE

        self._home_page = HomePage(self, self)
        self._sync_material_surface_styles()
        yield WindowStartupStage.HOME_PAGE

        # 导航亚克力会在云母上再做一层实时模糊，拖动和滚动时容易掉帧。
        self.navigationInterface.setAcrylicEnabled(False)
        self.addSubInterface(self._home_page, FluentIcon.HOME, tr("首页"))
        self.navigationInterface.addSeparator(NavigationItemPosition.SCROLL)
        self._workspace_navigation_page_keys: dict[str, str] = {}
        self._workspace_navigation_keys: dict[tuple[str, str], str] = {}
        workspace_navigation = (
            ("devices", "overview", "devicesPage", DEVICE_ICON, tr("设备概览"),
             tr("双击设备行选择或取消操作目标，右侧按钮打开该设备工具")),
            ("devices", "files", "filesPage", FluentIcon.FOLDER, tr("文件管理"),
             tr("浏览、传输和管理当前设备的文件")),
            ("devices", "remote", "remotePage", FluentIcon.PROJECTOR, tr("远程控制"),
             tr("屏幕镜像、按键和手势在同一页面操作")),
            ("apps", "manager", "appManagerPage", FluentIcon.APPLICATION, tr("应用管理"),
             tr("查看已安装应用，管理列表中的应用")),
            ("apps", "overview", "appsPage", FluentIcon.CODE, tr("应用与诊断"),
             tr("应用包操作、文本输入、Monkey 测试与诊断报告")),
            ("apps", "media", "screenshotsPage", FluentIcon.CAMERA, tr("截图与屏幕"),
             tr("截图录屏，查看并保存截图")),
            ("system", "overview", "systemPage", FluentIcon.DEVELOPER_TOOLS, tr("系统工具"),
             tr("系统命令、设备配置、网络与模拟器操作")),
            ("system", "logcat", "logcatPage", FluentIcon.SCROLL, tr("实时 Logcat"),
             tr("持续读取当前设备日志，支持应用过滤")),
            ("system", "performance", "performancePage", FluentIcon.SPEED_HIGH, tr("性能采集"),
             tr("配置采样，查看运行状态与采集结果")),
        )
        for section, page in self._workspace_pages.items():
            # 物理宿主继续保有会话，左栏直接选择语义功能；不重复创建页面或业务资源。
            page.setProperty("isStackedTransparent", False)
            self.stackedWidget.addWidget(page)
            self._workspace_navigation_page_keys[section] = page.objectName()
        for section, feature, route_key, icon, label, subtitle in workspace_navigation:
            self.navigationInterface.addItem(
                routeKey=route_key, icon=icon, text=label,
                onClick=lambda _clicked=False, s=section, f=feature: (
                    self._open_workspace_feature(s, f)
                ),
                position=NavigationItemPosition.SCROLL, tooltip=label,
            )
            self._workspace_navigation_keys[(section, feature)] = route_key
            self._workspace_pages[section].set_route_presentation(feature, label, subtitle)
        self.navigationInterface.addSeparator(NavigationItemPosition.SCROLL)
        for page, icon, label in (
            (self._tasks_page, FluentIcon.HISTORY, tr("任务中心")),
        ):
            self.addSubInterface(page, icon, label, NavigationItemPosition.SCROLL)
        self._theme_navigation_widget = NavigationThemeToggle(self.navigationInterface)
        self.navigationInterface.addWidget(
            routeKey="themeToggle",
            widget=self._theme_navigation_widget,
            onClick=self._toggle_theme,
            position=NavigationItemPosition.BOTTOM,
            tooltip=self._theme_navigation_widget.toolTip(),
        )
        self.addSubInterface(
            self._settings_page,
            FluentIcon.SETTING,
            tr("设置"),
            NavigationItemPosition.BOTTOM,
        )
        self._navigation_labels = {
            self._home_page.objectName(): tr("首页"),
            self._tasks_page.objectName(): tr("任务中心"),
            self._settings_page.objectName(): tr("设置"),
        }
        self._navigation_labels.update({
            route_key: label for _s, _f, route_key, _icon, label, _subtitle in workspace_navigation
        })
        self._sync_navigation_typography()
        panel = self.navigationInterface.panel
        self._navigation_focus_scroll = panel.scrollArea
        self._navigation_focus_viewport = panel.scrollArea.viewport()
        self._navigation_keyboard_focus = False
        panel.scrollArea.installEventFilter(self)
        panel.scrollArea.viewport().installEventFilter(self)
        try:
            panel.menuButton.clicked.disconnect(panel.toggle)
        except (RuntimeError, TypeError):
            pass
        panel.menuButton.clicked.connect(self._toggle_navigation_panel)
        try:
            panel.returnButton.clicked.disconnect(panel.history.pop)
        except (RuntimeError, TypeError):
            pass
        try:
            panel.history.emptyChanged.disconnect(panel.returnButton.setDisabled)
        except (RuntimeError, TypeError):
            pass
        panel.returnButton.clicked.connect(self._navigate_back)
        panel.expandAni.finished.connect(self._on_navigation_animation_finished)
        self.navigationInterface.setUpdateIndicatorPosOnCollapseFinished(True)
        self.navigationInterface.displayModeChanged.connect(
            self._on_navigation_display_mode_changed
        )
        self._sync_navigation_accessibility()

        self._connect_all_signals()
        for page in self._workspace_pages.values():
            page.routeChanged.connect(self._on_workspace_route_changed)
            page.routeChanged.connect(self._sync_global_session_controls)
        self._visible_workspace_section: str | None = None
        self.stackedWidget.currentChanged.connect(self._on_stacked_page_changed)
        current = self.stackedWidget.currentWidget()
        if current is not None:
            self._current_navigation_location = self._navigation_location_for_page(
                current
            )
        self._update_navigation_back_button()
        self.left_panel.device_discovery_state_changed.connect(self._sync_device_context)
        self.left_panel.responsive_layout_settled.connect(
            self._on_side_panel_responsive_layout_settled
        )
        BaseStyles.theme_changed.connect(self._on_theme_changed)
        BaseStyles.accent_color_changed.connect(self._on_accent_color_changed)
        BaseStyles.ui_font_changed.connect(self._on_ui_font_changed)
        self._bind_system_theme_changes()
        self._sync_plain_container_palettes()
        self._sync_device_context()

    def _activate_remote_workspace(self, category: str, device_id: str) -> str:
        """远程页面使用全部已选在线目标，已有镜像的停止归属由面板保存。"""

        panel = self.left_panel.remote_panel
        if panel is None:
            return device_id
        context = self.left_panel.device_context_snapshot()
        panel.set_connected_devices(
            list(context.connected_devices) if context.discovery_state == "ready" else [],
        )
        panel.set_target_devices(self._remote_operation_devices())
        panel.category_stack.set_current(category)
        panel.apply_responsive_width(0)
        return ""

    def _remote_operation_devices(self) -> list[str]:
        """发现状态不可靠时撤销新操作准入，但不停止已有远程会话。"""
        context = self.left_panel.device_context_snapshot()
        if context.discovery_state != "ready":
            return []
        return [device for device in context.selected_devices
                if device in context.connected_devices]

    def _stop_operation_from_task_center(self, operation_id: str) -> None:
        """把任务中心取消动作路由到拥有实际资源的控制器用例。"""

        snapshot = self.adb_controller.operation_manager.get(operation_id)
        if snapshot is None:
            return
        if "install" in snapshot.kind:
            self.adb_controller.cancel_install_batch(operation_id)
        elif snapshot.kind == "screenshot":
            self.adb_controller.cancel_screenshot(operation_id)

    def _onCurrentInterfaceChanged(self, index: int) -> None:
        """同步物理页面，但把返回历史统一交给应用级逻辑路由。"""

        widget = self.stackedWidget.widget(index)
        if widget is None:
            return
        location = self._navigation_location_for_page(widget)
        if isinstance(location, WorkspaceRoute):
            self._sync_workspace_navigation_selection(location)
        elif location:
            self.navigationInterface.setCurrentItem(location)
        self._updateStackedBackground()

    @staticmethod
    def _stable_workspace_route(route: WorkspaceRoute) -> WorkspaceRoute:
        """返回可进入历史的稳定位置，排除一次性激活参数。"""

        return WorkspaceRoute(route.section, route.feature, route.device_id)

    def _navigation_location_for_page(
        self,
        page: QWidget | None,
    ) -> str | WorkspaceRoute | None:
        workspace_pages = getattr(self, "_workspace_pages", {})
        for workspace_page in workspace_pages.values():
            if workspace_page is page:
                return self._stable_workspace_route(workspace_page.current_route)
        route_key = getattr(page, "objectName", lambda: "")()
        return str(route_key) or None

    def _commit_navigation_location(
        self,
        location: str | WorkspaceRoute | None,
        *,
        record_history: bool,
    ) -> None:
        """原子提交当前语义位置，并维护去重的应用级返回栈。"""

        if isinstance(location, WorkspaceRoute):
            location = MainFrame._stable_workspace_route(location)
        current = getattr(self, "_current_navigation_location", None)
        if location is None or location == current:
            MainFrame._update_navigation_back_button(self)
            return
        history = getattr(self, "_navigation_history", None)
        if history is None:
            history = []
            self._navigation_history = history
        if record_history and current is not None:
            if not history or history[-1] != current:
                history.append(current)
                del history[:-100]
        self._current_navigation_location = location
        MainFrame._update_navigation_back_button(self)

    def _update_navigation_back_button(self) -> None:
        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        can_go_back = bool(getattr(self, "_navigation_history", ()))
        navigation.panel.returnButton.setEnabled(can_go_back)

    def _navigate_to_location(self, location: str | WorkspaceRoute) -> bool:
        """在不产生新历史项的前提下恢复一个语义位置。"""

        if isinstance(location, WorkspaceRoute):
            return self._open_workspace_feature(
                location.section,
                location.feature,
                device_id=location.device_id,
                _record_history=False,
            )
        for index in range(self.stackedWidget.count()):
            page = self.stackedWidget.widget(index)
            if page is not None and page.objectName() == location:
                self.switchTo(page, _record_history=False, _target_location=location)
                return True
        return False

    def _navigate_back(self, *_args) -> None:
        """返回上一个功能入口；设备弹层不改变页面或返回历史。"""

        self._navigation_reopen_after_collapse = False
        self._navigation_reopen_requires_wide = False
        self._collapse_navigation_menu_after_switch()
        history = getattr(self, "_navigation_history", [])
        if not history:
            self._update_navigation_back_button()
            return
        target = history.pop()
        if not self._navigate_to_location(target):
            history.append(target)
        self._update_navigation_back_button()

    def _responsive_coordinator(self):
        """返回左侧栏与各功能面板共享的响应式协调器，尚未创建时返回 None。"""

        return getattr(self.left_panel, "_responsive_coordinator", None)

    def switchTo(
        self,
        interface,
        *,
        _record_history: bool = True,
        _target_location: str | WorkspaceRoute | None = None,
    ) -> None:
        """切换独立主页面，并同步功能会话的前后台生命周期。"""

        with MainFrame._page_change_batch(self):
            MainFrame._switch_to_prepared_page(
                self, interface, _record_history=_record_history, _target_location=_target_location,
            )

    def _page_change_batch(self):
        """同宿主路由和跨宿主切换共用绘制批次；构建期及纯协调测试保持同步兼容。"""

        transition = getattr(self, "_page_transition", None)
        if transition is None:
            return nullcontext()
        return transition.batch(
            lambda: self._navigation_location_for_page(self.stackedWidget.currentWidget()),
        )

    def _switch_to_prepared_page(
        self, interface, *, _record_history: bool,
        _target_location: str | WorkspaceRoute | None,
    ) -> None:
        """同步提交导航身份与会话；调用方在完整布局确定后一次恢复绘制。"""

        workspace_pages = getattr(self, "_workspace_pages", {})
        next_section = next(
            (key for key, page in workspace_pages.items() if page is interface),
            None,
        )
        target_location = _target_location or self._navigation_location_for_page(interface)
        self._commit_navigation_location(
            target_location,
            record_history=_record_history,
        )
        super().switchTo(interface)
        self._refresh_page_accent(interface)
        # 首次显示的页面可能仍带着构造期的旧几何：这里必须在首帧绘制前同时落实
        # 宿主最终几何和对应的响应式计划，否则用户会看到一次布局跳动。退出流程
        # 只需要页面可见性，不再为关闭路径同步跑一整代重规划。
        if not getattr(self, "_closing", False):
            settle_responsive_layout(interface, self._responsive_coordinator())
        route_key = getattr(interface, "objectName", lambda: "")()
        if next_section is not None:
            self._sync_workspace_navigation_selection(
                workspace_pages[next_section].current_route
            )
        elif route_key:
            # FluentWindow 默认等页面过渡结束才更新 NavigationPanel。业务页面已经
            # 切换时选中态若仍停在旧项，会让快速连续点击看起来没有响应。
            self.navigationInterface.setCurrentItem(route_key)
        self._navigation_reopen_after_collapse = False
        self._navigation_reopen_requires_wide = False
        self._collapse_navigation_menu_after_switch()

    def _on_stacked_page_changed(self, index: int) -> None:
        """统一处理点击导航和历史返回造成的业务宿主页可见性变化。"""

        self._global_device_bar.dismiss_popups()
        workspace_pages = getattr(self, "_workspace_pages", {})
        current = self.stackedWidget.widget(index)
        self._commit_navigation_location(
            self._navigation_location_for_page(current),
            record_history=True,
        )
        next_section = next(
            (key for key, page in workspace_pages.items() if page is current),
            None,
        )
        previous_section = getattr(self, "_visible_workspace_section", None)
        self._sync_global_session_controls()
        if previous_section == next_section:
            return
        if previous_section is not None:
            workspace_pages[previous_section].deactivate("top_level_navigation")
        self._visible_workspace_section = next_section
        if next_section is None:
            return
        page = workspace_pages[next_section]
        page.activate()
        self._sync_workspace_navigation_selection(page.current_route)
        self._sync_global_session_controls()

    def _collapse_navigation_menu_after_switch(self) -> None:
        """切页后收起窄窗覆盖菜单，包括尚在执行的展开动画。"""

        panel = self.navigationInterface.panel
        if panel.displayMode != NavigationDisplayMode.MENU:
            return
        focus = QApplication.focusWidget()
        target = self._global_device_bar.targets_button
        if (focus is not None and (focus is panel or panel.isAncestorOf(focus))
                and target.isVisible() and target.isEnabled()):
            # Fluent 收起后重挂导航面板会把鼠标焦点自动标成 Tab；先按真实输入
            # 来源交回页头，保留键盘提示，也避免点击切页凭空出现蓝色焦点框。
            target.setFocus(
                Qt.FocusReason.TabFocusReason
                if self._navigation_keyboard_focus
                else Qt.FocusReason.OtherFocusReason,
            )
        animation = panel.expandAni
        if animation.state() == QAbstractAnimation.State.Running:
            # NavigationPanel.collapse() 会忽略运行中的动画；若当前已在收起，
            # 保留原动画，否则先停止展开再从当前宽度开始收起。
            if not bool(animation.property("expand")):
                return
            animation.stop()
        panel.collapse()

    def _toggle_navigation_panel(self, *_args) -> None:
        """按内容可用宽度切换常驻左栏或覆盖菜单。"""

        panel = self.navigationInterface.panel
        animation = panel.expandAni
        if animation.state() == QAbstractAnimation.State.Running:
            if bool(animation.property("expand")):
                animation.stop()
                panel.collapse()
            else:
                # NavigationPanel 会忽略动画期间的 collapse/expand。记住第二次
                # 点击，在收起尾沿重新展开，确保快速双击不会丢失用户意图。
                self._navigation_reopen_after_collapse = True
                self._navigation_reopen_requires_wide = False
            return
        if panel.displayMode in {
            NavigationDisplayMode.COMPACT,
            NavigationDisplayMode.MINIMAL,
        }:
            self._expand_navigation_panel(use_animation=True)
            return
        panel.collapse()

    def _expand_navigation_panel(self, *, use_animation: bool) -> None:
        """消除自定义左栏宽度造成的展开断点偏移。"""

        panel = self.navigationInterface.panel
        configured_minimum = panel.minimumExpandWidth
        # qfluentwidgets 以默认 322px 左栏修正展开阈值。项目把左栏收窄到
        # 220px 后，直接调用会在 898px 就错误进入常驻模式；只在判定阶段
        # 补回差值，动画宽度和后续自动折叠仍使用项目声明的 1120px 断点。
        panel.minimumExpandWidth = (
            self.NAVIGATION_EXPAND_BREAKPOINT
            + self._QFLUENT_DEFAULT_EXPAND_WIDTH
            - panel.expandWidth
        )
        try:
            panel.expand(use_animation)
        finally:
            panel.minimumExpandWidth = configured_minimum
        if not use_animation:
            self._on_navigation_display_mode_changed(panel.displayMode)

    def _sync_navigation_width_mode(self) -> None:
        """首次显示及跨断点缩放时同步桌面常驻左栏。"""

        if not getattr(self, "_layout_ready", False):
            return
        panel = self.navigationInterface.panel
        wide = self.width() >= self.NAVIGATION_EXPAND_BREAKPOINT
        if not wide:
            self._navigation_wide_state = False
            return
        if (
            self._navigation_wide_state is True
            and panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() != QAbstractAnimation.State.Running
        ):
            return
        self._navigation_wide_state = False
        if panel.displayMode == NavigationDisplayMode.MENU:
            self._navigation_reopen_after_collapse = True
            self._navigation_reopen_requires_wide = True
            self._collapse_navigation_menu_after_switch()
            return
        if panel.expandAni.state() == QAbstractAnimation.State.Running:
            self._navigation_layout_timer.start(
                panel.expandAni.duration() + 20
            )
            return
        if panel.displayMode in {
            NavigationDisplayMode.COMPACT,
            NavigationDisplayMode.MINIMAL,
        }:
            self._expand_navigation_panel(use_animation=False)
        self._navigation_wide_state = (
            panel.displayMode == NavigationDisplayMode.EXPAND
        )

    def _on_navigation_display_mode_changed(
        self,
        mode: NavigationDisplayMode,
    ) -> None:
        """导航形态变化后同步当前入口并在动画尾沿重排内容。"""

        self._sync_navigation_accessibility()
        self._sync_navigation_typography()
        self._navigation_wide_state = (
            mode == NavigationDisplayMode.EXPAND
            and self.width() >= self.NAVIGATION_EXPAND_BREAKPOINT
        )
        current = self.stackedWidget.currentWidget()
        for section, page in getattr(self, "_workspace_pages", {}).items():
            if page is current:
                self._sync_workspace_navigation_selection(
                    self._workspace_pages[section].current_route
                )
                break
        delay = (
            self.navigationInterface.panel.expandAni.duration() + 20
            if mode
            in {
                NavigationDisplayMode.EXPAND,
                NavigationDisplayMode.MENU,
            }
            else 0
        )
        self._navigation_reflow_timer.start(delay)
        # 宽度协调由显示和缩放事件触发；模式通知也会来自用户主动收起，
        # 若在此重新按宽度展开，宽窗的收起选择会在动画尾沿立即被覆盖。

    def _on_navigation_animation_finished(self) -> None:
        """在导航最终宽度提交后刷新当前项位置和响应式布局。"""

        panel = self.navigationInterface.panel
        self._sync_navigation_typography()
        if panel.displayMode == NavigationDisplayMode.COMPACT:
            # 上游收起尾沿会重新设置 QStyle，清除面板背景填充和调色板。
            # 恢复当前材质策略，避免关闭云母后透明或开启后重新被实色遮挡。
            panel.setPalette(self.navigationInterface.palette())
            panel.setAutoFillBackground(not self.isMicaEffectEnabled())
        if self._navigation_reopen_after_collapse and panel.displayMode in {
            NavigationDisplayMode.COMPACT,
            NavigationDisplayMode.MINIMAL,
        }:
            should_reopen = (
                not self._navigation_reopen_requires_wide
                or self.width() >= self.NAVIGATION_EXPAND_BREAKPOINT
            )
            self._navigation_reopen_after_collapse = False
            self._navigation_reopen_requires_wide = False
            if should_reopen:
                self._expand_navigation_panel(
                    use_animation=self.width() < self.NAVIGATION_EXPAND_BREAKPOINT
                )
                return
        current = self.navigationInterface.panel.currentItem()
        if current is not None:
            self._pending_navigation_scroll_key = str(
                current.property("routeKey") or ""
            )
            self._navigation_scroll_timer.start(0)
        self._navigation_reflow_timer.start(0)

    def _settle_navigation_content_layout(self) -> None:
        """用导航动画结束后的真实 viewport 重新规划响应式控件。"""

        if getattr(self, "_closing", False):
            return
        self._request_side_panel_reflow(self, ReflowReason.RESIZE)

    def _navigation_widget(self, route_key: str):
        """按键读取导航控件；缺失键返回 None，不依赖异常控制流。"""

        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return None
        entry = navigation.panel.items.get(route_key)
        return entry.widget if entry is not None else None

    def _sync_navigation_accessibility(self, *_args) -> None:
        """统一导航项、折叠按钮的中文提示和可访问名称。"""

        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        navigation.setAccessibleName(tr("主导航"))
        panel = navigation.panel
        panel.menuButton.setAccessibleName(tr("展开或收起主导航"))
        panel.menuButton.setToolTip(tr("展开或收起主导航"))
        panel.returnButton.setAccessibleName(tr("返回上一页"))
        panel.returnButton.setToolTip(tr("返回上一页"))
        for route_key, label in getattr(self, "_navigation_labels", {}).items():
            item = self._navigation_widget(route_key)
            if item is None:
                continue
            item.setAccessibleName(label)
            item.setToolTip(label)

    def _sync_workspace_navigation_selection(self, route: WorkspaceRoute) -> None:
        """把当前规范功能映射到左栏一级入口，不以物理宿主代替用户所在页面。"""

        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        host = getattr(self, "_workspace_feature_hosts", {}).get(route.section)
        feature = host.canonical_feature(route.feature) if host is not None else route.feature
        route_key = getattr(self, "_workspace_navigation_keys", {}).get((route.section, feature))
        if route_key is None:
            return
        navigation.setCurrentItem(route_key)
        self._pending_navigation_scroll_key = route_key
        self._navigation_scroll_timer.start(0)

    def _ensure_current_navigation_item_visible(self) -> None:
        """只纵向定位当前入口，展开动画不能把图标列横向卷出视口。"""

        route_key = self._pending_navigation_scroll_key
        self._pending_navigation_scroll_key = ""
        if not route_key:
            return
        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        item = self._navigation_widget(route_key)
        if item is None or item.isHidden():
            return
        panel = navigation.panel
        panel.scrollArea.horizontalScrollBar().setValue(0)
        if not panel.scrollWidget.isAncestorOf(item):
            return
        # 动画首帧中控件已展开而视口仍窄，ensureWidgetVisible 会同时水平居中。
        # 用纵向中心与半高保留完整入口及上下留白，固定 x=0 遵循参考导航的图标列。
        center = item.mapTo(panel.scrollWidget, item.rect().center())
        panel.scrollArea.ensureVisible(0, center.y(), 0, item.height() // 2 + 12)

    def _on_workspace_route_changed(self, route: WorkspaceRoute) -> None:
        page = getattr(self, "_workspace_pages", {}).get(route.section)
        if page is self.stackedWidget.currentWidget():
            location = (route.section, route.feature)
            if location != getattr(self, "_device_popup_location", None):
                self._global_device_bar.dismiss_popups()
                self._device_popup_location = location
            if not getattr(self, "_workspace_navigation_in_progress", False):
                self._commit_navigation_location(
                    route,
                    record_history=False,
                )
            self._sync_workspace_navigation_selection(route)
        self._request_side_panel_reflow(self, ReflowReason.EXPLICIT)

    def _sync_device_context(self, *_args) -> None:
        panel = getattr(self, "left_panel", None)
        if panel is None:
            return
        context = panel.device_context_snapshot()
        selected = list(context.selected_devices)
        if self._pending_package_device and selected != [self._pending_package_device]:
            self._package_query_invalidated = True
        connected = list(context.connected_devices)
        state = context.discovery_state
        remote = panel.remote_panel
        if remote is not None:
            remote.set_connected_devices(connected if state == "ready" else [])
            remote.set_target_devices(self._remote_operation_devices())
        bar = getattr(self, "_global_device_bar", None)
        if bar is not None:
            bar.set_context(selected, connected, state)
        pages = [getattr(self, "_home_page", None)]
        pages.append(getattr(self, "_device_hub", None))
        pages.extend(getattr(self, "_workspace_pages", {}).values())
        for page in pages:
            setter = getattr(page, "set_device_context", None)
            if callable(setter):
                setter(selected, connected, state)
        self._sync_device_metadata(connected)
        self._sync_global_session_controls()

    def _sync_device_metadata(self, devices: list[str], *, incremental: bool = False) -> None:
        """展示元数据独立于设备选择上下文；单设备响应只刷新该设备卡片。"""
        panel = self.left_panel
        bar = getattr(self, "_global_device_bar", None)
        hub = getattr(self, "_device_hub", None)
        if hub is not None:
            records = {info["ip"]: info for info in DeviceStore.get_full_devices_info(devices)}
            for device in devices:
                records.setdefault(device, {"ip": device}).update(
                    self._device_metadata.get(device, {})
                )
            if bar is not None:
                def projected_name(device: str) -> str:
                    record = records[device]
                    if any(
                        _metadata_text(record.get(key))
                        for key in ("name", "alias", "Brand", "Model")
                    ):
                        return _device_name(device, record)
                    # 没有新元数据时沿用顶部栏已有名称，避免把用户可见标签
                    # 回退成“Android USB设备”；有元数据时以新快照为准。
                    return bar.device_label(device) or _device_name(device, record)

                names = {device: projected_name(device) for device in devices}
                for device, name in names.items():
                    records[device]["name"] = name
                if bar.set_device_labels(names):
                    # 电量等指标不改变显示名称，不应反复重建选择器和会话标签。
                    labels = bar.device_labels()
                    self.adb_controller.action_results.set_target_labels(labels)
                    apps = panel.app_panel
                    if apps is not None:
                        apps.set_device_labels(labels)
                    for host in self._workspace_feature_hosts.values():
                        host.performance_sessions.set_device_labels(labels)
                # 展示属性独立投影；仅品牌或版本变化也须更新已展开行，不改任务归属名称。
                bar.set_device_details({
                    device: {
                        "brand": _metadata_text(info.get("Brand")),
                        "model": _metadata_text(info.get("Model")),
                        "android_version": (
                            _metadata_text(info.get("Aversion"))
                            or _metadata_text(info.get("Android Version"))
                        ),
                        "connection": _connection_kind(device),
                    }
                    for device, info in records.items()
                })
            if incremental:
                for record in records.values():
                    hub.update_device_metadata(record)
            else:
                hub.set_device_metadata(list(records.values()))

    def _on_device_info_updated(self, device: str, info: dict) -> None:
        """只保留在线设备的展示字段；补充信息不写入用户配置或缓存唯一标识。"""

        if (
            self._closing
            or device not in self.left_panel.device_context_snapshot().connected_devices
        ):
            return
        generation = info.get("_overview_generation")
        if generation is not None and not self.adb_controller.is_device_overview_current(
            device, generation,
        ):
            return
        metrics = (
            "Resolution", "Density", "Total Memory", "Available Memory", "Storage Total",
            "Storage Available", "Battery Level", "Battery Status",
        )
        fields = (
            "Brand", "Model", "Aversion", "SDK Version", "CPU Architecture", "Hardware", *metrics,
        )
        metadata = self._device_metadata.setdefault(device, {})
        # 每次刷新都是新的设备快照，缺失的动态指标不能继续冒充本轮读取结果。
        for field in metrics:
            metadata.pop(field, None)
        for field in fields:
            value = str(info.get(field, "")).strip()
            if value and value.casefold() not in ("unknown", "n/a", "-"):
                metadata[field] = value
        self._sync_device_metadata([device], incremental=True)

    def _open_device_tool(self, section: str, feature: str, device_id: str) -> None:
        """概览快捷入口只接受已选在线目标，多选时保持其他目标不变。"""

        context = self.left_panel.device_context_snapshot()
        if context.discovery_state != "ready" or device_id not in context.selected_devices:
            return
        self._open_workspace_feature(section, feature, device_id=device_id)

    def _current_feature_host(self) -> WorkspaceFeatureHost | None:
        """只从当前可见物理页面解析宿主，后台会话不改变全局栏。"""

        current = self.stackedWidget.currentWidget()
        for section, page in getattr(self, "_workspace_pages", {}).items():
            if page is current:
                return self._workspace_feature_hosts[section]
        return None

    def _sync_global_session_controls(self) -> None:
        """设备任务显示当前页标题和所需目标入口，无设备任务保持独立页面。"""

        bar = getattr(self, "_global_device_bar", None)
        if bar is None:
            return
        host = self._current_feature_host()
        remote = self._current_remote_panel()
        bar.set_device_operations(
            remote.device_operations() if remote is not None else None,
            selection_locked=remote.is_mirror_selection_locked() if remote is not None else False,
        )
        current = self.stackedWidget.currentWidget()
        device_overview = (
            host is not None and host.section_key == "devices"
            and host.current_feature == "overview"
        )
        bar.setVisible(host is not None and not device_overview)
        bar.set_page_title(current.accessibleName() if current is not None else "")
        if host is None:
            bar.set_session_context(None, None)
            return
        requires = host.feature_requires_device(host.current_feature)
        close = host.close_session_button
        bar.set_session_context(
            host.device_combo if requires else None,
            close if not close.isHidden() else None,
            host.session_badge if not host.session_badge.isHidden() else None,
            single=requires and host.current_feature != "performance",
            selection_locked=host.is_device_selection_locked(),
            close_scope="session" if requires else "page",
        )

    def _select_operation_devices(self, devices: list[str]) -> None:
        """一次选择同时提交操作目标并切换单设备会话，避免查看与准入互相脱节。"""
        remote = self._current_remote_panel()
        if remote is not None and remote.is_mirror_selection_locked():
            return
        host = self._current_feature_host()
        single = bool(host is not None and host.feature_requires_device(host.current_feature)
                      and host.current_feature != "performance")
        if single:
            devices = devices[-1:]
            if (host is not None and host.is_device_selection_locked() and devices
                    and devices[0] != host.current_device_id):
                return
        self.left_panel.set_selected_devices(devices)
        if host is not None and devices:
            if single or (host.current_feature == "performance"
                          and host.current_device_id not in devices):
                self._choose_global_session(devices[0])

    def _current_remote_panel(self):
        """只为当前远程页面投影镜像状态，后台通知不污染其他页面的操作入口。"""
        host = self._current_feature_host()
        if host is None or host.section_key != "devices" or host.current_feature != "remote":
            return None
        return self.left_panel.remote_panel

    def _show_remote_device_selector(self) -> None:
        """空目标镜像动作复用当前页选择区，不创建另一份设备列表。"""
        if self._current_remote_panel() is not None and not self._closing:
            self._global_device_bar.open_picker()

    def _request_remote_device_operation(self, device: str, action: str) -> None:
        """行内动作交回原镜像控制器重新准入，既不改勾选也不切换设备会话。"""
        remote = self._current_remote_panel()
        if remote is not None and not self._closing:
            remote.request_device_operation(device, action)

    def _choose_global_session(self, device_id: str) -> None:
        """会话切换走原宿主入口，运行锁生效且不改写批量目标。"""

        host = self._current_feature_host()
        if host is None or not host.device_combo.isEnabled():
            return
        for index in range(host.device_combo.count()):
            if host.device_combo.itemData(index) == device_id:
                host.device_combo.setCurrentIndex(index)
                break

    def _close_global_session(self) -> None:
        host = self._current_feature_host()
        if host is not None and host.close_session_button.isEnabled():
            host.close_current_session()
            self._sync_global_session_controls()

    def _show_global_connection(self) -> None:
        """仅在概览显式切换连接区；复用组件，每次展开读取当前历史快照。"""

        if self._closing or not self._device_hub.isVisibleTo(self):
            return
        panel = self._connection_panel
        if panel is not None and panel.is_expanded:
            panel.collapse()
            return
        from gui.adapters.adb_pairing import QtAdbPairing
        from gui.widgets.device_connection import DeviceConnectionPanel

        if self._adb_pairing is None:
            self._adb_pairing = QtAdbPairing(self.task_supervisor, self)
            self._adb_pairing.connected.connect(self._on_wireless_connected)
        if panel is None:
            panel = DeviceConnectionPanel(
                self._adb_pairing, parent=self._device_hub, animated=True,
            )
            self._connection_panel = panel
            self._device_hub.set_connection_panel(panel)
            panel.transition_changed.connect(self._on_connection_transition_changed)
            panel.reveal_geometry_changed.connect(self._sync_device_reveal_geometry)
            panel.address_connect_requested.connect(self._connect_address)
            self.adb_controller.signals.connection_completed.connect(
                panel.complete_address_connection
            )
            panel.expanded_changed.connect(self._device_hub.set_connection_expanded)
        panel.expand(history=self.left_panel.connection_history())
        self._device_hub.set_connection_expanded(panel.is_expanded)

    def _connect_address(self, target: str, request_id: str) -> None:
        """地址请求沿用任务反馈准入，并把终态关联到仍然打开的连接面板。"""
        submitted = False

        def submit(address):
            nonlocal submitted
            self.adb_controller.connect_device(address, request_id=request_id)
            submitted = True

        self._action_feedback.dispatch(ACTION_SIGNALS["connect_requested"], submit, (target,))
        if not submitted and self._connection_panel is not None:
            # 已有同类任务或关闭准入拒绝时，不把面板留在永远等不到结果的忙碌状态。
            self._connection_panel.complete_address_connection(request_id, False)

    def _on_wireless_connected(self, outcome) -> None:
        """仅接纳当前已核实连接；页内反馈不再重复发送全局完成 Toast。"""
        pairing = self._adb_pairing
        if not self._closing and pairing is not None and pairing.accepts_outcome(outcome):
            self.adb_controller.accept_wireless_connection(outcome)

    def _on_nav_requested(self, key: str | WorkspaceRoute) -> None:
        """把业务键映射到对应的 FluentWindow 主页面。"""
        if not getattr(self, "_startup_complete", True) or getattr(self, "_closing", False):
            return

        if isinstance(key, WorkspaceRoute):
            self._open_workspace_feature(
                key.section,
                key.feature,
                device_id=key.device_id,
                payload=key.payload,
            )
            return

        pages = {
            "home": getattr(self, "_home_page", None),
            "devices": getattr(self, "_devices_page", None),
            "apps": getattr(self, "_apps_page", None),
            "system": getattr(self, "_system_page", None),
            "tasks": getattr(self, "_tasks_page", None),
            "settings": getattr(self, "_settings_page", None),
        }
        if key == "remote":
            self._open_workspace_feature("devices", "remote")
            return
        page = pages.get(key)
        if page is None:
            return
        if key in getattr(self, "_workspace_pages", {}):
            self._open_workspace_feature(key, "overview")
            return
        self.switchTo(page)
        if key == "tasks":
            self._task_page.refresh()

    def _on_run_library_error(self, message: str) -> None:
        """保存错误在当前页提示，不导航或把底层设备路径写入日志。"""
        if self._closing:
            return
        show_toast(
            self, title=tr("测试结果"), content=message, level="warning",
        )

    def _reuse_test_run(self, record: RunRecord) -> None:
        """只恢复参数；设备仍由当前会话准入决定，历史记录不能自动执行。"""
        if record.kind == "performance":
            self._open_workspace_feature(
                "system", "performance", payload={"run_parameters": record.parameters},
            )
        elif record.kind == "monkey":
            panel = self.left_panel.app_panel
            if panel is None:
                return
            try:
                panel.apply_run_parameters(record.parameters)
            except (TypeError, ValueError):
                self._on_run_library_error(tr("请先停止当前测试，并检查方案参数是否完整有效。"))
                return
            self._open_workspace_feature("apps", "overview")

    def _open_workspace_feature(
        self,
        section: str,
        feature: str = "overview",
        *,
        device_id: str = "",
        payload=None,
        _record_history: bool = True,
    ) -> bool:
        """在所属主页面打开内嵌功能，不创建独立业务窗口。"""

        with MainFrame._page_change_batch(self):
            return MainFrame._open_workspace_feature_now(
                self, section, feature, device_id=device_id, payload=payload,
                _record_history=_record_history,
            )

    def _open_workspace_feature_now(
        self, section: str, feature: str, *, device_id: str, payload,
        _record_history: bool,
    ) -> bool:
        """在现有准入和代次规则下打开路由，不把业务执行推迟到动画结束。"""

        if not getattr(self, "_startup_complete", True) or getattr(self, "_closing", False):
            return False
        if section == "remote":
            section = "devices"
            feature = "remote" if feature == "overview" else feature
        page = getattr(self, "_workspace_pages", {}).get(section)
        if page is None:
            return False
        route = WorkspaceRoute(section, feature, device_id, payload)
        if not page.supports_route(route):
            self.log_service.log(
                "WARNING",
                f"Unknown workspace route: {section}/{feature}",
            )
            return False
        previous_transition = getattr(
            self,
            "_workspace_navigation_in_progress",
            False,
        )
        self._workspace_navigation_in_progress = True
        try:
            opened = page.open_route(route)
        finally:
            self._workspace_navigation_in_progress = previous_transition
        if not opened:
            self.log_service.log(
                "WARNING",
                f"Unknown workspace route: {section}/{feature}",
            )
            return False
        stable_route = MainFrame._stable_workspace_route(page.current_route)
        MainFrame._commit_navigation_location(
            self,
            stable_route,
            record_history=_record_history,
        )
        self.switchTo(
            page,
            _record_history=False,
            _target_location=stable_route,
        )
        return opened

    def _setup_shortcuts(self) -> None:
        self._actions.setup_shortcuts()

    def _request_device_refresh(self) -> None:
        """让 SidePanel 统一提交扫描状态并抑制重复刷新。"""

        self.left_panel.request_device_refresh()

    def _on_theme_changed(self, _name: str):
        """主题变化后刷新窗口与页面状态，并持久化主题选择。"""
        if self._closing:
            return
        transition = getattr(self, "_page_transition", None)
        if transition is not None:
            transition.cancel()
        _debug_log(self, "ui.theme", action="apply", phase="applied", theme=_name)
        from core.settings_manager import AppSettings

        AppSettings.instance().set("theme", _name)

        settings_page = getattr(self, "_settings_page", None)
        if settings_page is not None:
            label = settings_page.THEME_LABELS.get(_name, tr("跟随系统"))
            blocker = QSignalBlocker(settings_page.theme_card.combo_box)
            settings_page.theme_card.combo_box.setCurrentText(label)
            del blocker

        self._refresh_save_path()
        self._refresh_window_chrome_theme()
        self._sync_title_bar_typography()
        self._theme_navigation_widget.sync_theme()
        self.left_panel.apply_device_theme()
        task_page = getattr(self, "_task_page", None)
        if task_page is not None:
            task_page._sync_theme_state()

    def _content_pages(self) -> tuple[QWidget, ...]:
        """返回主窗口直接持有的页面，供强调色按可见页刷新。"""
        pages = [
            getattr(self, name, None)
            for name in (
                "_home_page", "_devices_page", "_apps_page",
                "_system_page", "_tasks_page", "_settings_page",
            )
        ]
        pages.extend(getattr(self, "_workspace_pages", {}).values())
        return tuple(page for page in pages if page is not None)

    def _refresh_page_accent(self, page: QWidget | None) -> None:
        """只刷新当前页的注入样式；隐藏页在下次显示时按代次补刷。"""
        if page is None:
            return
        revision = getattr(self, "_accent_revision", 0)
        if getattr(page, "_accent_applied_revision", -1) == revision:
            return
        for widget in (page, *page.findChildren(QWidget)):
            refresh_fluent_widget_style(widget)
        setattr(page, "_accent_applied_revision", revision)

    def _on_accent_color_changed(self, _color: str) -> None:
        """强调色变化后刷新主窗口及当前可见页面，隐藏页延迟到显示时补刷。"""

        self._accent_revision = getattr(self, "_accent_revision", 0) + 1
        self._sync_plain_container_palettes()
        refresh_fluent_widget_style(self)
        for page in self._content_pages():
            if not page.isVisible():
                continue
            for widget in (page, *page.findChildren(QWidget)):
                refresh_fluent_widget_style(widget)
            setattr(page, "_accent_applied_revision", self._accent_revision)
        self.left_panel._on_theme_changed(BaseStyles.current_theme())
        for name in (
            "_home_page",
            "_devices_page",
            "_apps_page",
            "_system_page",
            "_tasks_page",
            "_settings_page",
        ):
            page = getattr(self, name, None)
            if page is None:
                continue
            QWidget.update(page)
            for child in page.findChildren(QWidget):
                # 表格等视图的 update 重载要求模型索引；此处只请求 QWidget 重绘，
                # 其 viewport 也在后代列表中，不能误入数据视图的更新接口。
                QWidget.update(child)

    def setMicaEffectEnabled(self, isEnabled: bool) -> None:
        """切换系统云母并同步 Qt 表面；不支持的平台保留实际生效的实色模式。"""

        super().setMicaEffectEnabled(isEnabled)
        # FluentWidget 构造期间也会调用此公开边界，此时尚无导航和内容栈。
        if getattr(self, "navigationInterface", None) is None:
            return
        if QApplication.platformName() == "windows":
            from gui.window_effects import sync_mica_backdrop

            applied = sync_mica_backdrop(int(self.winId()), self.isMicaEffectEnabled())
            if self.isMicaEffectEnabled() and not applied:
                super().setMicaEffectEnabled(False)
        self._sync_material_surface_styles()
        self._refresh_window_chrome_theme()

    def _sync_material_surface_styles(self) -> None:
        """保持原生内容层次，由根窗口决定云母或实色背景。"""

        transition = getattr(self, "_page_transition", None)
        if transition is not None:
            transition.cancel()
        mica = self.isMicaEffectEnabled()
        home = getattr(self, "_home_page", None)
        # 云母只改变材质，页面形状保持一致；滚动视口与内容壳共用左上圆角。
        corner_radius = self._CONTENT_CORNER_RADIUS
        if home is not None:
            home.set_top_left_radius(corner_radius)
        light = BaseStyles.color_for("Light", "WINDOW_BG")
        dark = BaseStyles.color_for("Dark", "WINDOW_BG")
        content_light = BaseStyles.color_for("Light", "CONTENT_BG")
        content_dark = BaseStyles.color_for("Dark", "CONTENT_BG")
        content_surface = getattr(self, "_content_surface", None)
        if content_surface is not None:
            # 云母模式让 DWM 壁纸参与合成；实色模式使用与原生命中内容层一致
            # 的不透明 token，避免浅色主题在关闭云母时仍透出一层灰色。
            if mica:
                mica_light = BaseStyles.color_for("Light", "CONTENT_MICA_BG")
                mica_dark = BaseStyles.color_for("Dark", "CONTENT_MICA_BG")
                light_style = (
                    f"background-color: {mica_light}; "
                    "border: 1px solid rgba(0, 0, 0, 0.068);"
                )
                dark_style = (
                    f"background-color: {mica_dark}; "
                    "border: 1px solid rgba(0, 0, 0, 0.18);"
                )
            else:
                light_style = (
                    f"background-color: {content_light}; "
                    "border: 1px solid rgba(0, 0, 0, 0.068);"
                )
                dark_style = (
                    f"background-color: {content_dark}; "
                    "border: 1px solid rgba(0, 0, 0, 0.18);"
                )
            setCustomStyleSheet(
                content_surface,
                f"QWidget#workspaceSurface {{ {light_style} border-right: none; "
                f"border-bottom: none; border-top-left-radius: {corner_radius}px; }}",
                f"QWidget#workspaceSurface {{ {dark_style} border-right: none; "
                f"border-bottom: none; border-top-left-radius: {corner_radius}px; }}",
            )
            self._update_content_surface_mask()
        # 内容壳承接原生 FluentWindow 的表面；内层栈保持透明，避免重复叠色。
        for surface, selector, light_color, dark_color, border in (
            (
                self.stackedWidget,
                "StackedWidget",
                "transparent" if content_surface is not None else light,
                "transparent" if content_surface is not None else dark,
                "none",
            ),
            (
                self.navigationInterface.panel,
                "NavigationPanel[menu=false]",
                "transparent" if mica else light,
                "transparent" if mica else dark,
                # 与 MENU 保持相同边框占位，避免展开时顶部下移、底部上移。
                "1px solid transparent",
            ),
        ):
            setCustomStyleSheet(
                surface,
                f"{selector} {{ background-color: {light_color}; "
                f"border: {border}; border-radius: 0px; }}",
                f"{selector} {{ background-color: {dark_color}; "
                f"border: {border}; border-radius: 0px; }}",
            )

    def _update_content_surface_mask(self) -> None:
        """裁剪内容壳及其子控件，避免实色页面背景覆盖左上圆角。"""

        surface = self._content_surface
        radius = min(self._CONTENT_CORNER_RADIUS, surface.width() // 2, surface.height() // 2)
        if radius <= 0:
            surface.clearMask()
            return
        # QRegion 是二值裁剪，QWidget 没有路径级 clip；移除 mask 会让滚动
        # 内容直接盖住左上圆角。圆角背景/边框仍由 QSS 抗锯齿绘制，mask 只
        # 负责裁掉圆角外的子树；这里的 1px 台阶是当前视口裁剪的硬约束。
        corner = QRegion(QRect(0, 0, radius, radius))
        circle = QRegion(QRect(0, 0, radius * 2, radius * 2), QRegion.RegionType.Ellipse)
        surface.setMask(QRegion(surface.rect()).subtracted(corner.subtracted(circle)))

    def _refresh_window_chrome_theme(self) -> None:
        """在 Mica/DWM 更新之后重新同步 FluentWindow 壳层的实际明暗外观。"""

        if getattr(self, "_closing", False):
            return
        # FluentWindow 默认用 120 ms 动画切换根背景，但外层堆栈的主题 QSS
        # 会立即生效。两者不同步时，暗色半透明边框会短暂叠在浅色背景上；
        # 项目契约要求主题 QSS 生效时根背景同步完成，因此这里停止动画并直达终态。
        self.backgroundColorAni.stop()
        self.setBackgroundColor(self._normalBackgroundColor())
        self._sync_plain_container_palettes()
        apply_dark_title_bar(self)

    def _onThemeChangedFinished(self) -> None:
        """沿用 Gallery 的延后同步，覆盖 Windows 主题消息晚于 Qt 样式提交的情况。"""
        super()._onThemeChangedFinished()
        QTimer.singleShot(100, self, self._refresh_window_chrome_theme)

    def _bind_system_theme_changes(self) -> None:
        """跟随 Qt 的系统配色信号，在应用运行中重新解析 System 主题。"""

        style_hints = QApplication.styleHints()
        signal = getattr(style_hints, "colorSchemeChanged", None)
        if signal is not None:
            signal.connect(self._on_system_color_scheme_changed)

    def _on_system_color_scheme_changed(self, *_args) -> None:
        if BaseStyles.current_theme() == "System":
            BaseStyles.switch_theme("System")

    def _sync_plain_container_palettes(self) -> None:
        """让移植页面及隐藏卡片立即承接当前应用主题。"""

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        palette = app.palette()
        candidates = []
        shell_roots = tuple(
            filter(
                None,
                (
                    getattr(self, "navigationInterface", None),
                    getattr(self, "titleBar", None),
                ),
            )
        )
        candidates.extend(shell_roots)
        navigation = getattr(self, "navigationInterface", None)
        if navigation is not None:
            candidates.extend(navigation.findChildren(NavigationPanel))
        shell_ids = {id(widget) for widget in candidates}
        for name in (
            "_home_page",
            "_devices_page",
            "_apps_page",
            "_system_page",
            "_tasks_page",
            "_settings_page",
        ):
            page = getattr(self, name, None)
            if page is None:
                continue
            candidates.append(page)
            viewport = getattr(page, "viewport", None)
            if callable(viewport):
                candidates.append(viewport())
            widget = getattr(page, "widget", None)
            if callable(widget):
                candidates.append(widget())
            body = getattr(page, "body", None)
            if body is not None:
                body_viewport = getattr(body, "viewport", None)
                if callable(body_viewport):
                    candidates.append(body_viewport())
                body_widget = getattr(body, "widget", None)
                if callable(body_widget):
                    candidates.append(body_widget())
        roots = []
        seen: set[int] = set()
        for widget in filter(None, candidates):
            identity = id(widget)
            if identity in seen:
                continue
            seen.add(identity)
            roots.append(widget)
            widget.setPalette(palette)
            # 页面留白始终透出共享内容层；只有窗口壳在关闭云母时填充根底色。
            widget.setAutoFillBackground(
                identity in shell_ids and not self.isMicaEffectEnabled()
            )
            widget.update()

        # 壳层透明不等于沿用旧调色板；文字、图标仍需同步当前主题。
        for root in shell_roots:
            for child in root.findChildren(QWidget):
                child.setPalette(palette)
                child.update()

        # qfluentwidgets 用 120 ms 动画更新 CardWidget 背景。隐藏业务页面的
        # 动画不会推进，稍后打开时会保留切换前的浅色卡片，因此在主题切换边界
        # 直接同步静止态背景；悬停/按压后仍由组件自己的动画接管。
        for root in roots:
            for container in root.findChildren(QWidget):
                if container.autoFillBackground():
                    container.setPalette(palette)
                    container.update()
            if isinstance(root, CardWidget):
                root._updateBackgroundColor()
                root.backgroundColorAni.setCurrentTime(root.backgroundColorAni.duration())
                root.update()
            for card in root.findChildren(CardWidget):
                card._updateBackgroundColor()
                card.backgroundColorAni.setCurrentTime(card.backgroundColorAni.duration())
                card.update()

    def _on_ui_font_changed(self, _config) -> None:
        """应用新的界面字体。"""

        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._sync_title_bar_typography()
        self._sync_navigation_typography()

    def _sync_title_bar_typography(self) -> None:
        """标题栏沿用界面字体，大字号时同步预留正文顶部空间。"""
        label = cast(FluentTitleBar, self.titleBar).titleLabel
        apply_label_role(label, FontRole.UI)
        # Fluent 标题栏的父级 QSS 固定 13px，局部声明才能保留用户设置的字号。
        set_fluent_font_rule(
            label, f"QLabel#titleLabel {{ {font_qss(BaseStyles.font_for_role(FontRole.UI))} }}",
        )
        label.adjustSize()
        height = max(40, label.fontMetrics().height() + 4)
        self.titleBar.setFixedHeight(height)
        self.widgetLayout.setContentsMargins(0, height, 0, 0)

    def _sync_navigation_typography(self) -> None:
        """同步导航显式字体及文字空间，保留原有控件、路由和选中状态。

        Fluent 树节点的文本控件单独设置字体且在展开收起时恢复固定尺寸，
        因此字体变化和导航形态提交后都需更新叶子尺寸，不能仅依赖窗口继承。
        """
        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        items = [self._navigation_widget(key) for key in getattr(self, "_navigation_labels", {})]
        items.append(getattr(self, "_theme_navigation_widget", None))
        items = [item for item in items if item is not None]
        if not items:
            return
        font = BaseStyles.font_for_role(FontRole.UI)
        for item in items:
            item.setFont(font)
        width = max(220, max(item.fontMetrics().horizontalAdvance(item.text()) + 67
                             for item in items))
        panel = navigation.panel
        width_changed = panel.expandWidth != width
        if width_changed:
            navigation.setExpandWidth(width)
        for item in items:
            text_item = getattr(item, "itemWidget", item)
            text_item.setFixedSize(
                40 if text_item.isCompacted else width - 10,
                max(36, text_item.fontMetrics().height() + 2),
            )
            if text_item is not item:
                item.setFixedSize(item.sizeHint())
        if width_changed and panel.displayMode in (
            NavigationDisplayMode.EXPAND, NavigationDisplayMode.MENU,
        ):
            if panel.expandAni.state() != QAbstractAnimation.State.Stopped:
                # 动画继续使用原几何终点会覆盖新字号需要的宽度；收起仍保留原终点。
                if panel.expandAni.property("expand"):
                    target = panel.expandAni.endValue()
                    target.setWidth(width)
                    panel.expandAni.setEndValue(target)
            else:
                panel.resize(width, panel.height())

    def _toggle_theme(self):
        return self._actions.toggle_theme()

    def _connect_all_signals(self):
        """将左侧面板信号连接到 ADB Controller，并包装危险操作校验。"""
        LP = self.left_panel.signals
        CTL = self.adb_controller.signals
        AC = self.adb_controller

        self._action_feedback = ActionFeedbackPresenter(self)
        self._connect_controller_feedback(LP, CTL)
        signal_map = (
            self._device_signal_map(LP, AC)
            + self._app_signal_map(LP, AC)
            + self._testing_signal_map(LP, AC)
            + self._system_signal_map(LP, AC)
        )
        for signal_, handler in signal_map:
            signal_.connect(self._action_feedback.bind(LP, signal_, handler))
        self.left_panel.selected_devices_changed.connect(self._update_device_actions)
        self._update_device_actions()

    def _connect_controller_feedback(self, LP, CTL):
        CTL.devices_updated.connect(self._on_devices_updated)
        CTL.device_refresh_superseded.connect(self.left_panel.on_device_refresh_superseded)
        CTL.screenshot_batch_ready.connect(self._on_screenshot_batch_ready)
        LP.log_message.connect(self.log_service.log)
        CTL.record_target_finished.connect(self.left_panel.on_recording_target_finished)
        CTL.record_target_retryable.connect(self.left_panel.on_recording_target_retryable)
        CTL.monkey_target_finished.connect(self.left_panel.on_monkey_target_finished)
        apps_panel = self.left_panel.app_panel
        if apps_panel is None:
            raise RuntimeError("apps panel was not initialized before signal binding")
        apps_panel.set_run_library(self.run_library)
        CTL.run_record_ready.connect(self.run_library.record_run)
        apps_panel.monkey_preparation_requested.connect(self.adb_controller.prepare_monkey_targets)
        CTL.monkey_preparation_finished.connect(apps_panel.on_monkey_preparation_finished)
        operation_handler = getattr(
            self,
            "_on_operation_completed",
            self.left_panel.on_operation_completed,
        )
        CTL.operation_completed.connect(operation_handler)
        CTL.current_package_received.connect(self._on_current_package_received)
        apps_panel.program_edit.textChanged.connect(self._invalidate_package_query)
        CTL.device_info_updated.connect(self._on_device_info_updated)

    def _request_current_package(self, devices: list[str]) -> None:
        """唯一输入框一次只接收一台明确目标的查询，禁止重复请求争用回填。"""

        targets = list(dict.fromkeys(devices))
        apps = self.left_panel.app_panel
        if (apps is None or self._pending_package_device or len(targets) != 1
                or targets != self.left_panel.selected_devices):
            return
        self._pending_package_device = targets[0]
        self._package_query_invalidated = False
        apps.set_package_query_pending(True)
        try:
            self.adb_controller.get_current_package(targets)
        except Exception:
            self._finish_package_query()
            raise

    def _invalidate_package_query(self, *_args) -> None:
        """编辑输入或变更目标后，已发出的读取只完成自身，不再覆盖当前输入。"""

        if self._pending_package_device:
            self._package_query_invalidated = True

    def _finish_package_query(self) -> None:
        self._pending_package_device = ""
        apps = self.left_panel.app_panel
        if apps is not None:
            apps.set_package_query_pending(False)

    def _on_current_package_received(self, device: str, package: str) -> None:
        """在 GUI 主线程核对请求与选择后同步回填，避免额外队列间隙覆盖编辑。"""

        if device != self._pending_package_device or self._closing:
            return
        accepted = (not self._package_query_invalidated
                    and self.left_panel.selected_devices == [device])
        self._finish_package_query()
        if accepted:
            self.left_panel.update_current_package(device, package)

    def _on_screenshot_batch_ready(self, image_paths: list[str]) -> None:
        """把截图结果送入 Apps 分区的持久媒体页。"""

        if getattr(self, "_closing", False):
            return
        paths = [str(path) for path in image_paths if str(path)]
        if not paths:
            return
        payload = {"image_paths": paths, "focus_new": True}
        if (
            self.stackedWidget.currentWidget() is self._apps_page
            and self._apps_page.current_route.feature == "media"
        ):
            self._open_workspace_feature("apps", "media", payload=payload)
            return
        page = self._workspace_feature_hosts["apps"].update_feature("media", payload)
        if page is None:
            self.log_service.log(
                "DEBUG", "Screenshot results queued until the previous page closes",
            )
            return

    def _on_operation_completed(self, operation: str, success: bool, message: str) -> None:
        """转发操作结果，并将刷新失败映射为明确的 ADB 不可用状态。"""

        if getattr(self, "_closing", False):
            return
        if operation == "refresh":
            self._pending_scanned_devices = None
            timer = getattr(self, "_scan_refresh_timer", None)
            if timer is not None:
                timer.stop()
        if operation == "get_package" and not success:
            self._finish_package_query()
        self.left_panel.on_operation_completed(operation, success, message)
        task_page = getattr(self, "_task_page", None)
        if task_page is not None and task_page.isVisible():
            task_page.refresh()
        if operation == "refresh" and not success:
            scan_thread = getattr(self, "_scan_thread", None)
            invalidate_snapshot = getattr(scan_thread, "invalidate_snapshot", None)
            if callable(invalidate_snapshot):
                invalidate_snapshot()
            QTimer.singleShot(
                0,
                self,
                lambda: self.left_panel.set_device_discovery_state("unavailable"),
            )

    def _device_signal_map(self, LP, AC):
        return [
            (LP.connect_requested, AC.connect_device),
            (LP.refresh_devices_requested, AC.refresh_devices),
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
            (LP.get_program_requested, self._request_current_package),
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
            (LP.execute_intent_requested, AC.execute_intent),
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
            (LP.system_service_requested, AC.system_service),
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
        if getattr(self, "_closing", False):
            return
        self._device_metadata = {
            device: info for device, info in self._device_metadata.items() if device in devices
        }
        self.left_panel.update_device_list(devices)
        self.left_panel.refresh_device_choices()
        self._update_device_actions()

    def _update_device_actions(self, _devices=None) -> None:
        """更新首页入口提示；无设备时由目标页提供可恢复空态。"""

        selected_count = len(self.left_panel.selected_devices)
        cards = getattr(getattr(self, "_home_page", None), "tool_cards", {})
        for key in ("app_mgr", "file_explorer", "logcat", "performance"):
            card = cards.get(key)
            if card is not None:
                card.setEnabled(True)
                card.setToolTip(
                    "" if selected_count else tr("打开后可前往设备页选择操作设备")
                )
        self._sync_device_context()


    def _show_settings(self):
        page = getattr(self, "_settings_page", None)
        if page is not None:
            self.switchTo(page)
        return None

    def _open_cmd(self):
        """在项目根目录打开系统终端。"""
        import platform

        _debug_log(self, "ui.action", action="cmd", phase="requested")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system = platform.system()
        runner = ProcessRunner()
        if system == "Windows":
            runner.spawn(["cmd.exe", "/K", f'cd /d "{root}"'], creationflags=CREATE_NEW_CONSOLE)
            _debug_log(self, "ui.action", action="cmd", backend="windows", phase="launched")
        elif system == "Darwin":
            runner.spawn(["open", "-a", "Terminal", root])
            _debug_log(self, "ui.action", action="cmd", backend="macos", phase="launched")
        else:
            for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"]:
                if shutil.which(term):
                    runner.spawn([term], cwd=root)
                    _debug_log(
                        self,
                        "ui.action",
                        action="cmd",
                        backend="linux",
                        phase="launched",
                    )
                    return
            _debug_log(
                self,
                "ui.action",
                action="cmd",
                phase="blocked",
                reason="terminal_unavailable",
            )

    # ── 窗口和面板尺寸 ──────────────────────────────────────────────────

    def apply_window_size(self, w: int, h: int):
        self._cancel_user_resize_transaction()
        preferred = normalize_window_size(w, h)
        self._preferred_window_size = QSize(preferred)
        self._apply_workspace_constraints(self._bound_screen, request_reflow=True)
        self._persist_window_size(preferred)

    def restore_default_window_size(self):
        """立即恢复并持久化默认窗口尺寸。"""

        if self.isMaximized() or self.isMinimized() or self.isFullScreen():
            self.showNormal()
        self.apply_window_size(DEFAULT_WINDOW_SIZE.width(), DEFAULT_WINDOW_SIZE.height())

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

    def _set_always_on_top_qt(self, enabled: bool) -> bool:
        """非 Windows 更新 Qt 置顶请求，保留显隐、几何和窗口状态，不抢占后台窗口焦点。"""
        flag = Qt.WindowType.WindowStaysOnTopHint
        if bool(self.windowFlags() & flag) == enabled:
            return True
        visible = self.isVisible()
        state = self.windowState()
        geometry = self.saveGeometry()
        active = self.isActiveWindow()
        focus = self.focusWidget()
        without_activation = self.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlag(flag, enabled)
        self.restoreGeometry(geometry)
        self.setWindowState(state)
        if visible:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not active)
            self.show()
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, without_activation)
            if active and not self.isMinimized():
                self.activateWindow()
                if focus is not None:
                    focus.setFocus(Qt.FocusReason.OtherFocusReason)
        return bool(self.windowFlags() & flag) == enabled

    def set_always_on_top(self, enabled: bool):
        self._always_on_top = bool(enabled)
        native_applied = False
        if os.name == "nt":
            # Windows 原生失败时不得通过重建窗口兜底，以免破坏材质与窗口生命周期。
            applied = native_applied = self._set_always_on_top_native(self._always_on_top)
        else:
            applied = MainFrame._set_always_on_top_qt(self, self._always_on_top)
            self._always_on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        _debug_log(
            self,
            "ui.window",
            action="always_on_top",
            enabled=self._always_on_top,
            native_applied=native_applied,
            phase="applied" if applied else "deferred",
        )
        self._refresh_always_on_top_button()
        from core.settings_manager import AppSettings

        AppSettings.instance().set("always_on_top", self._always_on_top)

    def _refresh_always_on_top_button(self):
        card = getattr(getattr(self, "_settings_page", None), "pin_card", None)
        if card is not None and card.isChecked() != self._always_on_top:
            card.setChecked(self._always_on_top)

    @staticmethod
    def _request_side_panel_reflow(owner, reason: ReflowReason) -> None:
        """以兼容 mock/精简壳对象的方式请求 SidePanel 响应式重排。"""

        panel = getattr(owner, "left_panel", None)
        callback = getattr(panel, "request_responsive_reflow", None)
        if callable(callback):
            callback(reason)

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
        if getattr(self, "_startup_aborting", False):
            return
        timer = getattr(self, "_window_size_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
            MainFrame._save_pending_window_size(self)

        # 原生无边框缩放在部分窗口系统上可能只产生 resizeEvent，而没有回到热区的
        # 事务完成回调。关闭前以最终可见状态兜底，确保尺寸和主题不会跨会话丢失。
        if (
            not self.isMaximized()
            and not self.isMinimized()
            and not self.isFullScreen()
            and not self._restricted_workspace
        ):
            preferred_size = normalize_window_size(self.width(), self.height())
        else:
            preferred_size = QSize(self._preferred_window_size)
        self._preferred_window_size = QSize(preferred_size)
        MainFrame._update_settings(
            AppSettings.instance(),
            {
                "window_width": int(preferred_size.width()),
                "window_height": int(preferred_size.height()),
                "theme": BaseStyles.current_theme(),
            },
        )

    # ── 全局保存路径 ────────────────────────────────────────────────────

    def _refresh_save_path(self):
        settings = AppSettings.instance()
        path = str(settings.save_directory or "")
        card = getattr(getattr(self, "_settings_page", None), "save_card", None)
        if card is not None:
            card.setContent(path or tr("系统默认目录"))
        return path

    def _on_save_path_clicked(self):
        return self._actions.choose_save_directory()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        forced_size = getattr(self, "_workspace_forced_size", None)
        if (
            not getattr(self, "_applying_workspace_constraints", False)
            and forced_size is not None
            and event.size() != forced_size
        ):
            self._workspace_forced_size = None
        controller = getattr(self, "_resize_controller", None)
        if controller is not None:
            controller.update_geometry()
        if getattr(self, "_layout_ready", False):
            self._navigation_layout_timer.start()
        self._schedule_window_size_save(event.size())

    def showEvent(self, event):
        super().showEvent(event)
        self._bind_window_screen()
        # FluentWidget.showEvent 会在 Win11 再次应用 Mica；必须在它之后覆盖
        # 标题栏和导航壳层，否则“浅色 + 系统深色”首次启动会出现黑色侧栏。
        self._refresh_window_chrome_theme()
        QTimer.singleShot(0, self, self._refresh_window_chrome_theme)
        self._navigation_layout_timer.start(0)
        if getattr(self, "_startup_complete", False):
            self._start_startup_services()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._finish_user_resize_transaction()
            controller = getattr(self, "_resize_controller", None)
            if controller is not None:
                controller.update_geometry()

    def eventFilter(self, watched, event):
        """同步内容边界裁剪，并在原生调色板事件后恢复云母明暗。"""
        if watched in (
            getattr(self, "_navigation_focus_scroll", None),
            getattr(self, "_navigation_focus_viewport", None),
        ):
            # 导航项的鼠标事件会传播到视口；即使焦点未移动也要更新输入来源。
            if event.type() == QEvent.Type.FocusIn and isinstance(event, QFocusEvent):
                self._navigation_keyboard_focus = event.reason() in (
                    Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                    Qt.FocusReason.ShortcutFocusReason,
                )
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._navigation_keyboard_focus = False
            elif event.type() == QEvent.Type.KeyPress:
                self._navigation_keyboard_focus = True
        if (
            watched is getattr(self, "_content_surface", None)
            and event.type() == QEvent.Type.Resize
        ):
            self._update_content_surface_mask()
        if (
            watched is getattr(self, "_bound_window_handle", None)
            and event.type() == QEvent.Type.ApplicationPaletteChange
            and not getattr(self, "_closing", False)
        ):
            # QApplication 先向平台窗口分发，再调用对象过滤器。Qt 6.8 在前一步
            # 会清除无边框窗口的 DWM 深色属性；云母也使用它，必须在此处重申。
            apply_dark_title_bar(self)
        return super().eventFilter(watched, event)

    def _wire_installer_update(self) -> None:
        """安装版组合根连接显式下载与交接；缺省不创建下载或准备线程。"""
        if self._handoff is None:
            return
        from gui.adapters.installer_update import QtInstallerUpdate

        about = self._settings_page.about_panel
        self._installer_update = QtInstallerUpdate(self)
        self._installer_handoff = QtInstallerHandoff(self._handoff, self)
        about.set_installer_enabled(True)
        self._app_update.changed.connect(self._on_installer_release_changed)
        self._installer_update.changed.connect(about.set_installer_snapshot)
        self._installer_handoff.changed.connect(about.set_handoff_state)
        self._installer_handoff.ready.connect(self._on_installer_handoff_ready)
        about.installerDownloadRequested.connect(self._request_installer_download)
        about.installerCancelRequested.connect(self._installer_update.cancel)
        about.installerInstallRequested.connect(self._request_installer_install)
        self._installer_update.set_release(self._app_update.snapshot)
        about.set_installer_snapshot(self._installer_update.snapshot)

    def _on_installer_release_changed(self, snapshot) -> None:
        """重查立即作废旧安装意图，helper 的晚到 READY 不能触发退出。"""
        if self._closing or self._installer_update is None:
            return
        if self._installer_requested_asset is not None and (
            snapshot.status != "available"
            or snapshot.installer_asset != self._installer_requested_asset
        ):
            self._installer_requested_asset = None
            assert self._installer_handoff is not None
            self._installer_handoff.cancel()
            self._settings_page.about_panel.set_handoff_state("cancelled")
        self._installer_update.set_release(snapshot)

    def _request_installer_download(self) -> None:
        """下载准入复核当前正式发布，按钮可见性不作为信任依据。"""
        if self._closing or self._installer_update is None:
            return
        snapshot = self._app_update.snapshot
        if snapshot.status == "available" and snapshot.installer_asset is not None:
            self._settings_page.about_panel.set_handoff_state("idle")
            self._installer_update.start(snapshot.installer_asset)

    def _request_installer_install(self) -> None:
        """确认结束本实例任务后才异步准备；准备失败时尚未进入不可逆关闭。"""
        if (
            self._closing or self._installer_confirmation_pending
            or self._installer_update is None or self._installer_handoff is None
            or self._installer_handoff.is_running()
        ):
            return
        snapshot = self._installer_update.snapshot
        release = self._app_update.snapshot
        verified = snapshot.verified
        if (
            snapshot.status != "ready" or verified is None or release.status != "available"
            or release.installer_asset != verified.asset
        ):
            return
        self._installer_confirmation_pending = True
        try:
            confirmed = self._confirm_installer_exit()
        finally:
            self._installer_confirmation_pending = False
        # 确认框的嵌套事件循环可能交付重查或普通关闭，确认返回后再次核对准入。
        current = self._app_update.snapshot
        if (
            not confirmed or self._closing or current.status != "available"
            or current.installer_asset != verified.asset
            or self._installer_update.snapshot.verified is not verified
        ):
            return
        self._installer_requested_asset = verified.asset
        self._installer_handoff.start(verified)

    def _confirm_installer_exit(self) -> bool:
        """使用现有 Fluent 确认外壳，仅展示任务类型，不输出设备身份和缓存路径。"""
        names = sorted({
            _operation_label(item.kind)
            for item in self.adb_controller.operation_manager.active_snapshot()
        })
        content = tr(
            "将停止本实例的设备任务和后台采集，保存设置与结果后退出，并打开安装向导。"
            "\n若关闭或保存失败，本次不会运行安装器；安装包将保留供下次启动重试。"
        )
        if names:
            content += "\n" + tr("当前任务：{tasks}").format(tasks="、".join(names))
        dialog = MessageBox(tr("退出并安装更新？"), content, self)
        dialog.contentLabel.setTextFormat(Qt.TextFormat.PlainText)
        dialog.yesButton.setText(tr("退出并安装"))
        dialog.cancelButton.setText(tr("继续使用"))
        for widget in (
            dialog.titleLabel, dialog.contentLabel, dialog.yesButton, dialog.cancelButton,
        ):
            apply_dialog_font_role(widget, FontRole.UI)
            widget.ensurePolished()
        # 第三方 MessageBox 在构造时固定尺寸；按最终项目字号重新度量正文和操作区。
        width = max(300, min(560, self.width() - 64))
        dialog.contentLabel.setText(content)
        for label in (dialog.titleLabel, dialog.contentLabel):
            label.setWordWrap(True)
            label.setFixedWidth(width - 48)
            label.setFixedHeight(max(
                label.fontMetrics().height(), label.heightForWidth(width - 48),
            ))
        for button in (dialog.yesButton, dialog.cancelButton):
            button.setFixedHeight(max(32, button.fontMetrics().height() + 16))
        dialog.buttonGroup.setFixedHeight(dialog.yesButton.height() + 48)
        dialog.widget.setFixedSize(
            width,
            dialog.titleLabel.height() + dialog.contentLabel.height()
            + dialog.buttonGroup.height() + 60,
        )
        dialog.cancelButton.setFocus(Qt.FocusReason.OtherFocusReason)
        try:
            return bool(dialog.exec())
        finally:
            dialog.deleteLater()

    def _on_installer_handoff_ready(self) -> None:
        """只接受当前意图的 READY；真正执行授权由关闭结果与根入口共同控制。"""
        if self._installer_update is None or self._installer_handoff is None:
            return
        release = self._app_update.snapshot
        verified = self._installer_update.snapshot.verified
        valid = (
            not self._closing and self._handoff is not None and self._handoff.prepared
            and release.status == "available" and verified is not None
            and release.installer_asset == self._installer_requested_asset == verified.asset
        )
        if not valid:
            self._installer_handoff.cancel()
            self._settings_page.about_panel.set_handoff_state("cancelled")
            return
        self._installer_close_requested = True
        self.close()

    def closeEvent(self, event):
        transition = getattr(self, "_page_transition", None)
        if transition is not None:
            transition.cancel()
        if not getattr(self, "_startup_complete", True) and not self._startup_aborting:
            event.ignore()
            self.abort_startup()
            return
        (getattr(self, "_close_controller", None) or CloseController(self)).handle_close_event(
            event
        )
        if getattr(self, "_startup_aborting", False) and self._close_ready:
            self._finish_startup_abort()

    def _register_application_shutdown_tasks(self):
        return (
            getattr(self, "_close_controller", None) or CloseController(self)
        )._register_application_shutdown_tasks()

    def _prepare_ui_for_shutdown(self):
        return (
            getattr(self, "_close_controller", None) or CloseController(self)
        )._prepare_ui_for_shutdown()

    def _on_application_stopped(self, results: tuple, residual: tuple) -> None:
        return (
            getattr(self, "_close_controller", None) or CloseController(self)
        )._on_application_stopped(results, residual)

    def _flush_shutdown_state(self):
        return (
            getattr(self, "_close_controller", None) or CloseController(self)
        )._flush_shutdown_state()

    def _on_application_finalized(self, result: TaskStopResult | None, residual: tuple) -> None:
        return (
            getattr(self, "_close_controller", None) or CloseController(self)
        )._on_application_finalized(result, residual)
