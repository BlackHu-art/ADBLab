"""提供 MobilePerf 启停控制、状态展示和 Perfetto 入口。"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from adblab.application.supervision import ThreadedShutdownTask
from core.settings_manager import AppSettings
from gui.dialogs.lifecycle import QThreadGroupShutdownTask, safe_disconnect, wait_for_thread_later
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from models.base.focus_detector import detect_current_package
from models.mobileperf import MobilePerfMonkeyConfig, MobilePerfRunConfig, MobilePerfRunner

CONFIG_HINTS = {
    "package": (
        "Test process. Example: package=com.alibaba.ailabs.genie.contacts. "
        "Supports multiple processes separated by ';'; if child processes are included, "
        "put the main process first."
    ),
    "frequency": "Collect frequency. Integer, unit: second.",
    "timeout": "Collect timeout. Integer, unit: minute. Example: 72 hours = 4320.",
    "dumpheap_freq": "Dumpheap frequency. Integer, unit: minute.",
    "serialnum": "ADB serialnum comes from the selected device in the window title.",
    "exceptionlog": (
        "Exception log tags checked in logcat. Matching logs are saved to exception.log; "
        "multiple tags are separated by ';'."
    ),
    "monkey": (
        "Monkey test switch. When enabled, Monkey uses the same timeout as "
        "MobilePerf collection and is stopped when the run finishes or Stop is clicked."
    ),
    "save_path": (
        "Test results save path. Avoid spaces. A device-name folder is appended automatically."
    ),
    "phone_log_path": "Device paths pulled to PC when the test ends; multiple paths use ';'.",
}

MONKEY_PERCENT_FIELDS = [
    ("Touch events", "pct_touch", "--pct-touch"),
    ("Motion events", "pct_motion", "--pct-motion"),
    ("Trackball events", "pct_trackball", "--pct-trackball"),
    ("Navigation events", "pct_nav", "--pct-nav"),
    ("Major navigation events", "pct_majornav", "--pct-majornav"),
    ("System key events", "pct_syskeys", "--pct-syskeys"),
    ("App switch events", "pct_appswitch", "--pct-appswitch"),
    ("Any events", "pct_anyevent", "--pct-anyevent"),
    ("Keyboard flip events", "pct_flip", "--pct-flip"),
    ("Pinch/zoom events", "pct_pinchzoom", "--pct-pinchzoom"),
]


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

    def __init__(self, device_ip: str = "", package_name: str = "", parent=None):
        super().__init__(parent)
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
        self.resize(940, 700)
        self.setModal(False)
        self.log_received.connect(self._append_log)
        self.runner_finished.connect(self._on_runner_finished)

        self._build_ui(package_name)
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._theme_sync_timer.start()

    def _build_ui(self, package_name: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_config_section(package_name))
        self.log_view = self._build_log_view()
        root.addWidget(self.log_view, 1)
        root.addLayout(self._build_actions())

    def _build_config_section(self, package_name: str) -> QGroupBox:
        g = QGroupBox("MobilePerf Config")
        g.setObjectName("performanceConfig")
        grid = QGridLayout(g)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

        self.package_edit = QLineEdit(package_name)
        self.package_edit.setObjectName("monoField")
        self.package_edit.setPlaceholderText("com.example.app")
        self.get_package_btn = QPushButton("Get Current Package")
        self.get_package_btn.setIcon(get_themed_icon("target.svg"))
        self.get_package_btn.setIconSize(QSize(14, 14))
        self.get_package_btn.setProperty("iconName", "target.svg")
        self.get_package_btn.setToolTip("Fetch current foreground app package")
        self.get_package_btn.clicked.connect(self.fetch_current_package)
        package_row = self._row_widget(self.package_edit, self.get_package_btn)

        self.frequency_combo = self._combo(["1", "2", "5", "10"], "5")
        self.timeout_combo = self._combo(["10", "30", "60", "120", "600", "4320"], "600")
        self.dumpheap_combo = self._combo(["5", "10", "30", "60", "120"], "60")
        self.exception_edit = QLineEdit("fatal exception;has died")
        self.exception_edit.setObjectName("monoField")
        self.phone_log_edit = QLineEdit("/data/anr")
        self.phone_log_edit.setObjectName("monoField")
        self.monkey_check = QCheckBox("Enable monkey")
        self.monkey_check.toggled.connect(self._on_monkey_enabled_changed)
        monkey_row = self._build_monkey_row()
        self.save_path_edit = QLineEdit(self._default_save_path())
        self.save_path_edit.setObjectName("monoField")
        self.save_path_edit.setPlaceholderText("Result root")
        self.pick_save_btn = QPushButton("Browse")
        self.pick_save_btn.setIcon(get_themed_icon("folder.svg"))
        self.pick_save_btn.setIconSize(QSize(14, 14))
        self.pick_save_btn.setProperty("iconName", "folder.svg")
        self.pick_save_btn.clicked.connect(self._pick_save_path)
        save_row = self._row_widget(self.save_path_edit, self.pick_save_btn)

        row = 0
        row = self._add_config_row(grid, row, "package", package_row, CONFIG_HINTS["package"])
        self.serialnum_label = QLabel(self.device_ip or "-")
        self.serialnum_label.setObjectName("onlineDeviceLabel")
        self.serialnum_label.setToolTip("Selected online device")
        row = self._add_config_row(
            grid, row, "serialnum", self.serialnum_label, CONFIG_HINTS["serialnum"]
        )
        row = self._add_config_row(
            grid, row, "frequency", self.frequency_combo, CONFIG_HINTS["frequency"]
        )
        row = self._add_config_row(
            grid, row, "timeout", self.timeout_combo, CONFIG_HINTS["timeout"]
        )
        row = self._add_config_row(
            grid, row, "dumpheap_freq", self.dumpheap_combo, CONFIG_HINTS["dumpheap_freq"]
        )
        row = self._add_config_row(
            grid, row, "exceptionlog", self.exception_edit, CONFIG_HINTS["exceptionlog"]
        )
        row = self._add_config_row(grid, row, "monkey", monkey_row, CONFIG_HINTS["monkey"])
        row = self._add_config_row(grid, row, "save_path", save_row, CONFIG_HINTS["save_path"])
        self._add_config_row(
            grid, row, "phone_log_path", self.phone_log_edit, CONFIG_HINTS["phone_log_path"]
        )
        self._on_monkey_enabled_changed(self.monkey_check.isChecked())
        return g

    def _build_monkey_row(self) -> QWidget:
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)

        self.monkey_throttle_combo = self._combo(
            ["100", "200", "300", "500", "1000", "2000"], "500"
        )
        self.monkey_seed_edit = QLineEdit("1000000")
        self.monkey_seed_edit.setPlaceholderText("Seed")
        self.monkey_total_label = QLabel("Total: 100%")
        self.monkey_total_label.setObjectName("monkeyTotalLabel")
        self.monkey_total_label.setMinimumWidth(92)

        layout.addWidget(self.monkey_check, 0, 0)
        layout.addWidget(
            self._inline_label("Throttle (ms)", "Monkey --throttle interval in milliseconds."), 0, 1
        )
        layout.addWidget(self.monkey_throttle_combo, 0, 2)
        layout.addWidget(self._inline_label("Seed", "Monkey -s random seed."), 0, 3)
        layout.addWidget(self.monkey_seed_edit, 0, 4)
        layout.addWidget(self.monkey_total_label, 0, 5)

        self.monkey_pct_combos: dict[str, QComboBox] = {}
        percent_defaults = MobilePerfMonkeyConfig()
        for index, (label, attr, option_name) in enumerate(MONKEY_PERCENT_FIELDS):
            row, col = divmod(index, 2)
            combo = self._combo(
                ["0", "5", "10", "15", "20", "25", "30", "40", "50", "100"],
                str(getattr(percent_defaults, attr)),
            )
            combo.setMinimumWidth(64)
            combo.setToolTip(f"{option_name}: {label} percentage")
            combo.currentTextChanged.connect(self._update_monkey_total)
            if combo.lineEdit():
                combo.lineEdit().textChanged.connect(self._update_monkey_total)
            self.monkey_pct_combos[attr] = combo
            layout.addWidget(self._inline_label(label, option_name), row + 1, col * 3)
            layout.addWidget(combo, row + 1, col * 3 + 1)

        self.monkey_ignore_crashes = QCheckBox("Ignore crashes")
        self.monkey_ignore_timeouts = QCheckBox("Ignore timeouts")
        self.monkey_ignore_security = QCheckBox("Ignore security")
        self.monkey_kill_after_error = QCheckBox("Kill after error")
        for checkbox in (
            self.monkey_ignore_crashes,
            self.monkey_ignore_timeouts,
            self.monkey_ignore_security,
            self.monkey_kill_after_error,
        ):
            checkbox.setChecked(True)
        flags_row = self._row_widget(
            self.monkey_ignore_crashes,
            self.monkey_ignore_timeouts,
            self.monkey_ignore_security,
            self.monkey_kill_after_error,
        )
        layout.addWidget(flags_row, 6, 0, 1, 6)
        layout.setColumnStretch(5, 1)
        self._update_monkey_total()
        self._apply_monkey_control_widths()
        return container

    def _inline_label(self, text: str, tooltip: str = "") -> QLabel:
        label = QLabel(text)
        label.setObjectName("inlineLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setMinimumWidth(136)
        if tooltip:
            label.setToolTip(tooltip)
        return label

    def _monkey_option_widgets(self) -> list[QWidget]:
        widgets: list[QWidget] = [
            self.monkey_throttle_combo,
            self.monkey_seed_edit,
            self.monkey_total_label,
            self.monkey_ignore_crashes,
            self.monkey_ignore_timeouts,
            self.monkey_ignore_security,
            self.monkey_kill_after_error,
        ]
        widgets.extend(self.monkey_pct_combos.values())
        return widgets

    def _on_monkey_enabled_changed(self, checked: bool):
        for widget in self._monkey_option_widgets():
            widget.setEnabled(checked)

    def _update_monkey_total(self):
        if not hasattr(self, "monkey_total_label"):
            return
        total = sum(
            self._int_text(self._combo_text(combo), 0, minimum=0, maximum=100)
            for combo in self.monkey_pct_combos.values()
        )
        color = BaseStyles.color("LOG_SUCCESS" if total == 100 else "LOG_WARNING")
        self.monkey_total_label.setText(f"Total: {total}%")
        self.monkey_total_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _collect_monkey_config(self) -> MobilePerfMonkeyConfig:
        defaults = MobilePerfMonkeyConfig()
        values = {
            attr: self._int_text(
                self._combo_text(combo), getattr(defaults, attr), minimum=0, maximum=100
            )
            for attr, combo in self.monkey_pct_combos.items()
        }
        return MobilePerfMonkeyConfig(
            throttle_ms=self._int_text(
                self._combo_text(self.monkey_throttle_combo), defaults.throttle_ms, minimum=1
            ),
            seed=self._int_text(self.monkey_seed_edit.text(), defaults.seed, minimum=0),
            ignore_crashes=self.monkey_ignore_crashes.isChecked(),
            ignore_timeouts=self.monkey_ignore_timeouts.isChecked(),
            ignore_security=self.monkey_ignore_security.isChecked(),
            kill_after_error=self.monkey_kill_after_error.isChecked(),
            **values,
        )

    def _add_config_row(
        self, grid: QGridLayout, row: int, key: str, field: QWidget, hint: str
    ) -> int:
        label = QLabel(key)
        label.setObjectName("fieldLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        grid.addWidget(label, row, 0)
        grid.addWidget(field, row, 1)
        hint_label = QLabel(hint)
        hint_label.setObjectName("configHint")
        hint_label.setWordWrap(True)
        grid.addWidget(hint_label, row + 1, 1)
        return row + 2

    def _row_widget(self, *widgets: QWidget) -> QWidget:
        container = QWidget()
        container.setObjectName("inlineRow")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, 1 if index == 0 else 0)
        return container

    def _build_log_view(self) -> QPlainTextEdit:
        log_view = QPlainTextEdit()
        log_view.setObjectName("performanceLog")
        log_view.setReadOnly(True)
        log_view.setUndoRedoEnabled(False)
        log_view.document().setMaximumBlockCount(self._max_log_lines)
        return log_view

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setMinimumWidth(92)
        row.addWidget(self.status_label, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("performanceProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumWidth(160)
        self.progress_bar.setProperty("adaptiveBaseHeight", 22)
        row.addWidget(self.progress_bar, 1)

        self.perfetto_btn = QPushButton("Open Perfetto")
        self.perfetto_btn.setIcon(get_themed_icon("speedometer.svg"))
        self.perfetto_btn.setIconSize(QSize(14, 14))
        self.perfetto_btn.setProperty("iconName", "speedometer.svg")
        self.perfetto_btn.clicked.connect(self.open_perfetto)
        row.addWidget(self.perfetto_btn)

        self.result_btn = QPushButton("Open Result")
        self.result_btn.setIcon(get_themed_icon("folder-open.svg"))
        self.result_btn.setIconSize(QSize(14, 14))
        self.result_btn.setProperty("iconName", "folder-open.svg")
        self.result_btn.clicked.connect(self.open_result)
        row.addWidget(self.result_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setIcon(get_themed_icon("stop-circle.svg"))
        self.stop_btn.setIconSize(QSize(14, 14))
        self.stop_btn.setProperty("iconName", "stop-circle.svg")
        self.stop_btn.clicked.connect(self.stop_mobileperf)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("accent")
        self.start_btn.setIcon(get_themed_icon("play.svg"))
        self.start_btn.setIconSize(QSize(14, 14))
        self.start_btn.setProperty("iconName", "play.svg")
        self.start_btn.clicked.connect(self.start_mobileperf)
        row.addWidget(self.start_btn)
        return row

    def _combo(self, items: list[str], current: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(items)
        combo.setEditable(True)
        combo.setCurrentText(current)
        return combo

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
        worker.finished.connect(lambda _w=worker: self._on_package_worker_finished(_w))
        self._package_worker = worker
        worker.start()

    def _on_current_package(self, package_name: str):
        self.package_edit.setText(package_name)
        self.log_received.emit("SUCCESS", f"Current package: {package_name}")

    def _on_package_worker_finished(self, worker: CurrentPackageWorker):
        if self._package_worker is worker:
            self._package_worker = None
        if self.get_package_btn:
            self.get_package_btn.setEnabled(True)
        worker.deleteLater()

    def build_config(self) -> MobilePerfRunConfig:
        return MobilePerfRunConfig(
            device_id=self.device_ip.strip(),
            package=self.package_edit.text().strip(),
            frequency_seconds=self._int_combo(self.frequency_combo, 5),
            timeout_minutes=self._int_combo(self.timeout_combo, 600),
            dumpheap_minutes=self._int_combo(self.dumpheap_combo, 60),
            monkey_enabled=self.monkey_check.isChecked(),
            monkey_config=self._collect_monkey_config(),
            exception_keywords=self.exception_edit.text().split(";"),
            phone_log_paths=self.phone_log_edit.text().split(";"),
            save_path=self._with_device_suffix(self.save_path_edit.text()),
            mailbox="",
        )

    def start_mobileperf(self):
        config = self.build_config()
        if not config.package:
            QMessageBox.warning(self, "Package Required", "Please enter a package name.")
            return
        if config.monkey_enabled and config.monkey_config.total_percentage != 100:
            QMessageBox.warning(
                self,
                "Monkey Event Mix",
                f"Monkey event percentages sum to {config.monkey_config.total_percentage}%, "
                f"not 100%.\n"
                "MobilePerf will still start, but the event distribution may be unexpected.",
            )
        self._last_result_root = self._runner.expected_result_root(config)
        self._runner_finished_handled = False
        self.log_received.emit("INFO", "Starting mobileperf")
        try:
            self._runner.start(
                config,
                on_log=lambda line: self.log_received.emit("RAW", line),
                on_finished=self.runner_finished.emit,
            )
        except Exception as exc:
            self.log_received.emit("ERROR", f"Start failed: {exc}")
            self._runner_finished_handled = True
            self._reset_progress()
            self._set_running(False)
            return
        self._run_started_at = time.monotonic()
        self._run_duration_seconds = max(1, int(config.timeout_minutes) * 60)
        self._set_progress(0)
        self._set_running(True)
        self._poll_timer.start()

    def stop_mobileperf(self):
        """在后台请求 MobilePerf 停止，避免等待子进程时阻塞 GUI。"""
        if self._stopping:
            return
        if not self._runner.is_running():
            self._mark_runner_finished()
            return
        self._stopping = True
        self.log_received.emit("INFO", "Stopping mobileperf and generating report...")
        self._poll_timer.stop()
        self._update_progress()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._set_status("Stopping", "stopping")
        self._stop_thread = threading.Thread(
            target=self._stop_mobileperf_worker,
            name="adblab-mobileperf-stop",
            daemon=True,
        )
        self._stop_thread.start()

    def _stop_mobileperf_worker(self):
        try:
            self._runner.stop()
        except Exception as exc:
            self.log_received.emit("ERROR", f"Stop failed: {exc}")
        finally:
            self.runner_finished.emit()

    def _poll_runner(self):
        self._update_progress()
        if self._runner.is_running():
            return
        self._mark_runner_finished()

    def _on_runner_finished(self):
        self._mark_runner_finished()

    def _mark_runner_finished(self):
        if self._closing or self._runner_finished_handled:
            return
        self._runner_finished_handled = True
        self._stopping = False
        self._poll_timer.stop()
        self._run_started_at = None
        result_dir = self._runner.latest_result_dir()
        if result_dir:
            self._last_result_root = result_dir
        report_file = self._runner.latest_report_file()
        last_config = getattr(self._runner, "last_config", None)
        exit_code = getattr(self._runner, "last_exit_code", None)

        # 保留既有调用方依赖的轻量启动前界面契约；真实采集总会记录 last_config。
        if last_config is None:
            self._set_progress(100)
            if report_file:
                self.log_received.emit(
                    "SUCCESS",
                    f"MobilePerf ended, report generated: {report_file}",
                )
            elif result_dir:
                self.log_received.emit(
                    "WARNING",
                    f"MobilePerf ended, report not found in: {result_dir}",
                )
            else:
                self.log_received.emit("WARNING", "MobilePerf ended, result directory not found")
            self._set_running(False)
            return

        successful_exit = exit_code == 0
        if report_file and successful_exit:
            self.log_received.emit("SUCCESS", f"MobilePerf ended, report generated: {report_file}")
            self._set_running(False)
            self._set_progress(100)
            self._set_status("Completed", "completed")
            return

        self._set_running(False)
        self._set_progress(min(99, self.progress_bar.value()))
        if report_file:
            self.log_received.emit(
                "WARNING",
                f"MobilePerf exited with code {exit_code}; report may be incomplete: {report_file}",
            )
            self._set_status("Warning", "warning")
        elif exit_code not in (None, 0):
            self.log_received.emit(
                "ERROR",
                f"MobilePerf failed with exit code {exit_code}; no report was generated",
            )
            self._set_status("Failed", "failed")
        elif result_dir:
            self.log_received.emit(
                "WARNING",
                f"MobilePerf ended, report not found in: {result_dir}",
            )
            self._set_status("Warning", "warning")
        else:
            self.log_received.emit("WARNING", "MobilePerf ended, result directory not found")
            self._set_status("Warning", "warning")

    def open_result(self):
        path = self._last_result_root or self._with_device_suffix(self.save_path_edit.text())
        if not path:
            path = self._default_save_path()
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @staticmethod
    def open_perfetto():
        QDesktopServices.openUrl(QUrl("https://ui.perfetto.dev/"))

    def _append_log(self, level: str, message: str):
        if self._closing:
            return
        scrollbar = self.log_view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 20
        message_lines = str(message).splitlines() or [str(message)]
        rows = [self._format_log_line(level, line) for line in message_lines if line.strip()]
        if not rows:
            return
        self._pending_log_rows.extend(rows)
        if len(self._pending_log_rows) > self.MAX_PENDING_LOG_ROWS:
            del self._pending_log_rows[: len(self._pending_log_rows) - self.MAX_PENDING_LOG_ROWS]
        self._pending_log_scroll_to_bottom = self._pending_log_scroll_to_bottom or at_bottom
        if len(self._pending_log_rows) >= self.IMMEDIATE_LOG_BATCH_SIZE:
            self._flush_pending_logs()
        elif not self._log_flush_timer.isActive():
            self._log_flush_timer.start(self.LOG_RENDER_DEBOUNCE_MS)

    def _flush_pending_logs(self):
        if not self._pending_log_rows:
            return
        rows = self._pending_log_rows
        at_bottom = self._pending_log_scroll_to_bottom
        self._pending_log_rows = []
        self._pending_log_scroll_to_bottom = False
        self._render_log_rows(rows)
        if at_bottom:
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _render_log_rows(self, rows: list[str]):
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.beginEditBlock()
        try:
            cursor.insertText("\n".join(rows) + "\n")
        finally:
            cursor.endEditBlock()

    @staticmethod
    def _format_log_line(level: str, message: str) -> str:
        text = str(message)
        if level.upper() == "RAW":
            return text
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = level.upper()
        return f"{timestamp} [{level}] {text}"

    @staticmethod
    def _configured_log_max_lines() -> int:
        try:
            return max(100, int(AppSettings.instance().get("log_max_lines", 2000)))
        except (TypeError, ValueError):
            return 2000

    def _set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self._set_status("Running" if running else "Idle", "running" if running else "idle")
        if not running:
            self._flush_pending_logs()

    def _set_status(self, text: str, state: str):
        self._status_state = state
        self.status_label.setText(text)
        self._apply_status_style()

    def _apply_status_style(self):
        color_key = {
            "running": "LOG_SUCCESS",
            "stopping": "LOG_WARNING",
            "completed": "LOG_SUCCESS",
            "warning": "LOG_WARNING",
            "failed": "LOG_ERROR",
            "idle": "TEXT_SECONDARY",
        }.get(self._status_state, "TEXT_SECONDARY")
        weight = (
            "bold"
            if self._status_state in {"running", "stopping", "completed", "warning", "failed"}
            else "normal"
        )
        self.status_label.setStyleSheet(
            f"color: {BaseStyles.color(color_key)}; font-weight: {weight};"
        )

    def _update_progress(self):
        if self._run_started_at is None or self._run_duration_seconds <= 0:
            return
        elapsed = max(0.0, time.monotonic() - self._run_started_at)
        percent = int((elapsed / self._run_duration_seconds) * 100)
        if self._runner.is_running():
            percent = min(99, percent)
        self._set_progress(percent)

    def _set_progress(self, percent: int):
        value = max(0, min(100, int(percent)))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{value}%")

    def _reset_progress(self):
        self._run_started_at = None
        self._run_duration_seconds = 0
        self._set_progress(0)

    @staticmethod
    def _int_combo(combo: QComboBox, default: int) -> int:
        try:
            return max(1, int(combo.currentText().strip()))
        except ValueError:
            return default

    @staticmethod
    def _int_text(
        text: str, default: int, *, minimum: int | None = None, maximum: int | None = None
    ) -> int:
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            value = int(default)
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    @staticmethod
    def _combo_text(combo: QComboBox) -> str:
        if combo.isEditable() and combo.lineEdit():
            return combo.lineEdit().text()
        return combo.currentText()

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
        self.log_view.document().setMaximumBlockCount(self._max_log_lines)
        self.setStyleSheet(
            BaseStyles.INPUT_STYLE()
            + BaseStyles.BUTTON_QSS()
            + BaseStyles.SCROLLBAR_STYLE()
            + f"""
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
            QLabel#fieldLabel {{
                color: {c("TEXT_PRIMARY")};
                font-weight: bold;
            }}
            QLabel#onlineDeviceLabel {{
                color: {c("LOG_SUCCESS")};
                font-weight: bold;
            }}
            QLabel#inlineLabel {{
                color: {c("TEXT_PRIMARY")};
            }}
            QLabel#configHint {{
                color: {c("TEXT_SECONDARY")};
            }}
            QLabel#statusLabel {{
                color: {c("TEXT_SECONDARY")};
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
            QPlainTextEdit#performanceLog {{
                background-color: {c("LOG_BACKGROUND")};
                color: {c("LOG_TEXT_COLOR")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {BaseStyles.RADIUS_LG}px;
                padding: 4px;
            }}
            QCheckBox {{
                color: {c("TEXT_PRIMARY")};
            }}
            QWidget#inlineRow,
            QWidget#inlineRow QLabel,
            QWidget#inlineRow QCheckBox {{
                color: {c("TEXT_PRIMARY")};
                background-color: transparent;
            }}
            QWidget#inlineRow QLineEdit,
            QWidget#inlineRow QComboBox,
            QWidget#inlineRow QComboBox QLineEdit {{
                background-color: {c("INPUT_BG")};
                color: {c("TEXT_PRIMARY")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {BaseStyles.RADIUS_MD}px;
                selection-background-color: {c("SELECTION_BG")};
                selection-color: {c("SELECTION_TEXT")};
            }}
            QWidget#inlineRow QLineEdit:disabled,
            QWidget#inlineRow QComboBox:disabled,
            QWidget#inlineRow QComboBox QLineEdit:disabled,
            QWidget#inlineRow QCheckBox:disabled {{
                color: {c("TEXT_DISABLED")};
                background-color: {c("PANEL_BG")};
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
        self.log_view.setFont(log_font)
        self.log_view.viewport().setFont(log_font)
        self.log_view.document().setDefaultFont(log_font)
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
