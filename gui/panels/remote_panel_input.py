"""提供 Remote 面板的输入队列执行与队列状态回写。"""

import threading


class RemotePanelInput:
    """组合进 RemotePanel 的输入执行控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame
        self._lock = threading.Lock()

    def _input_closing(self) -> bool:
        return bool(
            getattr(self._frame, "_closing", False)
            or getattr(self._frame, "_remote_input_closing", False)
        )

    def _submit_remote_input(self, task):
        """遥控输入放入单线程队列，并把队列状态回写到 UI。"""
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
            text = f"队列：{queued}"
            if failed:
                text += f" · 失败：{failed}"
            label.setText(text)
            details = f"排队：{queued} · 已发送：{sent} · 失败：{failed}"
            label.setToolTip(details)
            label.setAccessibleDescription(details)

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
        if self._input_closing():
            return
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

    def _start_warm_remote_input_session(self):
        """启动并保留 warmup producer，供 Remote 关闭屏障等待。"""

        if self._input_closing():
            return None
        lock = getattr(self._frame, "_warmup_threads_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._frame._warmup_threads_lock = lock
        threads = getattr(self._frame, "_warmup_threads", None)
        if threads is None:
            threads = set()
            self._frame._warmup_threads = threads

        def warmup() -> None:
            try:
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
