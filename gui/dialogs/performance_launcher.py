"""提供 MobilePerf 启停控制、状态展示和 Perfetto 入口。"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from adblab.application.supervision import ThreadedShutdownTask
from core.settings_manager import AppSettings
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    alive_signal_emitter,
    safe_disconnect,
    wait_for_thread_later,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from gui.widgets.preset_spin_box import StrictIntComboBox, StrictIntLineEdit
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
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._theme_sync_timer.start()

    def _build_ui(self, package_name: str):
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self._root_layout = root

        self._config_group = self._build_config_section(package_name)
        root.addWidget(self._config_group, 1)
        self.log_view = self._build_log_view()
        self.log_view.setFixedHeight(96)
        root.addWidget(self.log_view)
        self._action_row = self._build_actions()
        root.addWidget(self._action_row)

    def _build_config_section(self, package_name: str) -> QGroupBox:
        """按分页前版本的九项纵向表单构建配置区。"""

        group = QGroupBox("MobilePerf Config")
        group.setObjectName("performanceConfig")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self._config_group_layout = grid

        self.package_edit = QLineEdit(package_name)
        self.package_edit.setObjectName("monoField")
        self.package_edit.setPlaceholderText("com.example.app")
        self.get_package_btn = QPushButton("Get Current Package")
        self.get_package_btn.setIcon(get_themed_icon("target.svg"))
        self.get_package_btn.setIconSize(QSize(14, 14))
        self.get_package_btn.setProperty("iconName", "target.svg")
        self.get_package_btn.setToolTip("Fetch current foreground app package")
        self.get_package_btn.clicked.connect(self.fetch_current_package)
        self.frequency_input = StrictIntComboBox(
            1,
            2_147_483_647,
            5,
            presets=(1, 2, 5, 10),
        )
        self.timeout_input = StrictIntComboBox(
            1,
            2_147_483_647,
            600,
            presets=(10, 30, 60, 120, 600, 4320),
        )
        self.dumpheap_input = StrictIntComboBox(
            1,
            2_147_483_647,
            60,
            presets=(5, 10, 30, 60, 120),
        )
        self.frequency_combo = self.frequency_input
        self.timeout_combo = self.timeout_input
        self.dumpheap_combo = self.dumpheap_input
        self.frequency_unit_label = self._unit_label("s", "seconds")
        self.timeout_unit_label = self._unit_label("min", "minutes")
        self.dumpheap_unit_label = self._unit_label("min", "minutes")
        for unit_label in (
            self.frequency_unit_label,
            self.timeout_unit_label,
            self.dumpheap_unit_label,
        ):
            unit_label.setParent(group)
            unit_label.hide()

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
        self.pick_save_btn.setToolTip("Select the MobilePerf result directory")
        self.pick_save_btn.setIcon(get_themed_icon("folder.svg"))
        self.pick_save_btn.setIconSize(QSize(14, 14))
        self.pick_save_btn.setProperty("iconName", "folder.svg")
        self.pick_save_btn.clicked.connect(self._pick_save_path)
        save_row = self._row_widget(self.save_path_edit, self.pick_save_btn)

        self.serialnum_label = QLabel(self.device_ip or "-")
        self.serialnum_label.setObjectName("onlineDeviceLabel")
        self.serialnum_label.setToolTip(f"Selected online device: {self.device_ip or '-'}")
        self.serialnum_label.setAccessibleName(f"Selected device: {self.device_ip or '-'}")
        self.serialnum_label.setAccessibleDescription(f"Selected device: {self.device_ip or '-'}")

        row = self._add_config_row(
            grid,
            0,
            "package",
            self._row_widget(self.package_edit, self.get_package_btn),
            CONFIG_HINTS["package"],
        )
        row = self._add_config_row(
            grid,
            row,
            "serialnum",
            self.serialnum_label,
            CONFIG_HINTS["serialnum"],
        )
        row = self._add_config_row(
            grid,
            row,
            "frequency",
            self.frequency_input,
            CONFIG_HINTS["frequency"],
        )
        row = self._add_config_row(
            grid,
            row,
            "timeout",
            self.timeout_input,
            CONFIG_HINTS["timeout"],
        )
        row = self._add_config_row(
            grid,
            row,
            "dumpheap_freq",
            self.dumpheap_input,
            CONFIG_HINTS["dumpheap_freq"],
        )
        row = self._add_config_row(
            grid,
            row,
            "exceptionlog",
            self.exception_edit,
            CONFIG_HINTS["exceptionlog"],
        )
        row = self._add_config_row(
            grid,
            row,
            "monkey",
            monkey_row,
            CONFIG_HINTS["monkey"],
        )
        row = self._add_config_row(
            grid,
            row,
            "save_path",
            save_row,
            CONFIG_HINTS["save_path"],
        )
        self._add_config_row(
            grid,
            row,
            "phone_log_path",
            self.phone_log_edit,
            CONFIG_HINTS["phone_log_path"],
        )

        self._config_canvas = group
        self._configuration_sections = (group,)
        self._on_monkey_enabled_changed(self.monkey_check.isChecked())
        self._apply_monkey_control_widths()
        return group

    def _build_monkey_row(self) -> QWidget:
        container = QWidget()
        container.setObjectName("performanceMonkeyOptions")
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        self.monkey_throttle_input = StrictIntComboBox(
            1,
            2_147_483_647,
            500,
            presets=(100, 200, 300, 500, 1000, 2000),
        )
        self.monkey_throttle_combo = self.monkey_throttle_input
        self.monkey_seed_input = StrictIntLineEdit(
            minimum=0,
            maximum=2_147_483_647,
            value=1_000_000,
        )
        self.monkey_seed_edit = self.monkey_seed_input
        self.monkey_throttle_unit_label = self._unit_label("ms")
        self.monkey_throttle_unit_label.setParent(container)
        self.monkey_throttle_unit_label.hide()

        throttle_hint = "Monkey --throttle interval in milliseconds."
        seed_hint = "Monkey -s random seed."
        self.monkey_check.setAccessibleName("Enable Monkey test")
        self._apply_hint(self.monkey_check, CONFIG_HINTS["monkey"])
        self._apply_hint(self.monkey_throttle_input, throttle_hint)
        self._apply_hint(self.monkey_seed_input, seed_hint)
        self.monkey_throttle_input.setAccessibleName("Monkey throttle interval")
        self.monkey_seed_input.setAccessibleName("Monkey random seed")
        layout.addWidget(self.monkey_check, 0, 0)
        layout.addWidget(
            self._inline_label("Throttle (ms)", throttle_hint),
            0,
            1,
        )
        layout.addWidget(self.monkey_throttle_input, 0, 2)
        layout.addWidget(self._inline_label("Seed", seed_hint), 0, 3)
        layout.addWidget(self.monkey_seed_input, 0, 4)

        self.monkey_total_label = QLabel("Total: 100%")
        self.monkey_total_label.setObjectName("monkeyTotalLabel")
        self.monkey_total_label.setMinimumWidth(92)
        self.monkey_total_label.setToolTip("Total: 100%")
        self.monkey_total_label.setAccessibleName("Total: 100%")
        self.monkey_total_label.setAccessibleDescription("Monkey event percentage total: 100%")
        self._monkey_total_labels = [self.monkey_total_label]
        layout.addWidget(self.monkey_total_label, 0, 5)

        self.monkey_pct_inputs: dict[str, StrictIntComboBox] = {}
        self.monkey_pct_combos = self.monkey_pct_inputs
        defaults = MobilePerfMonkeyConfig()
        for index, (label, attr, option_name) in enumerate(MONKEY_PERCENT_FIELDS):
            event_row, column = divmod(index, 2)
            field = StrictIntComboBox(
                0,
                100,
                getattr(defaults, attr),
                presets=(0, 5, 10, 15, 20, 25, 30, 40, 50, 100),
            )
            field.setMinimumWidth(64)
            tooltip = f"{label} percentage ({option_name})."
            self._apply_hint(field, tooltip)
            field.setAccessibleName(f"{label} percentage")
            field.valueChanged.connect(self._update_monkey_total)
            field.validityChanged.connect(self._update_monkey_total)
            self.monkey_pct_inputs[attr] = field
            layout.addWidget(self._inline_label(label, tooltip), event_row + 1, column * 3)
            layout.addWidget(field, event_row + 1, column * 3 + 1)

        self.monkey_ignore_crashes = QCheckBox("Ignore crashes")
        self.monkey_ignore_timeouts = QCheckBox("Ignore timeouts")
        self.monkey_ignore_security = QCheckBox("Ignore security")
        self.monkey_kill_after_error = QCheckBox("Kill after error")
        monkey_flags = (
            self.monkey_ignore_crashes,
            self.monkey_ignore_timeouts,
            self.monkey_ignore_security,
            self.monkey_kill_after_error,
        )
        flag_hints = (
            "Continue after an application crash.",
            "Continue after an application-not-responding timeout.",
            "Continue after a security exception.",
            "Stop Monkey after the first error.",
        )
        flag_names = (
            "Ignore application crashes",
            "Ignore application timeouts",
            "Ignore security exceptions",
            "Kill Monkey after error",
        )
        self._monkey_flag_labels: list[QLabel] = []
        for checkbox, hint, accessible_name in zip(monkey_flags, flag_hints, flag_names):
            checkbox.setChecked(True)
            self._apply_hint(checkbox, hint)
            checkbox.setAccessibleName(accessible_name)
        flags_row = self._row_widget(*monkey_flags)
        layout.addWidget(flags_row, 6, 0, 1, 6)
        layout.setColumnStretch(5, 1)
        self._event_panel = container
        self._event_sections = (container,)
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
            label.setAccessibleDescription(tooltip)
        return label

    @staticmethod
    def _unit_label(text: str, semantic_name: str | None = None) -> QLabel:
        """创建不会参与严格数字解析的可见单位标签。"""

        label = QLabel(text)
        label.setObjectName("unitLabel")
        label.setAccessibleName(f"Unit: {semantic_name or text}")
        return label

    def _monkey_option_widgets(self) -> list[QWidget]:
        widgets: list[QWidget] = [
            self.monkey_throttle_combo,
            self.monkey_seed_edit,
            self.monkey_ignore_crashes,
            self.monkey_ignore_timeouts,
            self.monkey_ignore_security,
            self.monkey_kill_after_error,
        ]
        widgets.extend(getattr(self, "_monkey_total_labels", (self.monkey_total_label,)))
        widgets.extend(self.monkey_pct_combos.values())
        return widgets

    def _on_monkey_enabled_changed(self, checked: bool):
        pending_invalid = {}
        for field in getattr(self, "monkey_pct_combos", {}).values():
            editor = self._numeric_editor(field)
            if editor is not None and not field.input_is_acceptable():
                pending_invalid[field] = editor.text()
        for widget in self._monkey_option_widgets():
            widget.setEnabled(checked)
        for field, raw_text in pending_invalid.items():
            editor = self._numeric_editor(field)
            if editor is not None and editor.text() != raw_text:
                editor.setText(raw_text)
        self._update_monkey_total()

    @staticmethod
    def _numeric_editor(field: QWidget) -> QLineEdit | None:
        if isinstance(field, QLineEdit):
            return field
        return field.findChild(QLineEdit)

    def _update_monkey_total(self, *_args):
        if not hasattr(self, "monkey_total_label"):
            return
        if self.monkey_check.isChecked() and any(
            not field.input_is_acceptable() for field in self.monkey_pct_combos.values()
        ):
            for label in getattr(self, "_monkey_total_labels", (self.monkey_total_label,)):
                label.setText("Total: Invalid")
                label.setToolTip("Total: Invalid")
                label.setAccessibleName("Total: Invalid")
                label.setAccessibleDescription("Monkey event percentage total is invalid")
                label.setStyleSheet(f"color: {BaseStyles.color('LOG_ERROR')}; font-weight: bold;")
            return
        total = sum(field.value() for field in self.monkey_pct_combos.values())
        color = BaseStyles.color("LOG_SUCCESS" if total == 100 else "LOG_ERROR")
        for label in getattr(self, "_monkey_total_labels", (self.monkey_total_label,)):
            full_text = f"Total: {total}%"
            label.setText(full_text)
            label.setToolTip(full_text)
            label.setAccessibleName(full_text)
            label.setAccessibleDescription(f"Monkey event percentage total: {total}%")
            label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _collect_monkey_config(self) -> MobilePerfMonkeyConfig:
        values = {attr: field.value() for attr, field in self.monkey_pct_combos.items()}
        return MobilePerfMonkeyConfig(
            throttle_ms=self.monkey_throttle_input.value(),
            seed=self.monkey_seed_input.value(),
            ignore_crashes=self.monkey_ignore_crashes.isChecked(),
            ignore_timeouts=self.monkey_ignore_timeouts.isChecked(),
            ignore_security=self.monkey_ignore_security.isChecked(),
            kill_after_error=self.monkey_kill_after_error.isChecked(),
            **values,
        )

    def _add_config_row(
        self,
        grid: QGridLayout,
        row: int,
        key: str,
        field: QWidget,
        hint: str,
    ) -> int:
        label = QLabel(key)
        label.setObjectName("fieldLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        buddy = field
        if not field.focusPolicy() & Qt.FocusPolicy.TabFocus:
            buddy = next(
                (
                    child
                    for child in field.findChildren(QWidget)
                    if child.focusPolicy() & Qt.FocusPolicy.TabFocus
                ),
                field,
            )
        if buddy is not field or field.focusPolicy() & Qt.FocusPolicy.TabFocus:
            label.setBuddy(buddy)
            if not buddy.accessibleName():
                buddy.setAccessibleName(key.replace("_", " ").title())
        if hint:
            self._apply_hint(label, hint)
            self._apply_hint(field, hint)
            for child in field.findChildren(QWidget):
                if child.focusPolicy() & Qt.FocusPolicy.TabFocus:
                    self._apply_hint(child, hint)
        grid.addWidget(label, row, 0)
        grid.addWidget(field, row, 1)
        hint_label = QLabel(hint)
        hint_label.setObjectName("configHint")
        hint_label.setWordWrap(True)
        hint_label.setAccessibleName(f"{key} help")
        hint_label.setAccessibleDescription(hint)
        grid.addWidget(hint_label, row + 1, 1)
        return row + 2

    @staticmethod
    def _apply_hint(widget: QWidget, hint: str):
        current = widget.toolTip().strip()
        if not current:
            widget.setToolTip(hint)
        elif hint not in current:
            widget.setToolTip(f"{current}\n\n{hint}")
        if not widget.accessibleDescription().strip():
            widget.setAccessibleDescription(hint)

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

    def _build_actions(self) -> QWidget:
        container = QWidget()
        container.setObjectName("performanceActionRow")
        container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
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

        self.perfetto_action = QAction(
            get_themed_icon("speedometer.svg"),
            "Open Perfetto",
            self,
        )
        self.perfetto_action.setObjectName("performancePerfettoAction")
        self.perfetto_action.setToolTip("Open Perfetto trace viewer")
        self.perfetto_action.triggered.connect(self._trigger_open_perfetto)
        self.result_action = QAction(
            get_themed_icon("folder-open.svg"),
            "Open Result",
            self,
        )
        self.result_action.setObjectName("performanceResultAction")
        self.result_action.setToolTip("Open the latest MobilePerf result")
        self.result_action.triggered.connect(self._trigger_open_result)
        self.result_action.setEnabled(False)

        self.perfetto_btn = QPushButton("Open Perfetto")
        self.perfetto_btn.setIcon(get_themed_icon("speedometer.svg"))
        self.perfetto_btn.setIconSize(QSize(14, 14))
        self.perfetto_btn.setProperty("iconName", "speedometer.svg")
        self.perfetto_btn.clicked.connect(self.perfetto_action.trigger)
        self.perfetto_action.changed.connect(self._sync_perfetto_button)
        row.addWidget(self.perfetto_btn)

        self.result_btn = QPushButton("Open Result")
        self.result_btn.setIcon(get_themed_icon("folder-open.svg"))
        self.result_btn.setIconSize(QSize(14, 14))
        self.result_btn.setProperty("iconName", "folder-open.svg")
        self.result_btn.clicked.connect(self.result_action.trigger)
        self.result_action.changed.connect(self._sync_result_button)
        row.addWidget(self.result_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop the active performance collection")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setIcon(get_themed_icon("stop-circle.svg"))
        self.stop_btn.setIconSize(QSize(14, 14))
        self.stop_btn.setProperty("iconName", "stop-circle.svg")
        self.stop_btn.clicked.connect(self.stop_mobileperf)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)

        self.start_btn = QPushButton("Start")
        self.start_btn.setToolTip("Start performance collection with this configuration")
        self.start_btn.setObjectName("accent")
        self.start_btn.setIcon(get_themed_icon("play.svg"))
        self.start_btn.setIconSize(QSize(14, 14))
        self.start_btn.setProperty("iconName", "play.svg")
        self.start_btn.clicked.connect(self.start_mobileperf)
        row.addWidget(self.start_btn)
        self._sync_perfetto_button()
        self._sync_result_button()
        return container

    def _sync_perfetto_button(self) -> None:
        self.perfetto_btn.setEnabled(self.perfetto_action.isEnabled())
        self.perfetto_btn.setText(self.perfetto_action.text())
        self.perfetto_btn.setIcon(self.perfetto_action.icon())
        self.perfetto_btn.setToolTip(self.perfetto_action.toolTip())
        self.perfetto_btn.setAccessibleName(self.perfetto_action.text())
        self.perfetto_btn.setAccessibleDescription(self.perfetto_action.toolTip())

    def _sync_result_button(self) -> None:
        self.result_btn.setEnabled(self.result_action.isEnabled())
        self.result_btn.setText(self.result_action.text())
        self.result_btn.setIcon(self.result_action.icon())
        self.result_btn.setToolTip(self.result_action.toolTip())
        self.result_btn.setAccessibleName(self.result_action.text())
        self.result_btn.setAccessibleDescription(self.result_action.toolTip())

    def _trigger_open_perfetto(self, _checked: bool = False) -> None:
        self.open_perfetto()

    def _trigger_open_result(self, _checked: bool = False) -> None:
        self.open_result()

    def _enabled_numeric_inputs(self) -> tuple[tuple[str, QWidget], ...]:
        """返回当前业务语义下必须有效并提交的数字字段。"""

        fields: tuple[tuple[str, QWidget], ...] = (
            ("frequency", self.frequency_input),
            ("timeout", self.timeout_input),
            ("dumpheap frequency", self.dumpheap_input),
        )
        if self.monkey_check.isChecked():
            fields += (
                ("Monkey throttle", self.monkey_throttle_input),
                ("Monkey seed", self.monkey_seed_input),
            )
            fields += tuple(
                (
                    f"Monkey {name.replace('pct_', '').replace('_', ' ')} percentage",
                    field,
                )
                for name, field in self.monkey_pct_combos.items()
            )
        return fields

    def _commit_numeric_inputs(self) -> bool:
        """先校验全部启用字段，再统一提交，避免产生半提交配置。"""

        fields = self._enabled_numeric_inputs()
        for label, field in fields:
            if field.input_is_acceptable():
                continue
            QMessageBox.warning(
                self,
                "Invalid Number",
                f"Please enter a valid {label} value within the allowed range.",
            )
            field.focus_editor()
            self._update_monkey_total()
            return False
        for _label, field in fields:
            if not field.commit_value():
                field.focus_editor()
                self._update_monkey_total()
                return False
        return True

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
        worker.finished.connect(alive_callback(self, "_on_package_worker_finished", worker))
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

    def start_mobileperf(self):
        if not self._commit_numeric_inputs():
            return
        config = self.build_config()
        if not config.package:
            QMessageBox.warning(self, "Package Required", "Please enter a package name.")
            return
        if config.monkey_enabled and config.monkey_config.total_percentage != 100:
            answer = QMessageBox.question(
                self,
                "Monkey Event Mix",
                f"Monkey event percentages sum to {config.monkey_config.total_percentage}"
                f"%, not 100%.\n"
                "Continue with this event distribution?",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                defaultButton=QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._last_result_root = ""
        self._update_result_action()
        self._runner_finished_handled = False
        self.log_received.emit("INFO", "Starting mobileperf")
        try:
            self._runner.start(
                config,
                on_log=alive_signal_emitter(self, "log_received", "RAW"),
                on_finished=alive_signal_emitter(self, "runner_finished"),
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
            target=self._stop_runner_worker,
            args=(
                self._runner,
                alive_signal_emitter(self, "log_received", "ERROR"),
                alive_signal_emitter(self, "runner_finished"),
            ),
            name="adblab-mobileperf-stop",
            daemon=True,
        )
        self._stop_thread.start()

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
        result_dir = self._runner.latest_result_dir() or ""
        self._last_result_root = result_dir
        self._update_result_action()
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

    def _all_numeric_inputs(self) -> tuple[QWidget, ...]:
        return (
            self.frequency_input,
            self.timeout_input,
            self.dumpheap_input,
            self.monkey_throttle_input,
            self.monkey_seed_input,
            *self.monkey_pct_inputs.values(),
        )

    def _set_configuration_enabled(self, enabled: bool) -> None:
        """只锁定唯一配置分组，并保留严格输入的非法原文。"""

        self._configuration_locked = not enabled
        pending_invalid = {}
        for field in self._all_numeric_inputs():
            editor = self._numeric_editor(field)
            if editor is not None and not field.input_is_acceptable():
                pending_invalid[field] = editor.text()
        for section in self._configuration_sections:
            section.setEnabled(enabled)
        if enabled:
            self._on_monkey_enabled_changed(self.monkey_check.isChecked())
            worker_running = self._package_worker is not None and self._package_worker.isRunning()
            self.get_package_btn.setEnabled(not worker_running)
        for field, raw_text in pending_invalid.items():
            editor = self._numeric_editor(field)
            if editor is not None and editor.text() != raw_text:
                editor.setText(raw_text)

    def _set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self._set_configuration_enabled(not running)
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
            QLineEdit#monoField {{
                background-color: {c("INPUT_BG")};
                color: {c("TEXT_PRIMARY")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {BaseStyles.RADIUS_MD}px;
                selection-background-color: {c("SELECTION_BG")};
                selection-color: {c("SELECTION_TEXT")};
            }}
            QLineEdit#monoField:disabled,
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
        if (
            self._runner.is_running() is True
            and not self._shutdown_registered
            and not self._closing
        ):
            answer = QMessageBox.question(
                self,
                "Stop Active Collection",
                "MobilePerf is still running. Stop it and close this window?",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                defaultButton=QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
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
