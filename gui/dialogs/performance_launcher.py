"""提供 MobilePerf 启停控制、状态展示和 Perfetto 入口。"""

from __future__ import annotations

import os
import re
import threading

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QWidget,
)
from qfluentwidgets import InfoLevel

from adblab.application.supervision import ThreadedShutdownTask
from core.settings_manager import AppSettings
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    safe_disconnect,
    wait_for_thread_later,
)
from gui.dialogs.performance_launcher_form import (
    CONFIG_HINTS,
    MONKEY_PERCENT_FIELDS,
    PerformanceLauncherForm,
)
from gui.dialogs.performance_launcher_log import PerformanceLauncherLog
from gui.dialogs.performance_launcher_run import PerformanceLauncherRun
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from gui.widgets.preset_spin_box import StrictIntComboBox, StrictIntLineEdit
from models.base.focus_detector import detect_current_package
from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner

__all__ = ["CONFIG_HINTS", "MONKEY_PERCENT_FIELDS", "PerformanceLauncherDialog"]


class CurrentPackageWorker(QThread):
    package_ready = Signal(str)
    log_ready = Signal(str, str)

    def __init__(self, device_ip: str):
        super().__init__()
        self.device_ip = device_ip

    def run(self):
        try:
            result = detect_current_package(self.device_ip)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.log_ready.emit("ERROR", f"Get current package failed: {exc}")
            return
        if self.isInterruptionRequested():
            return
        if result.get("success") and result.get("package_name"):
            self.package_ready.emit(result["package_name"])
        else:
            self.log_ready.emit(
                "WARNING",
                result.get("error") or "No foreground package found",
            )


