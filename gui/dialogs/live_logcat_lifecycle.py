"""提供 Logcat 对话框关闭与 worker 生命周期管理。"""

from PySide6.QtCore import QTimer

from adblab.application.supervision import StopDisposition, TaskStopResult
from gui.dialogs.lifecycle import is_qobject_alive, safe_disconnect
from gui.dialogs.live_logcat_worker import CurrentPackageWorker, LogcatWorker


class LiveLogcatLifecycle:
    """组合进 LiveLogcatDialog 的生命周期控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def _on_task_stopped(self, result: TaskStopResult):
        if (
            self._frame._closing
            or result.owner_id != self._frame._supervisor_owner_id
            or result.task_id != self._frame._supervisor_task_id
        ):
            return
        if result.disposition is StopDisposition.GRACEFUL:
            self._frame.status_bar.showMessage("Logcat stopped")
        elif result.disposition is StopDisposition.FORCED:
            self._frame.status_bar.showMessage("Logcat force-stopped")
        elif result.disposition is StopDisposition.TIMED_OUT:
            self._frame.status_bar.showMessage("Logcat cleanup timed out; task remains supervised")
        elif result.disposition is StopDisposition.ALREADY_STOPPED:
            self._frame.status_bar.showMessage("Logcat already stopped")
        else:
            self._frame.status_bar.showMessage("Logcat cleanup failed")
        worker = self._frame.worker
        if worker is None:
            self._frame._set_running_actions(False)
        elif self._release_logcat_worker(worker):
            self._frame._set_running_actions(False)
        elif not self._frame._worker_release_timer.isActive():
            # 监督结果和 QThread.finished 可能乱序；继续观察晚退出的受跟踪进程。
            self._frame._worker_release_timer.start(self._frame.CLEANUP_RECHECK_MS)

    def _on_current_pkg(self, package: str):
        if self._frame._closing:
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

    def _release_pkg_worker(self, worker: CurrentPackageWorker) -> bool:
        """释放已经停止的包名查询线程，并返回它是否仍是当前线程。"""
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
        if self._frame._closing:
            self._try_finalize_close("package_worker_finished")
        elif was_current:
            self._frame.btn_get_pkg.setEnabled(not self._frame._logcat_stopping)

    def _release_logcat_worker(self, worker: LogcatWorker) -> bool:
        """仅在线程和受跟踪进程都停止后释放 Logcat 工作对象。"""
        if worker.is_active():
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
        """在窗口保持打开时释放线程先结束、进程稍后退出的日志任务。"""

        if self._frame._closing:
            return
        worker = self._frame.worker
        if worker is None:
            self._frame._set_running_actions(False)
            return
        if self._release_logcat_worker(worker):
            self._frame._set_running_actions(False)
            return
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
        self._frame._debug_lifecycle("resources_stopped", trigger=trigger)
        QTimer.singleShot(0, self._frame.close)
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
