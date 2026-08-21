"""应用级异步关闭状态机与最终落盘收尾。"""

import time

from PySide6.QtCore import QTimer

from adblab.application.supervision import (
    StopDisposition,
    TaskStopResult,
    ThreadedShutdownTask,
)
from core.exec import ProcessRunner


class CloseController:
    """组合进 MainFrame 的关闭控制器，通过 ``self._frame`` 访问主窗口。"""

    def __init__(self, frame):
        self._frame = frame

    def handle_close_event(self, event):
        """启动异步关闭，只在资源停止和最终状态落盘完成后接受事件。"""
        self._frame._unbind_window_screen()
        if getattr(self._frame, "_close_ready", False):
            event.accept()
            return
        event.ignore()
        if getattr(self._frame, "_close_started", False):
            return
        self._frame._flush_pending_layout_state()
        self._frame._close_started = True
        self._frame._closing = True
        self._frame._shutdown_deadline_at = time.monotonic() + max(
            0.0,
            float(self._frame.SHUTDOWN_DEADLINE_SECONDS),
        )
        self._frame.log_service.log(
            "DEBUG",
            (
                "application shutdown requested: "
                f"deadline_seconds={float(self._frame.SHUTDOWN_DEADLINE_SECONDS):.1f}"
            ),
        )
        self._frame.setWindowTitle("ADBLab - Closing...")
        self._frame.setEnabled(False)
        self._frame.task_supervisor.begin_application_shutdown()
        self._frame._register_application_shutdown_tasks()
        self._frame._prepare_ui_for_shutdown()
        remaining = max(0.0, self._frame._shutdown_deadline_at - time.monotonic())
        reserve = min(
            max(0.0, float(self._frame.SHUTDOWN_FINALIZER_RESERVE_SECONDS)),
            remaining * 0.25,
        )
        self._frame.task_supervisor.stop_all_async(deadline=max(0.0, remaining - reserve))

    def _register_application_shutdown_tasks(self):
        """按扫描、面板、对话框和 Controller 顺序注册应用级关闭资源。"""
        supervisor = self._frame.task_supervisor.supervisor
        thread = self._frame._scan_thread
        if thread is not None:

            def scan_running():
                try:
                    return thread.isRunning()
                except RuntimeError:
                    return False

            if scan_running():
                supervisor.register(
                    f"{self._frame._shutdown_owner_id}-scan",
                    owner_id=self._frame._shutdown_owner_id,
                    kind="device_scan",
                    request_stop=thread.stop,
                    wait=lambda timeout: thread.wait(max(0, int(timeout * 1000))),
                    is_running=scan_running,
                )

        register_panel_tasks = getattr(self._frame.left_panel, "register_shutdown_tasks", None)
        if callable(register_panel_tasks):
            register_panel_tasks(
                supervisor,
                owner_id=self._frame._shutdown_owner_id,
            )

        for index, dialog in enumerate(list(self._frame._active_dialogs)):
            register_dialog_tasks = getattr(dialog, "register_shutdown_tasks", None)
            if not callable(register_dialog_tasks):
                continue
            try:
                register_dialog_tasks(
                    supervisor,
                    owner_id=self._frame._shutdown_owner_id,
                    task_prefix=f"{self._frame._shutdown_owner_id}-dialog-{index}",
                )
            except Exception as exc:
                self._frame.log_service.log(
                    "ERROR",
                    f"Shutdown task registration failed: {type(exc).__name__}",
                    flush_immediately=True,
                )

        controller_shutdown = ThreadedShutdownTask(
            self._frame.adb_controller.shutdown,
            name="adblab-controller-shutdown",
        )
        self._frame._shutdown_handles.append(controller_shutdown)

        def controller_running():
            return controller_shutdown.is_running() or ProcessRunner.tracked_active_count() > 0

        def wait_for_controller(timeout: float):
            if not controller_shutdown.wait(timeout):
                return False
            return ProcessRunner.tracked_active_count() == 0

        supervisor.register(
            f"{self._frame._shutdown_owner_id}-controller",
            owner_id=self._frame._shutdown_owner_id,
            kind="controller_shutdown",
            request_stop=controller_shutdown.request_stop,
            wait=wait_for_controller,
            is_running=controller_running,
            force_stop=ProcessRunner.force_all_tracked,
            error_type=controller_shutdown.get_error_type,
        )

    def _prepare_ui_for_shutdown(self):
        """先停止界面定时器并断开生产者信号，再广播资源停止请求。"""
        if self._frame._initial_refresh_timer.isActive():
            self._frame._initial_refresh_timer.stop()
        if self._frame._scan_refresh_timer.isActive():
            self._frame._scan_refresh_timer.stop()
        if self._frame._scan_thread is not None:
            self._frame._scan_thread.stop()
            devices_changed = getattr(self._frame._scan_thread, "devices_changed", None)
            discovery_state_changed = getattr(
                self._frame._scan_thread,
                "discovery_state_changed",
                None,
            )
            try:
                if devices_changed is not None:
                    devices_changed.disconnect(self._frame._schedule_scan_refresh)
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                if discovery_state_changed is not None:
                    discovery_state_changed.disconnect(
                        self._frame.left_panel.set_device_discovery_state
                    )
            except (TypeError, RuntimeError, AttributeError):
                pass
        for dlg in list(self._frame._active_dialogs):
            try:
                dlg.close()
            except Exception:
                pass
        # 独立窗口可能在后台资源停止前忽略关闭事件；保留强引用直到 destroyed 回调移除。
        for viewer in list(getattr(self._frame.adb_controller, "_active_viewers", [])):
            try:
                viewer.close()
            except Exception:
                pass
        shutdown_left_panel = getattr(self._frame.left_panel, "shutdown", None)
        if callable(shutdown_left_panel):
            shutdown_left_panel()

    def _on_application_stopped(self, results: tuple, residual: tuple) -> None:
        """汇总资源停止结果，再启动配置和日志收尾任务。"""
        if (
            not self._frame._close_started
            or self._frame._close_ready
            or getattr(self._frame, "_shutdown_finalizer_started", False)
        ):
            return
        self._frame._shutdown_finalizer_started = True
        self._frame._shutdown_results = tuple(results)
        self._frame._shutdown_residual = tuple(residual)
        self._frame.log_service.log(
            "DEBUG",
            (
                "application producers stopped: "
                f"result_count={len(self._frame._shutdown_results)} "
                f"residual_count={len(self._frame._shutdown_residual)}"
            ),
        )
        failed = [
            result
            for result in self._frame._shutdown_results
            if getattr(result, "disposition", None) == StopDisposition.FAILED
        ]
        if failed:
            error_types = sorted({result.error_type or "UnknownError" for result in failed})
            self._frame.log_service.log(
                "ERROR",
                f"Shutdown task failures count={len(failed)} types={','.join(error_types)}",
                flush_immediately=True,
            )
        if self._frame._shutdown_residual:
            kinds = sorted({item.kind for item in self._frame._shutdown_residual})
            self._frame.setWindowTitle(
                f"ADBLab - Closing ({len(self._frame._shutdown_residual)} residual resources)"
            )
            self._frame.log_service.log(
                "WARNING",
                (
                    f"Shutdown residual resources count={len(self._frame._shutdown_residual)} "
                    f"kinds={','.join(kinds)}"
                ),
                flush_immediately=True,
            )
        if self._frame._panel_size_save_timer.isActive():
            self._frame._panel_size_save_timer.stop()
            self._frame._save_pending_panel_sizes()

        # 最终用户日志必须在 GUI 线程刷新并冻结；后台 finalizer 只负责配置落盘。
        self._frame.log_service.shutdown()
        finalizer = ThreadedShutdownTask(
            self._frame._flush_shutdown_state,
            name="adblab-shutdown-finalizer",
        )
        self._frame._shutdown_handles.append(finalizer)
        finalizer_task_id = f"{self._frame._shutdown_owner_id}-finalizer"
        self._frame.task_supervisor.supervisor.register(
            finalizer_task_id,
            owner_id=self._frame._shutdown_owner_id,
            kind="shutdown_finalizer",
            request_stop=finalizer.request_stop,
            wait=finalizer.wait,
            is_running=finalizer.is_running,
            error_type=finalizer.get_error_type,
        )
        remaining = max(0.0, self._frame._shutdown_deadline_at - time.monotonic())
        self._frame.task_supervisor.stop_finalizer_async(
            finalizer_task_id,
            deadline=remaining,
        )

    def _flush_shutdown_state(self):
        """在后台原子保存待写配置；日志服务已在 GUI 线程提前关闭。"""
        from core.settings_manager import AppSettings

        s = AppSettings.instance()
        if s._save_timer:
            s._save_timer.cancel()
        s._save_atomic()

    def _on_application_finalized(
        self,
        result: TaskStopResult | None,
        residual: tuple,
    ) -> None:
        """记录收尾结果并重新触发关闭事件，使 Qt 最终销毁窗口。"""
        if not self._frame._close_started or self._frame._close_ready:
            return
        if result is not None:
            self._frame._shutdown_results = (*self._frame._shutdown_results, result)
        self._frame._shutdown_residual = tuple(residual)
        finalizer_failed = result is not None and result.disposition in {
            StopDisposition.FAILED,
            StopDisposition.TIMED_OUT,
        }
        if finalizer_failed:
            self._frame.setWindowTitle(
                "ADBLab - Closing "
                f"(finalizer {result.disposition.value}, "
                f"{len(self._frame._shutdown_residual)} residual resources)"
            )
        if self._frame._shutdown_residual:
            self._frame.setWindowTitle(
                f"ADBLab - Closing ({len(self._frame._shutdown_residual)} residual resources)"
            )
        self._frame._close_ready = True
        QTimer.singleShot(0, self._frame.close)
