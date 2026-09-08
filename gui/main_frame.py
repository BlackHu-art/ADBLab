"""组装主窗口、功能面板、设备扫描和应用级关闭流程。"""

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QSignalBlocker,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QResizeEvent
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
    FluentWindow,
    NavigationDisplayMode,
    NavigationItemPosition,
    NavigationPanel,
    SmoothScrollArea,
    setCustomStyleSheet,
)
from shiboken6 import isValid

from adblab.application.supervision import TaskStopResult
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from controllers import ADBController
from core.exec import CREATE_NEW_CONSOLE, CommandRunner, ProcessRunner, adb_runtime
from core.log_service import LogService
from core.settings_manager import AppSettings, set_error_sink
from gui.action_feedback import ActionFeedbackPresenter
from gui.close_controller import CloseController
from gui.i18n import tr
from gui.main_frame_actions import MainFrameActions
from gui.notifications import show_toast
from gui.pages.device_hub import DeviceHubPage, _device_name
from gui.pages.fluent_pages import (
    GalleryPage,
    HomePage,
    SettingsPage,
    WorkspaceAreaPage,
    WorkspaceSectionPage,
)
from gui.pages.tasks_page import TaskCenterPage
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute
from gui.panels.side_panel import SidePanel
from gui.run_library import RunLibraryController
from gui.screen_adapter import QtScreenAdapter, ScreenAdapter
from gui.styles.icon_loader import DEVICE_ICON
from gui.widgets.device_context_bar import DeviceContextBar
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.navigation_theme import NavigationThemeToggle
from gui.widgets.responsive_controller import ReflowReason
from gui.window_layout import (
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    compute_workspace_constraints,
    normalize_window_size,
)
from models.device_store import DeviceStore
from services.run_library import RunLibrary, RunRecord
from services.task_history import TaskHistoryStore
from utils.resource_path import resource_path

from .styles import BaseStyles, FontRole
from .styles.fluent import refresh_fluent_widget_style
from .styles.theme import apply_dark_title_bar


def _debug_log(owner, event: str, **fields) -> None:
    """输出不含敏感业务值的结构化开发诊断。"""
    log_service = getattr(owner, "log_service", None)
    if log_service is None:
        return
    details = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    message = event if not details else f"{event} {details}"
    log_service.log("DEBUG", message)


