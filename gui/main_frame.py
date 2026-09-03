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
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    FluentWindow,
    NavigationDisplayMode,
    NavigationItemPosition,
    NavigationPanel,
    SmoothScrollArea,
)

from adblab.application.supervision import TaskStopResult
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from controllers import ADBController
from core.exec import CREATE_NEW_CONSOLE, CommandRunner, ProcessRunner
from core.log_service import LogService
from core.settings_manager import AppSettings, set_error_sink
from gui.close_controller import CloseController
from gui.main_frame_actions import MainFrameActions
from gui.pages.fluent_pages import (
    GalleryPage,
    HomePage,
    SettingsPage,
    WorkspacePage,
    WorkspaceSectionPage,
)
from gui.pages.tasks_page import TaskCenterPage
from gui.panels.log_panel import LogPanel
from gui.panels.side_panel import SidePanel
from gui.screen_adapter import QtScreenAdapter, ScreenAdapter
from gui.secondary_windows import SecondaryWindowHost
from gui.widgets.frameless_resize import FramelessResizeController
from gui.widgets.responsive_controller import ReflowReason
from gui.window_layout import (
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    compute_workspace_constraints,
    normalize_window_size,
)
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
            if CommandRunner.active_count() != 0:
                # 有受管命令在执行时跳过本轮，等待完整间隔后再试。
                if self._sleep_interruptibly(self._interval_ms):
                    return
                continue
            try:
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

        端点防护会拖慢每次 adb 进程启动（实测约 7 秒），超时按 15 秒
        设置；停止请求到来时立即终止子进程并返回 None，使线程可及时退出。
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
        self._workspace_forced_size = None
        self._last_workspace_minimum_size = QSize(MINIMUM_WINDOW_SIZE)
        self._workspace_constraint_refresh_timer = QTimer(self)
        self._workspace_constraint_refresh_timer.setSingleShot(True)
        self._workspace_constraint_refresh_timer.timeout.connect(
            self._refresh_workspace_after_responsive_layout
        )
        self.log_service = LogService()
        set_error_sink(self.log_service.log)
        self.log_panel = LogPanel()
        self.left_panel = SidePanel()
        self.adb_controller = ADBController(self.log_service)
        setattr(self.adb_controller, "window_owner", self)
        self.task_supervisor = QtTaskSupervisor()
        self.task_supervisor.application_stopped.connect(self._on_application_stopped)
        self.task_supervisor.application_finalized.connect(self._on_application_finalized)
        self._actions = MainFrameActions(self)
        self._secondary_window_host = SecondaryWindowHost(self)
        self._close_controller = CloseController(self)
        self._shutdown_owner_id = f"application-{id(self)}"
        self._shutdown_handles = []
        self._shutdown_results = ()
        self._shutdown_residual = ()
        self._shutdown_deadline_at = 0.0
        self._shutdown_finalizer_started = False
        self._close_started = False
        self._close_ready = False
        self._drag_pos = None
        self._layout_ready = False
        self._resize_controller = None
        self._normal_window_size = QSize(DEFAULT_WINDOW_SIZE)
        self._active_dialogs = []
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
        self._adb_bootstrap_thread = None
        self._adb_bootstrap_finished.connect(self._start_device_discovery)
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
        """首帧绘制后再解析并预热 ADB，避免文件系统和 PATH 检查阻塞启动界面。

        端点防护环境下每次 adb 进程启动约需数秒；解析路径后直接在后台拉起
        Server，避免首轮设备扫描在超时窗口内失败并产生误告警。
        """
        from utils.adb_resolver import resolve_adb_path

        def _bootstrap():
            try:
                path = resolve_adb_path()
                if path:
                    CommandRunner.run([path, "start-server"], timeout=30)
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
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        BaseStyles.set_accent_color(str(s.get("accent_color", "#0F6CBD")))
        self.setCustomBackgroundColor(QColor("#F3F3F3"), QColor("#202020"))
        self.setMicaEffectEnabled(bool(s.get("mica_enabled", True)))
        self.navigationInterface.setExpandWidth(220)
        self.navigationInterface.setMinimumExpandWidth(1000)
        self._always_on_top = bool(s.get("always_on_top", False))
        if self._always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
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
            self._disconnect_screen_token(self._window_screen_token)
            self._window_screen_token = self._screen_adapter.connect_window_screen_changed(
                self,
                self._on_window_screen_changed,
            )
            self._bound_window_handle = handle

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
        device_panel = getattr(getattr(self, "left_panel", None), "device_widget", None)
        if device_scroll is not None and device_panel is not None:
            vertical_restricted = bool(
                available_size.isValid()
                and available_size.height() < design_minimum.height()
            )
            device_scroll.setProperty(
                "preserveDeviceContentHeight",
                not vertical_restricted,
            )
            device_scroll_minimum = 0 if vertical_restricted else device_panel.minimumHeight()
            if device_scroll.minimumHeight() != device_scroll_minimum:
                device_scroll.setMinimumHeight(device_scroll_minimum)
        if apply_effective_size:
            self._effective_window_size = QSize(constraints.effective_window_size)
        elif minimum_forced_size != size_before_constraints:
            self._effective_window_size = QSize(minimum_forced_size)
        self._logical_dpi = self._screen_adapter.logical_dpi(screen)
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
        """构建设备上下文常驻的一体化 Fluent 工作台。"""

        self._central_widget = self.stackedWidget
        self._workspace_page = WorkspacePage(self, self)

        device_scroll = SmoothScrollArea(self)
        device_scroll.setWidgetResizable(True)
        device_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        device_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        device_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._device_scroll_area = device_scroll

        self._devices_page = WorkspaceSectionPage(
            "devicesPage",
            self.left_panel.device_widget,
            scroll_area=device_scroll,
            parent=self,
        )

        def build_feature_section(
            index: int,
            route: str,
        ) -> WorkspaceSectionPage:
            self.left_panel._ensure_tab_loaded(index)
            scroll = self.left_panel._tab_scroll_areas[index]
            content = scroll.takeWidget()
            if content is None:
                content = QWidget()
            return WorkspaceSectionPage(
                route,
                content,
                scroll_area=scroll,
                parent=self,
            )

        self._apps_page = build_feature_section(0, "appsPage")
        self._system_page = build_feature_section(1, "systemPage")
        self._remote_page = build_feature_section(2, "remotePage")
        for key, label, icon, page in (
            ("devices", "设备与连接", FluentIcon.PHONE, self._devices_page),
            ("apps", "应用与自动化", FluentIcon.APPLICATION, self._apps_page),
            ("system", "系统与诊断", FluentIcon.DEVELOPER_TOOLS, self._system_page),
            ("remote", "远程控制", FluentIcon.PROJECTOR, self._remote_page),
        ):
            self._workspace_page.add_section(key, label, icon, page)

        self._task_history = TaskHistoryStore()
        self._task_page = TaskCenterPage(
            self.adb_controller.operation_manager,
            history_store=self._task_history,
            stop_hook=self._stop_operation_from_task_center,
        )
        self._tasks_page = GalleryPage(
            "tasksPage",
            "任务中心",
            "查看正在运行和最近完成的设备任务",
            self._task_page,
            scroll=False,
            parent=self,
        )
        self._logs_page = GalleryPage(
            "logsPage",
            "操作日志",
            "查看 ADBLab 操作记录与诊断信息",
            self.log_panel,
            scroll=False,
            parent=self,
        )
        self._settings_page = SettingsPage(self, self)
        self._home_page = HomePage(self, self)

        self.navigationInterface.setAcrylicEnabled(True)
        self.addSubInterface(self._home_page, FluentIcon.HOME, "首页")
        self.addSubInterface(self._workspace_page, FluentIcon.PHONE, "设备工作台")
        self.navigationInterface.addSeparator()
        for page, icon, label in (
            (self._tasks_page, FluentIcon.HISTORY, "任务中心"),
            (self._logs_page, FluentIcon.SCROLL, "操作日志"),
        ):
            self.addSubInterface(page, icon, label, NavigationItemPosition.SCROLL)
        self.addSubInterface(
            self._settings_page,
            FluentIcon.SETTING,
            "设置",
            NavigationItemPosition.BOTTOM,
        )
        self._navigation_labels = {
            self._home_page.objectName(): "首页",
            self._workspace_page.objectName(): "设备工作台",
            self._tasks_page.objectName(): "任务中心",
            self._logs_page.objectName(): "操作日志",
            self._settings_page.objectName(): "设置",
        }
        self.navigationInterface.displayModeChanged.connect(
            self._sync_navigation_accessibility
        )
        self._sync_navigation_accessibility()

        for page in (
            self._workspace_page,
            self._tasks_page,
            self._logs_page,
        ):
            page.header.theme_button.clicked.connect(self._toggle_theme)

        self._connect_all_signals()
        self._workspace_page.sectionChanged.connect(self._on_workspace_section_changed)
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

    def _stop_operation_from_task_center(self, operation_id: str) -> None:
        """把任务中心取消动作路由到拥有实际资源的控制器用例。"""

        snapshot = self.adb_controller.operation_manager.get(operation_id)
        if snapshot is None:
            return
        if "install" in snapshot.kind:
            self.adb_controller.cancel_install_batch(operation_id)
        elif snapshot.kind == "screenshot":
            self.adb_controller.cancel_screenshot(operation_id)

    def switchTo(self, interface) -> None:
        """切换顶层导航并立即同步选中反馈，设备功能页进入工作台分区。"""

        workspace = getattr(self, "_workspace_page", None)
        if workspace is not None:
            section_key = workspace.key_for_widget(interface)
            if section_key is not None:
                super().switchTo(workspace)
                self.navigationInterface.setCurrentItem(workspace.objectName())
                workspace.set_section(section_key)
                self._collapse_navigation_menu_after_switch()
                return
        super().switchTo(interface)
        route_key = getattr(interface, "objectName", lambda: "")()
        if route_key:
            # FluentWindow 默认等页面过渡结束才更新 NavigationPanel。业务页面已经
            # 切换时选中态若仍停在旧项，会让快速连续点击看起来没有响应。
            self.navigationInterface.setCurrentItem(route_key)
        self._collapse_navigation_menu_after_switch()

    def _collapse_navigation_menu_after_switch(self) -> None:
        """切页后收起窄窗覆盖菜单，包括尚在执行的展开动画。"""

        panel = self.navigationInterface.panel
        if panel.displayMode != NavigationDisplayMode.MENU:
            return
        animation = panel.expandAni
        if animation.state() == QAbstractAnimation.State.Running:
            # NavigationPanel.collapse() 会忽略运行中的动画；若当前已在收起，
            # 保留原动画，否则先停止展开再从当前宽度开始收起。
            if not bool(animation.property("expand")):
                return
            animation.stop()
        panel.collapse()

    def _sync_navigation_accessibility(self, *_args) -> None:
        """统一导航项、折叠按钮的中文提示和可访问名称。"""

        navigation = getattr(self, "navigationInterface", None)
        if navigation is None:
            return
        navigation.setAccessibleName("主导航")
        panel = navigation.panel
        panel.menuButton.setAccessibleName("展开或收起主导航")
        panel.menuButton.setToolTip("展开或收起主导航")
        panel.returnButton.setAccessibleName("返回上一页")
        panel.returnButton.setToolTip("返回上一页")
        for route_key, label in getattr(self, "_navigation_labels", {}).items():
            item = navigation.widget(route_key)
            item.setAccessibleName(label)
            item.setToolTip(label)

    def _on_workspace_section_changed(self, _key: str) -> None:
        self._request_side_panel_reflow(self, ReflowReason.EXPLICIT)

    def _sync_device_context(self, *_args) -> None:
        panel = getattr(self, "left_panel", None)
        if panel is None:
            return
        selected = list(panel.selected_devices)
        connected = list(getattr(panel, "_connected_device_cache", []))
        state = str(getattr(panel, "_device_discovery_state", "empty"))
        for page_name in ("_workspace_page", "_home_page"):
            page = getattr(self, page_name, None)
            setter = getattr(page, "set_device_context", None)
            if callable(setter):
                setter(selected, connected, state)

    def _on_nav_requested(self, key: str) -> None:
        """兼容旧调用方，把业务键映射到 FluentWindow 或工作台分区。"""

        pages = {
            "home": getattr(self, "_home_page", None),
            "devices": getattr(self, "_devices_page", None),
            "apps": getattr(self, "_apps_page", None),
            "system": getattr(self, "_system_page", None),
            "remote": getattr(self, "_remote_page", None),
            "tasks": getattr(self, "_tasks_page", None),
            "logs": getattr(self, "_logs_page", None),
            "settings": getattr(self, "_settings_page", None),
        }
        page = pages.get(key)
        if page is None:
            return
        self.switchTo(page)
        if key == "tasks":
            self._task_page.refresh()
        elif key == "logs":
            self.log_panel.text_output.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.log_panel.text_output.ensureCursorVisible()

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
            label = settings_page.THEME_LABELS.get(_name, "跟随系统")
            blocker = QSignalBlocker(settings_page.theme_card.combo_box)
            settings_page.theme_card.combo_box.setCurrentText(label)
            del blocker

        self._refresh_save_path()
        self._refresh_window_chrome_theme()
        self._sync_page_header_theme_actions()
        self.left_panel.apply_device_theme()
        self._refresh_active_dialog_themes()
        task_page = getattr(self, "_task_page", None)
        if task_page is not None:
            task_page._sync_theme_state()

    def _on_accent_color_changed(self, _color: str) -> None:
        """强调色变化后刷新项目自绘表面、图标和已打开二级窗口。"""

        self._sync_plain_container_palettes()
        for widget in (self, *self.findChildren(QWidget)):
            refresh_fluent_widget_style(widget)
        self.left_panel._on_theme_changed(BaseStyles.current_theme())
        for name in (
            "_home_page",
            "_workspace_page",
            "_tasks_page",
            "_logs_page",
            "_settings_page",
        ):
            page = getattr(self, name, None)
            if page is None:
                continue
            page.update()
            for child in page.findChildren(QWidget):
                child.update()
        self._refresh_active_dialog_themes()

    def _sync_page_header_theme_actions(self) -> None:
        """让每个 Gallery 页的主题动作显示下一步操作，而不是固定图标。"""

        for name in ("_workspace_page", "_tasks_page", "_logs_page"):
            page = getattr(self, name, None)
            header = getattr(page, "header", None)
            sync = getattr(header, "sync_theme_action", None)
            if callable(sync):
                sync()

    def _refresh_window_chrome_theme(self) -> None:
        """在 Mica/DWM 更新之后重新同步 FluentWindow 壳层的实际明暗外观。"""

        self._sync_plain_container_palettes()
        apply_dark_title_bar(self)

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
        workspace = getattr(self, "_workspace_page", None)
        if workspace is not None:
            candidates.extend((workspace, workspace.stack))
        for name in (
            "_home_page",
            "_devices_page",
            "_apps_page",
            "_system_page",
            "_remote_page",
            "_tasks_page",
            "_logs_page",
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
            # FluentWindow 的内部堆栈使用自己的浅色 QSS；页面若保持透明，
            # 深色模式会露出这层底色。移植页作为完整表面应主动绘制应用底色。
            widget.setAutoFillBackground(True)
            widget.update()

        # Mica 下 FluentWindow 壳层默认透明。Windows 原生主题切换后若不更新
        # 壳层子控件调色板，浅色页面会继续透出深色 DWM 背景。
        for root in shell_roots:
            for child in root.findChildren(QWidget):
                child.setPalette(palette)
                child.update()

        # qfluentwidgets 用 120 ms 动画更新 CardWidget 背景。隐藏工作台分区的
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

    def _refresh_active_dialog_themes(self):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._refresh_active_dialog_themes()

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
            signal_.connect(handler)
        self.left_panel.selected_devices_changed.connect(self._update_device_actions)
        self._update_device_actions()

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
        task_history = getattr(self, "_task_history", None)
        if task_history is not None:
            task_history.record_completed(operation, success, message)
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
        self._update_device_actions()

    def _update_device_actions(self, _devices=None) -> None:
        """让首页设备工具卡片跟随当前复选设备集合。"""

        selected_count = len(self.left_panel.selected_devices)
        has_selection = selected_count > 0
        cards = getattr(getattr(self, "_home_page", None), "tool_cards", {})
        for key in ("app_mgr", "file_explorer", "logcat"):
            card = cards.get(key)
            if card is not None:
                card.setEnabled(has_selection)
                card.setToolTip("" if has_selection else "请先在设备工作台选择操作设备")
        performance = cards.get("performance")
        if performance is not None:
            performance.setEnabled(selected_count == 1)
            if selected_count > 1:
                performance.setToolTip("性能监控仅支持单个设备")
            elif selected_count == 0:
                performance.setToolTip("请先在设备工作台选择操作设备")
            else:
                performance.setToolTip("")
        self._sync_device_context()

    def clear_log(self):
        """清空用户日志面板并记录操作结果。"""
        _debug_log(self, "ui.action", action="clear_log", phase="requested")
        self.log_panel.clear()
        self.log_service.log("INFO", "Log cleared")

    def _show_about_dialog(self):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_about_dialog()

    def _show_app_manager(self):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_app_manager()

    def _show_file_explorer(self):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_file_explorer()

    def _show_logcat(self):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_logcat()

    def _show_performance_monitor(self):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_performance_monitor()

    def _show_device_dialogs(self, dialog_cls, **dialog_kwargs):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_device_dialogs(dialog_cls, **dialog_kwargs)

    def _register_dialog(self, dialog, dialog_cls=None, device_ip=None):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._register_dialog(dialog, dialog_cls, device_ip)

    def _show_fitted_dialog(self, dialog) -> None:
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._show_fitted_dialog(dialog)

    def _find_active_dialog(self, dialog_cls, device_ip):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._find_active_dialog(dialog_cls, device_ip)

    def _forget_dialog(self, dialog):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._forget_dialog(dialog)

    def _on_dialog_destroyed(self, dialog, dialog_name: str):
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._on_dialog_destroyed(dialog, dialog_name)

    def eventFilter(self, watched, event):
        host = getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        handled = host.eventFilter(watched, event)
        if handled is not None:
            return handled
        return super().eventFilter(watched, event)

    def _show_settings(self):
        page = getattr(self, "_settings_page", None)
        if page is not None:
            self.switchTo(page)
        return None

    def _refresh_live_settings(self) -> None:
        return (
            getattr(self, "_secondary_window_host", None) or SecondaryWindowHost(self)
        )._refresh_live_settings()

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
        self._normal_window_size = QSize(preferred)
        self._apply_workspace_constraints(self._bound_screen, request_reflow=True)
        self._persist_window_size(preferred)

    def restore_default_window_size(self):
        """立即恢复并持久化默认窗口尺寸。"""

        if self.isMaximized() or self.isMinimized() or self.isFullScreen():
            self.showNormal()
        self.apply_window_size(DEFAULT_WINDOW_SIZE.width(), DEFAULT_WINDOW_SIZE.height())

    def _apply_window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
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
        self._normal_window_size = QSize(preferred_size)
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
            card.setContent(path or "系统默认目录")
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
        self._schedule_window_size_save(event.size())

    def showEvent(self, event):
        super().showEvent(event)
        self._bind_window_screen()
        # FluentWidget.showEvent 会在 Win11 再次应用 Mica；必须在它之后覆盖
        # 标题栏和导航壳层，否则“浅色 + 系统深色”首次启动会出现黑色侧栏。
        self._refresh_window_chrome_theme()
        QTimer.singleShot(0, self._refresh_window_chrome_theme)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._finish_user_resize_transaction()
            controller = getattr(self, "_resize_controller", None)
            if controller is not None:
                controller.update_geometry()

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
