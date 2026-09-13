"""按页面串行调度传输，并动态监督晚到清理任务的资源归属。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.dialogs.lifecycle import QThreadGroupShutdownTask
from models.file_explorer_worker import TransferWorker

if TYPE_CHECKING:
    from gui.dialogs.file_explorer import FileExplorerPage


class _TransferThread(Protocol):
    """队列只依赖线程的启动、取消和等待边界。"""

    def start(self) -> None: ...
    def abort(self) -> None: ...
    def wait(self, timeout: int) -> bool: ...


@dataclass
class _QueuedTransfer:
    worker: _TransferThread
    preview: bool
    on_terminal: Callable[[], None] | None
    cleanup: Callable[[], None] | None


class FileTransferCoordinator(QObject):
    """GUI 线程调度队列；后台仅请求停止和读取动态资源快照。"""

    drain_requested = Signal()

    def __init__(self, frame: FileExplorerPage, task_supervisor=None):
        super().__init__(frame if isinstance(frame, QObject) else None)
        self._frame = frame
        self._supervisor = task_supervisor or QtTaskSupervisor.shared()
        self._queue: list[_QueuedTransfer] = []
        self._active: _QueuedTransfer | None = None
        self._holds: set[object] = set()
        self._stopping = threading.Event()
        self._lock = threading.RLock()
        self._stopping_workers: set[object] = set()
        self._finishing_workers: set[object] = set()
        self._stop_requested_workers: set[object] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._poll)
        self.drain_requested.connect(self.cancel_pending, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def worker_active(worker) -> bool:
        """传输复核进程存活，其他线程沿用 QThread 的运行状态。"""
        try:
            method = getattr(worker, "is_active", None)
            if callable(method):
                return bool(method())
            if isinstance(worker, QThread):
                return worker.isRunning() or not worker.wait(0)
            return QThreadGroupShutdownTask._running(worker)
        except RuntimeError:
            return False

    def hold_cleanup(self) -> object:
        """在准备资源前登记清理义务，直到生命周期回调显式释放。"""
        token = object()
        with self._lock:
            self._holds.add(token)
        return token

    def release_cleanup(self, token: object) -> None:
        """GUI 生命周期回调完成清理后释放义务，重复释放安全。"""
        with self._lock:
            self._holds.discard(token)
        self._frame._finish_async_dispose()

    def enqueue(self, worker, *, preview=False, on_terminal=None, cleanup=None):
        """接管未启动线程；预览排在当前项后，终态回调包括未执行取消。"""
        entry = _QueuedTransfer(worker, preview, on_terminal, cleanup)
        if self._stopping.is_set() or not self._frame._can_operate():
            worker.abort()
            self._terminal(entry)
            self._frame._prune_worker(worker)
            return worker
        with self._lock:
            if preview:
                position = next(
                    (i for i, item in enumerate(self._queue) if not item.preview), len(self._queue)
                )
                self._queue.insert(position, entry)
            else:
                self._queue.append(entry)
        self._dispatch()
        return worker

    def _dispatch(self):
        if self._active is not None:
            return
        if self._stopping.is_set() or not self._frame._can_operate():
            self.cancel_pending()
            return
        with self._lock:
            if not self._queue:
                return
            self._active = self._queue.pop(0)
        setattr(self._active.worker, "_transfer_dispatched", True)
        self._active.worker.start()

    def _terminal(self, entry):
        try:
            if entry.on_terminal is not None:
                entry.on_terminal()
        finally:
            if entry.cleanup is not None:
                entry.cleanup()

    def worker_finished(self, worker) -> bool:
        """在线程和进程均退出后交付一次终态，供页面随后删除线程。"""
        if self.worker_active(worker):
            # finished 先于原生线程完全 join；先登记等待，不能被第二次存活检查漏掉。
            self._finishing_workers.add(worker)
            self._timer.start()
            if (isinstance(worker, TransferWorker) and worker._proc is not None
                    and worker._proc.poll() is None):
                self._stop_worker(worker)
            return False
        self._finishing_workers.discard(worker)
        with self._lock:
            self._stop_requested_workers.discard(worker)
        if worker in self._stopping_workers:
            self._stopping_workers.discard(worker)
            self._supervisor.supervisor.unregister(f"file-transfer-stop-{id(worker)}")
        entry = self._active
        if entry is not None and entry.worker is worker:
            with self._lock:
                self._active = None
            self._terminal(entry)
            self._dispatch()
        return True

    def cancel_pending(self, *, preview_only=False):
        """GUI 线程取消未执行项目，仍交付终态以归还请求拥有的资源。"""
        with self._lock:
            cancelled = [item for item in self._queue if not preview_only or item.preview]
            self._queue = [item for item in self._queue if preview_only and not item.preview]
        for entry in cancelled:
            entry.worker.abort()
            self._terminal(entry)
            prune = getattr(self._frame, "_prune_worker", None)
            if callable(prune):
                prune(entry.worker)

    def cancel_preview(self):
        """取消旧预览的排队或运行项，不中止普通文件传输。"""
        self.cancel_pending(preview_only=True)
        if self._active is not None and self._active.preview:
            self._stop_worker(self._active.worker)

    def _stop_worker(self, worker):
        self._request_worker_stop(worker)
        if worker in self._stopping_workers or not self.worker_active(worker):
            return
        self._stopping_workers.add(worker)
        task_id = f"file-transfer-stop-{id(worker)}"
        wait = getattr(worker, "wait_stopped", None)

        def wait_stopped(timeout):
            return bool(wait(timeout)) if callable(wait) else bool(worker.wait(int(timeout * 1000)))

        self._supervisor.supervisor.register(
            task_id, owner_id=f"file-page-{id(self)}", kind="file_transfer_stop",
            request_stop=lambda: self._request_worker_stop(worker),
            wait=wait_stopped,
            is_running=lambda: self.worker_active(worker),
            force_stop=getattr(worker, "force_stop", None),
        )
        self._supervisor.stop_async(task_id)
        self._timer.start()

    def _request_worker_stop(self, worker):
        if not self.worker_active(worker):
            return
        with self._lock:
            if worker in self._stop_requested_workers:
                return
            self._stop_requested_workers.add(worker)
        worker.abort()

    def _poll(self):
        for worker in tuple(self._stopping_workers | self._finishing_workers):
            if not self.worker_active(worker):
                self._finishing_workers.discard(worker)
                self._stopping_workers.discard(worker)
                self._supervisor.supervisor.unregister(f"file-transfer-stop-{id(worker)}")
                self._frame._prune_worker(worker)
        if not self._stopping_workers and not self._finishing_workers:
            self._timer.stop()
        self._frame._finish_async_dispose()

    def request_stop(self):
        """后台安全停止准入，队列终态交回 GUI 线程处理。"""
        self._stopping.set()
        self.drain_requested.emit()
        for worker in tuple(self._frame._workers):
            if (worker not in getattr(self._frame, "_cleanup_workers", ())
                    and self.worker_active(worker)):
                self._request_worker_stop(worker)

    def is_running(self) -> bool:
        """包含等待 GUI 收口的队列和清理义务，不能只观察旧线程快照。"""
        with self._lock:
            pending = bool(self._queue or self._active or self._holds)
        return pending or any(self.worker_active(worker) for worker in tuple(self._frame._workers))

    def wait(self, timeout: float) -> bool:
        """后台有界等待动态资源，GUI 仍可追加既有请求的清理任务。"""
        deadline = time.monotonic() + max(0.0, timeout)
        while self.is_running():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            threading.Event().wait(min(0.01, remaining))
        return True

    def force_stop(self, timeout: float) -> bool:
        """后台强停当前资源，仍等待晚到清理义务真正归零。"""
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in tuple(self._frame._workers):
            force = getattr(worker, "force_stop", None)
            if callable(force) and self.worker_active(worker):
                force(max(0.0, deadline - time.monotonic()))
        return self.wait(max(0.0, deadline - time.monotonic()))
