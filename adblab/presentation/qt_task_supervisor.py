"""由 Qt 生命周期管理的 TaskSupervisor 异步适配器。"""

from __future__ import annotations

import time
from threading import Lock, Thread

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from adblab.application.supervision import TaskSupervisor


class QtTaskSupervisor(QObject):
    """在 GUI 线程之外执行有时限的资源停止和等待。"""

    task_stopped = Signal(object)
    owner_stopped = Signal(str, object)
    application_stopped = Signal(tuple, tuple)
    application_finalized = Signal(object, tuple)

    _shared = None
    _shared_lock = Lock()

    def __init__(self, supervisor: TaskSupervisor | None = None):
        super().__init__(None)
        self.supervisor = supervisor or TaskSupervisor()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        self._application_stop_lock = Lock()
        self._application_stop_started = False
        self._application_stop_dispatched = False
        self._application_finalizer_dispatched = False

    @classmethod
    def shared(cls) -> QtTaskSupervisor:
        with cls._shared_lock:
            if cls._shared is None:
                cls._shared = cls()
            return cls._shared

    def stop_async(
        self,
        task_id: str,
        *,
        graceful_timeout: float = 1.5,
        force_timeout: float = 1.5,
    ) -> None:
        """在线程池中停止单个资源，并通过 Qt 信号返回结果。"""
        adapter = self

        class StopTask(QRunnable):
            def run(self):
                result = adapter.supervisor.stop(
                    task_id,
                    graceful_timeout=graceful_timeout,
                    force_timeout=force_timeout,
                )
                if result is not None:
                    try:
                        adapter.task_stopped.emit(result)
                    except RuntimeError:
                        pass

        self._pool.start(StopTask())

    def stop_owner_async(self, owner_id: str, *, deadline: float = 3.0) -> bool:
        """异步停止指定 owner 的资源，并返回请求是否已提交。

        应用级关闭开始后由 ``stop_all_async`` 接管全部资源；调用方可依据
        ``False`` 改为等待 ``application_stopped``，避免永远等待不会发送的
        ``owner_stopped`` 信号。
        """
        with self._application_stop_lock:
            if self._application_stop_started:
                return False
        adapter = self

        class StopOwnerTask(QRunnable):
            def run(self):
                results = adapter.supervisor.stop_owner(owner_id, deadline=deadline)
                try:
                    adapter.owner_stopped.emit(owner_id, results)
                except RuntimeError:
                    pass

        self._pool.start(StopOwnerTask())
        return True

    def begin_application_shutdown(self) -> bool:
        """原子标记应用关闭开始，仅首次调用返回 True。"""
        with self._application_stop_lock:
            if self._application_stop_started:
                return False
            self._application_stop_started = True
            return True

    def stop_all_async(self, *, deadline: float = 3.0) -> bool:
        """停止全部已注册任务一次，并发送结果和残留资源快照。"""
        self.begin_application_shutdown()
        with self._application_stop_lock:
            if self._application_stop_dispatched:
                return False
            self._application_stop_dispatched = True
        final_end = time.monotonic() + max(0.0, float(deadline))
        adapter = self

        def stop_application():
            remaining = max(0.0, final_end - time.monotonic())
            results = adapter.supervisor.stop_all(deadline=remaining)
            residual = adapter.supervisor.active_snapshot()
            try:
                adapter.application_stopped.emit(results, residual)
            except RuntimeError:
                pass

        # 应用关闭不能排在 owner 清理任务之后；此处提前记录绝对截止时间，使线程启动延迟也计入预算。
        Thread(
            target=stop_application,
            name="adblab-application-shutdown",
            daemon=True,
        ).start()
        return True

    def stop_finalizer_async(self, task_id: str, *, deadline: float = 1.0) -> bool:
        """在独立且有时限的执行通道中停止资源清理后的唯一收尾任务。"""
        with self._application_stop_lock:
            if self._application_finalizer_dispatched:
                return False
            self._application_finalizer_dispatched = True
        final_end = time.monotonic() + max(0.0, float(deadline))
        adapter = self

        def stop_finalizer():
            remaining = max(0.0, final_end - time.monotonic())
            result = adapter.supervisor.stop(
                task_id,
                graceful_timeout=remaining,
                force_timeout=0.0,
            )
            residual = adapter.supervisor.active_snapshot()
            try:
                adapter.application_finalized.emit(result, residual)
            except RuntimeError:
                pass

        Thread(
            target=stop_finalizer,
            name="adblab-application-finalizer",
            daemon=True,
        ).start()
        return True