class _ScanThread(QThread):
    """以低频率轮询 ``adb devices`` 的长生命周期线程。

    扫描调用走 ProcessRunner 并以 100ms 轮询推进：停止请求可在任意时刻
    终止正在执行的 adb 子进程，保证线程在关闭窗口的等待预算内退出，
    避免 Qt 在 QThread 运行中销毁对象导致进程崩溃。
    """

    SCAN_CALL_TIMEOUT_S = 15.0

    devices_changed = Signal(list)
    discovery_state_changed = Signal(str)

    def __init__(self, parent=None, interval_ms: int = 15000):
        super().__init__(parent)
        self._stop_flag = False
        self._interval_ms = max(3000, int(interval_ms))
        self._snapshot_invalidated = threading.Event()

    def stop(self):
        self._stop_flag = True

    def invalidate_snapshot(self) -> None:
        """让下一次成功轮询重发快照，用于恢复外部刷新失败状态。"""

        self._snapshot_invalidated.set()

    def run(self):
        from models.adb_device import parse_connected_devices

        runner: ProcessRunner | None = None
        last_devices = None  # 首次轮询必须发布设备列表。
        last_state = "scanning"
        while not self._stop_flag:
            runtime = adb_runtime()
            if runtime is not None:
                # 恢复检查独立于原生扫描成功和普通命令忙碌状态，避免慢客户端拖住恢复。
                runtime.request_device_check()
            fast_scan = runtime is not None and runtime.can_scan_fast()
            if not fast_scan and CommandRunner.active_count() != 0:
                # 有受管命令在执行时跳过本轮，等待完整间隔后再试。
                if self._sleep_interruptibly(self._interval_ms):
                    return
                continue
            try:
                if fast_scan:
                    result = CommandRunner.run(
                        ["adb", "devices", "-l"], timeout=self.SCAN_CALL_TIMEOUT_S,
                        cancelled=lambda: self._stop_flag,
                    )
                    if result.stale:
                        # 晚到列表不代表发现失败，保持当前快照并等待下一轮正常扫描。
                        if self._sleep_interruptibly(self._interval_ms):
                            return
                        continue
                    output = result.output if result.success else None
                else:
                    if runner is None:
                        runner = ProcessRunner()
                    output = self._run_devices_scan(runner)
                if self._stop_flag:
                    return
                if output is None:
                    if last_state != "unavailable":
                        self.discovery_state_changed.emit("unavailable")
                    last_state = "unavailable"
                else:
                    devices = parse_connected_devices(output)
                    device_set = tuple(sorted(devices))
                    # 成功状态由同一设备快照在主线程提交，避免 ready/empty
                    # 先于 300ms 防抖列表到达。故障恢复时即使集合相同也重发。
                    if (
                        device_set != last_devices
                        or last_state == "unavailable"
                        or self._snapshot_invalidated.is_set()
                    ):
                        self._snapshot_invalidated.clear()
                        last_devices = device_set
                        self.devices_changed.emit(devices)
                    last_state = "ready" if devices else "empty"
            except Exception:
                if not self._stop_flag and last_state != "unavailable":
                    self.discovery_state_changed.emit("unavailable")
                last_state = "unavailable"
            if self._sleep_interruptibly(self._interval_ms):
                return

    def _run_devices_scan(self, runner: ProcessRunner) -> str | None:
        """执行一次 ``adb devices`` 并返回 stdout 文本。

        原生客户端在部分环境启动缓慢，使用独立超时；停止请求到来时
        终止本次子进程并返回 None，不推断具体监控软件的因果关系。
        """
        try:
            proc = runner.start(
                "device_scan",
                ["adb", "devices"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return None
        deadline = time.monotonic() + self.SCAN_CALL_TIMEOUT_S
        try:
            return_code = None
            while True:
                if self._stop_flag:
                    runner.stop("device_scan", timeout=2.0)
                    return None
                try:
                    return_code = proc.poll()
                    if return_code is not None:
                        break
                except OSError:
                    return None
                if time.monotonic() >= deadline:
                    runner.stop("device_scan", timeout=2.0)
                    return None
                self.msleep(100)
            stdout, _stderr = proc.communicate()
            return stdout if return_code == 0 else None
        except Exception:
            return None

    def _sleep_interruptibly(self, delay_ms: int) -> bool:
        """把等待拆成 100ms 小段，返回是否收到停止请求。"""

        remaining = max(0, int(delay_ms))
        while remaining > 0:
            if self._stop_flag:
                return True
            wait_ms = min(100, remaining)
            self.msleep(wait_ms)
            remaining -= wait_ms
        return bool(self._stop_flag)


class MainFrame(FluentWindow):
    SHUTDOWN_DEADLINE_SECONDS = 6.0
    SHUTDOWN_FINALIZER_RESERVE_SECONDS = 1.0
    DEVICE_SCAN_DEBOUNCE_MS = 300
    WINDOW_SIZE_SAVE_DEBOUNCE_MS = 350
    WINDOW_SIZE_SAVE_POLL_MS = 50
    NAVIGATION_EXPAND_BREAKPOINT = 1120
    NAVIGATION_LAYOUT_DEBOUNCE_MS = 60
    _QFLUENT_DEFAULT_EXPAND_WIDTH = 322

    def __init__(
        self,
        *,
        screen_adapter: ScreenAdapter | None = None,
        mouse_buttons_provider: Callable[[], Qt.MouseButton] | None = None,
    ):
        super().__init__()
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
        self.log_service = LogService()
        self._device_metadata: dict[str, dict[str, str]] = {}
        self._pending_package_device = ""
        self._package_query_invalidated = False
        set_error_sink(self.log_service.log)
        # 隐藏协调器必须随主窗销毁，不能在工作区视图释放后继续接收全局样式信号。
        self.left_panel = SidePanel(self)
        self.left_panel.hide()
        self.adb_controller = ADBController(self.log_service)
        setattr(self.adb_controller, "window_owner", self)
        self.task_supervisor = QtTaskSupervisor()
        self.task_supervisor.application_stopped.connect(self._on_application_stopped)
        self.task_supervisor.application_finalized.connect(self._on_application_finalized)
        self._actions = MainFrameActions(self)
        self._close_controller = CloseController(self)
        self._shutdown_owner_id = f"application-{id(self)}"
        self._shutdown_handles = []
        self._shutdown_results = ()
        self._shutdown_residual = ()
        self._shutdown_deadline_at = 0.0
        self._shutdown_finalizer_started = False
        self._close_started = False
        self._close_ready = False
        self._layout_ready = False
        self._resize_controller = None
        self._scan_thread = None
        self._continuous_scan_enabled = False
        self._closing = False
        self._scan_refresh_timer = QTimer(self)
        self._scan_refresh_timer.setSingleShot(True)
        self._scan_refresh_timer.timeout.connect(self._publish_scanned_devices)
        self._pending_scanned_devices = []
        self._initial_refresh_timer = QTimer(self)
        self._initial_refresh_timer.setSingleShot(True)
        self._initial_refresh_timer.timeout.connect(self.adb_controller.refresh_devices)
        self._pending_window_size = None
        self._window_size_save_timer = QTimer(self)
        self._window_size_save_timer.setSingleShot(True)
        self._window_size_save_timer.timeout.connect(self._poll_user_resize_transaction)
        self._always_on_top = False

        self._setup_window()
        self._init_panels()
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
        self._bootstrap_adb_async()

    # ── 持续设备扫描 ────────────────────────────────────────────────────

    def _bootstrap_adb_async(self):
        """安排后台环境检查；服务可用即开始发现，不等待原生性能基准。"""
        from adblab.presentation.qt_adb_runtime import QtAdbRuntime

        self._adb_environment = QtAdbRuntime(self)
        self._adb_environment.ready.connect(self._start_device_discovery)
        self._adb_environment.changed.connect(self._update_adb_environment)
        self._adb_environment.diagnostic.connect(self._log_adb_environment)
        self._adb_environment.schedule()

    def _log_adb_environment(self, message: str) -> None:
        """后台诊断经主线程写日志，内容只有能力和耗时。"""
        if not self._closing:
            self.log_service.log("DEBUG", message)

    def _update_adb_environment(self, snapshot) -> None:
        """显示执行范围与检测状态，不把性能策略当作设备在线状态。"""
        if not self._closing:
            self._settings_page.update_adb_environment(snapshot)

    def recheck_adb_environment(self) -> None:
        """重新检测不重启 ADB 服务，也不重复提交用户命令。"""
        environment = getattr(self, "_adb_environment", None)
        if environment is not None and not self._closing:
            environment.recheck()

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
        scan_thread.devices_changed.connect(self._schedule_scan_refresh)
        discovery_state_changed = getattr(
            scan_thread,
            "discovery_state_changed",
            None,
        )
        if discovery_state_changed is not None and callable(set_discovery_state):
            discovery_state_changed.connect(set_discovery_state)
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
        self._continuous_scan_enabled = bool(enabled)
        if self._continuous_scan_enabled:
            self._start_scan_thread()
        else:
            self._stop_scan_thread()
            panel = getattr(self, "left_panel", None)
            if (
                panel is not None
                and getattr(panel, "_device_discovery_state", None) == "scanning"
            ):
                connected = list(getattr(panel, "_connected_device_cache", []))
                panel.set_device_discovery_state("ready" if connected else "empty")

    def _setup_window(self):
        self.setWindowTitle("ADBLab")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        # 主标题栏省略品牌图标；windowIcon 仍供任务栏和系统切换器使用。
        getattr(self.titleBar, "iconLabel").hide()
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        BaseStyles.set_accent_color(str(s.get("accent_color", "#0F6CBD")))
        self.setCustomBackgroundColor(QColor("#F3F3F3"), QColor("#202020"))
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
        if maximum > previous and followed_previous_bottom:
            bar.setValue(maximum)

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

        from gui.features.app_manager import AppManagerPage
        from gui.features.file_explorer import FileExplorerPage
        from gui.features.logcat import LiveLogcatPage
        from gui.features.media import ScreenshotPage
        from gui.features.performance import PerformancePage

        self._central_widget = self.stackedWidget
        self.run_library = RunLibraryController(RunLibrary.for_user(), self)
        self.run_library.error.connect(self._on_run_library_error)

        self._global_device_bar = DeviceContextBar(self)
        self.widgetLayout.removeWidget(self.stackedWidget)
        # 设备栏与页面共用一个材质面，避免两次半透明合成或接缝处出现色带。
        self._content_surface = QWidget(self)
        self._content_surface.setObjectName("workspaceSurface")
        self._content_surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        FluentStyleSheet.FLUENT_WINDOW.apply(self._content_surface)
        self._content_layout = QVBoxLayout(self._content_surface)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._content_layout.addWidget(self._global_device_bar)
        # 滚动区铺满材质面；阅读留白由滚动内容承担，避免覆盖滚动条随正文内缩。
        self.stackedWidget.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self.stackedWidget, 1)
        self.widgetLayout.addWidget(self._content_surface, 1)
        self._sync_material_surface_styles()
        self._device_hub = DeviceHubPage(self)
        # 旧设备视图作为兼容状态源保留在协调器下；不拆走仍被响应式绑定引用的控件。
        self.left_panel.device_widget.setParent(self.left_panel)
        self.left_panel.device_widget.hide()

        device_scroll = SmoothScrollArea(self)
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
            self.left_panel._ensure_tab_loaded(index)
            scroll = self.left_panel._tab_scroll_areas[index]
            content = scroll.takeWidget()
            if content is None:
                content = QWidget()
            return WorkspaceSectionPage(
                f"{route}OverviewPage",
                content,
                scroll_area=scroll,
                parent=self,
            )

        apps_overview = build_overview(0, "apps")
        system_overview = build_overview(1, "system")
        remote_overview = build_overview(2, "remote")

        apps_panel = self.left_panel._apps_tab
        system_panel = self.left_panel._advanced_tab
        remote_panel = self.left_panel._scrcpy_tab
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
            lambda key: FileExplorerPage(device_ip=key.device_id),
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
            close_label=tr("清除截图结果"),
        )

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
        self._device_hub.choose_requested.connect(bar.open_picker)
        self._device_hub.connect_requested.connect(self._show_global_connection)
        self._device_hub.refresh_requested.connect(self._request_device_refresh)
        self._device_hub.selection_requested.connect(
            self.left_panel._devices_tab.set_selected_devices
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

        self._task_history = TaskHistoryStore()
        self._task_page = TaskCenterPage(
            self.adb_controller.operation_manager,
            history_store=self._task_history,
            stop_hook=self._stop_operation_from_task_center,
            run_library=self.run_library,
        )
        assert self._task_page.run_results is not None
        self._task_page.run_results.reuse_requested.connect(self._reuse_test_run)
        self._tasks_page = GalleryPage(
            "tasksPage",
            tr("任务中心"),
            tr("查看任务进度、测试归档与本次操作结果"),
            self._task_page,
            scroll=False,
            parent=self,
        )
        self._settings_page = SettingsPage(self, self)
        self._home_page = HomePage(self, self)
        self._sync_material_surface_styles()

        self.navigationInterface.setAcrylicEnabled(True)
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
             tr("应用包操作、Monkey 测试与诊断报告")),
            ("apps", "media", "screenshotsPage", FluentIcon.CAMERA, tr("截图与屏幕"),
             tr("发送文本、截图录屏，查看并保存截图")),
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
        panel = self.navigationInterface.panel
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
        panel.expandAni.stateChanged.connect(
            self._on_navigation_animation_state_changed
        )
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

        panel = self.left_panel._scrcpy_tab
        if panel is None:
            return device_id
        panel.set_target_devices(self._remote_operation_devices())
        panel.category_stack.set_current(category)
        panel.apply_responsive_width(0)
        return ""

    def _remote_operation_devices(self) -> list[str]:
        """发现状态不可靠时撤销新操作准入，但不停止已有远程会话。"""
        panel = self.left_panel
        if panel._device_discovery_state != "ready":
            return []
        return [device for device in panel.selected_devices
                if device in panel._connected_device_cache]

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

    def switchTo(
        self,
        interface,
        *,
        _record_history: bool = True,
        _target_location: str | WorkspaceRoute | None = None,
    ) -> None:
        """切换独立主页面，并同步功能会话的前后台生命周期。"""

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
        self._prepare_navigation_collapse()
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
        self._prepare_navigation_collapse()
        panel.collapse()

    def _prepare_navigation_collapse(self) -> None:
        """在 MENU 收缩前隐藏标签，规避上游动画末端的窄栏文字裁切。"""

        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        panel = navigation.panel
        if panel.displayMode not in {
            NavigationDisplayMode.EXPAND,
            NavigationDisplayMode.MENU,
        }:
            return
        for item in panel.items.values():
            item.widget.setCompacted(True)
        panel.update()

    def _on_navigation_animation_state_changed(
        self,
        state: QAbstractAnimation.State,
        _previous: QAbstractAnimation.State,
    ) -> None:
        """覆盖上游所有收缩入口，在动画首帧前提交紧凑控件状态。"""

        panel = self.navigationInterface.panel
        if (
            state == QAbstractAnimation.State.Running
            and not bool(panel.expandAni.property("expand"))
        ):
            self._prepare_navigation_collapse()

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
        """把当前一级入口滚入主导航 viewport。"""

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
        navigation.panel.scrollArea.ensureWidgetVisible(item, 0, 12)

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
        selected = list(panel.selected_devices)
        if self._pending_package_device and selected != [self._pending_package_device]:
            self._package_query_invalidated = True
        connected = list(getattr(panel, "_connected_device_cache", []))
        state = str(getattr(panel, "_device_discovery_state", "empty"))
        remote = getattr(panel, "_scrcpy_tab", None)
        if remote is not None:
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
        hub = getattr(self, "_device_hub", None)
        if hub is not None:
            records = {info["ip"]: info for info in DeviceStore.get_full_devices_info(connected)}
            for device in connected:
                records.setdefault(device, {"ip": device}).update(
                    self._device_metadata.get(device, {})
                )
            if bar is not None:
                bar.set_device_labels({device: _device_name(device, records[device])
                                       for device in connected})
                self.adb_controller.action_results.set_target_labels(bar.device_labels())
                panel._apps_tab.set_device_labels(bar.device_labels())
                for host in self._workspace_feature_hosts.values():
                    host.performance_sessions.set_device_labels(bar.device_labels())
                records = {device: {**info, "name": bar.device_label(device)}
                           for device, info in records.items()}
            hub.set_device_metadata(list(records.values()))
        self._sync_global_session_controls()

    def _on_device_info_updated(self, device: str, info: dict) -> None:
        """只保留在线设备的展示字段；补充信息不写入用户配置或缓存唯一标识。"""

        if self._closing or device not in self.left_panel._connected_device_cache:
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
        self._sync_device_context()

    def _open_device_tool(self, section: str, feature: str, device_id: str) -> None:
        """概览快捷入口只接受已选在线目标，多选时保持其他目标不变。"""

        if (self.left_panel._device_discovery_state != "ready"
                or device_id not in self.left_panel.selected_devices):
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
        )

    def _select_operation_devices(self, devices: list[str]) -> None:
        """一次选择同时提交操作目标并切换单设备会话，避免查看与准入互相脱节。"""
        host = self._current_feature_host()
        single = bool(host is not None and host.feature_requires_device(host.current_feature)
                      and host.current_feature != "performance")
        if single:
            devices = devices[-1:]
            if (host is not None and host.is_device_selection_locked() and devices
                    and devices[0] != host.current_device_id):
                return
        self.left_panel._devices_tab.set_selected_devices(devices)
        if host is not None and devices:
            if single or (host.current_feature == "performance"
                          and host.current_device_id not in devices):
                self._choose_global_session(devices[0])

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
        """只从设备概览打开连接表单，使用已加载历史，不额外读取用户存储。"""

        if not self._device_hub.isVisibleTo(self):
            return
        source = self.left_panel._devices_tab.ip_entry
        history = [
            (source.itemText(index), str(source.itemData(index) or ""))
            for index in range(source.count())
        ]
        self._global_device_bar.open_connection(history, anchor=self._device_hub.connect_button)

    def _on_nav_requested(self, key: str | WorkspaceRoute) -> None:
        """把业务键映射到对应的 FluentWindow 主页面。"""

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
            panel = self.left_panel._apps_tab
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
        self._theme_navigation_widget.sync_theme()
        self.left_panel.apply_device_theme()
        task_page = getattr(self, "_task_page", None)
        if task_page is not None:
            task_page._sync_theme_state()

    def _on_accent_color_changed(self, _color: str) -> None:
        """强调色变化后刷新主窗口及已创建的内嵌页面。"""

        self._sync_plain_container_palettes()
        for widget in (self, *self.findChildren(QWidget)):
            refresh_fluent_widget_style(widget)
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
            page.update()
            for child in page.findChildren(QWidget):
                child.update()

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
        """按生效材质绘制内容与导航底层，确保切页及折叠中间帧同样正确。"""

        mica = self.isMicaEffectEnabled()
        home = getattr(self, "_home_page", None)
        if home is not None:
            home.set_top_left_radius(10 if mica else 0)
        light = BaseStyles.color_for("Light", "WINDOW_BG")
        dark = BaseStyles.color_for("Dark", "WINDOW_BG")
        content_surface = getattr(self, "_content_surface", None)
        if content_surface is not None:
            light_style = (
                "background-color: rgba(242, 244, 246, 0.20); "
                "border: 1px solid rgba(0, 0, 0, 0.068); border-top-left-radius: 10px;"
                if mica else f"background-color: {light}; border: none; border-radius: 0px;"
            )
            dark_style = (
                "background-color: rgba(255, 255, 255, 0.0314); "
                "border: 1px solid rgba(0, 0, 0, 0.18); border-top-left-radius: 10px;"
                if mica else f"background-color: {dark}; border: none; border-radius: 0px;"
            )
            setCustomStyleSheet(
                content_surface,
                f"QWidget#workspaceSurface {{ {light_style} border-right: none; "
                "border-bottom: none; }",
                f"QWidget#workspaceSurface {{ {dark_style} border-right: none; "
                "border-bottom: none; }",
            )
        # 浅色使用轻量中性遮罩，避免白色与卡片再次合成后冲淡云母；深色保持原层次。
        for surface, selector, light_color, dark_color in (
            (
                self.stackedWidget,
                "StackedWidget",
                "transparent" if content_surface is not None else light,
                "transparent" if content_surface is not None else dark,
            ),
            (
                self.navigationInterface.panel,
                "NavigationPanel[menu=false]",
                "transparent" if mica else light,
                "transparent" if mica else dark,
            ),
        ):
            setCustomStyleSheet(
                surface,
                f"{selector} {{ background-color: {light_color}; "
                "border: none; border-radius: 0px; }",
                f"{selector} {{ background-color: {dark_color}; "
                "border: none; border-radius: 0px; }",
            )

    def _refresh_window_chrome_theme(self) -> None:
        """在 Mica/DWM 更新之后重新同步 FluentWindow 壳层的实际明暗外观。"""

        if getattr(self, "_closing", False):
            return
        # FluentWindow 默认用 120 ms 动画切换根背景，但外层堆栈的主题 QSS
        # 会立即生效。两者不同步时，暗色半透明边框会短暂叠在浅色背景上。
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
            # 云母由根窗口及内容栈统一合成，普通容器不能再次覆盖实色底板。
            widget.setAutoFillBackground(not self.isMicaEffectEnabled())
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
                root.backgroundColorAni.stop()
                root.setBackgroundColor(root._normalBackgroundColor())
                root.update()
            for card in root.findChildren(CardWidget):
                card.backgroundColorAni.stop()
                card.setBackgroundColor(card._normalBackgroundColor())
                card.update()

    def _on_ui_font_changed(self, _config) -> None:
        """应用新的界面字体。"""

        self.setFont(BaseStyles.font_for_role(FontRole.UI))

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
        CTL.monkey_target_finished.connect(self.left_panel.on_monkey_target_finished)
        apps_panel = self.left_panel._apps_tab
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
        apps = self.left_panel._apps_tab
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
        apps = self.left_panel._apps_tab
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
            self.log_service.log("WARNING", "Screenshot result page is still closing")
            return

    def _on_operation_completed(self, operation: str, success: bool, message: str) -> None:
        """转发操作结果，并将刷新失败映射为明确的 ADB 不可用状态。"""

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
            (LP.system_service_requested, AC.run_shell_command),
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

    def set_always_on_top(self, enabled: bool):
        self._always_on_top = bool(enabled)
        native_applied = self._set_always_on_top_native(self._always_on_top)
        _debug_log(
            self,
            "ui.window",
            action="always_on_top",
            enabled=self._always_on_top,
            native_applied=native_applied,
            phase="applied",
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

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._finish_user_resize_transaction()
            controller = getattr(self, "_resize_controller", None)
            if controller is not None:
                controller.update_geometry()

    def eventFilter(self, watched, event):
        """在 Qt 原生窗口处理调色板后恢复云母明暗，不再触发 Qt 样式更新。"""
        if (
            watched is getattr(self, "_bound_window_handle", None)
            and event.type() == QEvent.Type.ApplicationPaletteChange
            and not getattr(self, "_closing", False)
        ):
            # QApplication 先向平台窗口分发，再调用对象过滤器。Qt 6.8 在前一步
            # 会清除无边框窗口的 DWM 深色属性；云母也使用它，必须在此处重申。
            apply_dark_title_bar(self)
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        (getattr(self, "_close_controller", None) or CloseController(self)).handle_close_event(
            event
        )

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
