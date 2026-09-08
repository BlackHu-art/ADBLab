"""为单次 MobilePerf 采集提供原始双流执行与分阶段取消，不引入 Qt 依赖。"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from core.adb_runtime import AdbRuntime, RuntimeSnapshot, native_capture
from core.adb_transport import CancelCheck, ExecutionResult
from mobileperf.common.log import logger


class MobilePerfAdbExecutor:
    """会话拥有执行策略；采集请求可取消，收尾线程在最终封闭前仍可查询设备。"""

    def __init__(
        self,
        resolver: Callable[[], str | None],
        serial: str | None,
        exit_event: threading.Event,
        stop_file: str = "",
    ):
        self._exit_event = exit_event
        self._stop_file = stop_file
        self._ready = threading.Event()
        self._condition = threading.Condition()
        self._cleanup_thread: threading.Thread | None = None
        self._closed = False
        self._active = 0
        self._native_only = os.environ.get("MOBILEPERF_ADB_MODE") == "native"
        self.runtime = AdbRuntime(
            resolver,
            probe_serial=serial or None,
            changed=self._changed,
            diagnostic=lambda message: logger.debug("MobilePerf %s", message),
        )
        self.runtime.set_native_only(self._native_only)

    def _changed(self, snapshot: RuntimeSnapshot) -> None:
        if snapshot.checked_devices or not snapshot.checking:
            self._ready.set()

    def stop_requested(self) -> bool:
        """保留创建时的退出事件，避免旧采集线程读取下一次运行的共享状态。"""
        return self._exit_event.is_set() or bool(
            self._stop_file and os.path.exists(self._stop_file)
        )

    def start(self) -> None:
        """有界等待目标能力验证，原生测速继续后台运行；原生模式不启动探测。"""
        if self._native_only or self.stop_requested():
            return
        self._ready.clear()
        self.runtime.start()
        deadline = time.monotonic() + 1.5
        while not self.stop_requested() and time.monotonic() < deadline:
            if self._ready.wait(min(0.1, max(0, deadline - time.monotonic()))):
                break

    def _cancelled(self, caller: CancelCheck | None) -> bool:
        with self._condition:
            if self._closed or (caller is not None and caller()):
                return True
            if self._cleanup_thread is not None:
                return threading.current_thread() is not self._cleanup_thread
        return self.stop_requested()

    def run(
        self, cmd: list[str], timeout: float, cancelled: CancelCheck | None = None
    ) -> ExecutionResult:
        """执行已由调用方筛选的同步短命令，保留原始双流及一次总超时。

        MobilePerf 依赖原始输出和非零退出时的 stdout，不能套用 GUI 的文本结果转换。
        协议后端仅在发送前允许原生选择，设备端失败或中途断线均不重放。
        """
        deadline = time.monotonic() + timeout
        def check() -> bool:
            return self._cancelled(cancelled)

        with self._condition:
            if check():
                return ExecutionResult(kind="cancelled")
            self._active += 1
        try:
            if not self._native_only:
                self.runtime.request_device_check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ExecutionResult(kind="timeout")
            result = self.runtime.try_run(cmd, remaining, check)
            if result is not None:
                return result
            if check():
                return ExecutionResult(kind="cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ExecutionResult(kind="timeout")
            return native_capture(cmd, remaining, check)
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def begin_cleanup(self) -> None:
        """封闭采集线程准入并取消在途请求，当前收尾线程保留必要查询权限。"""
        with self._condition:
            if self._cleanup_thread is None:
                self._cleanup_thread = threading.current_thread()
        self.runtime.prepare_shutdown()

    def close(self, timeout: float = 2.0) -> bool:
        """最终取消双后端请求，在同一预算内等待探测、连接和原生客户端释放。"""
        deadline = time.monotonic() + timeout
        with self._condition:
            self._closed = True
        self.runtime.close()
        runtime_stopped = self.runtime.wait(max(0, deadline - time.monotonic()))
        with self._condition:
            while self._active and time.monotonic() < deadline:
                self._condition.wait(max(0, deadline - time.monotonic()))
            stopped = runtime_stopped and self._active == 0
        if not stopped:
            logger.warning("MobilePerf ADB shutdown exceeded its wait budget")
        return stopped
