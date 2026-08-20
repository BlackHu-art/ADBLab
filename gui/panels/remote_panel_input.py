"""提供 Remote 面板的输入队列执行与队列状态回写。"""


class RemotePanelInput:
    """组合进 RemotePanel 的输入执行控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def _submit_remote_input(self, task):
        """遥控输入放入单线程队列，并把队列状态回写到 UI。"""
        executor = getattr(self._frame, "_remote_executor", None)
        if executor is None:
            self._frame._mark_remote_submitted()
            try:
                result = task()
                state = "sent" if self._frame._remote_input_succeeded(result) else "failed"
            except Exception:
                state = "failed"
            if state == "failed":
                self._frame._log("WARNING", "Remote input was not sent")
            self._frame._mark_remote_completed(state)
            return
        self._frame._mark_remote_submitted()

        def _wrapped():
            try:
                service_result = task()
                result = "sent" if self._frame._remote_input_succeeded(service_result) else "failed"
            except Exception as exc:
                result = "failed"
                self._frame._log("ERROR", f"remote input failed: {type(exc).__name__}")
            if result == "failed":
                self._frame._log("WARNING", "Remote input was not sent")
            self._frame._mark_remote_completed(result)

        try:
            executor.submit(_wrapped)
        except RuntimeError as exc:
            self._frame._remote_submitted = max(
                getattr(self._frame, "_remote_completed", 0),
                getattr(self._frame, "_remote_submitted", 0) - 1,
            )
            self._frame._remote_failed = getattr(self._frame, "_remote_failed", 0) + 1
            self._frame._emit_remote_queue_status(
                self._frame._remote_submitted,
                getattr(self._frame, "_remote_completed", 0),
                "failed",
            )
            self._frame._log("ERROR", f"remote executor stopped: {type(exc).__name__}")

    def _mark_remote_submitted(self):
        self._frame._remote_submitted = getattr(self._frame, "_remote_submitted", 0) + 1
        self._frame._emit_remote_queue_status(
            self._frame._remote_submitted,
            getattr(self._frame, "_remote_completed", 0),
            "queued",
        )

    def _mark_remote_completed(self, result: str):
        self._frame._remote_completed = min(
            getattr(self._frame, "_remote_submitted", 0),
            getattr(self._frame, "_remote_completed", 0) + 1,
        )
        if result == "sent":
            self._frame._remote_sent = getattr(self._frame, "_remote_sent", 0) + 1
        elif result == "failed":
            self._frame._remote_failed = getattr(self._frame, "_remote_failed", 0) + 1
        self._frame._emit_remote_queue_status(
            getattr(self._frame, "_remote_submitted", 0),
            self._frame._remote_completed,
            result,
        )

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
            label.setText(
                f"Queue: {queued} queued · {getattr(self._frame, '_remote_sent', 0)} sent · "
                f"{getattr(self._frame, '_remote_failed', 0)} failed"
            )

    def _send_keyevent(self, key_name: str):
        device = self._frame._selected_remote_device()
        if not device:
            return
        self._frame._submit_remote_input(
            lambda: self._frame._remote_control.send_keyevent(device, key_name)
        )

    def _send_remote_action(self, action: str):
        device = self._frame._selected_remote_device()
        if not device:
            return

        def _run():
            try:
                return self._frame._remote_control.perform_action(device, action)
            except Exception as exc:
                self._frame._log("ERROR", f"remote action failed: {type(exc).__name__}")
                raise

        self._frame._submit_remote_input(_run)

    def _warm_remote_input_session(self):
        active_device = getattr(self._frame, "_active_device", None)
        if not active_device:
            return
        try:
            if self._frame._adb.warm_input_session(active_device):
                self._frame._log("DEBUG", "remote input session warmed")
        except Exception as exc:
            self._frame._log(
                "DEBUG",
                f"remote input session warmup skipped: error_type={type(exc).__name__}",
            )
