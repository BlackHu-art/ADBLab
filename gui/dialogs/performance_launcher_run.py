"""提供 MobilePerf 启停、运行状态展示与进度更新。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from adblab.application.supervision import ThreadedShutdownTask
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.lifecycle import alive_signal_emitter
from gui.i18n import tr
from gui.styles import BaseStyles
from services.mobileperf_runner import PerformanceArtifacts


class PerformanceStartWorker(QThread):
    """拥有一次启动准备及取消后的进程收口；不读取或修改页面控件。"""

    def __init__(self, runner, config, on_log, on_finished, parent):
        super().__init__(parent)
        self.runner = runner
        self.config = config
        self.on_log = on_log
        self.on_finished = on_finished
        self.cancelled = threading.Event()
        self.error = ""
        self.started_at: float | None = None

    def abort(self):
        """只记录意图，避免 GUI 等待 Runner 准备阶段持有的状态锁。"""
        self.cancelled.set()

    def run(self):
        try:
            if self.cancelled.is_set():
                return
            self.runner.start(
                self.config, on_log=self.on_log, on_finished=self.on_finished,
                cancelled=self.cancelled.is_set,
            )
            self.started_at = time.monotonic()
        except CancelledError:
            self.cancelled.set()
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
        finally:
            # spawn 已进入时无法撤回；同一任务必须确认其停止后才交回 GUI 终态。
            if (self.cancelled.is_set() or self.error) and self.runner.is_running():
                try:
                    self.runner.stop()
                except Exception as exc:
                    self.error = self.error or str(exc) or type(exc).__name__


class PerformanceLauncherRun(QObject):
    """组合进 PerformancePage 的运行控制器，通过 ``self._frame`` 访问页面。"""

    _runner_log = Signal(object, str)
    _runner_done = Signal(object)

    def __init__(self, frame):
        super().__init__(frame)
        self._frame = frame
        self._start_worker: PerformanceStartWorker | None = None
        self._generation = 0
        self._finished_during_start = False
        self._start_timer = QTimer(self)
        self._start_timer.setInterval(25)
        self._start_timer.timeout.connect(self._finish_start)
        self._runner_log.connect(self._on_run_log, Qt.ConnectionType.QueuedConnection)
        self._runner_done.connect(self._on_run_finished, Qt.ConnectionType.QueuedConnection)

    @property
    def starting(self):
        """直到启动线程实际 join 且 GUI 接收终态前保留配置和关闭屏障。"""
        return self._start_worker is not None

    def cancel_start(self):
        """撤销尚未交付的启动，已运行会话不受后续设备失选影响。"""
        worker = self._start_worker
        if worker is None:
            return
        worker.abort()
        self._frame._run_cancel_requested = True
        self._frame._library_controller.request_cancel()
        self._frame.stop_btn.setEnabled(False)
        self._set_status(tr("Stopping"), "stopping")

    @Slot(object, str)  # type: ignore[reportArgumentType]  # PySide6 Slot 桩未包含 self。
    def _on_run_log(self, generation, message):
        if generation == self._generation and not self._frame._closing:
            self._frame.log_received.emit("RAW", message)

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 Slot 桩未包含 self。
    def _on_run_finished(self, generation):
        if generation != self._generation:
            return
        if self.starting:
            self._finished_during_start = True
        else:
            self._mark_runner_finished()

    def start_mobileperf(self):
        if self._frame._closing or self._frame._configuration_locked:
            return
        if not self._frame._can_operate_device():
            FluentMessageBox.warning(
                self._frame,
                tr("未选择当前设备"),
                tr("请在顶部勾选并连接当前设备，再开始性能采集。"),
            )
            self._frame._set_status(tr("No device selected"), "failed")
            return
        if not self._frame._commit_numeric_inputs():
            return
        config = self._frame.build_config()
        if not config.package:
            FluentMessageBox.warning(
                self._frame,
                tr("Package Required"),
                tr("Please enter a package name."),
            )
            return
        if config.monkey_enabled and config.monkey_config.total_percentage != 100:
            self._frame.log_received.emit(
                "WARNING",
                tr(
                    "Monkey event percentages sum to {value0}%, not 100%; "
                    "continuing with this distribution."
                ).format(value0=config.monkey_config.total_percentage),
            )
        self._frame._result_loader.invalidate()
        self._frame.chart_view.clear()
        self._frame.chart_status.clear()
        self._frame._last_result_root = ""
        self._frame._update_result_action()
        self._frame._runner_finished_handled = False
        self._frame._run_cancel_requested = False
        self._frame._run_elapsed_seconds = 0
        self._frame._run_started_at = None
        self._frame._run_duration_seconds = max(1, int(config.timeout_minutes) * 60)
        self._frame._library_controller.begin(config)
        self._frame.log_received.emit("INFO", tr("Starting mobileperf"))
        self._generation += 1
        self._finished_during_start = False
        worker = PerformanceStartWorker(
            self._frame._runner, config,
            alive_signal_emitter(self, "_runner_log", self._generation),
            alive_signal_emitter(self, "_runner_done", self._generation), self,
        )
        self._start_worker = worker
        worker.finished.connect(self._finish_start, Qt.ConnectionType.QueuedConnection)
        self._set_running(True)
        self._set_status(tr("Starting mobileperf"), "starting")
        self._frame._set_progress(0)
        try:
            worker.start()
        except Exception as exc:
            worker.error = str(exc) or type(exc).__name__
            worker.abort()
            self._finish_start()

    @Slot()
    def _finish_start(self):
        """启动结果只在所属 GUI 线程处理，finished 信号不能代替实际 join。"""
        worker = self._start_worker
        if worker is None:
            return
        if worker.isRunning() or not worker.wait(0):
            self._start_timer.start()
            return
        self._start_timer.stop()
        self._start_worker = None
        worker.deleteLater()
        frame = self._frame
        if worker.cancelled.is_set() or worker.error:
            if worker.cancelled.is_set():
                frame._run_cancel_requested = True
                frame._library_controller.request_cancel()
            if worker.runner.is_running():
                # 收口失败仍保留停止入口和原 Runner，不把启动线程结束当作资源归零。
                frame._stopping = False
                if not frame._closing:
                    self._set_running(True)
                    self._set_status(tr("Stop failed"), "warning")
                    frame._poll_timer.start()
                if worker.cancelled.is_set() and not frame._shutdown_registered:
                    self.stop_mobileperf()
                return
            if worker.started_at is not None:
                # 创建后取消仍可能生成报告，沿原有后台结果归档保留本次附件。
                self._mark_runner_finished()
                if frame._closing:
                    frame._poll_dispose_ready()
                return
            if worker.error:
                frame._library_controller.finish(start_error=worker.error)
            else:
                frame._library_controller.finish(artifact_snapshot=PerformanceArtifacts())
            frame._runner_finished_handled = True
            frame._stopping = False
            if not frame._closing:
                frame._reset_progress()
                self._set_running(False)
                if worker.error:
                    frame.log_received.emit(
                        "ERROR", tr('Start failed: {value0}').format(value0=worker.error),
                    )
                    self._set_status(tr("Failed"), "failed")
                else:
                    self._set_status(tr("已停止"), "cancelled")
        elif not frame._closing:
            frame._run_started_at = worker.started_at
            self._set_running(True)
            frame._poll_timer.start()
            if self._finished_during_start:
                self._mark_runner_finished()
        if frame._closing:
            frame._poll_dispose_ready()

    def register_start_shutdown(self, supervisor, *, owner_id, task_prefix):
        """监督准备线程及其可能创建的进程，任务快照保留到后台 join 完成。"""
        worker = self._start_worker
        if worker is None:
            return None
        task_id = f"{task_prefix}-start-worker"

        def thread_active():
            try:
                return worker.isRunning() or not worker.wait(0)
            except RuntimeError:
                return False

        def join_start(timeout):
            try:
                return worker.wait(max(0, int(timeout * 1000)))
            except RuntimeError:
                return True

        def stop_after_start():
            # 注册与全局停止分属两个时刻；启动已交付时也必须保留新进程的停止义务。
            try:
                worker.wait()
            except RuntimeError:
                pass
            if worker.runner.is_running():
                worker.runner.stop()

        shutdown = ThreadedShutdownTask(stop_after_start, name="adblab-mobileperf-start-stop")

        def request_stop():
            worker.abort()
            shutdown.request_stop()

        def wait(timeout):
            deadline = time.monotonic() + max(0, timeout)
            return (join_start(timeout)
                    and shutdown.wait(max(0, deadline - time.monotonic()))
                    and not worker.runner.is_running())

        def force_stop(timeout):
            worker.abort()
            # 准备中的同步文件调用不可强杀；有限时等待保留未退出资源供诊断。
            return False if thread_active() else worker.runner.force_stop(timeout)

        supervisor.register(
            task_id, owner_id=owner_id, kind="performance_start_worker",
            request_stop=request_stop, wait=wait,
            is_running=lambda: (thread_active() or shutdown.is_running()
                                or worker.runner.is_running()),
            force_stop=force_stop, error_type=shutdown.get_error_type,
        )
        return task_id

    def stop_mobileperf(self):
        """在后台请求 MobilePerf 停止，避免等待子进程时阻塞 GUI。"""
        if self.starting:
            self.cancel_start()
            return
        if self._frame._stopping:
            return
        if not self._frame._runner.is_running():
            self._mark_runner_finished()
            return
        self._frame._stopping = True
        self._frame._run_cancel_requested = True
        self._frame._library_controller.request_cancel()
        self._frame.log_received.emit("INFO", tr("Stopping mobileperf and generating report..."))
        self._frame._poll_timer.stop()
        self._update_progress()
        self._frame.start_btn.setEnabled(False)
        self._frame.stop_btn.setEnabled(False)
        self._set_status(tr("Stopping"), "stopping")
        self._frame._stop_thread = threading.Thread(
            target=self._stop_runner_worker,
            args=(
                self._frame._runner,
                alive_signal_emitter(self._frame, "log_received", "ERROR"),
                alive_signal_emitter(self._frame, "runner_finished"),
            ),
            name="adblab-mobileperf-stop",
            daemon=True,
        )
        self._frame._stop_thread.start()

    @staticmethod
    def _stop_runner_worker(runner, error_callback, finished_callback):
        try:
            runner.stop()
        except Exception as exc:
            error_callback(tr('Stop failed: {value0}').format(value0=exc))
        finally:
            finished_callback()

    def _poll_runner(self):
        if self.starting:
            return
        self._update_progress()
        if self._frame._runner.is_running():
            return
        self._mark_runner_finished()

    def _on_runner_finished(self):
        self._mark_runner_finished()

    def _mark_runner_finished(self):
        if self.starting:
            return
        frame = self._frame
        factory = getattr(type(frame._runner), "freeze_result_query", None)
        if (factory is not None and not frame._runner.is_running()
                and not frame._runner_finished_handled):
            # 冻结归属不做 I/O，先解锁交互，再由受监督任务发现附件和读取图表。
            query = frame._runner.freeze_result_query()
            frame._result_loader.submit(
                query, active=frame._library_controller._active,
                exit_code=frame._runner.last_exit_code,
                had_config=frame._runner.last_config is not None,
                cancelled_run=frame._run_cancel_requested,
            )
            frame._runner_finished_handled = True
            frame._stopping = False
            frame._poll_timer.stop()
            frame._run_started_at = None
            if not frame._closing:
                self._set_running(False)
                frame.chart_status.setText(tr("Loading chart…"))
            return
        # 注入的旧 runner 未提供冻结快照接口时保留同步兼容边界。
        self._frame._library_controller.finish()
        if self._frame._closing or self._frame._runner_finished_handled:
            return
        if self._frame._runner.is_running():
            # 停止线程结束不代表采集进程退出；保留原会话并恢复停止入口。
            # 非停止流程的晚到完成信号不得改变当前运行的状态。
            if self._frame._stopping:
                self._frame._stopping = False
                self._set_running(True)
                self._set_status(tr("Stop failed"), "warning")
                self._frame.log_received.emit(
                    "ERROR", tr("MobilePerf is still running. Click Stop to retry.")
                )
                self._frame._poll_timer.start()
            return
        self._frame._runner_finished_handled = True
        self._frame._stopping = False
        self._frame._poll_timer.stop()
        self._frame._run_started_at = None
        artifact_error = False
        result_dir = ""
        report_file = ""
        # 输出目录可能在运行结束时失联；探测失败也必须释放配置锁和停止计时器。
        try:
            result_dir = self._frame._runner.latest_result_dir() or ""
        except OSError:
            artifact_error = True
        try:
            if artifact_error:
                # 首次目录读取失败时仍保留独立重试机会；正常结果只使用一次目录快照。
                report_file = self._frame._runner.latest_report_file() or ""
            elif result_dir:
                report_file = self._frame._runner.latest_report_file(result_dir=result_dir) or ""
        except OSError:
            artifact_error = True
        self._present_finished_result(
            PerformanceArtifacts(result_dir, report_file, artifact_error),
            getattr(self._frame._runner, "last_config", None) is not None,
            getattr(self._frame._runner, "last_exit_code", None), self._frame._run_cancel_requested,
        )

    def _present_finished_result(self, artifacts, had_config, exit_code, cancelled_run):
        """只展示后台验证过的附件；图表解析失败不改变采集业务终态。"""
        result_dir, report_file, artifact_error = (
            artifacts.result_dir, artifacts.report_file, artifacts.error,
        )
        self._frame._last_result_root = result_dir
        self._frame._update_result_action()
        if artifact_error:
            self._set_running(False)
            self._frame._set_progress(min(99, self._frame.progress_bar.value()))
            self._frame.log_received.emit("WARNING", tr("采集已结束，结果可能不完整。"))
            self._set_status(tr("Warning"), "warning")
            return

        if cancelled_run:
            self._set_running(False)
            self._frame._set_progress(min(99, self._frame.progress_bar.value()))
            self._set_status(tr("已停止"), "cancelled")
            return

        # 保留既有调用方依赖的轻量启动前界面契约；真实采集总会记录 last_config。
        if not had_config:
            self._frame._set_progress(100)
            if report_file:
                self._frame.log_received.emit(
                    "SUCCESS",
                    tr('MobilePerf ended, report generated: {value0}').format(value0=report_file),
                )
            elif result_dir:
                self._frame.log_received.emit(
                    "WARNING",
                    tr('MobilePerf ended, report not found in: {value0}').format(value0=result_dir),
                )
            else:
                self._frame.log_received.emit(
                    "WARNING", tr("MobilePerf ended, result directory not found")
                )
            self._set_running(False)
            return

        successful_exit = exit_code == 0
        if report_file and successful_exit:
            self._frame.log_received.emit(
                "SUCCESS",
                tr("MobilePerf ended, report generated: {value0}").format(value0=report_file),
            )
            self._set_running(False)
            self._frame._set_progress(100)
            self._set_status(tr("Completed"), "completed")
            return

        self._set_running(False)
        self._frame._set_progress(min(99, self._frame.progress_bar.value()))
        if report_file:
            self._frame.log_received.emit(
                "WARNING",
                tr(
                    "MobilePerf exited with code {value0}; report may be incomplete: {value1}"
                ).format(value0=exit_code, value1=report_file),
            )
            self._set_status(tr("Warning"), "warning")
        elif exit_code not in (None, 0):
            self._frame.log_received.emit(
                "ERROR",
                tr("MobilePerf failed with exit code {value0}; no report was generated").format(
                    value0=exit_code
                ),
            )
            self._set_status(tr("Failed"), "failed")
        elif result_dir:
            self._frame.log_received.emit(
                "WARNING",
                tr('MobilePerf ended, report not found in: {value0}').format(value0=result_dir),
            )
            self._set_status(tr("Warning"), "warning")
        else:
            self._frame.log_received.emit(
                "WARNING", tr("MobilePerf ended, result directory not found")
            )
            self._set_status(tr("Warning"), "warning")

    def _set_running(self, running: bool):
        self._frame.start_btn.setEnabled(
            not running and self._frame._can_operate_device()
        )
        self._frame.stop_btn.setEnabled(running)
        self._frame._set_configuration_enabled(not running)
        self._set_status(tr("Running") if running else tr("Idle"), "running" if running else "idle")
        if not running:
            self._frame._flush_pending_logs()

    def _set_status(self, text: str, state: str):
        self._frame._status_state = state
        self._frame.status_label.setText(text)
        self._apply_status_style()

    def _apply_status_style(self):
        color_key = {
            "running": "LOG_SUCCESS",
            "stopping": "LOG_WARNING",
            "completed": "LOG_SUCCESS",
            "warning": "LOG_WARNING",
            "failed": "LOG_ERROR",
            "idle": "TEXT_SECONDARY",
        }.get(self._frame._status_state, "TEXT_SECONDARY")
        weight = (
            "bold"
            if self._frame._status_state
            in {"running", "stopping", "completed", "warning", "failed"}
            else "normal"
        )
        self._frame.status_label.setStyleSheet(
            f"color: {BaseStyles.color(color_key)}; font-weight: {weight};"
        )
        self._frame.progress_display.refresh(
            self._frame._status_state,
            active=self._frame._configuration_locked and not self._frame._closing,
        )
        self._frame.session_state_changed.emit()

    def _update_progress(self):
        if self._frame._run_started_at is None or self._frame._run_duration_seconds <= 0:
            return
        elapsed = max(0.0, time.monotonic() - self._frame._run_started_at)
        self._frame._run_elapsed_seconds = int(elapsed)
        # 时间只是估算，进程退出到结果确认之间也不能提前显示 100%。
        percent = min(99, int((elapsed / self._frame._run_duration_seconds) * 100))
        self._frame._set_progress(percent)
