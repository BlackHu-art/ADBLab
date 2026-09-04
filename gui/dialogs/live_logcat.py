"""提供设备 Logcat 实时读取、筛选、高亮和导出功能页。"""

import uuid
from collections import deque

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, InfoBadge, InfoLevel

from adblab.application.supervision import TaskStopResult
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.dialogs.lifecycle import safe_disconnect
from gui.dialogs.live_logcat_form import LiveLogcatForm
from gui.dialogs.live_logcat_lifecycle import LiveLogcatLifecycle
from gui.dialogs.live_logcat_stream import LiveLogcatStream
from gui.dialogs.live_logcat_worker import (
    CurrentPackageWorker,
    LogcatBatch,
    LogcatTermination,
    LogcatWorker,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon


class LiveLogcatPage(QWidget):
    """嵌入 System 分区的实时日志页面，并持有一个稳定设备会话。"""

    dispose_ready = Signal(object)
    MAX_BUFFER = 8000
    CLEANUP_RECHECK_MS = 100
    status_badge: InfoBadge
    status_bar: BodyLabel

    def __init__(
        self,
        parent=None,
        device_ip: str = "",
        task_supervisor: QtTaskSupervisor | None = None,
        log_service=None,
    ):
        super().__init__(parent)
        self._form_controller = LiveLogcatForm(self)
        self._stream_controller = LiveLogcatStream(self)
        self._lifecycle_controller = LiveLogcatLifecycle(self)
        self.device_ip = device_ip
        self._task_supervisor = task_supervisor or QtTaskSupervisor.shared()
        self._log_service = log_service
        self._device_connected = bool(device_ip)
        self._supervisor_owner_id = f"live-logcat-page-{uuid.uuid4()}"
        self._supervisor_task_id = None
        self.worker = None
        self._pkg_worker = None
        self.entries = deque(maxlen=self.MAX_BUFFER)
        self._pending_visible_lines = deque(maxlen=self.MAX_BUFFER)
        self._closing = False
        self._close_pending = False
        self._close_ready = False
        self._owner_cleanup_requested = False
        self._owner_cleanup_completed = False
        self._application_cleanup_fallback = False
        self._logcat_stopping = False
        self._view_active = False
        self._dispose_emitted = False
        self._package_filter_revision = 0
        self._reflowing_filters = False
        self._line_flush_timer = QTimer(self)
        self._line_flush_timer.setSingleShot(True)
        self._line_flush_timer.timeout.connect(self._flush_pending_lines)
        self._filter_reflow_timer = QTimer(self)
        self._filter_reflow_timer.setSingleShot(True)
        self._filter_reflow_timer.timeout.connect(self._reflow_filters)
        self._cleanup_recheck_timer = QTimer(self)
        self._cleanup_recheck_timer.setSingleShot(True)
        self._cleanup_recheck_timer.timeout.connect(self._poll_close_cleanup)
        self._worker_release_timer = QTimer(self)
        self._worker_release_timer.setSingleShot(True)
        self._worker_release_timer.timeout.connect(self._poll_worker_release)

        self.setWindowTitle(f"Live Logcat - {device_ip}")
        self._window_icon_name = "scroll.svg"
        self.setWindowIcon(get_themed_icon(self._window_icon_name))
        self.setMinimumSize(0, 0)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._task_supervisor.task_stopped.connect(self._on_task_stopped)
        self._task_supervisor.owner_stopped.connect(self._on_owner_stopped)
        self._task_supervisor.application_stopped.connect(
            self._on_application_stopped
        )

    def activate(self, payload=None) -> None:
        """恢复当前页面绘制；导航返回不会重复启动采集。"""

        if self._closing:
            return
        self._view_active = True
        if isinstance(payload, dict):
            package = str(payload.get("package_name", "") or "").strip()
            if package:
                package_input = getattr(self, "pkg_input", None)
                if package_input is not None:
                    package_input.setText(package)
                self._apply_package_filter(package)
        if self._pending_visible_lines and not self._line_flush_timer.isActive():
            self._line_flush_timer.start(0)
        self.show()

    def deactivate(self, _reason: str = "navigation") -> None:
        """暂停批量绘制但继续消费日志，防止切页隐式停止设备进程。"""

        self._view_active = False
        self._line_flush_timer.stop()

    def set_device_connected(self, connected: bool) -> None:
        """反映固定会话设备的在线状态，不把页面静默切到其他设备。"""

        self._device_connected = bool(connected and self.device_ip)
        active = bool(self.worker is not None and self.worker.is_active())
        self._set_running_actions(active, stopping=self._logcat_stopping)
        self.status_badge.setText("Ready" if self._device_connected else "Device offline")
        self.status_badge.setLevel(
            InfoLevel.SUCCESS if self._device_connected else InfoLevel.ERROR
        )
        if not self._device_connected and not active:
            self.status_bar.setText("Device offline; reconnect or choose another device")

    def request_dispose(self, _reason: str = "user") -> bool:
        """非阻塞停止日志会话；资源归零后由 ``dispose_ready`` 通知宿主。"""

        if self._close_ready:
            return True
        self.close()
        return self._close_ready

    def _debug_lifecycle(self, phase: str, **fields):
        """记录不包含设备标识和日志正文的窗口生命周期诊断。"""
        if self._log_service is None:
            return
        values = {
            "page": type(self).__name__,
            "phase": phase,
            **fields,
        }
        details = " ".join(f"{name}={value}" for name, value in sorted(values.items()))
        self._log_service.log("DEBUG", f"ui.feature_session {details}")

    # ── 表单控制器委托 wrapper ─────────────────────────────────────────

    def _init_ui(self):
        return (getattr(self, "_form_controller", None) or LiveLogcatForm(self))._init_ui()

    def _apply_theme(self, _value=None):
        return (
            getattr(self, "_form_controller", None) or LiveLogcatForm(self)
        )._apply_theme(_value)

    @staticmethod
    def _filter_minimum_width(widget) -> int:
        return LiveLogcatForm._filter_minimum_width(widget)

    def _reflow_filters(self) -> None:
        return (
            getattr(self, "_form_controller", None) or LiveLogcatForm(self)
        )._reflow_filters()

    def _apply_action_button_styles(self) -> None:
        return (
            getattr(self, "_form_controller", None) or LiveLogcatForm(self)
        )._apply_action_button_styles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        return (
            getattr(self, "_form_controller", None) or LiveLogcatForm(self)
        ).resizeEvent(event)

    def _set_running_actions(self, running: bool, *, stopping: bool = False) -> None:
        return (
            getattr(self, "_form_controller", None) or LiveLogcatForm(self)
        )._set_running_actions(running, stopping=stopping)

    # ── 流式控制器委托 wrapper ─────────────────────────────────────────

    def _min_level(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._min_level()

    def _passes(self, level: str) -> bool:
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._passes(level)

    def _rebuild(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._rebuild()

    def _update_content_actions(self, has_visible_content: bool | None = None):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._update_content_actions(has_visible_content)

    def _submit_package_filter(self):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._submit_package_filter()

    def _apply_package_filter(self, package: str):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._apply_package_filter(package)

    def _fetch_current_pkg(self):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._fetch_current_pkg()

    def _start(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._start()

    def _stop(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._stop()

    def _clear(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._clear()

    def _toggle_wrap(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._toggle_wrap()

    def _export(self):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._export()

    @Slot(object)  # type: ignore  # PySide6 stub 将 Slot 装饰器限定为单参函数
    def _on_lines_signal(self, batch: LogcatBatch):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_lines_signal(batch)

    @Slot(int)  # type: ignore  # PySide6 stub 将 Slot 装饰器限定为单参函数
    def _on_dropped_signal(self, count: int):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_dropped_signal(count)

    @Slot(str)  # type: ignore  # PySide6 stub 将 Slot 装饰器限定为单参函数
    def _on_worker_status_signal(self, message: str):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_worker_status_signal(message)

    @Slot(object)  # type: ignore  # PySide6 stub 将 Slot 装饰器限定为单参函数
    def _on_worker_terminated_signal(self, result: LogcatTermination):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_worker_terminated_signal(result)

    @Slot()
    def _on_worker_finished_signal(self):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_worker_finished_signal()

    @Slot()
    def _on_pkg_worker_finished_signal(self):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_pkg_worker_finished_signal()

    def _on_line(self, text: str, level: str, pid: int = 0):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._on_line(
            text, level, pid
        )

    def _on_lines(self, worker: LogcatWorker, batch: LogcatBatch):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_lines(worker, batch)

    def _on_dropped(self, worker: LogcatWorker, count: int):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_dropped(worker, count)

    def _schedule_line_flush(self):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._schedule_line_flush()

    def _flush_pending_lines(self):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._flush_pending_lines()

    def _on_status(self, msg: str):
        return (getattr(self, "_stream_controller", None) or LiveLogcatStream(self))._on_status(msg)

    def _on_worker_status(self, worker: LogcatWorker, msg: str):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_worker_status(worker, msg)

    def _on_worker_terminated(self, worker: LogcatWorker, result: LogcatTermination):
        return (
            getattr(self, "_stream_controller", None) or LiveLogcatStream(self)
        )._on_worker_terminated(worker, result)

    # ── 生命周期控制器委托 wrapper ─────────────────────────────────────

    def _on_task_stopped(self, result: TaskStopResult):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._on_task_stopped(result)

    def _on_current_pkg(self, package: str):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._on_current_pkg(package)

    def _release_pkg_worker(self, worker: CurrentPackageWorker) -> bool:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._release_pkg_worker(worker)

    def _on_pkg_worker_finished(self, worker: CurrentPackageWorker):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._on_pkg_worker_finished(worker)

    def _release_logcat_worker(self, worker: LogcatWorker) -> bool:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._release_logcat_worker(worker)

    def _on_worker_finished(self, worker: LogcatWorker | None = None):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._on_worker_finished(worker)

    def _poll_worker_release(self) -> None:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._poll_worker_release()

    def _owner_residual_tasks(self):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._owner_residual_tasks()

    def _schedule_cleanup_recheck(self) -> None:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._schedule_cleanup_recheck()

    def _poll_close_cleanup(self) -> None:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._poll_close_cleanup()

    def _prune_stopped_owner_tasks(self, residual) -> None:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._prune_stopped_owner_tasks(residual)

    def _try_finalize_close(self, trigger: str, *, log_deferred: bool = True) -> bool:
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._try_finalize_close(trigger, log_deferred=log_deferred)

    def _on_owner_stopped(self, owner_id: str, results):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._on_owner_stopped(owner_id, results)

    def _on_application_stopped(self, results, residual):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._on_application_stopped(results, residual)

    def _disconnect_worker(self, worker: LogcatWorker, *, keep_finished: bool = False):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._disconnect_worker(worker, keep_finished=keep_finished)

    def _disconnect_pkg_worker(
        self,
        worker: CurrentPackageWorker,
        *,
        keep_finished: bool = False,
    ):
        return (
            getattr(self, "_lifecycle_controller", None) or LiveLogcatLifecycle(self)
        )._disconnect_pkg_worker(worker, keep_finished=keep_finished)

    def closeEvent(self, event):
        """先隐藏并清理后台资源，完成后再释放页面会话。"""
        if self._close_ready:
            self._debug_lifecycle("close_accepted")
            event.accept()
            super().closeEvent(event)
            self._emit_dispose_ready()
            return
        if self._close_pending:
            self._debug_lifecycle("close_ignored", reason="cleanup_pending")
            event.ignore()
            return
        self._debug_lifecycle(
            "close_requested",
            package_worker_active=bool(
                self._pkg_worker is not None and self._pkg_worker.isRunning()
            ),
            worker_active=bool(self.worker is not None and self.worker.is_active()),
        )
        self._close_pending = True
        self._closing = True
        should_stop_owner = False
        self._line_flush_timer.stop()
        self._worker_release_timer.stop()
        self._pending_visible_lines.clear()
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        safe_disconnect(self._task_supervisor.task_stopped, self._on_task_stopped)
        if self.worker:
            w = self.worker
            if w.is_active():
                # 数据信号停止进入界面，但 finished 槽必须保留为真实资源屏障。
                self._disconnect_worker(w, keep_finished=True)
                should_stop_owner = True
            else:
                self._release_logcat_worker(w)
        if self._pkg_worker:
            w = self._pkg_worker
            if w.isRunning():
                self._disconnect_pkg_worker(w, keep_finished=True)
                should_stop_owner = True
            else:
                self._release_pkg_worker(w)
        residual = self._owner_residual_tasks()
        if should_stop_owner or residual:
            # 关闭动作必须立即反馈，但 QObject 要保留到线程和进程停止完成。
            self._owner_cleanup_requested = True
            self._debug_lifecycle(
                "hidden_for_cleanup",
                residual_count=len(residual),
            )
            event.ignore()
            self.hide()
            owner_stop_started = self._task_supervisor.stop_owner_async(
                self._supervisor_owner_id,
                deadline=6.0,
            )
            if owner_stop_started is False:
                self._application_cleanup_fallback = True
                self._debug_lifecycle("waiting_for_application_stop")
            return
        self._close_ready = True
        self._debug_lifecycle("close_accepted", reason="no_active_resource")
        safe_disconnect(self._task_supervisor.owner_stopped, self._on_owner_stopped)
        safe_disconnect(
            self._task_supervisor.application_stopped,
            self._on_application_stopped,
        )
        super().closeEvent(event)
        self._emit_dispose_ready()

    def _emit_dispose_ready(self) -> None:
        if self._dispose_emitted:
            return
        self._dispose_emitted = True
        self.dispose_ready.emit(self.property("session_generation"))
