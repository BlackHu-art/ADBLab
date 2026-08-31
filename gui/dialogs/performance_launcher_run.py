"""提供 MobilePerf 启停、运行状态展示与进度更新。"""

from __future__ import annotations

import threading
import time

from PySide6.QtWidgets import QMessageBox

from gui.dialogs.lifecycle import alive_signal_emitter
from gui.styles import BaseStyles


class PerformanceLauncherRun:
    """组合进 PerformanceLauncherDialog 的运行控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def start_mobileperf(self):
        if not self._frame._commit_numeric_inputs():
            return
        config = self._frame.build_config()
        if not config.package:
            QMessageBox.warning(
                self._frame,
                "Package Required",
                "Please enter a package name.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        if config.monkey_enabled and config.monkey_config.total_percentage != 100:
            self._frame.log_received.emit(
                "WARNING",
                f"Monkey event percentages sum to {config.monkey_config.total_percentage}"
                f"%, not 100%; continuing with this distribution.",
            )
        self._frame._last_result_root = ""
        self._frame._update_result_action()
        self._frame._runner_finished_handled = False
        self._frame.log_received.emit("INFO", "Starting mobileperf")
        try:
            self._frame._runner.start(
                config,
                on_log=alive_signal_emitter(self._frame, "log_received", "RAW"),
                on_finished=alive_signal_emitter(self._frame, "runner_finished"),
            )
        except Exception as exc:
            self._frame.log_received.emit("ERROR", f"Start failed: {exc}")
            self._frame._runner_finished_handled = True
            self._frame._reset_progress()
            self._set_running(False)
            return
        self._frame._run_started_at = time.monotonic()
        self._frame._run_duration_seconds = max(1, int(config.timeout_minutes) * 60)
        self._frame._set_progress(0)
        self._set_running(True)
        self._frame._poll_timer.start()

    def stop_mobileperf(self):
        """在后台请求 MobilePerf 停止，避免等待子进程时阻塞 GUI。"""
        if self._frame._stopping:
            return
        if not self._frame._runner.is_running():
            self._mark_runner_finished()
            return
        self._frame._stopping = True
        self._frame.log_received.emit("INFO", "Stopping mobileperf and generating report...")
        self._frame._poll_timer.stop()
        self._update_progress()
        self._frame.start_btn.setEnabled(False)
        self._frame.stop_btn.setEnabled(False)
        self._set_status("Stopping", "stopping")
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
            error_callback(f"Stop failed: {exc}")
        finally:
            finished_callback()

    def _poll_runner(self):
        self._update_progress()
        if self._frame._runner.is_running():
            return
        self._mark_runner_finished()

    def _on_runner_finished(self):
        self._mark_runner_finished()

    def _mark_runner_finished(self):
        if self._frame._closing or self._frame._runner_finished_handled:
            return
        self._frame._runner_finished_handled = True
        self._frame._stopping = False
        self._frame._poll_timer.stop()
        self._frame._run_started_at = None
        result_dir = self._frame._runner.latest_result_dir() or ""
        self._frame._last_result_root = result_dir
        # P3：加载静态 CSV 指标到图表视图（空结果保持空态，不阻塞完成流程）。
        loader = getattr(self._frame, "_load_chart_metrics", None)
        if loader is not None:
            try:
                loader(result_dir)
            except Exception:
                pass
        self._frame._update_result_action()
        report_file = self._frame._runner.latest_report_file()
        last_config = getattr(self._frame._runner, "last_config", None)
        exit_code = getattr(self._frame._runner, "last_exit_code", None)

        # 保留既有调用方依赖的轻量启动前界面契约；真实采集总会记录 last_config。
        if last_config is None:
            self._frame._set_progress(100)
            if report_file:
                self._frame.log_received.emit(
                    "SUCCESS",
                    f"MobilePerf ended, report generated: {report_file}",
                )
            elif result_dir:
                self._frame.log_received.emit(
                    "WARNING",
                    f"MobilePerf ended, report not found in: {result_dir}",
                )
            else:
                self._frame.log_received.emit(
                    "WARNING", "MobilePerf ended, result directory not found"
                )
            self._set_running(False)
            return

        successful_exit = exit_code == 0
        if report_file and successful_exit:
            self._frame.log_received.emit(
                "SUCCESS", f"MobilePerf ended, report generated: {report_file}"
            )
            self._set_running(False)
            self._frame._set_progress(100)
            self._set_status("Completed", "completed")
            return

        self._set_running(False)
        self._frame._set_progress(min(99, self._frame.progress_bar.value()))
        if report_file:
            self._frame.log_received.emit(
                "WARNING",
                f"MobilePerf exited with code {exit_code}; report may be incomplete: {report_file}",
            )
            self._set_status("Warning", "warning")
        elif exit_code not in (None, 0):
            self._frame.log_received.emit(
                "ERROR",
                f"MobilePerf failed with exit code {exit_code}; no report was generated",
            )
            self._set_status("Failed", "failed")
        elif result_dir:
            self._frame.log_received.emit(
                "WARNING",
                f"MobilePerf ended, report not found in: {result_dir}",
            )
            self._set_status("Warning", "warning")
        else:
            self._frame.log_received.emit(
                "WARNING", "MobilePerf ended, result directory not found"
            )
            self._set_status("Warning", "warning")

    def _set_running(self, running: bool):
        self._frame.start_btn.setEnabled(not running)
        self._frame.stop_btn.setEnabled(running)
        self._frame._set_configuration_enabled(not running)
        self._set_status("Running" if running else "Idle", "running" if running else "idle")
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

    def _update_progress(self):
        if self._frame._run_started_at is None or self._frame._run_duration_seconds <= 0:
            return
        elapsed = max(0.0, time.monotonic() - self._frame._run_started_at)
        percent = int((elapsed / self._frame._run_duration_seconds) * 100)
        if self._frame._runner.is_running():
            percent = min(99, percent)
        self._frame._set_progress(percent)
