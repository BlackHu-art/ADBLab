"""提供不依赖 Qt 和 asyncio 的协作式取消原语。"""

from __future__ import annotations

from threading import Event, Lock


class CancellationError(RuntimeError):
    """任务在显式取消检查点发现取消请求时抛出。"""


class CancellationToken:
    """提供线程安全且幂等的取消信号。

    令牌本身不会停止线程或进程；worker 必须在安全边界主动检查，具体资源的停止回调由
    TaskSupervisor 负责调用。
    """

    def __init__(self) -> None:
        self._event = Event()
        self._cancel_lock = Lock()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def request(self) -> bool:
        """请求取消，仅首次请求返回 True。"""
        with self._cancel_lock:
            if self._event.is_set():
                return False
            self._event.set()
            return True

    def cancel(self) -> bool:
        """保留兼容入口，语义与 request() 相同。"""
        return self.request()

    def wait(self, timeout: float | None = None) -> bool:
        """等待取消信号，避免调用方直接依赖 Event。"""
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        """在取消检查点抛出 CancellationError，否则保持静默。"""
        if self.is_cancelled:
            raise CancellationError("Operation was cancelled")
