"""提供 MobilePerf 启停控制、状态展示和 Perfetto 入口。"""

from __future__ import annotations

import os
import re
import threading

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)
from qfluentwidgets import BodyLabel, CardWidget, InfoBadge, InfoLevel, ProgressBar

from adblab.application.supervision import ThreadedShutdownTask
from core.settings_manager import AppSettings
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    safe_disconnect,
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
from gui.styles.typography import FontRole
from gui.widgets.preset_spin_box import StrictIntComboBox, StrictIntLineEdit
from models.base.focus_detector import detect_current_package
from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner

__all__ = ["CONFIG_HINTS", "MONKEY_PERCENT_FIELDS", "PerformancePage"]


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


class PerformancePage(QWidget):
    """嵌入 System 分区，针对一个稳定设备会话管理 MobilePerf 采集。"""

    LOG_RENDER_DEBOUNCE_MS = 50
    IMMEDIATE_LOG_BATCH_SIZE = 100
    MAX_PENDING_LOG_ROWS = 2000
    log_received = Signal(str, str)
    runner_finished = Signal()
    dispose_ready = Signal(object)

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
    progress_bar: ProgressBar
    start_btn: QPushButton
    stop_btn: QPushButton
    monkey_throttle_combo: StrictIntComboBox
    monkey_seed_edit: StrictIntLineEdit
    monkey_pct_combos: dict[str, StrictIntComboBox]
    perfetto_action: QAction
    serialnum_label: BodyLabel
    # 页头控件由 PerformanceLauncherForm 注入；此处声明类型供 pyright 与
    # 主题刷新方法稳定引用（视觉重设计新增，不影响任何既有契约）。
    header_card: CardWidget
    dialog_title: BodyLabel
    dialog_subtitle: BodyLabel
    status_badge: InfoBadge

    def __init__(self, device_ip: str = "", package_name: str = "", parent=None):
        super().__init__(parent)
        self._form_controller = PerformanceLauncherForm(self)
        self._run_controller = PerformanceLauncherRun(self)
        self._log_controller = PerformanceLauncherLog(self)
        self.device_ip = device_ip
        self._device_connected = bool(device_ip)
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
        self._view_active = False
        self._dispose_ready_state = False
        self._dispose_emitted = False
        self._disposing_package_workers: list[CurrentPackageWorker] = []
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.timeout.connect(self._flush_pending_logs)
        self._theme_sync_timer = QTimer(self)
        self._theme_sync_timer.setInterval(750)
        self._theme_sync_timer.timeout.connect(self._sync_theme_state)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_runner)
        self._dispose_poll_timer = QTimer(self)
        self._dispose_poll_timer.setSingleShot(True)
        self._dispose_poll_timer.timeout.connect(self._poll_dispose_ready)
        self.setWindowTitle(f"Performance - {device_ip}" if device_ip else "Performance")
        self.setWindowIcon(get_themed_icon("speedometer.svg"))
        self.setMinimumSize(0, 0)
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

    def prepare_for_workspace(self) -> None:
        """让主工作区成为唯一纵向滚动所有者。"""

        self._form_controller.use_workspace_scroll_container()

    def activate(self, payload=None) -> None:
        """恢复页面外观刷新；已运行采集不会因返回页面而重启。"""

        if self._closing:
            return
        self._view_active = True
        if isinstance(payload, dict):
            package = str(payload.get("package_name", "") or "").strip()
            if package and not self._configuration_locked:
                self.package_edit.setText(package)
        self._sync_theme_state(force=True)
        self._theme_sync_timer.start()
        self.show()

    def deactivate(self, _reason: str = "navigation") -> None:
        """停止隐藏页的主题轮询，但允许采集和进度轮询继续。"""

        self._view_active = False
        self._theme_sync_timer.stop()

    def set_device_connected(self, connected: bool) -> None:
        """显示固定设备会话的在线状态，并阻止新的离线采集请求。"""

        self._device_connected = bool(connected and self.device_ip)
        running = self._runner.is_running()
        self.start_btn.setEnabled(self._device_connected and not running and not self._closing)
        self.get_package_btn.setEnabled(
            self._device_connected
            and not running
            and self._package_worker is None
            and not self._closing
        )
        self.status_badge.setText("Ready" if self._device_connected else "Device offline")
        self.status_badge.setLevel(
            InfoLevel.SUCCESS if self._device_connected else InfoLevel.ERROR
        )
        if not self._device_connected and not running:
            self._set_status("Device offline", "failed")

    def request_dispose(self, _reason: str = "user") -> bool:
        """请求异步停止页面资源，并在真实资源归零后通知宿主。"""

        if self._dispose_ready_state:
            return True
        if not self._closing:
            self._begin_dispose()
        self._poll_dispose_ready()
        return self._dispose_ready_state

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
        self.chart_view.set_series({name: series.values for name, series in metrics.items()})

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
        if not self.device_ip or not self._device_connected:
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
            FluentMessageBox.information(
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
        self._max_log_lines = self._configured_log_max_lines()
        self._flush_pending_logs()
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        # 视觉重设计：页头卡片由 CardWidget 自绘制随主题切换，徽标按 device_ip 刷新。
        if hasattr(self, "header_card"):
            self.dialog_title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
            self.dialog_subtitle.setFont(BaseStyles.font_for_role(FontRole.UI))
            self.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
            has_device = bool(self.device_ip and self._device_connected)
            self.status_badge.setText("Ready" if has_device else "No device")
            self.status_badge.setLevel(InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION)
        self.log_view.document().setMaximumBlockCount(self._max_log_lines)
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

    @staticmethod
    def _theme_signature() -> tuple[str, str, int, int]:
        return (
            BaseStyles.resolved_theme(),
            BaseStyles.DEFAULT_FONT_FAMILY,
            int(BaseStyles.DEFAULT_FONT_SIZE),
            int(BaseStyles.LOG_FONT_SIZE_VAR),
        )

    def _sync_theme_state(self, force: bool = False):
        if self._closing:
            return
        current_signature = self._theme_signature()
        if force or current_signature != self._applied_theme_signature:
            # 定时兜底可补齐一次漏发的主题信号；页面壳层由工作区统一刷新。
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

    def _begin_dispose(self) -> None:
        """隔离界面回调并发起停止，页面对象保留到所有资源退出。"""

        self._closing = True
        self._view_active = False
        self._log_flush_timer.stop()
        self._theme_sync_timer.stop()
        self._pending_log_rows = []
        if self._runner.is_running() and not self._stopping:
            if self._shutdown_registered:
                # 应用关闭时 runner 已交给全局监督器；这里只发出轻量停止意图，
                # 避免再创建一个线程并发调用同一个 MobilePerfRunner.stop()。
                self._runner.request_stop()
            else:
                self.stop_mobileperf()
        package_worker = self._package_worker
        if package_worker is not None:
            self._package_worker = None
            if package_worker.isRunning():
                package_worker.requestInterruption()
                safe_disconnect(package_worker.package_ready, self._on_current_package)
                safe_disconnect(package_worker.log_ready, self.log_received.emit)
                package_worker.setParent(None)
                self._disposing_package_workers.append(package_worker)
            else:
                package_worker.deleteLater()
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)

    def _poll_dispose_ready(self) -> None:
        """等待 runner、停止线程和包名查询线程全部真实退出。"""

        retained: list[CurrentPackageWorker] = []
        for worker in self._disposing_package_workers:
            if worker.isRunning():
                retained.append(worker)
            else:
                worker.deleteLater()
        self._disposing_package_workers = retained
        stop_thread = self._stop_thread
        resources_running = bool(
            retained
            or self._runner.is_running()
            or (stop_thread is not None and stop_thread.is_alive())
        )
        if resources_running:
            self._dispose_poll_timer.start(50)
            return
        self._poll_timer.stop()
        safe_disconnect(self.log_received, self._append_log)
        safe_disconnect(self.runner_finished, self._on_runner_finished)
        self._dispose_ready_state = True
        if not self._dispose_emitted:
            self._dispose_emitted = True
            self.dispose_ready.emit(self.property("session_generation"))

    def closeEvent(self, event):
        """顶层兼容关闭也走非阻塞页面销毁协议。"""

        if self.request_dispose("widget_close"):
            event.accept()
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()
