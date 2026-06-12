"""Performance launcher dialog with MobilePerf controls and Perfetto link."""

from __future__ import annotations

import os
import re
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.settings_manager import AppSettings
from gui.dialogs.lifecycle import safe_disconnect, wait_for_thread_later
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from models.base.focus_detector import detect_current_package
from models.mobileperf import MobilePerfRunConfig, MobilePerfRunner

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
    "monkey": "Monkey test switch. Checked means true; unchecked disables it.",
    "save_path": (
        "Test results save path. Avoid spaces. A device-name folder is appended automatically."
    ),
    "phone_log_path": "Device paths pulled to PC when the test ends; multiple paths use ';'.",
    "mailbox": "Reserved by mobileperf; currently no use.",
}


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
    """Launch mobileperf collection for one selected device."""

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
        self._last_result_root = ""
        self._closing = False
        self._runner_finished_handled = True
        self._max_log_lines = self._configured_log_max_lines()
        self._pending_log_rows: list[str] = []
        self._pending_log_scroll_to_bottom = False
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.timeout.connect(self._flush_pending_logs)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_runner)
        self.setWindowTitle(f"Performance - {device_ip}" if device_ip else "Performance")
        self.setWindowIcon(get_themed_icon("speedometer.svg"))
        self.setMinimumSize(760, 620)
        self.resize(820, 660)
        self.setModal(False)
        self.log_received.connect(self._append_log)
        self.runner_finished.connect(self._on_runner_finished)

        self._build_ui(package_name)
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)

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
        self.phone_log_edit = QLineEdit("/data/anr")
        self.mailbox_edit = QLineEdit("")
        self.mailbox_edit.setPlaceholderText("Reserved")
        self.monkey_check = QCheckBox("Enable monkey")
        self.save_path_edit = QLineEdit(self._default_save_path())
        self.save_path_edit.setPlaceholderText("Result root")
        self.pick_save_btn = QPushButton("Browse")
        self.pick_save_btn.setIcon(get_themed_icon("folder.svg"))
        self.pick_save_btn.setIconSize(QSize(14, 14))
        self.pick_save_btn.setProperty("iconName", "folder.svg")
        self.pick_save_btn.clicked.connect(self._pick_save_path)
        save_row = self._row_widget(self.save_path_edit, self.pick_save_btn)

        row = 0
        row = self._add_config_row(grid, row, "package", package_row, CONFIG_HINTS["package"])
        row = self._add_config_row(grid, row, "serialnum", QLabel(self.device_ip or "-"), CONFIG_HINTS["serialnum"])
        row = self._add_config_row(grid, row, "frequency", self.frequency_combo, CONFIG_HINTS["frequency"])
        row = self._add_config_row(grid, row, "timeout", self.timeout_combo, CONFIG_HINTS["timeout"])
        row = self._add_config_row(grid, row, "dumpheap_freq", self.dumpheap_combo, CONFIG_HINTS["dumpheap_freq"])
        row = self._add_config_row(grid, row, "exceptionlog", self.exception_edit, CONFIG_HINTS["exceptionlog"])
        row = self._add_config_row(grid, row, "monkey", self.monkey_check, CONFIG_HINTS["monkey"])
        row = self._add_config_row(grid, row, "save_path", save_row, CONFIG_HINTS["save_path"])
        row = self._add_config_row(grid, row, "phone_log_path", self.phone_log_edit, CONFIG_HINTS["phone_log_path"])
        self._add_config_row(grid, row, "mailbox", self.mailbox_edit, CONFIG_HINTS["mailbox"])
        return g

    def _add_config_row(self, grid: QGridLayout, row: int, key: str, field: QWidget, hint: str) -> int:
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
        row.addWidget(self.status_label, 1)

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
            exception_keywords=self.exception_edit.text().split(";"),
            phone_log_paths=self.phone_log_edit.text().split(";"),
            save_path=self._with_device_suffix(self.save_path_edit.text()),
            mailbox=self.mailbox_edit.text().strip(),
        )

    def start_mobileperf(self):
        config = self.build_config()
        if not config.package:
            QMessageBox.warning(self, "Package Required", "Please enter a package name.")
            return
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
            self._set_running(False)
            return
        self._set_running(True)
        self._poll_timer.start()

    def stop_mobileperf(self):
        self.log_received.emit("INFO", "Stopping mobileperf")
        self._poll_timer.stop()
        self._runner.stop(timeout=3)
        self._runner_finished_handled = True
        self._set_running(False)

    def _poll_runner(self):
        if self._runner.is_running():
            return
        self._mark_runner_finished()

    def _on_runner_finished(self):
        self._mark_runner_finished()

    def _mark_runner_finished(self):
        if self._closing or self._runner_finished_handled:
            return
        self._runner_finished_handled = True
        self._poll_timer.stop()
        self.log_received.emit("INFO", "MobilePerf ended")
        self._set_running(False)

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
        self.status_label.setText("Running" if running else "Idle")
        if not running:
            self._flush_pending_logs()

    @staticmethod
    def _int_combo(combo: QComboBox, default: int) -> int:
        try:
            return max(1, int(combo.currentText().strip()))
        except ValueError:
            return default

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        c = BaseStyles.color
        r = BaseStyles.RADIUS_MD
        self._max_log_lines = self._configured_log_max_lines()
        self._flush_pending_logs()
        self.setFont(BaseStyles.get_default_font())
        self.log_view.document().setMaximumBlockCount(self._max_log_lines)
        self.setStyleSheet(
            BaseStyles.INPUT_STYLE()
            + BaseStyles.BUTTON_QSS()
            + BaseStyles.SCROLLBAR_STYLE()
            + f"""
            QDialog {{
                background-color: {c('PANEL_BG')};
                color: {c('TEXT_PRIMARY')};
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QDialog QLabel,
            QDialog QLineEdit,
            QDialog QComboBox,
            QDialog QComboBox QAbstractItemView,
            QDialog QCheckBox,
            QDialog QPushButton,
            QDialog QPushButton#accent,
            QDialog QPushButton#danger,
            QDialog QGroupBox {{
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QGroupBox#performanceConfig {{
                background-color: {c('INPUT_BG')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                margin-top: 7px;
                padding: 10px 10px 8px 10px;
                color: {c('TEXT_PRIMARY')};
                font-weight: bold;
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QGroupBox#performanceConfig::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 10px;
                color: {c('GROUP_TITLE_COLOR')};
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QLabel#fieldLabel {{
                color: {c('TEXT_PRIMARY')};
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
                font-weight: bold;
            }}
            QLabel#configHint {{
                color: {c('TEXT_SECONDARY')};
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QLabel#statusLabel {{
                color: {c('TEXT_SECONDARY')};
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QPlainTextEdit#performanceLog {{
                background-color: {c('LOG_BACKGROUND')};
                color: {c('LOG_TEXT_COLOR')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {BaseStyles.RADIUS_LG}px;
                padding: 4px;
                font-family: '{BaseStyles.LOG_FONT}';
                font-size: {BaseStyles.LOG_FONT_SIZE_VAR}px;
            }}
            QCheckBox {{
                color: {c('TEXT_PRIMARY')};
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            """
        )
        self._apply_widget_fonts()
        for button in self.findChildren(QPushButton):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(get_themed_icon(icon_name))

    def _apply_widget_fonts(self):
        ui_font = BaseStyles.get_default_font()
        log_font = BaseStyles.get_log_font()
        self.setFont(ui_font)
        for widget in self.findChildren(QWidget):
            widget.setFont(log_font if widget is self.log_view else ui_font)

    def closeEvent(self, event):
        self._closing = True
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        self._pending_log_rows = []
        self._poll_timer.stop()
        if self._runner.is_running():
            self._runner.stop(timeout=2)
        if self._package_worker and self._package_worker.isRunning():
            worker = self._package_worker
            self._package_worker = None
            worker.requestInterruption()
            safe_disconnect(worker.package_ready, self._on_current_package)
            safe_disconnect(worker.log_ready, self.log_received.emit)
            wait_for_thread_later(worker, 2000)
        safe_disconnect(self.log_received, self._append_log)
        safe_disconnect(self.runner_finished, self._on_runner_finished)
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        super().closeEvent(event)
