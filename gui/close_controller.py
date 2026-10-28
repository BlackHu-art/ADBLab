"""应用级异步关闭状态机与最终落盘收尾。"""

import time
from datetime import datetime

from PySide6.QtCore import QThread, QTimer

from core.exec import CommandRunner, ProcessRunner
from core.tasks.supervision import (
    StopDisposition,
    TaskStopResult,
    ThreadedShutdownTask,
)
from gui.dialogs.lifecycle import is_qobject_alive
from gui.i18n import tr
from gui.widgets.settings_scroll import SettingsWheelScroll


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
        handoff = getattr(self._frame, "_handoff", None)
        if handoff is not None:
            handoff.mark_shutdown_success(False)
        # 选框的嵌套事件循环可在后台关闭任务启动前返回；同步封结果准入，
        # 让 Controller 在选择返回后停止续发任务，不等待资源清理线程。
        self._frame.adb_controller.action_results.close()
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
        self._frame.setWindowTitle(tr("ADBLab - Closing..."))
        self._frame.setEnabled(False)
        self._frame.task_supervisor.begin_application_shutdown()
        # 关闭状态已不可逆；注册或 UI 准备失败仍必须提交停止，否则窗口会停在禁用态。
        try:
            self._frame._register_application_shutdown_tasks()
        except Exception as exc:
            self._record_shutdown_failure("task_registration", exc)
        try:
            self._frame._prepare_ui_for_shutdown()
        except Exception as exc:
            self._record_shutdown_failure("ui_preparation", exc)
        remaining = max(0.0, self._frame._shutdown_deadline_at - time.monotonic())
        reserve = min(
            max(0.0, float(self._frame.SHUTDOWN_FINALIZER_RESERVE_SECONDS)),
            remaining * 0.25,
        )
        try:
            self._frame.task_supervisor.stop_all_async(deadline=max(0.0, remaining - reserve))
        except Exception as exc:
            # 调度失败是编程错误；仍推进收尾，避免窗口永久禁用且无法再次关闭。
            self._record_shutdown_failure("stop_scheduling", exc)
            self._frame._on_application_stopped((), ())

    def _register_application_shutdown_tasks(self):
        """按扫描、面板、内嵌会话和 Controller 顺序注册关闭资源。"""
        supervisor = self._frame.task_supervisor.supervisor
        for attribute, kind in (
            ("_installer_update", "installer_download"),
            ("_installer_handoff", "installer_handoff_prepare"),
        ):
            owner = getattr(self._frame, attribute, None)
            if owner is not None:
                self._attempt_shutdown_registration(
                    f"{kind}_registration",
                    lambda owner=owner, kind=kind: supervisor.register(
                        f"{self._frame._shutdown_owner_id}-{kind}",
                        owner_id=self._frame._shutdown_owner_id,
                        kind=kind,
                        # Qt 取消由下方 GUI 准备阶段完成，后台通道只负责真实等待。
                        request_stop=lambda: None,
                        wait=owner.wait,
                        is_running=owner.is_running,
                    ),
                )
        pairing = getattr(self._frame, "_adb_pairing", None)
        if pairing is not None:
            self._attempt_shutdown_registration(
                "pairing_registration",
                lambda: pairing.register_shutdown_tasks(supervisor),
            )
        environment = getattr(self._frame, "_adb_environment", None)
        if environment is not None:
            self._attempt_shutdown_registration(
                "adb_environment_registration",
                lambda: supervisor.register(
                    f"{self._frame._shutdown_owner_id}-adb-environment",
                    owner_id=self._frame._shutdown_owner_id,
                    kind="adb_environment",
                    request_stop=environment.prepare_shutdown,
                    wait=environment.runtime.wait,
                    is_running=environment.runtime.is_running,
                ),
            )
        thread = self._frame._scan_thread
        if thread is not None:

            def scan_running():
                try:
                    return thread.isRunning()
                except RuntimeError:
                    return False

            if scan_running():
                self._attempt_shutdown_registration(
                    "device_scan_registration",
                    lambda: supervisor.register(
                        f"{self._frame._shutdown_owner_id}-scan",
                        owner_id=self._frame._shutdown_owner_id,
                        kind="device_scan",
                        request_stop=thread.stop,
                        wait=lambda timeout: thread.wait(max(0, int(timeout * 1000))),
                        is_running=scan_running,
                    ),
                )

        register_panel_tasks = getattr(self._frame.left_panel, "register_shutdown_tasks", None)
        if callable(register_panel_tasks):
            self._attempt_shutdown_registration(
                "panel_registration",
                lambda: register_panel_tasks(
                    supervisor,
                    owner_id=self._frame._shutdown_owner_id,
                ),
            )

        feature_hosts = getattr(self._frame, "_workspace_feature_hosts", {})
        for index, host in enumerate(feature_hosts.values()):
            register_feature_tasks = getattr(host, "register_shutdown_tasks", None)
            if not callable(register_feature_tasks):
                continue
            try:
                register_feature_tasks(
                    supervisor,
                    owner_id=self._frame._shutdown_owner_id,
                    task_prefix=f"{self._frame._shutdown_owner_id}-feature-{index}",
                )
            except Exception as exc:
                self._record_feature_shutdown_failure("registration", index, exc)

        controller_shutdown = ThreadedShutdownTask(
            self._frame.adb_controller.shutdown,
            name="adblab-controller-shutdown",
        )
        self._frame._shutdown_handles.append(controller_shutdown)

        def controller_running():
            return (
                controller_shutdown.is_running()
                or ProcessRunner.tracked_active_count() > 0
                or CommandRunner.active_count() > 0
            )

        def wait_for_controller(timeout: float):
            deadline = time.monotonic() + timeout
            if not controller_shutdown.wait(timeout):
                return False
            return (
                CommandRunner.wait_for_idle(max(0.0, deadline - time.monotonic()))
                and ProcessRunner.tracked_active_count() == 0
            )

        try:
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
        except Exception as exc:
            # 注册失败仍启动 Controller 停止线程；不能把清理义务留在异常路径上。
            self._record_shutdown_failure("controller_registration", exc)
            controller_shutdown.request_stop()

    def _attempt_shutdown_registration(self, stage: str, callback) -> None:
        """隔离单个注册分组的异常；失败只记录，不阻断其他资源的停止编排。"""

        try:
            callback()
        except Exception as exc:
            self._record_shutdown_failure(stage, exc)

    def _record_shutdown_failure(
        self,
        stage: str,
        error: Exception,
        *,
        task_suffix: str = "",
    ) -> None:
        """保留 GUI 阶段的失败事实，后续资源退出不能将它改报为成功。

        只记录异常类型，不写异常正文，避免设备标识或本机路径进入界面与诊断。
        """
        failures = getattr(self._frame, "_shutdown_preparation_failures", ())
        self._frame._shutdown_preparation_failures = (
            *failures,
            TaskStopResult(
                task_id=f"{self._frame._shutdown_owner_id}-{task_suffix or stage}",
                owner_id=self._frame._shutdown_owner_id,
                disposition=StopDisposition.FAILED,
                error_type=type(error).__name__,
            ),
        )
        self._frame.log_service.log(
            "ERROR",
            f"Application shutdown {stage} failed: {type(error).__name__}",
            flush_immediately=True,
        )

    def _record_feature_shutdown_failure(self, stage: str, index: int, error: Exception) -> None:
        """保留单个内嵌会话的注册或释放失败，任务标识沿用原功能索引。"""
        self._record_shutdown_failure(
            f"feature_{stage}",
            error,
            task_suffix=f"feature-{index}-{stage}",
        )

    def _prepare_ui_for_shutdown(self):
        """先停止界面定时器并断开生产者信号，再广播资源停止请求。"""
        # 升级线程的停止只能在 GUI 发起，必须先于其他可失败的页面清理且逐项尝试。
        installer_update = getattr(self._frame, "_installer_update", None)
        if installer_update is not None:
            try:
                installer_update.prepare_shutdown()
            except Exception as exc:
                self._record_shutdown_failure("installer_download_preparation", exc)
        installer_handoff = getattr(self._frame, "_installer_handoff", None)
        if installer_handoff is not None:
            try:
                installer_handoff.prepare_shutdown(
                    preserve_prepared=bool(
                        getattr(self._frame, "_installer_close_requested", False)
                    ),
                )
            except Exception as exc:
                self._record_shutdown_failure("installer_handoff_preparation", exc)
        for scroll in self._frame.findChildren(SettingsWheelScroll):
            scroll.prepare_shutdown()
        device_bar = getattr(self._frame, "_global_device_bar", None)
        if device_bar is not None:
            # 先结束几何过渡，避免动画完成回调在 SidePanel 清理后恢复布局计时器。
            device_bar.dismiss_popups()
        device_hub = getattr(self._frame, "_device_hub", None)
        if device_hub is not None:
            device_hub.prepare_shutdown()
        tasks_page = getattr(self._frame, "_tasks_page", None)
        shutdown_tasks = getattr(tasks_page, "shutdown", None)
        if callable(shutdown_tasks):
            # 关闭期间窗口仍可见，hideEvent 不会触发；这里显式停止任务中心轮询。
            shutdown_tasks()
        settings = getattr(self._frame, "_settings_page", None)
        prepare_settings = getattr(settings, "prepare_shutdown", None)
        if callable(prepare_settings):
            prepare_settings()
        else:
            client_card = getattr(settings, "adb_client_card", None)
            if client_card is not None:
                client_card.prepare_shutdown()
        connection = getattr(self._frame, "_connection_panel", None)
        if connection is not None:
            connection.prepare_shutdown()
        pairing = getattr(self._frame, "_adb_pairing", None)
        if pairing is not None:
            pairing.prepare_shutdown()
        app_update = getattr(self._frame, "_app_update", None)
        if app_update is not None:
            app_update.prepare_shutdown()
        environment = getattr(self._frame, "_adb_environment", None)
        if environment is not None:
            environment.prepare_shutdown()
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
                        self._frame._on_scan_discovery_state
                    )
            except (TypeError, RuntimeError, AttributeError):
                pass
        for index, host in enumerate(
            getattr(self._frame, "_workspace_feature_hosts", {}).values()
        ):
            try:
                host.shutdown()
            except Exception as exc:
                self._record_feature_shutdown_failure("dispose", index, exc)
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
        self._frame._shutdown_results = (
            *getattr(self._frame, "_shutdown_preparation_failures", ()),
            *results,
        )
        self._frame._shutdown_residual = tuple(residual)
        self._frame._shutdown_had_residual = (
            getattr(self._frame, "_shutdown_had_residual", False) or bool(residual)
        )
        environment = getattr(self._frame, "_adb_environment", None)
        if environment is not None:
            environment.close()
        self._frame._shutdown_archive_failed = False
        # 生产者退出后在 GUI 线程提交最后一条测试记录，再由后台收尾排空写入队列。
        for host in getattr(self._frame, "_workspace_feature_hosts", {}).values():
            for page in host.registry.pages():
                archive = getattr(page, "archive_finished_run", None)
                if callable(archive):
                    try:
                        archive()
                    except Exception as exc:
                        # 单页归档失败仍要收尾其他生产者，最终状态必须保留失败事实。
                        # 页面归档不属于核心资源清理，任何异常都不能中断关闭收尾链。
                        self._frame._shutdown_archive_failed = True
                        self._frame.log_service.log(
                            "ERROR", f"Test result archive failed: {type(exc).__name__}"
                        )
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
        archive_monkey = getattr(self._frame.adb_controller, "archive_finished_monkey_runs", None)
        if callable(archive_monkey):
            try:
                archive_monkey(resources_stopped=not self._frame._shutdown_residual and not failed)
            except Exception as exc:
                self._frame._shutdown_archive_failed = True
                self._frame.log_service.log(
                    "ERROR", f"Monkey result archive failed: {type(exc).__name__}"
                )
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
                tr("ADBLab - Closing ({count} residual resources)").format(
                    count=len(self._frame._shutdown_residual)
                )
            )
            self._frame.log_service.log(
                "WARNING",
                (
                    f"Shutdown residual resources count={len(self._frame._shutdown_residual)} "
                    f"kinds={','.join(kinds)}"
                ),
                flush_immediately=True,
            )
        # 最终用户日志必须在 GUI 线程刷新并冻结；后台 finalizer 只负责配置落盘。
        self._frame.log_service.shutdown()
        # 最后设置写入仍可能失败；给后台传值快照，不在 finalizer 访问 GUI 日志对象。
        self._frame._shutdown_diagnostic_text = self._frame.log_service.diagnostics.text()
        finalizer = ThreadedShutdownTask(
            self._frame._flush_shutdown_state,
            name="adblab-shutdown-finalizer",
        )
        self._frame._shutdown_handles.append(finalizer)
        finalizer_task_id = f"{self._frame._shutdown_owner_id}-finalizer"
        remaining = max(0.0, self._frame._shutdown_deadline_at - time.monotonic())
        try:
            self._frame.task_supervisor.supervisor.register(
                finalizer_task_id,
                owner_id=self._frame._shutdown_owner_id,
                kind="shutdown_finalizer",
                request_stop=finalizer.request_stop,
                wait=finalizer.wait,
                is_running=finalizer.is_running,
                error_type=finalizer.get_error_type,
            )
            self._frame.task_supervisor.stop_finalizer_async(
                finalizer_task_id,
                deadline=remaining,
            )
        except Exception as exc:
            # 监督器登记/调度失败也必须启动一次收尾并释放关闭事件，不能让窗口
            # 永远停在“正在关闭”且 _close_ready 永不置位。
            self._frame.log_service.log(
                "ERROR",
                f"Shutdown finalizer scheduling failed: {type(exc).__name__}",
            )
            finalizer.request_stop()
            finalizer.wait(remaining)
            self._on_application_finalized(None, ())

    def _flush_shutdown_state(self):
        """在后台原子保存待写配置；日志服务已在 GUI 线程提前关闭。"""
        from core.settings_manager import AppSettings

        settings_saved = AppSettings.instance().close()
        library = getattr(self._frame, "run_library", None)
        library_saved = True
        if library is not None:
            if settings_saved is False:
                # 日志服务已冻结，直接向尚未关闭的同一文件队列补交有界、无隐私的失败摘要。
                previous = getattr(self._frame, "_shutdown_diagnostic_text", "")
                lines = previous.splitlines()[-199:]
                lines.append(
                    f"{datetime.now():%H:%M:%S} [ERROR] 应用设置未能完成保存；"
                    "请检查用户数据目录权限和可用空间。"
                )
                library.save_diagnostics("\n".join(lines))
            remaining = max(0.0, self._frame._shutdown_deadline_at - time.monotonic())
            library_saved = library.shutdown(remaining)
        if settings_saved is False:
            raise RuntimeError("应用设置未能完成保存")
        if not library_saved or getattr(self._frame, "_shutdown_archive_failed", False):
            raise RuntimeError("本地结果或诊断记录未能完成保存")

    def _on_application_finalized(
        self,
        result: TaskStopResult | None,
        residual: tuple,
    ) -> None:
        """记录收尾结果并重新触发关闭事件，使 Qt 最终销毁窗口。"""
        if (
            not self._frame._close_started or self._frame._close_ready
            or getattr(self._frame, "_shutdown_native_join_pending", False)
        ):
            return
        if result is not None:
            self._frame._shutdown_results = (*self._frame._shutdown_results, result)
        self._frame._shutdown_residual = tuple(residual)
        self._frame._shutdown_had_residual = (
            getattr(self._frame, "_shutdown_had_residual", False) or bool(residual)
        )
        finalizer_failed = result is not None and result.disposition in {
            StopDisposition.FAILED,
            StopDisposition.TIMED_OUT,
        }
        if finalizer_failed:
            assert result is not None  # finalizer_failed 蕴含 result 非 None
            self._frame.setWindowTitle(
                tr("ADBLab - Closing (finalizer {status}, {count} residual resources)").format(
                    status=result.disposition.value,
                    count=len(self._frame._shutdown_residual),
                )
            )
        if self._frame._shutdown_residual:
            self._frame.setWindowTitle(
                tr("ADBLab - Closing ({count} residual resources)").format(
                    count=len(self._frame._shutdown_residual)
                )
            )
        self._frame._shutdown_native_join_pending = True
        self._finish_close_after_native_join(result)

    def _finish_close_after_native_join(self, result: TaskStopResult | None) -> None:
        """停止预算耗尽后仍保留原生子线程归属，确认 join 才销毁 Qt 父树。

        普通残留沿用原有截止时间语义；只复核 QThread，不重跑停止、收尾或升级授权。
        """
        for worker in self._frame.findChildren(QThread):
            if is_qobject_alive(worker) and not worker.wait(0):
                QTimer.singleShot(
                    50, self._frame, lambda: self._finish_close_after_native_join(result),
                )
                return
        self._frame._shutdown_native_join_pending = False
        handoff = getattr(self._frame, "_handoff", None)
        if handoff is not None:
            # 普通退出保持原契约；升级另需严格成功证据，不能把关闭事件被接受当授权。
            successful = (
                bool(getattr(self._frame, "_installer_close_requested", False))
                and handoff.prepared
                and result is not None
                and result.task_id == f"{self._frame._shutdown_owner_id}-finalizer"
                and not getattr(self._frame, "_shutdown_preparation_failures", ())
                and not self._frame._shutdown_had_residual
                and all(
                    item.disposition in {StopDisposition.GRACEFUL, StopDisposition.ALREADY_STOPPED}
                    and not item.error_type
                    for item in self._frame._shutdown_results
                )
            )
            handoff.mark_shutdown_success(successful)
            if not successful:
                handoff.abort()
        self._frame._close_ready = True
        QTimer.singleShot(0, self._frame.close)