class PerformanceLauncherDialog(QDialog):
    """针对一个已选设备启动和管理 MobilePerf 采集。"""

    LOG_RENDER_DEBOUNCE_MS = 50
    IMMEDIATE_LOG_BATCH_SIZE = 100
    MAX_PENDING_LOG_ROWS = 2000
    log_received = Signal(str, str)
    runner_finished = Signal()

    # 表单与动作区控件在控制器中创建，此处提供类级类型声明供跨控制器解析。
    log_view: QPlainTextEdit
    save_path_edit: QLineEdit
    get_package_btn: QPushButton
    package_edit: QLineEdit
    frequency_input: StrictIntComboBox
    timeout_input: StrictIntComboBox
    dumpheap_input: StrictIntComboBox
    monkey_check: QCheckBox
    exception_edit: QLineEdit
    phone_log_edit: QLineEdit
    result_action: QAction
    progress_bar: QProgressBar
    monkey_throttle_combo: StrictIntComboBox
    monkey_seed_edit: StrictIntLineEdit
    monkey_pct_combos: dict[str, StrictIntComboBox]
    perfetto_action: QAction
    serialnum_label: QLabel
    # 页头控件由 PerformanceLauncherForm 注入；此处声明类型供 pyright 与
    # 主题刷新方法稳定引用（视觉重设计新增，不影响任何既有契约）。
    header_card: QFrame
    dialog_title: QLabel
    dialog_subtitle: QLabel
    status_badge: QLabel

    def __init__(self, device_ip: str = "", package_name: str = "", parent=None):
        super().__init__(parent)
        self._form_controller = PerformanceLauncherForm(self)
        self._run_controller = PerformanceLauncherRun(self)
        self._log_controller = PerformanceLauncherLog(self)
        self.device_ip = device_ip
        self._runner = MobilePerfRunner()
        self._package_worker: CurrentPackageWorker | None = None
        self._stop_thread: threading.Thread | None = None
        self._shutdown_registered = False
        self._last_result_root = ""
        self._closing = False
        self._runner_finished_handled = True
        self._stopping = False
        self._status_state = "idle"
        self._run_started_at: float | None = None
        self._run_duration_seconds = 0
        self._max_log_lines = self._configured_log_max_lines()
        self._pending_log_rows: list[str] = []
        self._pending_log_scroll_to_bottom = False
        self._applied_theme_signature: tuple[str, str, int, int] | None = None
        self._configuration_locked = False
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.timeout.connect(self._flush_pending_logs)
        self._theme_sync_timer = QTimer(self)
        self._theme_sync_timer.setInterval(750)
        self._theme_sync_timer.timeout.connect(self._sync_theme_state)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_runner)
        self.setWindowTitle(f"Performance - {device_ip}" if device_ip else "Performance")
        self.setWindowIcon(get_themed_icon("speedometer.svg"))
        self.setMinimumSize(880, 660)
        self.resize(1200, 900)
        self.setModal(False)
        self.log_received.connect(self._append_log)
        self.runner_finished.connect(self._on_runner_finished)

        self._build_ui(package_name)
        # P3 图表视图：注入到双视图栈，运行结束后由 _mark_runner_finished 加载指标。
        from gui.widgets.perf_chart_view import PerfChartView

        self.chart_view = PerfChartView(self)
        chart_stack = getattr(self, "_chart_stack", None)
        if chart_stack is not None:
            chart_stack.addWidget(self.chart_view)
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._theme_sync_timer.start()

    # ── 表单控制器委托 wrapper ──────────────────────────────────────────

    def _build_ui(self, package_name):
        return self._form_controller._build_ui(package_name)

    def _load_chart_metrics(self, result_dir: str) -> None:
        """解析结果目录 CSV 并全量替换图表曲线（P3）。"""

        from services.perf_chart_data import load_result_metrics

        if not result_dir:
            self.chart_view.clear()
            return
        metrics = load_result_metrics(result_dir)
        self.chart_view.set_series(
            {name: series.values for name, series in metrics.items()}
        )

    def _build_config_section(self, package_name):
        return self._form_controller._build_config_section(package_name)

    def _build_monkey_row(self):
        return self._form_controller._build_monkey_row()

    def _inline_label(self, text, tooltip=""):
        return self._form_controller._inline_label(text, tooltip)

    @staticmethod
    def _unit_label(text, semantic_name=None):
        return PerformanceLauncherForm._unit_label(text, semantic_name)

    def _monkey_option_widgets(self):
        return self._form_controller._monkey_option_widgets()

    def _on_monkey_enabled_changed(self, checked):
        return self._form_controller._on_monkey_enabled_changed(checked)

    @staticmethod
    def _numeric_editor(field):
        return PerformanceLauncherForm._numeric_editor(field)

    def _update_monkey_total(self, *_args):
        return self._form_controller._update_monkey_total(*_args)

    def _collect_monkey_config(self):
        return self._form_controller._collect_monkey_config()

    def _add_config_row(self, grid, row, key, field, hint):
        return self._form_controller._add_config_row(grid, row, key, field, hint)

    @staticmethod
    def _apply_hint(widget, hint):
        return PerformanceLauncherForm._apply_hint(widget, hint)

    def _row_widget(self, *widgets):
        return self._form_controller._row_widget(*widgets)

    def _build_log_view(self):
        return self._form_controller._build_log_view()

    def _build_actions(self):
        return self._form_controller._build_actions()

    def _enabled_numeric_inputs(self):
        return self._form_controller._enabled_numeric_inputs()

    def _all_numeric_inputs(self):
        return self._form_controller._all_numeric_inputs()

    def _set_configuration_enabled(self, enabled):
        return self._form_controller._set_configuration_enabled(enabled)

    def _commit_numeric_inputs(self):
        return self._form_controller._commit_numeric_inputs()

    def _sync_perfetto_button(self):
        return self._form_controller._sync_perfetto_button()

    def _sync_result_button(self):
        return self._form_controller._sync_result_button()

    # ── 运行控制器委托 wrapper ──────────────────────────────────────────

    def start_mobileperf(self):
        return self._run_controller.start_mobileperf()

    def stop_mobileperf(self):
        return self._run_controller.stop_mobileperf()

    @staticmethod
    def _stop_runner_worker(runner, error_callback, finished_callback):
        return PerformanceLauncherRun._stop_runner_worker(runner, error_callback, finished_callback)

    def _poll_runner(self):
        return self._run_controller._poll_runner()

    def _on_runner_finished(self):
        return self._run_controller._on_runner_finished()

    def _mark_runner_finished(self):
        return self._run_controller._mark_runner_finished()

    def _set_running(self, running):
        return self._run_controller._set_running(running)

    def _set_status(self, text, state):
        return self._run_controller._set_status(text, state)

    def _apply_status_style(self):
        return self._run_controller._apply_status_style()

    def _update_progress(self):
        return self._run_controller._update_progress()

    # ── 日志控制器委托 wrapper ──────────────────────────────────────────

    def _append_log(self, level, message):
        return self._log_controller._append_log(level, message)

    def _flush_pending_logs(self):
        return self._log_controller._flush_pending_logs()

    def _render_log_rows(self, rows):
        return self._log_controller._render_log_rows(rows)

    @staticmethod
    def _format_log_line(level, message):
        return PerformanceLauncherLog._format_log_line(level, message)

    @staticmethod
    def _configured_log_max_lines():
        return PerformanceLauncherLog._configured_log_max_lines()

    # ── Perfetto 与结果入口 ─────────────────────────────────────────────

    def _trigger_open_perfetto(self, _checked: bool = False) -> None:
        self.open_perfetto()

    def _trigger_open_result(self, _checked: bool = False) -> None:
        self.open_result()

    def _device_tag(self) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", self.device_ip.strip() or "unknown")

    def _with_device_suffix(self, path: str) -> str:
        path = self._normalize_local_path(path)
        if not path:
            return ""
        tag = self._device_tag()
        if os.path.basename(os.path.normpath(path)) == tag:
            return path
        return self._normalize_local_path(os.path.join(path, tag))

    def _default_save_path(self) -> str:
        base = AppSettings.instance().save_directory
        return self._normalize_local_path(os.path.join(base, "mobileperf", self._device_tag()))

    @staticmethod
    def _normalize_local_path(path: str) -> str:
        path = str(path or "").strip()
        if not path:
            return ""
        return os.path.normpath(path)

    def _pick_save_path(self):
        current = self.save_path_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select MobilePerf Result Directory",
            current if os.path.isdir(current) else AppSettings.instance().save_directory,
        )
        if selected:
            self.save_path_edit.setText(self._with_device_suffix(selected))

    def fetch_current_package(self):
        if self._package_worker and self._package_worker.isRunning():
            return
        if not self.device_ip:
            self.log_received.emit("WARNING", "No device selected")
            return
        self.get_package_btn.setEnabled(False)
        self.log_received.emit("INFO", "Fetching current package...")
        worker = CurrentPackageWorker(self.device_ip)
        worker.package_ready.connect(self._on_current_package)
        worker.log_ready.connect(self.log_received.emit)
        worker.finished.connect(
            alive_callback(self, "_on_package_worker_finished", worker),
            Qt.ConnectionType.QueuedConnection,
        )
        self._package_worker = worker
        worker.start()

    def _on_current_package(self, package_name: str):
        if self._configuration_locked or self._closing:
            return
        self.package_edit.setText(package_name)
        self.log_received.emit("SUCCESS", f"Current package: {package_name}")

    def _on_package_worker_finished(self, worker: CurrentPackageWorker):
        if self._package_worker is worker:
            self._package_worker = None
        if self.get_package_btn:
            self.get_package_btn.setEnabled(not self._configuration_locked and not self._closing)
        worker.deleteLater()

    def build_config(self) -> MobilePerfRunConfig:
        return MobilePerfRunConfig(
            device_id=self.device_ip.strip(),
            package=self.package_edit.text().strip(),
            frequency_seconds=self.frequency_input.value(),
            timeout_minutes=self.timeout_input.value(),
            dumpheap_minutes=self.dumpheap_input.value(),
            monkey_enabled=self.monkey_check.isChecked(),
            monkey_config=self._collect_monkey_config(),
            exception_keywords=self.exception_edit.text().split(";"),
            phone_log_paths=self.phone_log_edit.text().split(";"),
            save_path=self._with_device_suffix(self.save_path_edit.text()),
            mailbox="",
        )

    def open_result(self):
        path = self._last_result_root
        if not path or not os.path.isdir(path):
            QMessageBox.information(
                self,
                "Result Not Available",
                "No MobilePerf result is available yet.",
            )
            self._update_result_action()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _update_result_action(self):
        self.result_action.setEnabled(
            bool(self._last_result_root and os.path.isdir(self._last_result_root))
        )

    @staticmethod
    def open_perfetto():
        QDesktopServices.openUrl(QUrl("https://ui.perfetto.dev/"))

    def _set_progress(self, percent: int):
        value = max(0, min(100, int(percent)))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{value}%")

    def _reset_progress(self):
        self._run_started_at = None
        self._run_duration_seconds = 0
        self._set_progress(0)

    def _apply_monkey_control_widths(self):
        if not hasattr(self, "monkey_throttle_combo"):
            return
        metrics = self.fontMetrics()
        throttle_width = metrics.horizontalAdvance("2000") + 54
        seed_width = metrics.horizontalAdvance("1000000") + 28
        percent_width = metrics.horizontalAdvance("100") + 50
        self.monkey_throttle_combo.setMinimumWidth(max(92, throttle_width))
        self.monkey_seed_edit.setMinimumWidth(max(98, seed_width))
        for combo in self.monkey_pct_combos.values():
            combo.setMinimumWidth(max(72, percent_width))

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self)
        c = BaseStyles.color
        r = BaseStyles.RADIUS_MD
        group_title_margin = BaseStyles.group_box_title_margin()
        self._max_log_lines = self._configured_log_max_lines()
        self._flush_pending_logs()
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        # 视觉重设计：页头卡片由 CardWidget 自绘制随主题切换，徽标按 device_ip 刷新。
        if hasattr(self, "header_card"):
            self.dialog_title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
            self.dialog_subtitle.setFont(BaseStyles.font_for_role(FontRole.UI))
            self.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
            has_device = bool(self.device_ip)
            self.status_badge.setText("Ready" if has_device else "No device")
            self.status_badge.setLevel(
                InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION
            )
        self.log_view.document().setMaximumBlockCount(self._max_log_lines)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {c("PANEL_BG")};
                color: {c("TEXT_PRIMARY")};
            }}
            QGroupBox#performanceConfig {{
                background-color: {c("INPUT_BG")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {r}px;
                margin-top: {group_title_margin}px;
                padding: 10px 10px 8px 10px;
                color: {c("TEXT_PRIMARY")};
                font-weight: bold;
            }}
            QGroupBox#performanceConfig::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 10px;
                color: {c("GROUP_TITLE_COLOR")};
            }}
            QProgressBar#performanceProgress {{
                background-color: {c("INPUT_BG")};
                color: {c("TEXT_PRIMARY")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {BaseStyles.RADIUS_MD}px;
                text-align: center;
            }}
            QProgressBar#performanceProgress::chunk {{
                background-color: {c("LOG_SUCCESS")};
                border-radius: {BaseStyles.RADIUS_MD - 1}px;
            }}
            QWidget#inlineRow,
            QWidget#inlineRow QLabel {{
                color: {c("TEXT_PRIMARY")};
                background-color: transparent;
            }}
            """
        )
        self._apply_widget_fonts()
        self._apply_status_style()
        if hasattr(self, "monkey_total_label"):
            self._update_monkey_total()
            self._apply_monkey_control_widths()
        for button in self.findChildren(QPushButton):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(get_themed_icon(icon_name))
        self.perfetto_action.setIcon(get_themed_icon("speedometer.svg"))
        self.result_action.setIcon(get_themed_icon("folder-open.svg"))
        self._applied_theme_signature = self._theme_signature()

    def _apply_widget_fonts(self):
        ui_font = BaseStyles.font_for_role(FontRole.UI)
        mono_font = BaseStyles.font_for_role(FontRole.MONO)
        log_font = BaseStyles.font_for_role(FontRole.LOG)
        self.setFont(ui_font)
        for widget in self.findChildren(QWidget):
            widget.setFont(ui_font)
        for widget in (
            self.package_edit,
            self.exception_edit,
            self.phone_log_edit,
            self.save_path_edit,
            self.serialnum_label,
        ):
            widget.setFont(mono_font)
        # 加粗字段标签：字体遍历会覆盖 bold，这里按 objectName 补回。
        for label in self.findChildren(QWidget):
            if label.objectName() in ("fieldLabel", "onlineDeviceLabel"):
                font = label.font()
                font.setBold(True)
                label.setFont(font)
        self.log_view.setFont(log_font)
        self.log_view.viewport().setFont(log_font)
        self.log_view.document().setDefaultFont(log_font)
        log_height = max(72, min(110, QFontMetrics(log_font).height() * 4 + 12))
        self.log_view.setFixedHeight(log_height)
        progress_height = QFontMetrics(ui_font).height() + 10
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setMinimumHeight(
            max(22, self.progress_bar.sizeHint().height(), progress_height)
        )

    @staticmethod
    def _theme_signature() -> tuple[str, str, int, int]:
        return (
            BaseStyles.current_theme(),
            BaseStyles.DEFAULT_FONT_FAMILY,
            int(BaseStyles.DEFAULT_FONT_SIZE),
            int(BaseStyles.LOG_FONT_SIZE_VAR),
        )

    def _sync_theme_state(self, force: bool = False):
        if self._closing:
            return
        current_signature = self._theme_signature()
        if force or current_signature != self._applied_theme_signature:
            self._apply_theme(BaseStyles.current_theme())

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        """分别注册包名查询线程和 MobilePerf 进程的有限时关闭任务。"""
        task_ids = []
        package_worker = self._package_worker
        if package_worker is not None and package_worker.isRunning():
            package_handle = QThreadGroupShutdownTask([package_worker])
            package_task_id = f"{task_prefix}-package-worker"
            supervisor.register(
                package_task_id,
                owner_id=owner_id,
                kind="performance_package_worker",
                request_stop=package_handle.request_stop,
                wait=package_handle.wait,
                is_running=package_handle.is_running,
            )
            task_ids.append(package_task_id)

        stop_thread = self._stop_thread
        runner_active = self._runner.is_running()
        if runner_active or (stop_thread is not None and stop_thread.is_alive()):
            runner_task_id = f"{task_prefix}-mobileperf"
            if stop_thread is not None and stop_thread.is_alive():

                def request_runner_stop():
                    self._runner.request_stop()

                def wait_runner(timeout: float) -> bool:
                    stop_thread.join(max(0.0, float(timeout)))
                    return not stop_thread.is_alive() and not self._runner.is_running()

                def runner_running() -> bool:
                    return stop_thread.is_alive() or self._runner.is_running()

                supervisor.register(
                    runner_task_id,
                    owner_id=owner_id,
                    kind="mobileperf_runner",
                    request_stop=request_runner_stop,
                    wait=wait_runner,
                    is_running=runner_running,
                    force_stop=self._runner.force_stop,
                )
            else:
                runner_handle = ThreadedShutdownTask(
                    self._runner.stop,
                    name="adblab-mobileperf-stop",
                )
                supervisor.register(
                    runner_task_id,
                    owner_id=owner_id,
                    kind="mobileperf_runner",
                    request_stop=runner_handle.request_stop,
                    wait=runner_handle.wait,
                    is_running=runner_handle.is_running,
                    force_stop=self._runner.force_stop,
                    error_type=runner_handle.get_error_type,
                )
            task_ids.append(runner_task_id)

        self._shutdown_registered = bool(task_ids)
        return tuple(task_ids)

    def closeEvent(self, event):
        """停止界面定时器并断开信号，资源等待由已注册的关闭任务接管。"""
        self._closing = True
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        if self._theme_sync_timer.isActive():
            self._theme_sync_timer.stop()
        self._pending_log_rows = []
        self._poll_timer.stop()
        if self._runner.is_running() is True and not self._shutdown_registered:
            self.stop_mobileperf()
        if self._package_worker and self._package_worker.isRunning():
            worker = self._package_worker
            self._package_worker = None
            worker.requestInterruption()
            safe_disconnect(worker.package_ready, self._on_current_package)
            safe_disconnect(worker.log_ready, self.log_received.emit)
            worker.setParent(None)
            if not self._shutdown_registered:
                wait_for_thread_later(worker, 2000)
        safe_disconnect(self.log_received, self._append_log)
        safe_disconnect(self.runner_finished, self._on_runner_finished)
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        super().closeEvent(event)
