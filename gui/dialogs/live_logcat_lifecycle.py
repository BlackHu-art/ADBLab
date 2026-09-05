"""提供 Logcat 功能页关闭与 worker 生命周期管理。"""

import weakref

from PySide6.QtCore import QTimer

from adblab.application.supervision import StopDisposition, TaskStopResult
from gui.dialogs.lifecycle import is_qobject_alive, safe_disconnect
from gui.dialogs.live_logcat_worker import CurrentPackageWorker, LogcatWorker


class LiveLogcatLifecycle:
    """组合进 LiveLogcatPage 的生命周期控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        # 控制器由页面持有，反向使用弱引用，避免 Qt 包装对象进入 Python 引用环。
        self._frame_ref = weakref.ref(frame)

    @property
    def _frame(self):
        frame = self._frame_ref()
        if frame is None:
            raise RuntimeError("LiveLogcatPage has been released")
        return frame

    def _on_task_stopped(self, result: TaskStopResult):
        if (
            self._frame._closing
            or result.owner_id != self._frame._supervisor_owner_id
            or result.task_id != self._frame._supervisor_task_id
        ):
            return
        if result.disposition is StopDisposition.GRACEFUL:
            self._frame.status_bar.setText("采集已停止")
        elif result.disposition is StopDisposition.FORCED:
            self._frame.status_bar.setText("已强制停止采集")
        elif result.disposition is StopDisposition.TIMED_OUT:
            self._frame.status_bar.setText("停止采集超时；任务仍受监督，请等待清理完成")
        elif result.disposition is StopDisposition.ALREADY_STOPPED:
            self._frame.status_bar.setText("日志采集已停止")
        else:
            self._frame.status_bar.setText("日志任务清理失败，请重试停止操作")
        worker = self._frame.worker
        if worker is None:
            self._frame._set_running_actions(False)
        elif self._release_logcat_worker(worker):
            self._frame._set_running_actions(False)
        elif not self._frame._worker_release_timer.isActive():
            # 监督结果和 QThread.finished 可能乱序；继续观察晚退出的受跟踪进程。
            self._frame._worker_release_timer.start(self._frame.CLEANUP_RECHECK_MS)

    def _on_current_pkg(self, package: str):
        if not self._frame._can_operate_device():
            return
        source = self._frame.sender()
        if source is not None and (
            getattr(source, "_package_filter_revision", self._frame._package_filter_revision)
            != self._frame._package_filter_revision
        ):
            # 用户按 Enter 后，旧查询即使已有排队信号也不得覆盖手动提交。
            return
        self._frame.pkg_input.setText(package)
        self._frame._apply_package_filter(package)

    @staticmethod
    def _thread_is_joined(worker) -> bool:
        """非阻塞确认 QThread 的原生收尾已经完成。"""

        wait = getattr(worker, "wait", None)
        if not callable(wait):
            return True
        try:
            return bool(wait(0))
        except RuntimeError:
            # C++ 对象已经释放时，不再存在需要等待的原生线程。
            return True

    def _release_pkg_worker(self, worker: CurrentPackageWorker) -> bool:
        """释放已经停止的包名查询线程，并返回它是否仍是当前线程。"""
        try:
            if worker.isRunning():
                return False
        except RuntimeError:
            pass
        if not self._thread_is_joined(worker):
            return False
        self._disconnect_pkg_worker(worker)
        task_id = getattr(worker, "_supervisor_task_id", None)
        if task_id:
            self._frame._task_supervisor.supervisor.unregister(task_id)
        was_current = self._frame._pkg_worker is worker
        if was_current:
            self._frame._pkg_worker = None
        if is_qobject_alive(worker):
            worker.deleteLater()
        return was_current

    def _on_pkg_worker_finished(self, worker: CurrentPackageWorker):
        if (
            self._frame._closing
            and self._frame._owner_cleanup_requested
            and not self._frame._owner_cleanup_completed
        ):
            self._frame._debug_lifecycle("worker_finished_waiting", worker_kind="package_probe")
            return
        was_current = self._release_pkg_worker(worker)
        if self._frame._pkg_worker is worker:
            if not self._frame._closing and not self._frame._worker_release_timer.isActive():
                self._frame._worker_release_timer.start(self._frame.CLEANUP_RECHECK_MS)
            if self._frame._closing:
                self._try_finalize_close("package_worker_join_pending")
            return
        if self._frame._closing:
            self._try_finalize_close("package_worker_finished")
        elif was_current:
            self._frame._sync_device_actions()

    def _release_logcat_worker(self, worker: LogcatWorker) -> bool:
        """仅在线程和受跟踪进程都停止后释放 Logcat 工作对象。"""
        if worker.is_active():
            return False
        if not self._thread_is_joined(worker):
            return False
        self._disconnect_worker(worker)
        task_id = getattr(worker, "_supervisor_task_id", None)
        if task_id:
            self._frame._task_supervisor.supervisor.unregister(task_id)
        was_current = self._frame.worker is worker
        if was_current:
            self._frame.worker = None
            self._frame._supervisor_task_id = None
            release_timer = getattr(self._frame, "_worker_release_timer", None)
            if release_timer is not None:
                release_timer.stop()
        if is_qobject_alive(worker):
            worker.deleteLater()
        return was_current

    def _on_worker_finished(self, worker: LogcatWorker | None = None):
        worker = worker or self._frame.worker
        if worker is None:
            return
        if (
            self._frame._closing
            and self._frame._owner_cleanup_requested
            and not self._frame._owner_cleanup_completed
        ):
            self._frame._debug_lifecycle("worker_finished_waiting", worker_kind="live_logcat")
            return
        was_current = self._release_logcat_worker(worker)
        if self._frame.worker is worker:
            self._frame._debug_lifecycle("worker_retained", reason="process_still_active")
            if not self._frame._closing and not self._frame._worker_release_timer.isActive():
                self._frame._worker_release_timer.start(self._frame.CLEANUP_RECHECK_MS)
            return
        if self._frame._closing:
            self._try_finalize_close("logcat_worker_finished")
            return
        if was_current:
            self._frame._set_running_actions(False)

    def _poll_worker_release(self) -> None:
        """在窗口保持打开时等待工作线程完成原生收尾并释放对象。"""

        if self._frame._closing:
            return
        release_pending = False
        package_worker = self._frame._pkg_worker
        if package_worker is not None:
            if self._release_pkg_worker(package_worker):
                self._frame.btn_get_pkg.setEnabled(not self._frame._logcat_stopping)
            else:
                release_pending = True
        worker = self._frame.worker
        if worker is None:
            self._frame._set_running_actions(False)
        elif self._release_logcat_worker(worker):
            self._frame._set_running_actions(False)
        else:
            release_pending = True
        if release_pending:
            self._frame._worker_release_timer.start(self._frame.CLEANUP_RECHECK_MS)

    def _owner_residual_tasks(self):
        """返回仍由当前日志窗口负责的受监督资源。"""
        try:
            snapshots = self._frame._task_supervisor.supervisor.active_snapshot()
        except Exception:
            return (None,)
        return tuple(
            item for item in snapshots if item.owner_id == self._frame._supervisor_owner_id
        )

    def _schedule_cleanup_recheck(self) -> None:
        """在停止流程返回后继续观察晚退出的线程或外部进程。"""
        if (
            self._frame._close_pending
            and not self._frame._close_ready
            and not self._frame._cleanup_recheck_timer.isActive()
        ):
            self._frame._cleanup_recheck_timer.start(self._frame.CLEANUP_RECHECK_MS)

    def _poll_close_cleanup(self) -> None:
        """重新核对资源屏障，避免线程先结束而进程晚退出时丢失唤醒。"""
        if self._try_finalize_close("cleanup_recheck", log_deferred=False):
            return
        if self._frame._owner_cleanup_completed:
            self._schedule_cleanup_recheck()

    def _prune_stopped_owner_tasks(self, residual) -> None:
        """注销已确认停止但仍残留在监督注册表中的当前窗口任务。"""
        for item in residual:
            if item is not None and not item.running:
                self._frame._task_supervisor.supervisor.unregister(item.task_id)

    def _try_finalize_close(self, trigger: str, *, log_deferred: bool = True) -> bool:
        """仅在工作对象和监督注册均清零后允许销毁窗口。"""
        if not self._frame._close_pending or self._frame._close_ready:
            return False
        if self._frame._owner_cleanup_requested and not self._frame._owner_cleanup_completed:
            if log_deferred:
                self._frame._debug_lifecycle(
                    "close_deferred",
                    reason="owner_cleanup_running",
                    trigger=trigger,
                )
            return False
        if self._frame.worker is not None and not self._frame.worker.is_active():
            self._release_logcat_worker(self._frame.worker)
        if self._frame._pkg_worker is not None and not self._frame._pkg_worker.isRunning():
            self._release_pkg_worker(self._frame._pkg_worker)
        residual = self._owner_residual_tasks()
        self._prune_stopped_owner_tasks(residual)
        residual = self._owner_residual_tasks()
        if self._frame.worker is not None or self._frame._pkg_worker is not None or residual:
            if log_deferred:
                self._frame._debug_lifecycle(
                    "close_deferred",
                    package_worker_retained=self._frame._pkg_worker is not None,
                    residual_count=len(residual),
                    trigger=trigger,
                    worker_retained=self._frame.worker is not None,
                )
            if self._frame._owner_cleanup_completed:
                self._schedule_cleanup_recheck()
            return False
        if self._frame._cleanup_recheck_timer.isActive():
            self._frame._cleanup_recheck_timer.stop()
        self._frame._close_ready = True
        safe_disconnect(self._frame._task_supervisor.owner_stopped, self._frame._on_owner_stopped)
        safe_disconnect(
            self._frame._task_supervisor.application_stopped,
            self._frame._on_application_stopped,
        )
        self._frame._debug_lifecycle("resources_stopped", trigger=trigger)
        # 页面可能先被会话宿主销毁，关闭回调必须绑定 Qt 上下文以随之取消。
        QTimer.singleShot(0, self._frame, self._frame.close)
        return True

    def _on_owner_stopped(self, owner_id: str, results):
        """停止流程返回后复核真实资源屏障，不把超时误判为已停止。"""
        if (
            owner_id != self._frame._supervisor_owner_id
            or not self._frame._close_pending
            or self._frame._close_ready
        ):
            return
        results = tuple(results or ())
        unresolved = tuple(result for result in results if not result.stopped)
        self._frame._owner_cleanup_completed = True
        residual = self._owner_residual_tasks()
        self._frame._debug_lifecycle(
            "owner_stop_completed",
            residual_count=len(residual),
            result_count=len(results),
            unresolved_count=len(unresolved),
        )
        self._try_finalize_close("owner_stop_completed")

    def _on_application_stopped(self, results, residual) -> None:
        """应用级停止接管 owner 清理时，恢复页面释放状态机。"""

        if (
            not self._frame._application_cleanup_fallback
            or not self._frame._close_pending
            or self._frame._close_ready
        ):
            return
        own_results = tuple(
            result
            for result in tuple(results or ())
            if result.owner_id == self._frame._supervisor_owner_id
        )
        own_residual = tuple(
            item
            for item in tuple(residual or ())
            if item.owner_id == self._frame._supervisor_owner_id
        )
        self._frame._owner_cleanup_completed = True
        self._frame._debug_lifecycle(
            "application_stop_completed",
            residual_count=len(own_residual),
            result_count=len(own_results),
        )
        self._try_finalize_close("application_stop_completed")

    # ── 资源清理 ────────────────────────────────────────────────────────

    def _disconnect_worker(self, worker: LogcatWorker, *, keep_finished: bool = False):
        bindings = (
            ("_dialog_lines_handler", worker.lines_ready),
            ("_dialog_dropped_handler", worker.dropped_ready),
            ("_dialog_status_handler", worker.status_changed),
            ("_dialog_ended_handler", worker.terminated),
            ("_dialog_finished_handler", worker.finished),
        )
        for attribute, signal_ in bindings:
            if keep_finished and attribute == "_dialog_finished_handler":
                continue
            handler = getattr(worker, attribute, None)
            if handler is not None:
                safe_disconnect(signal_, handler)
            setattr(worker, attribute, None)

    def _disconnect_pkg_worker(
        self,
        worker: CurrentPackageWorker,
        *,
        keep_finished: bool = False,
    ):
        for signal_, handler in (
            (worker.package_ready, self._frame._on_current_pkg),
            (worker.status_changed, self._frame._on_status),
        ):
            if handler is not None:
                safe_disconnect(signal_, handler)
        handler = getattr(worker, "_dialog_finished_handler", None)
        if handler is not None and not keep_finished:
            safe_disconnect(worker.finished, handler)
            worker._dialog_finished_handler = None
