"""提供 scrcpy 投屏启动、快捷按键和 Remote 输入控制面板。"""

import os  # noqa: F401  测试通过 remote_panel 命名空间补丁 os.path.isfile。
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import cast

from PySide6.QtCore import QCoreApplication, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (  # noqa: F401  测试补丁 remote_panel 的 QWidget.closeEvent。
    QComboBox,
    QLabel,
    QPushButton,
    QWidget,
)
from qfluentwidgets import BodyLabel, InfoBadge, InfoLevel

from core.adb_bridge import ADBBridge
from core.settings_manager import AppSettings
from gui.panels.base_panel import BasePanel
from gui.panels.remote_panel_form import RemotePanelForm
from gui.panels.remote_panel_input import RemotePanelInput
from gui.panels.remote_panel_scrcpy import RemotePanelScrcpy
from services.remote import RemoteControlService, RemoteInputEngine, ScrcpyConfig, ScrcpyService


class _RemoteInputShutdown:
    """在 GUI 线程外按 producer → session 的顺序收口 Remote 输入资源。"""

    def __init__(
        self,
        *,
        executor: ThreadPoolExecutor | None,
        warmup_threads: tuple[threading.Thread, ...],
        close_input: Callable[[], object] | None,
        has_running_future: Callable[[], bool],
    ) -> None:
        self._executor = executor
        self._warmup_threads = warmup_threads
        self._close_input = close_input
        self._has_running_future = has_running_future
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._finished = threading.Event()
        self._started = False
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def has_resources(self) -> bool:
        return (
            self._executor is not None
            or bool(self._warmup_threads)
            or self._close_input is not None
        )

    def _record_error(self, exc: Exception) -> None:
        with self._lock:
            if self._error is None:
                self._error = exc

    def _warmup_running(self) -> bool:
        for thread in self._warmup_threads:
            try:
                if thread.is_alive():
                    return True
            except (AttributeError, RuntimeError):
                continue
        return False

    def _producer_running(self) -> bool:
        return self._has_running_future() or self._warmup_running()

    def _run(self) -> None:
        with self._run_lock:
            if self._finished.is_set():
                return
            executor = self._executor
            if executor is not None:
                try:
                    executor.shutdown(wait=True, cancel_futures=True)
                except Exception as exc:
                    self._record_error(exc)
            for warmup_thread in self._warmup_threads:
                if warmup_thread is threading.current_thread():
                    continue
                try:
                    warmup_thread.join()
                except (AttributeError, RuntimeError) as exc:
                    self._record_error(exc)
            close_input = self._close_input
            if close_input is not None:
                try:
                    close_input()
                except Exception as exc:
                    self._record_error(exc)
            self._finished.set()

    def start(self) -> None:
        """幂等启动后台清理；仅在线程无法启动且没有 producer 时同步兜底。"""

        start_error: Exception | None = None
        with self._lock:
            if self._started or self._finished.is_set():
                return
            self._started = True
            try:
                thread = threading.Thread(
                    target=self._run,
                    name="adblab-remote-input-shutdown",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
                return
            except Exception as exc:
                start_error = exc
                self._thread = None
                self._started = False

        # 线程资源耗尽时不能在 GUI 线程等待仍运行的 producer；让 supervisor
        # 保留 residual。没有 producer 时同步收口，维持故障注入场景的清理保证。
        if not self._producer_running():
            self._run()
            with self._lock:
                completion_error = self._error
            if completion_error is not None:
                raise completion_error
        assert start_error is not None
        raise start_error

    def wait(self, timeout: float) -> bool:
        return self._finished.wait(max(0.0, float(timeout)))

    def is_running(self) -> bool:
        return not self._finished.is_set()

    def error_type(self) -> str:
        with self._lock:
            return type(self._error).__name__ if self._error is not None else ""


class ScrcpyLaunchWorker(QThread):
    """在 GUI 线程之外执行可能阻塞的 scrcpy 启动检查。"""

    launch_ready = Signal(list, str)
    log_message = Signal(str, str)

    def __init__(self, config: ScrcpyConfig, service: ScrcpyService | None = None):
        super().__init__()
        self.config = config
        self.service = service or ScrcpyService()

    def run(self):
        # scrcpy 版本、设备预检和编码器探测都可能阻塞，放到 QThread 避免卡住 UI。
        if self.isInterruptionRequested():
            return
        try:
            plan = self.service.build_launch_plan(self.config)
        except Exception as exc:
            self.log_message.emit("ERROR", f"scrcpy preflight failed: {exc}")
            return
        for level, message in plan.messages:
            if self.isInterruptionRequested():
                return
            self.log_message.emit(level, message)
        if self.isInterruptionRequested():
            return
        self.launch_ready.emit(plan.args, plan.device_info)

class RemotePanel(BasePanel):
    """管理 scrcpy 会话、串行 Remote 输入队列和相关界面状态。"""

    _orphaned_launch_workers: list[ScrcpyLaunchWorker] = []
    _launch_worker_reaper_states: dict[int, dict[str, object]] = {}
    _launch_worker_reaper_lock = threading.RLock()
    _LAUNCH_WORKER_DELETE_RETRY_LIMIT = 3
    _LAUNCH_WORKER_DELETE_RETRY_MS = 1
    _status_update_requested = Signal(str, object)
    _remote_queue_status_requested = Signal(int, int, str)
    _stop_completed_requested = Signal(bool)
    workspace_target_lock_changed = Signal(bool)
    _SESSION_IDLE = "idle"
    _SESSION_STARTING = "starting"
    _SESSION_RUNNING = "running"
    _SESSION_STOPPING = "stopping"
    # 页头控件由 RemotePanelForm 通过 _frame 注入；此处声明类型供 pyright 与
    # 状态刷新方法稳定引用（视觉重设计新增，不影响任何既有契约）。
    remote_title: BodyLabel
    remote_subtitle: BodyLabel
    remote_status_badge: InfoBadge
    _remote_section_groups: list[QWidget]
    _IGNORED_SCRCPY_LOG_PATTERNS = (
        "Could not inject char u+",
        "libpng warning: iCCP: known incorrect sRGB profile",
    )

    _PRESETS = {
        0: {"maxsize": "1024", "fps": "30", "bitrate": "4", "codec": "h264", "buffer": "50"},
        1: {"maxsize": "1280", "fps": "30", "bitrate": "8", "codec": "h264", "buffer": "20"},
        2: {"maxsize": "1920", "fps": "60", "bitrate": "12", "codec": "h265", "buffer": "50"},
        3: {"maxsize": "720", "fps": "24", "bitrate": "2", "codec": "h264", "buffer": "0"},
    }

    _PRESET_NAMES = ["Smooth", "Balanced", "Quality", "Low Latency"]

    _SIZES = ["1024", "1280", "1920", "480p", "720p", "1080p", "Default"]
    _FPS = ["24", "30", "60", "120"]
    _CODECS = ["h264", "h265", "av1"]
    _BUFFERS = ["0", "10", "20", "30", "50", "100", "150", "200"]
    _BITRATES = ["2", "4", "6", "8", "12", "16", "24", "32"]
    _ORIENTATIONS = ["0", "90", "180", "270"]
    _KEY_ICONS = {
        "HOME": "house.svg",
        "BACK": "arrow-u-left-up.svg",
        "RECENTS": "squares-four.svg",
        "MENU": "list.svg",
        "POWER": "power.svg",
        "SETTINGS": "gear.svg",
        "CAMERA": "camera.svg",
        "SEARCH": "magnifying-glass.svg",
        "ENTER": "keyboard.svg",
        "DEL": "backspace.svg",
        "VOL_DOWN": "speaker-low.svg",
        "VOL_UP": "speaker-high.svg",
        "MEDIA_PLAY": "play.svg",
        "MEDIA_PREV": "skip-back.svg",
        "MEDIA_NEXT": "skip-forward.svg",
    }
    _ACTION_ICONS = {
        "swipe_up": "arrow-up.svg",
        "swipe_down": "arrow-down.svg",
        "swipe_left": "arrow-left.svg",
        "swipe_right": "arrow-right.svg",
        "notif_expand": "tray-arrow-down.svg",
        "notif_collapse": "tray-arrow-up.svg",
        "rotate_portrait": "device-rotate.svg",
        "rotate_landscape": "device-rotate.svg",
    }

    # 表单控件由 RemotePanelForm 控制器创建，此处提供类级类型声明供跨控制器解析。
    btn_start: QPushButton
    btn_stop: QPushButton
    preset: QComboBox
    maxsize: QComboBox
    fps: QComboBox
    codec: QComboBox
    buffer: QComboBox
    bitrate: QComboBox
    orientation: QComboBox
    _status_label: QLabel

    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self._workspace_device_id = ""
        self._workspace_device_connected: bool | None = None
        self._device_selected = True
        self._device_admission_revision = 0
        self._form_controller = RemotePanelForm(self)
        self._scrcpy_controller = RemotePanelScrcpy(self)
        self._input_controller = RemotePanelInput(self)
        self._process = None
        self._running = False
        self._session_state = self._SESSION_IDLE
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._poll_process)
        self._settings = AppSettings.instance()
        self._adb = ADBBridge()
        self._scrcpy_service = ScrcpyService()
        self._remote_control = RemoteControlService(self._adb)
        self._input_engine = RemoteInputEngine()
        self._loading = True
        self._closing = False
        self._launch_worker = None
        self._process_key = f"scrcpy_{id(self)}"
        self._active_device = None
        self._remote_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="adblab-remote"
        )
        self._remote_futures: set[Future] = set()
        self._remote_futures_lock = threading.Lock()
        self._warmup_threads: set[threading.Thread] = set()
        self._warmup_threads_lock = threading.Lock()
        self._remote_input_closing = False
        self._remote_input_shutdown: _RemoteInputShutdown | None = None
        self._remote_submitted = 0
        self._remote_completed = 0
        self._remote_sent = 0
        self._remote_failed = 0
        self._session_config = None
        self._status_device_info = ""
        self._allocated_record_paths = set()
        self._shutdown_request_lock = threading.Lock()
        self._scrcpy_stop_claim = None
        self._interrupted_launch_worker = None
        self._status_update_requested.connect(self._update_status)
        self._remote_queue_status_requested.connect(self._update_remote_queue_status)
        self._stop_completed_requested.connect(self._on_stop_completed)

    # ── 信号与快捷键 ────────────────────────────────────────────────────

    def connect_signals(self):
        self.btn_start.clicked.connect(self._start_scrcpy)
        self.btn_stop.clicked.connect(self._stop_scrcpy)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        # 任一参数变化后切换为自定义配置。
        for combo in (
            self.maxsize,
            self.fps,
            self.codec,
            self.buffer,
            self.bitrate,
            self.orientation,
        ):
            combo.currentTextChanged.connect(self._on_custom_setting_changed)
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._start_scrcpy)
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self).activated.connect(self._stop_scrcpy)
        # 启动时应用已加载预设；此时仍处于 loading 状态，不会重复保存。
        idx = self.preset.currentIndex()
        if idx in self._PRESETS:
            self._on_preset_changed(idx)
        self._loading = False

    # ── 运行态与状态方法 ────────────────────────────────────────────────

    def _update_action_states(self) -> None:
        self._refresh_remote_status_badge()
        self._set_session_state(getattr(self, "_session_state", self._SESSION_IDLE))

    def update_action_states(self) -> None:
        """供设备选择协调层刷新 Remote Start 的可用状态。"""

        self._update_action_states()

    @property
    def selected_devices(self) -> list[str]:
        """会话固定操作设备；查看该设备不能替代全局明确选择。"""

        workspace_device = str(getattr(self, "_workspace_device_id", "") or "")
        if workspace_device:
            connected = getattr(self, "_workspace_device_connected", None)
            if connected is False or not getattr(self, "_device_selected", True):
                return []
            return [workspace_device]
        return list(super().selected_devices)

    def _can_operate_device(self) -> bool:
        """新启动与遥控输入共用准入；停止既有资源不受当前选择限制。"""
        return not getattr(self, "_closing", False) and len(self.selected_devices) == 1

    def _invalidate_device_admission(self) -> None:
        """撤销尚未执行的输入与预检，重新勾选也不恢复旧请求。"""
        self._device_admission_revision = getattr(self, "_device_admission_revision", 0) + 1
        worker = getattr(self, "_launch_worker", None)
        if worker is not None:
            self._request_launch_worker_interruption_once(worker)

    def set_device_selected(self, selected: bool) -> None:
        """由主窗口投影固定会话设备是否在当前全局操作目标中。"""
        selected = bool(selected)
        if not selected and getattr(self, "_device_selected", True):
            self._invalidate_device_admission()
        self._device_selected = selected
        self._update_action_states()

    def set_workspace_device(
        self,
        device_id: str,
        *,
        connected: bool | None = None,
    ) -> str:
        """设置 Remote 会话目标；运行期间保持启动时设备，避免中途改向。"""

        requested = str(device_id).strip()
        active_device = str(getattr(self, "_active_device", "") or "")
        if active_device and requested != active_device:
            self._workspace_device_id = active_device
        else:
            self._workspace_device_id = active_device or requested
            if (
                connected is False
                and getattr(self, "_workspace_device_connected", None) is not False
            ):
                self._invalidate_device_admission()
            self._workspace_device_connected = connected
        self._update_action_states()
        return self._workspace_device_id

    # ── 卡片化页头与分区视觉 ─────────────────────────────────────────────

    def _apply_remote_header_style(self) -> None:
        """按当前主题刷新页头徽标颜色。"""

        if not hasattr(self, "remote_title"):
            return
        self._refresh_remote_status_badge()

    def _refresh_remote_status_badge(self) -> None:
        """按设备选中数量刷新徽标；Remote 只接受恰好一个设备。"""

        if not hasattr(self, "remote_status_badge"):
            return
        if (
            getattr(self, "_workspace_device_id", "")
            and getattr(self, "_workspace_device_connected", None) is False
        ):
            self.remote_status_badge.setText("设备离线")
            self.remote_status_badge.setLevel(InfoLevel.WARNING)
            description = "当前远程会话设备已离线，停止会话后可重新选择"
            self.remote_status_badge.setToolTip(description)
            self.remote_status_badge.setAccessibleDescription(description)
            return
        count = len(self.selected_devices)
        if count == 1:
            text, level = "可启动", InfoLevel.SUCCESS
            description = "已选择一台设备，可以启动远程控制"
        elif count > 1:
            text, level = "请选择一台", InfoLevel.WARNING
            description = "远程控制只能操作一台已选择设备"
        else:
            text, level = "未选择", InfoLevel.INFOAMTION
            description = "请先选择一台设备再使用远程控制"
        self.remote_status_badge.setText(text)
        self.remote_status_badge.setLevel(level)
        self.remote_status_badge.setToolTip(description)
        self.remote_status_badge.setAccessibleDescription(description)

    def _on_theme_changed_remote(self, _name: str) -> None:
        """主题切换时重建页头样式（分区 Card 自动跟随主题）。"""

        self._apply_remote_header_style()

    def _set_running(self, running: bool):
        RemotePanel._set_session_state(
            self,
            RemotePanel._SESSION_RUNNING if running else RemotePanel._SESSION_IDLE,
        )

    # ── 状态指示 ────────────────────────────────────────────────────────

    def _update_status(self, text: str, color: str | None):
        self._status_label.setStyleSheet("font-weight: bold;")
        del color
        localized = {
            "Checking...": "正在检查…",
            "Error": "错误",
            "Running": "运行中",
            "Idle": "空闲",
            "Disconnected": "已断开",
            "Stopping...": "正在停止…",
            "Stop Failed": "停止失败",
        }.get(text, text)
        status = f"状态：{localized}"
        self._status_label.setText(status)
        device_info = str(getattr(self, "_status_device_info", "") or "").strip()
        details = f"{status}\n设备：{device_info}" if device_info else status
        self._status_label.setToolTip(details)
        self._status_label.setAccessibleDescription(details)

    # ── 按键与输入事件 ──────────────────────────────────────────────────

    def _selected_remote_device(self) -> str | None:
        try:
            devices = self.selected_devices
        except AttributeError:
            devices = []
        if not devices:
            self._log("WARNING", "No device selected")
            return None
        if len(devices) != 1:
            self._log("WARNING", "Select exactly one device for Remote control")
            return None
        return devices[0]

    @classmethod
    def _should_ignore_scrcpy_log_line(cls, line: str) -> bool:
        return any(pattern in line for pattern in cls._IGNORED_SCRCPY_LOG_PATTERNS)

    def showEvent(self, event):
        self._update_action_states()
        super().showEvent(event)

    # ── 辅助方法 ────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        if getattr(self, "_closing", False):
            return
        self.signals.log_message.emit(level, msg)

    def _redact_remote_diagnostic(self, message: str) -> str:
        """移除 Remote 诊断信息中的当前设备标识，并限制异常输出长度。"""
        text = str(message).replace("\r", " ").replace("\n", " ")
        active_device = str(getattr(self, "_active_device", "") or "")
        if active_device:
            text = text.replace(active_device, "<device>")
        return text[:1000]

    def shutdown(self):
        """先停止 scrcpy 和启动 worker，再关闭输入队列及持久 ADB 会话。"""
        self._closing = True
        if self._process:
            self._watchdog.stop()
            self._process = None
            try:
                self._request_scrcpy_stop_once()
            except Exception:
                # claim 已由 helper 回滚；注册过的 supervisor 仍可重试停止，
                # 其余 executor 与 ADB 会话清理不能被单个服务异常截断。
                pass
        self._active_device = None
        self._running = False
        try:
            self._stop_launch_worker(wait_ms=0)
        except Exception:
            pass
        input_shutdown = self._remote_input_shutdown_handle()
        if not getattr(self, "_shutdown_task_registered", False):
            try:
                input_shutdown.start()
            except Exception:
                # direct close 无可用后台线程时不得改为等待仍运行 producer
                # 的同步阻塞；已注册路径统一由 supervisor 记录失败。
                pass

    def register_shutdown_task(self, supervisor, *, owner_id: str, task_id: str) -> bool:
        """在界面断开引用前注册 scrcpy、启动 worker 和输入会话清理任务。"""
        worker = getattr(self, "_launch_worker", None)
        input_shutdown = self._remote_input_shutdown_handle()
        scrcpy_service = getattr(self, "_scrcpy_service", None)
        process_key = getattr(self, "_process_key", "")
        process_terminal = threading.Event()

        def process_running(*, raise_errors: bool = False) -> bool:
            if process_terminal.is_set():
                return False
            if scrcpy_service is None or not process_key:
                process_terminal.set()
                return False
            try:
                running = bool(scrcpy_service.is_active(process_key))
            except Exception:
                if raise_errors:
                    raise
                return True
            if not running:
                process_terminal.set()
            return running

        if worker is None and not input_shutdown.has_resources and not process_running():
            return False
        self._shutdown_task_registered = True

        def completion_error_type() -> str:
            return input_shutdown.error_type()

        def worker_running() -> bool:
            if worker is None:
                return False
            try:
                return worker.isRunning()
            except RuntimeError:
                return False

        def is_running() -> bool:
            return worker_running() or input_shutdown.is_running() or process_running()

        def request_stop() -> None:
            request_error = None
            if worker_running():
                try:
                    self._request_launch_worker_interruption_once(worker)
                except Exception as exc:
                    request_error = exc
            try:
                should_request_process_stop = process_running(raise_errors=True)
            except Exception as exc:
                should_request_process_stop = True
                if request_error is None:
                    request_error = exc
            if should_request_process_stop:
                try:
                    self._request_scrcpy_stop_once(scrcpy_service, process_key)
                except Exception as exc:
                    if request_error is None:
                        request_error = exc
            try:
                input_shutdown.start()
            except Exception as exc:
                if request_error is None:
                    request_error = exc
            if request_error is not None:
                raise request_error

        def wait(timeout: float) -> bool:
            deadline = time.monotonic() + max(0.0, float(timeout))
            while is_running():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                if worker_running():
                    assert worker is not None  # worker_running() 已排除 None
                    worker.wait(max(0, min(50, int(remaining * 1000))))
                elif input_shutdown.is_running():
                    input_shutdown.wait(min(remaining, 0.05))
                else:
                    time.sleep(min(remaining, 0.05))
            return True

        def force_stop(timeout: float) -> bool:
            if not process_running():
                return False
            assert scrcpy_service is not None  # process_running() 已排除 None
            forced = bool(scrcpy_service.force_stop(process_key, timeout))
            if forced:
                process_terminal.set()
            return forced

        supervisor.register(
            task_id,
            owner_id=owner_id,
            kind="remote_session",
            request_stop=request_stop,
            wait=wait,
            is_running=is_running,
            force_stop=force_stop,
            error_type=completion_error_type,
        )
        return True

    def _remote_future_lock(self) -> threading.Lock:
        lock = getattr(self, "_remote_futures_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._remote_futures_lock = lock
        return lock

    def _track_remote_future(self, future: Future) -> None:
        """持有 Remote future 到完成，供关闭故障注入和诊断读取。"""

        lock = self._remote_future_lock()
        futures = getattr(self, "_remote_futures", None)
        if futures is None:
            futures = set()
            self._remote_futures = futures
        with lock:
            futures.add(future)

        def release(completed: Future) -> None:
            with lock:
                futures.discard(completed)

        future.add_done_callback(release)

    def _has_running_remote_future(self) -> bool:
        lock = self._remote_future_lock()
        futures = getattr(self, "_remote_futures", set())
        with lock:
            return any(not future.done() for future in futures)

    def _remote_input_shutdown_handle(self) -> _RemoteInputShutdown:
        """捕获一次 Remote producer 集合，并关闭后续 executor 准入。"""

        lock = self._shutdown_lifecycle_lock()
        with lock:
            handle = getattr(self, "_remote_input_shutdown", None)
            if handle is not None:
                return handle
            # 注册 shutdown task 时主面板尚未调用 shutdown()；必须先单独关闭
            # Remote 输入准入，再摘除 executor，避免晚到输入走同步降级路径。
            self._remote_input_closing = True
            executor = getattr(self, "_remote_executor", None)
            self._remote_executor = None
            warmup_lock = getattr(self, "_warmup_threads_lock", None)
            if warmup_lock is None:
                warmup_lock = threading.Lock()
                self._warmup_threads_lock = warmup_lock
            with warmup_lock:
                warmup_threads = tuple(getattr(self, "_warmup_threads", ()))
            adb = getattr(self, "_adb", None)
            close_input = getattr(adb, "close_input_sessions", None)
            handle = _RemoteInputShutdown(
                executor=executor,
                warmup_threads=warmup_threads,
                close_input=close_input if callable(close_input) else None,
                has_running_future=self._has_running_remote_future,
            )
            self._remote_input_shutdown = handle
            return handle

    def _shutdown_lifecycle_lock(self):
        """兼容轻量测试实例，并为直接关闭与 supervisor 提供同一把锁。"""

        lock = getattr(self, "_shutdown_request_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._shutdown_request_lock = lock
        return lock

    def _disconnect_launch_worker(self, worker: ScrcpyLaunchWorker):
        for disconnect in (
            lambda: worker.log_message.disconnect(self._log),
            lambda: worker.launch_ready.disconnect(self._on_launch_ready),
            lambda: worker.finished.disconnect(),
        ):
            try:
                disconnect()
            except (RuntimeError, TypeError):
                pass

    @classmethod
    def _defer_launch_worker_delete(cls, worker: ScrcpyLaunchWorker):
        """持有未回收 worker，并在其 GUI 线程中执行有界删除重试。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                state = {
                    "attempts": 0,
                    "scheduled": False,
                    "exhausted": False,
                    "known_stopped": False,
                    "finished_seen": False,
                }
                cls._launch_worker_reaper_states[worker_key] = state
                if not any(item is worker for item in cls._orphaned_launch_workers):
                    cls._orphaned_launch_workers.append(worker)
                new_registration = True
            else:
                new_registration = False

        if new_registration:
            try:
                worker.setParent(None)
            except Exception:
                pass

            def release_after_finished():
                with cls._launch_worker_reaper_lock:
                    current = cls._launch_worker_reaper_states.get(worker_key)
                    if current is not state:
                        return
                    current["finished_seen"] = True
                    current["known_stopped"] = True
                cls._schedule_launch_worker_delete(worker, restart_exhausted=True)

            try:
                worker.finished.connect(release_after_finished, Qt.ConnectionType.QueuedConnection)
            except Exception:
                pass
            else:
                with cls._launch_worker_reaper_lock:
                    current = cls._launch_worker_reaper_states.get(worker_key)
                    if current is state:
                        current["finished_callback"] = release_after_finished

        try:
            running = bool(worker.isRunning())
        except Exception:
            running = None
        if running is False:
            with cls._launch_worker_reaper_lock:
                current = cls._launch_worker_reaper_states.get(worker_key)
                if current is state:
                    current["known_stopped"] = True
            # finished 可能早于回收器连接；已结束线程必须主动进入事件循环重试。
            cls._schedule_launch_worker_delete(worker, restart_exhausted=True)

    @classmethod
    def _schedule_launch_worker_delete(
        cls,
        worker: ScrcpyLaunchWorker,
        *,
        restart_exhausted: bool,
    ) -> None:
        """幂等安排一次删除尝试；真实 QObject 始终回到自身 GUI 线程执行。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                return
            if restart_exhausted and bool(state["exhausted"]):
                state["attempts"] = 0
                state["exhausted"] = False
            if bool(state["scheduled"]) or bool(state["exhausted"]):
                return
            state["scheduled"] = True

        def callback():
            cls._retry_launch_worker_delete(worker)

        try:
            application = QCoreApplication.instance()
            if application is not None:
                QTimer.singleShot(cls._LAUNCH_WORKER_DELETE_RETRY_MS, application, callback)
            else:
                QTimer.singleShot(cls._LAUNCH_WORKER_DELETE_RETRY_MS, callback)
        except Exception:
            with cls._launch_worker_reaper_lock:
                current = cls._launch_worker_reaper_states.get(worker_key)
                if current is state:
                    current["scheduled"] = False
                    current["exhausted"] = True
            cls._release_stopped_launch_worker(worker)

    @classmethod
    def _retry_launch_worker_delete(cls, worker: ScrcpyLaunchWorker) -> None:
        """执行一次删除尝试，并在固定次数耗尽后进入明确终态。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                return
            state["scheduled"] = False

        try:
            worker.deleteLater()
        except Exception:
            with cls._launch_worker_reaper_lock:
                current = cls._launch_worker_reaper_states.get(worker_key)
                if current is not state:
                    return
                attempts = cast(int, current["attempts"]) + 1
                current["attempts"] = attempts
                if attempts >= cls._LAUNCH_WORKER_DELETE_RETRY_LIMIT:
                    current["exhausted"] = True
            if attempts < cls._LAUNCH_WORKER_DELETE_RETRY_LIMIT:
                cls._schedule_launch_worker_delete(worker, restart_exhausted=False)
            else:
                # QObject 删除失败不应让已确认停止的 Python 包装对象永久残留；
                # 仍运行或状态未知时则继续保留，等待真实 finished 再开启一轮有限重试。
                cls._release_stopped_launch_worker(worker)
            return

        cls._forget_launch_worker(worker)

    @classmethod
    def _release_stopped_launch_worker(cls, worker: ScrcpyLaunchWorker) -> bool:
        """仅在线程明确停止时释放残余；运行或未知状态继续强引用。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                return True
            stopped_by_evidence = bool(state["known_stopped"] or state["finished_seen"])
        if stopped_by_evidence:
            cls._forget_launch_worker(worker)
            return True

        try:
            running = bool(worker.isRunning())
        except Exception:
            return False
        if running:
            return False
        with cls._launch_worker_reaper_lock:
            current = cls._launch_worker_reaper_states.get(worker_key)
            if current is state:
                current["known_stopped"] = True
        cls._forget_launch_worker(worker)
        return True

    @classmethod
    def _forget_launch_worker(cls, worker: ScrcpyLaunchWorker) -> None:
        """原子移除指定 worker 的回收状态和进程级强引用。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.pop(worker_key, None)
            for index, item in enumerate(cls._orphaned_launch_workers):
                if item is worker:
                    del cls._orphaned_launch_workers[index]
                    break
        finished_callback = None if state is None else state.get("finished_callback")
        if finished_callback is not None:
            try:
                worker.finished.disconnect(finished_callback)
            except Exception:
                pass

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    # ── 控制器委托 ─────────────────────────────────────────────────────

    def build_ui(self):
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self)).build_ui()

    def _build_mirroring(self):
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self))._build_mirroring()

    def _create_checkbox(self, text: str):
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self))._create_checkbox(
            text
        )

    def _build_control(self):
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self))._build_control()

    def _remote_key_button(self, label: str, code: str, tooltip: str):
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._remote_key_button(label, code, tooltip)

    def _remote_action_button(self, label: str, action: str, tooltip: str):
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._remote_action_button(label, action, tooltip)

    def _startup_configuration_controls(self):
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._startup_configuration_controls()

    def _on_custom_setting_changed(self, _value):
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._on_custom_setting_changed(_value)

    def _save(self, key: str, value: str):
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self))._save(key, value)

    def _save_all(self):
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self))._save_all()

    def _load(self, key: str) -> str:
        return (getattr(self, "_form_controller", None) or RemotePanelForm(self))._load(key)

    def reload_from_settings(self) -> bool:
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        ).reload_from_settings()

    def _on_preset_changed(self, idx: int):
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._on_preset_changed(idx)

    def _on_record_toggled(self, checked: bool):
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._on_record_toggled(checked)

    def _allocate_record_path(self, device: str) -> str:
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._allocate_record_path(device)

    def _display_record_path(self, path: str) -> None:
        return (
            getattr(self, "_form_controller", None) or RemotePanelForm(self)
        )._display_record_path(path)

    def _start_scrcpy(self):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._start_scrcpy()

    def _on_launch_ready(self, args: list, device_info: str):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._on_launch_ready(args, device_info)

    def _on_launch_finished(self, worker):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._on_launch_finished(worker)

    def _read_stderr(self):
        return (getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self))._read_stderr()

    def _poll_process(self):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._poll_process()

    def _stop_scrcpy(self):
        return (getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self))._stop_scrcpy()

    def _on_stop_completed(self, stopped: bool):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._on_stop_completed(stopped)

    def _set_session_state(self, state: str):
        result = (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._set_session_state(state)
        self.workspace_target_lock_changed.emit(state != self._SESSION_IDLE)
        return result

    def _scrcpy_config(self, exe: str, device: str) -> ScrcpyConfig:
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._scrcpy_config(exe, device)

    def _focus_scrcpy_window(self):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._focus_scrcpy_window()

    def _stop_launch_worker(self, wait_ms: int = 3000):
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._stop_launch_worker(wait_ms)

    def _claim_scrcpy_stop(self) -> object | None:
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._claim_scrcpy_stop()

    def _release_scrcpy_stop_claim(self, claim: object) -> bool:
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._release_scrcpy_stop_claim(claim)

    def _reset_scrcpy_stop_claim(self) -> None:
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._reset_scrcpy_stop_claim()

    def _request_scrcpy_stop_once(self, service=None, process_key: str | None = None) -> bool:
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._request_scrcpy_stop_once(service, process_key)

    def _request_launch_worker_interruption_once(self, worker) -> bool:
        return (
            getattr(self, "_scrcpy_controller", None) or RemotePanelScrcpy(self)
        )._request_launch_worker_interruption_once(worker)

    def _submit_remote_input(self, task):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._submit_remote_input(task)

    def _start_warm_remote_input_session(self):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._start_warm_remote_input_session()

    def _mark_remote_submitted(self):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._mark_remote_submitted()

    def _mark_remote_completed(self, result: str):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._mark_remote_completed(result)

    @staticmethod
    def _remote_input_succeeded(result) -> bool:
        return RemotePanelInput._remote_input_succeeded(result)

    def _emit_remote_queue_status(self, submitted: int, completed: int, result: str):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._emit_remote_queue_status(submitted, completed, result)

    def _update_remote_queue_status(self, submitted: int, completed: int, result: str):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._update_remote_queue_status(submitted, completed, result)

    def _send_keyevent(self, key_name: str):
        return (getattr(self, "_input_controller", None) or RemotePanelInput(self))._send_keyevent(
            key_name
        )

    def _send_remote_action(self, action: str):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._send_remote_action(action)

    def _warm_remote_input_session(self):
        return (
            getattr(self, "_input_controller", None) or RemotePanelInput(self)
        )._warm_remote_input_session()
