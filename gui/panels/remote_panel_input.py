"""提供 Remote 面板的输入队列执行与队列状态回写。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from gui.i18n import tr

if TYPE_CHECKING:
    from gui.panels.remote_panel_scrcpy import RemoteDeviceSession


class RemotePanelInput:
    """组合进 RemotePanel 的输入执行控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame
        self._lock = threading.Lock()
        self._session_input_tokens: dict[int, tuple[RemoteDeviceSession, threading.Event]] = {}

    def _input_closing(self) -> bool:
        """执行中的输入只响应关闭；选择变化由队列启动前的代次检查处理。"""
        return bool(
            getattr(self._frame, "_closing", False)
            or getattr(self._frame, "_remote_input_closing", False)
        )

    def _submit_remote_input(self, task, *, cancelled: Callable[[], bool] | None = None):
        """共用输入队列；广播检查选择代次，会话任务只接受已冻结的取消令牌。"""
        if cancelled is None and not self._frame._can_operate_device():
            return
        revision = getattr(self._frame, "_device_admission_revision", 0)

        def _wrapped():
            revoked = cancelled() if cancelled is not None else revision != getattr(
                self._frame, "_device_admission_revision", 0,
            )
            if self._input_closing() or revoked:
                self._frame._mark_remote_completed("failed")
                return
            try:
                service_result = task()
                result = "sent" if self._frame._remote_input_succeeded(service_result) else "failed"
            except Exception as exc:
                result = "failed"
                self._frame._log("ERROR", f"remote input failed: {type(exc).__name__}")
            if result == "failed":
                self._frame._log("WARNING", "Remote input was not sent")
            self._frame._mark_remote_completed(result)

        lifecycle_lock = self._frame._shutdown_lifecycle_lock()
        with lifecycle_lock:
            if self._input_closing():
                return
            executor = getattr(self._frame, "_remote_executor", None)
            if executor is None:
                return
            self._frame._mark_remote_submitted()
            try:
                future = executor.submit(_wrapped)
                track_future = getattr(self._frame, "_track_remote_future", None)
                if callable(track_future):
                    track_future(future)
            except RuntimeError as exc:
                with self._lock:
                    self._frame._remote_submitted = max(
                        getattr(self._frame, "_remote_completed", 0),
                        getattr(self._frame, "_remote_submitted", 0) - 1,
                    )
                    self._frame._remote_failed = getattr(self._frame, "_remote_failed", 0) + 1
                    submitted = self._frame._remote_submitted
                    completed = getattr(self._frame, "_remote_completed", 0)
                self._frame._emit_remote_queue_status(submitted, completed, "failed")
                self._frame._log("ERROR", f"remote executor stopped: {type(exc).__name__}")

    def _set_connected_devices(self, devices: list[str]) -> None:
        """GUI 线程更新在线快照；断线永久撤销旧任务，重连只允许新提交。"""
        connected = frozenset(devices)
        self._frame._connected_remote_devices = connected
        for session, _token in tuple(self._session_input_tokens.values()):
            if session.config.device not in connected:
                self._invalidate_session_input(session)

    def _invalidate_session_input(self, session: RemoteDeviceSession) -> None:
        """GUI 线程在停止、替换或离线时撤销该会话已排队及执行中的输入。"""
        entry = self._session_input_tokens.pop(id(session), None)
        if entry is not None:
            entry[1].set()

    def _session_input_cancelled(self, session: RemoteDeviceSession) -> Callable[[], bool] | None:
        """GUI 线程确认会话归属，worker 仅持有取消事件及关闭标记，不查询控件。"""
        device = session.config.device
        connected = getattr(self._frame, "_connected_remote_devices", None)
        if (
            self._input_closing()
            or getattr(self._frame, "_device_sessions", {}).get(device) is not session
            or session.state not in {"connecting", "ready", "running"}
            or not session.resource_owned
            or session.cancel_event.is_set()
            or (connected is not None and device not in connected)
        ):
            return None
        entry = self._session_input_tokens.get(id(session))
        if entry is None:
            entry = (session, threading.Event())
            self._session_input_tokens[id(session)] = entry
        token = entry[1]
        session_cancelled = session.cancel_event
        return lambda: token.is_set() or session_cancelled.is_set() or self._input_closing()

    def _send_session_keyevent(self, session: RemoteDeviceSession, key_name: str) -> None:
        """工具栏按键固定到所属会话，不受全局勾选变化影响。"""
        cancelled = self._session_input_cancelled(session)
        if cancelled is None:
            return
        device = session.config.device
        self._submit_remote_input(
            lambda: self._frame._remote_control.send_keyevent(
                device, key_name, cancelled=cancelled,
            ),
            cancelled=cancelled,
        )

    def _send_session_action(self, session: RemoteDeviceSession, action: str) -> None:
        """工具栏动作与尺寸查询共用会话取消令牌，停止后不继续链式输入。"""
        cancelled = self._session_input_cancelled(session)
        if cancelled is None:
            return
        device = session.config.device
        self._submit_remote_input(
            lambda: self._frame._remote_control.perform_action(
                device, action, cancelled=cancelled,
            ),
            cancelled=cancelled,
        )

    def _mark_remote_submitted(self):
        with self._lock:
            submitted = getattr(self._frame, "_remote_submitted", 0) + 1
            self._frame._remote_submitted = submitted
            completed = getattr(self._frame, "_remote_completed", 0)
        self._frame._emit_remote_queue_status(submitted, completed, "queued")

    def _mark_remote_completed(self, result: str):
        with self._lock:
            submitted = getattr(self._frame, "_remote_submitted", 0)
            completed = min(submitted, getattr(self._frame, "_remote_completed", 0) + 1)
            self._frame._remote_completed = completed
            if result == "sent":
                self._frame._remote_sent = getattr(self._frame, "_remote_sent", 0) + 1
            elif result == "failed":
                self._frame._remote_failed = getattr(self._frame, "_remote_failed", 0) + 1
        self._frame._emit_remote_queue_status(submitted, completed, result)

    @staticmethod
    def _remote_input_succeeded(result) -> bool:
        if isinstance(result, bool):
            return result
        if result is None:
            return False
        success = getattr(result, "success", None)
        if success is not None:
            return bool(success)
        return True

    def _emit_remote_queue_status(self, submitted: int, completed: int, result: str):
        try:
            self._frame._remote_queue_status_requested.emit(submitted, completed, result)
        except RuntimeError:
            # 兼容尚未完成 QObject 初始化的轻量嵌入场景。
            pass

    def _update_remote_queue_status(self, submitted: int, completed: int, result: str):
        queued = max(0, submitted - completed)
        label = getattr(self._frame, "_remote_queue_label", None)
        if label is not None:
            with self._lock:
                sent = getattr(self._frame, "_remote_sent", 0)
                failed = getattr(self._frame, "_remote_failed", 0)
            text = tr("队列：{queued}").format(queued=queued)
            if failed:
                text += tr(" · 失败：{failed}").format(failed=failed)
            label.setText(text)
            details = tr("排队：{queued} · 已发送：{sent} · 失败：{failed}").format(
                queued=queued, sent=sent, failed=failed
            )
            label.setToolTip(details)
            label.setAccessibleDescription(details)

    def _send_keyevent(self, key_name: str):
        devices = tuple(self._frame.selected_devices)
        if not devices:
            self._frame._log("WARNING", "No device selected")
            return
        for device in devices:
            self._frame._submit_remote_input(
                lambda target=device: self._frame._remote_control.send_keyevent(
                    target, key_name, cancelled=self._input_closing,
                )
            )

    def _send_remote_action(self, action: str):
        devices = tuple(self._frame.selected_devices)
        if not devices:
            self._frame._log("WARNING", "No device selected")
            return
        for device in devices:
            self._frame._submit_remote_input(
                lambda target=device: self._frame._remote_control.perform_action(
                    target, action, cancelled=self._input_closing,
                )
            )

    def _warm_remote_input_session(self):
        if (
            self._input_closing()
            or not getattr(self._frame, "_device_selected", True)
            or getattr(self._frame, "_workspace_device_connected", None) is False
        ):
            return
        active_device = getattr(self._frame, "_active_device", None)
        if not active_device:
            return
        try:
            if self._frame._adb.warm_input_session(active_device, cancelled=self._input_closing):
                self._frame._log("DEBUG", "remote input session warmed")
        except Exception as exc:
            self._frame._log(
                "DEBUG",
                f"remote input session warmup skipped: error_type={type(exc).__name__}",
            )

    def _start_warm_remote_input_session(self):
        """启动并保留 warmup producer，供 Remote 关闭屏障等待。"""

        if self._input_closing() or not self._frame._can_operate_device():
            return None
        lock = getattr(self._frame, "_warmup_threads_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._frame._warmup_threads_lock = lock
        threads = getattr(self._frame, "_warmup_threads", None)
        if threads is None:
            threads = set()
            self._frame._warmup_threads = threads
        revision = getattr(self._frame, "_device_admission_revision", 0)

        def warmup() -> None:
            try:
                if revision != getattr(self._frame, "_device_admission_revision", 0):
                    return
                self._frame._warm_remote_input_session()
            finally:
                current = threading.current_thread()
                with lock:
                    threads.discard(current)

        thread = threading.Thread(
            target=warmup,
            name="adblab-remote-input-warmup",
            daemon=True,
        )
        with lock:
            if self._input_closing():
                return None
            threads.add(thread)
            try:
                # 发布句柄与 start 保持同一锁域；shutdown 捕获到的 thread
                # 必然已经启动，因此 join 不会先于 warmup 执行。
                thread.start()
            except Exception:
                threads.discard(thread)
                raise
        return thread
