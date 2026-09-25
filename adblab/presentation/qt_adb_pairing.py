"""将单轮无线配对接入 Qt；业务结果不代替线程与原生客户端的退出屏障。"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from core.exec import require_adb_program
from core.native_process import NativeCommandScope
from services.adb_pairing import (
    PairingContext,
    PairingOutcome,
    PairingProgress,
    PairingService,
    create_continuation_request,
    create_manual_request,
    create_qr_request,
)


def _context(revision: int) -> PairingContext:
    """仅在后台解析客户端，避免打开表单时触发磁盘发现或 ADB。"""
    return PairingContext(require_adb_program(), dict(os.environ), revision)


class _PairingWorker(QThread):
    """拥有本轮秘密与二维码确认事件，结束时丢弃请求和秘密引用。"""

    progress = Signal(object)
    qr_ready = Signal(int, bytes, int)
    outcome = Signal(object)

    def __init__(self, request, revision, scope, service_factory, context_factory, parent):
        super().__init__(parent)
        self.request = request
        self.request_id = request.request_id
        self.revision = revision
        self.scope = scope
        self.cancel_event = threading.Event()
        self._qr_ack = threading.Event()
        self._qr_shown = False
        self._service_factory = service_factory
        self._context_factory = context_factory

    def abort(self):
        """取消及唤醒只设置线程安全事件，不在 GUI 等待子进程。"""
        self.cancel_event.set()
        self._qr_ack.set()
        self.scope.request_stop()

    def acknowledge_qr(self):
        self._qr_shown = True
        self._qr_ack.set()

    def _show_qr(self, request_id, png, module_count, timeout_seconds):
        self._qr_ack.clear()
        self._qr_shown = False
        if self.cancel_event.is_set():
            return False
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        self.qr_ready.emit(request_id, png, module_count)
        while not self.cancel_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._qr_ack.wait(min(remaining, 0.05)):
                return (
                    self._qr_shown
                    and not self.cancel_event.is_set()
                    and time.monotonic() < deadline
                )
        return False

    def run(self):
        request = self.request
        try:
            if request is None or self.cancel_event.is_set():
                return
            try:
                context = (
                    request.continuation.context
                    if request.continuation is not None
                    else self._context_factory(self.revision)
                )
            except (OSError, RuntimeError, ValueError):
                self.outcome.emit(
                    PairingOutcome(
                        self.request_id,
                        self.revision,
                        None,
                        False,
                        "adb_unavailable",
                        "Failed",
                    )
                )
                return
            if self.cancel_event.is_set():
                return
            result = self._service_factory().run(
                request,
                context,
                self.cancel_event,
                self.scope,
                self.progress.emit,
                self._show_qr,
            )
            self.outcome.emit(result)
        except Exception:
            # 服务边界异常也必须交付失败；原始异常可能含秘密，不能进入 Qt/日志。
            self.outcome.emit(
                PairingOutcome(
                    self.request_id,
                    self.revision,
                    None,
                    False,
                    "command_failed",
                    "Failed",
                )
            )
        finally:
            self.request = None
            del request


class _PairingResources:
    """监督器同时等待线程和异常路径残留进程，不借 finished 推断进程归零。"""

    def __init__(self, worker, scope):
        self.worker = worker
        self.scope = scope

    def request_stop(self):
        self.worker.abort()

    def is_running(self):
        return self.worker.isRunning() or self.scope.is_running()

    def wait(self, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        self.worker.wait(max(0, int(timeout * 1000)))
        if self.worker.isRunning():
            return False
        return self.scope.wait(max(0.0, deadline - time.monotonic()))


class QtAdbPairing(QObject):
    """主窗口所属的单会话协调器；所有公开启动/取消接口在 GUI 线程调用。"""

    progress = Signal(object)
    qr_ready = Signal(int, bytes, int)
    outcome_ready = Signal(object)
    connected = Signal(object)
    busy_changed = Signal(bool)
    idle = Signal()
    continuation_changed = Signal()

    def __init__(
        self,
        task_supervisor: QtTaskSupervisor,
        parent: QObject | None = None,
        *,
        service_factory: Callable = PairingService,
        scope_factory: Callable = NativeCommandScope,
        context_factory: Callable = _context,
    ):
        super().__init__(parent)
        self._supervisor = task_supervisor
        self._service_factory = service_factory
        self._scope_factory = scope_factory
        self._context_factory = context_factory
        self._owner_id = f"wireless-pairing-{uuid4().hex}"
        self._task_id = ""
        self._registered = False
        self._worker: _PairingWorker | None = None
        self._resources: _PairingResources | None = None
        self._request_counter = 0
        self._current_request = None
        self._context_revision = 0
        self._closing = False
        self._stop_inflight = False
        self._application_stop_inflight = False
        self._stop_reason = ""
        self._outcome = None
        self._verified_outcome = None
        self.continuation = None
        self.state = "Idle"
        self.reason = ""
        self._supervisor.owner_stopped.connect(self._owner_stopped)
        self._supervisor.application_stopped.connect(self._application_stopped)

    @property
    def busy(self) -> bool:
        """即使线程已退出，排队回调或残留客户端仍会阻止新轮次准入。"""
        return self._worker is not None

    @property
    def context_revision(self) -> int:
        """后台持久化只读取代次值，不访问 Qt 控件或秘密。"""
        return self._context_revision

    def _publish(self, state, reason="", remaining=0):
        self.state, self.reason = state, reason
        self.progress.emit(
            PairingProgress(
                self._current_request or 0,
                state,
                reason,
                remaining,
            )
        )

    def _new_request(self, factory, *args, **kwargs):
        if self.busy or self._closing:
            return False
        self._request_counter += 1
        try:
            request = factory(self._request_counter, *args, **kwargs)
        except ValueError:
            self._publish("Failed", "invalid_request")
            return False
        self.continuation = None
        self.continuation_changed.emit()
        self._current_request = request.request_id
        self._outcome = self._verified_outcome = None
        self._stop_reason = ""
        scope = self._scope_factory()
        worker = _PairingWorker(
            request,
            self._context_revision,
            scope,
            self._service_factory,
            self._context_factory,
            self,
        )
        self._worker = worker
        self._resources = _PairingResources(worker, scope)
        self._task_id = f"{self._owner_id}-{request.request_id}"
        worker.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        worker.qr_ready.connect(self._qr, Qt.ConnectionType.QueuedConnection)
        worker.outcome.connect(self._result, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.register_shutdown_tasks(self._supervisor.supervisor)
        self.busy_changed.emit(True)
        self._publish("Checking")
        try:
            worker.start()
        except RuntimeError:
            self._outcome = PairingOutcome(
                request.request_id,
                self._context_revision,
                None,
                False,
                "command_failed",
                "Failed",
            )
            worker.request = None
            self._publish("Failed", "command_failed")
            self._settle_resources()
        return True

    def start_qr(self, *, qr_scale=6) -> bool:
        """仅显式打开扫码页或刷新才创建新口令，普通地址页不调用此方法。"""
        return self._new_request(create_qr_request, qr_scale=qr_scale)

    def start_code(self, endpoint: str, code: str) -> bool:
        """六位码保留前导零，由服务工厂校验，受理后 UI 应立即清空输入。"""
        return self._new_request(create_manual_request, endpoint, code)

    def continue_connection(self, endpoint: str) -> bool:
        """只允许原环境下的无口令恢复快照；不隐式重放配对。"""
        continuation = self.continuation
        if continuation is None or continuation.context.context_revision != self._context_revision:
            return False
        return self._new_request(create_continuation_request, continuation, endpoint)

    def accepts_outcome(self, outcome) -> bool:
        """最终交付及 Controller 准入共用一次已验证结果的身份检查。"""
        return bool(
            outcome is self._verified_outcome
            and not self._closing
            and outcome.context_revision == self._context_revision
            and outcome.request_id == self._current_request
            and outcome.connected
            and outcome.device_id
        )

    def acknowledge_qr(self, request_id: int):
        """仅当前图像真正显示后的 GUI 确认才启动服务端扫码预算。"""
        if self._worker is not None and request_id == self._current_request:
            self._worker.acknowledge_qr()

    def _current_worker(self):
        worker = self.sender()
        return (
            worker is self._worker
            and isinstance(worker, _PairingWorker)
            and (
                worker.request_id == self._current_request
                and worker.revision == self._context_revision
                and not self._closing
            )
        )

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 Slot 的桩类型遗漏实例参数。
    def _progress(self, progress):
        if self._current_worker() and progress.request_id == self._current_request:
            if progress.state == "Connected":
                return
            self._publish(progress.state, progress.reason, progress.remaining_seconds)

    @Slot(int, bytes, int)  # type: ignore[reportArgumentType]  # PySide6 多参数 Slot 的桩类型不完整。
    def _qr(self, request_id, png, module_count):
        if self._current_worker() and request_id == self._current_request:
            self.qr_ready.emit(request_id, png, module_count)

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 Slot 的桩类型遗漏实例参数。
    def _result(self, outcome):
        if not self._current_worker() or self._outcome is not None:
            return
        if (outcome.request_id, outcome.context_revision) != (
            self._current_request,
            self._context_revision,
        ):
            return
        self._outcome = outcome
        self.continuation = outcome.continuation
        self.continuation_changed.emit()
        # 已连接文案会承诺设备列表刷新，必须与最终交付共用资源退出屏障。
        if not outcome.connected:
            self._publish(outcome.state, outcome.reason)
        self.outcome_ready.emit(outcome)

    @Slot()
    def _finished(self):
        if self.sender() is self._worker:
            self._settle_resources()

    def _settle_resources(self):
        resources = self._resources
        if resources is None or self._stop_inflight or self._application_stop_inflight:
            return
        if resources.is_running():
            if not resources.worker.isRunning():
                self._publish("CleanupFailed", "cleanup_failed")
                self.retry_stop()
            return
        worker = self._worker
        if self._registered:
            self._supervisor.supervisor.unregister(self._task_id)
        self._registered = False
        self._resources = None
        self._worker = None
        self._task_id = ""
        if worker is not None:
            worker.deleteLater()
        if self._stop_reason:
            self._publish("Idle", self._stop_reason)
        outcome = self._outcome
        self._verified_outcome = (
            outcome
            if outcome is not None
            and outcome.connected
            and outcome.request_id == self._current_request
            and outcome.context_revision == self._context_revision
            and not self._closing
            else None
        )
        self.busy_changed.emit(False)
        if self._verified_outcome is not None:
            self._publish(self._verified_outcome.state, self._verified_outcome.reason)
            self.connected.emit(self._verified_outcome)
        self.idle.emit()

    def cancel(self):
        """使旧回调和续连资格立即失效，等待资源退出后才发布已取消。"""
        self._current_request = None
        self.continuation = self._verified_outcome = None
        self.continuation_changed.emit()
        self._stop_reason = self._stop_reason or "cancelled"
        if not self.busy:
            self._publish("Idle", self._stop_reason)
            self.idle.emit()
            return
        self._publish("Stopping")
        self.retry_stop()

    def invalidate(self, _reason="context_changed"):
        """客户端重检、变更与重启准入均撤销已完成 PairedOnly 的恢复资格。"""
        self._context_revision += 1
        self._stop_reason = "context_changed"
        self.cancel()

    def retry_stop(self):
        """重试原资源清理，绝不创建新 ADB 命令或在 GUI 中 wait。"""
        if self._resources is None:
            return
        self._resources.request_stop()
        if self._stop_inflight:
            return
        self._stop_inflight = True
        if not self._supervisor.stop_owner_async(self._owner_id, deadline=3.0):
            self._stop_inflight = False
            # 应用 stop_all 已接管；finished 或 application_stopped 会再检查真实资源。

    @Slot(str, object)  # type: ignore[reportArgumentType]  # PySide6 多参数 Slot 的桩类型不完整。
    def _owner_stopped(self, owner_id, _results):
        if owner_id != self._owner_id:
            return
        self._stop_inflight = False
        if self._resources is not None and self._resources.is_running():
            self._publish("CleanupFailed", "cleanup_failed")
        else:
            self._settle_resources()

    def _application_stopped(self, _results, _residual):
        self._application_stop_inflight = False
        # stop_all 会跳过 owner 已认领的资源；其完成不能释放仍被 owner 使用的线程。
        # stop_owner_async 拒绝提交时没有此标记，因此仍可由应用完成信号正常收尾。
        if self._stop_inflight:
            return
        if self._resources is not None and self._resources.is_running():
            self._publish("CleanupFailed", "cleanup_failed")
        else:
            self._settle_resources()

    def register_shutdown_tasks(self, supervisor, **_kwargs):
        """每轮只注册一次；应用关闭可重复调用以纳入已有 owner 清理中的资源。"""
        if self._resources is None:
            return ()
        if not self._registered:
            supervisor.register(
                self._task_id,
                owner_id=self._owner_id,
                kind="adb_pairing",
                request_stop=self._resources.request_stop,
                wait=self._resources.wait,
                is_running=self._resources.is_running,
            )
            self._registered = True
        return (self._task_id,)

    def prepare_shutdown(self):
        """应用停止准入并广播取消；真实等待由应用监督器负责。"""
        self._closing = True
        self._application_stop_inflight = self.busy
        self._current_request = None
        self.continuation = self._verified_outcome = None
        self.continuation_changed.emit()
        if self._resources is not None:
            self._resources.request_stop()
        self._stop_reason = "cancelled"
