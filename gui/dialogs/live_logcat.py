"""提供设备 Logcat 实时读取、筛选、高亮和导出对话框。"""

import os
import re
import subprocess
import threading
import time
import uuid
from math import ceil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
)

from gui.dialogs.lifecycle import is_qobject_alive, safe_disconnect
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from adblab.application.supervision import StopDisposition, TaskStopResult
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from models.base.command_runner import CommandRunner
from models.base.process_runner import ProcessRunner

THREADTIME_RE = re.compile(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+\d+\s+([VDIWEAFS])\s+")
FALLBACK_RE = re.compile(r"\b([VDIWEAFS])/[^\s:]+")

LEVEL_ORDER = {"V": 0, "D": 1, "I": 2, "W": 3, "E": 4, "F": 5, "S": 6}
LEVEL_LABELS = {
    "V": "Verbose+",
    "D": "Debug+",
    "I": "Info+",
    "W": "Warning+",
    "E": "Error+",
    "F": "Fatal",
    "S": "Silent",
}


class LogcatTerminationKind(str, Enum):
    CANCELLED = "cancelled"
    START_FAILED = "start_failed"
    UNEXPECTED_EXIT = "unexpected_exit"


@dataclass(frozen=True)
class LogcatTermination:
    kind: LogcatTerminationKind
    exit_code: int | None = None
    error_type: str = ""


@dataclass(frozen=True)
class LogcatBatch:
    lines: tuple[tuple[str, str, int], ...]
    dropped_before: int = 0


class LogcatWorker(QThread):
    BATCH_SIZE = 100
    BATCH_INTERVAL_SECONDS = 0.075
    MAX_INFLIGHT_BATCHES = 8

    line_ready = Signal(str, str, int)
    lines_ready = Signal(object)
    dropped_ready = Signal(int)
    status_changed = Signal(str)
    terminated = Signal(object)

    def __init__(self, device_ip: str, package: str = "", tag: str = ""):
        super().__init__()
        self.device_ip = device_ip
        self.package = package.strip()
        self.tag = tag.strip()
        self._process_key = f"logcat_{id(self)}"
        self._process_runner = ProcessRunner()
        self._proc = None
        self._stop_event = threading.Event()
        self._finished_event = threading.Event()
        self._launch_lock = threading.Lock()
        self._batch_lock = threading.Lock()
        self._inflight_batches = 0
        self._dropped_lines = 0

    def request_stop(self):
        """向 logcat 线程和受跟踪进程发送幂等停止请求。"""
        with self._launch_lock:
            self._stop_event.set()
            self._process_runner.request_stop(self._process_key)

    def force_stop(self, timeout_seconds: float) -> bool:
        """在给定预算内强制终止受跟踪进程。"""
        with self._launch_lock:
            self._stop_event.set()
            return self._process_runner.force_stop(self._process_key, timeout_seconds)

    def stop(self):
        """保留兼容停止入口；这里只请求停止，不等待进程退出。"""
        self.request_stop()

    def is_active(self) -> bool:
        try:
            thread_running = self.isRunning()
        except RuntimeError:
            # QThread 完成后 Qt 包装对象可能已延迟删除，但进程监督必须持续到被跟踪进程退出。
            thread_running = False
        return (
            thread_running
            or not self._finished_event.is_set()
            or self._process_key in self._process_runner.active_keys
        )

    def wait_for_stop(self, timeout_seconds: float) -> bool:
        """等待线程和进程均退出，但不超过调用方给定的预算。"""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            if not self.is_active():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._finished_event.wait(min(remaining, 0.05))

    def acknowledge_batch(self) -> None:
        with self._batch_lock:
            self._inflight_batches = max(0, self._inflight_batches - 1)

    def run(self):
        termination = None
        batch = []
        last_batch_at = time.monotonic()
        cmd = ["adb", "-s", self.device_ip, "logcat", "-T", "1", "-v", "threadtime"]
        filter_pid = None
        try:
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                return
            if self.package:
                r = CommandRunner.run(
                    ["adb", "-s", self.device_ip, "shell", "pidof", self.package],
                    timeout=5,
                )
                if not r.success:
                    termination = LogcatTermination(
                        LogcatTerminationKind.START_FAILED,
                        error_type="PidProbeFailed",
                    )
                    self.status_changed.emit("Unable to start package-filtered logcat")
                    return
                pid = r.output.strip().split()[0] if r.output.strip() else ""
                if pid and pid.isdigit():
                    filter_pid = int(pid)
                    cmd.extend(["--pid", pid])
                    self.status_changed.emit("Package filter active")
                else:
                    self.status_changed.emit("Selected package is not running; showing all logs")
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                return
            self.status_changed.emit("Starting logcat...")
            with self._launch_lock:
                if self._stop_event.is_set():
                    termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                    return
                self._proc = self._process_runner.start(
                    self._process_key,
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="ignore",
                )
            self.status_changed.emit("Logcat running")
            while not self._stop_event.is_set():
                line = self._proc.stdout.readline()
                if not line:
                    if self._proc.poll() is not None:
                        break
                    continue
                text = line.rstrip("\r\n")
                if text:
                    batch.append((text, self._parse_level(text), filter_pid or 0))
                    now = time.monotonic()
                    if (
                        len(batch) >= self.BATCH_SIZE
                        or now - last_batch_at >= self.BATCH_INTERVAL_SECONDS
                    ):
                        self._emit_batch(batch)
                        batch = []
                        last_batch_at = now
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
            else:
                termination = LogcatTermination(
                    LogcatTerminationKind.UNEXPECTED_EXIT,
                    exit_code=self._proc.poll(),
                )
        except Exception as exc:
            termination = LogcatTermination(
                (
                    LogcatTerminationKind.START_FAILED
                    if self._proc is None
                    else LogcatTerminationKind.UNEXPECTED_EXIT
                ),
                error_type=type(exc).__name__,
            )
            self.status_changed.emit("Logcat could not continue")
        finally:
            if batch:
                self._emit_batch(batch)
            self._emit_remaining_drop_count()
            try:
                process_exited = self._proc is None or self._proc.poll() is not None
            except OSError:
                process_exited = False
            if process_exited:
                self._process_runner.stop(self._process_key, timeout=0)
            else:
                self._process_runner.request_stop(self._process_key)
            if self._proc and self._proc.stdout:
                try:
                    self._proc.stdout.close()
                except Exception:
                    pass
            self._proc = None
            if termination is None:
                termination = LogcatTermination(
                    LogcatTerminationKind.CANCELLED
                    if self._stop_event.is_set()
                    else LogcatTerminationKind.UNEXPECTED_EXIT
                )
            self.terminated.emit(termination)
            self._finished_event.set()

    def _emit_batch(self, lines: list[tuple[str, str, int]]) -> None:
        with self._batch_lock:
            if self._inflight_batches >= self.MAX_INFLIGHT_BATCHES:
                self._dropped_lines += len(lines)
                return
            dropped = self._dropped_lines
            self._dropped_lines = 0
            self._inflight_batches += 1
        self.lines_ready.emit(LogcatBatch(tuple(lines), dropped))

    def _emit_remaining_drop_count(self) -> None:
        with self._batch_lock:
            dropped = self._dropped_lines
            self._dropped_lines = 0
        if dropped:
            self.dropped_ready.emit(dropped)

    @staticmethod
    def _parse_level(line: str) -> str:
        m = THREADTIME_RE.search(line) or FALLBACK_RE.search(line)
        return m.group(1) if m else "U"


class CurrentPackageWorker(QThread):
    package_ready = Signal(str)
    status_changed = Signal(str)

    def __init__(self, device_ip: str):
        super().__init__()
        self.device_ip = device_ip

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            r = CommandRunner.run(
                ["adb", "-s", self.device_ip, "shell", "dumpsys", "window"],
                timeout=5,
            )
            if self.isInterruptionRequested():
                return
            for line in r.output.splitlines():
                if "mCurrentFocus" in line:
                    m = re.search(r"Window\{.*?\s(\S+?)/", line)
                    if m:
                        self.package_ready.emit(m.group(1))
                        return
            self.status_changed.emit("No foreground app found")
        except Exception as e:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Error: {e}")


class LogcatHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = {}

    def set_theme(self, theme_colors: dict):
        self._colors = theme_colors
        self.rehighlight()

    def highlightBlock(self, text: str):
        level = LogcatWorker._parse_level(text)
        color = self._colors.get(level, self._colors.get("U", "#cccccc"))
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        self.setFormat(0, len(text), fmt)


class LiveLogcatDialog(QDialog):
    MAX_BUFFER = 8000
    CLEANUP_RECHECK_MS = 100

    def __init__(
        self,
        parent=None,
        device_ip: str = "",
        task_supervisor: QtTaskSupervisor | None = None,
        log_service=None,
    ):
        super().__init__(parent, Qt.Window)
        self.device_ip = device_ip
        self._task_supervisor = task_supervisor or QtTaskSupervisor.shared()
        self._log_service = log_service
        self._supervisor_owner_id = f"live-logcat-dialog-{uuid.uuid4()}"
        self._supervisor_task_id = None
        self.worker = None
        self._pkg_worker = None
        self.entries = []
        self._pending_visible_lines = []
        self._closing = False
        self._close_pending = False
        self._close_ready = False
        self._owner_cleanup_requested = False
        self._owner_cleanup_completed = False
        self._line_flush_timer = QTimer(self)
        self._line_flush_timer.setSingleShot(True)
        self._line_flush_timer.timeout.connect(self._flush_pending_lines)
        self._cleanup_recheck_timer = QTimer(self)
        self._cleanup_recheck_timer.setSingleShot(True)
        self._cleanup_recheck_timer.timeout.connect(self._poll_close_cleanup)

        self.setWindowTitle(f"Live Logcat - {device_ip}")
        self.setWindowIcon(get_themed_icon("scroll.svg"))
        self.setMinimumSize(980, 620)
        self.resize(1000, 650)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        # 二级日志窗口不参与“最后窗口关闭即退出”的应用级判定。
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._task_supervisor.task_stopped.connect(self._on_task_stopped)
        self._task_supervisor.owner_stopped.connect(self._on_owner_stopped)

    def _debug_lifecycle(self, phase: str, **fields):
        """记录不包含设备标识和日志正文的窗口生命周期诊断。"""
        if self._log_service is None:
            return
        values = {
            "dialog": type(self).__name__,
            "phase": phase,
            **fields,
        }
        details = " ".join(f"{name}={value}" for name, value in sorted(values.items()))
        self._log_service.log("DEBUG", f"ui.secondary_window {details}")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        f1 = QHBoxLayout()
        f1.setSpacing(6)
        f1.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        self.level_combo.addItem("All", None)
        for code in ("V", "D", "I", "W", "E", "F"):
            self.level_combo.addItem(LEVEL_LABELS[code], code)
        self.level_combo.currentIndexChanged.connect(self._rebuild)
        self.level_combo.setMinimumWidth(120)
        f1.addWidget(self.level_combo)
        f1.addWidget(QLabel("Package:"))
        self.pkg_input = QLineEdit()
        self.pkg_input.setPlaceholderText("com.example.app")
        f1.addWidget(self.pkg_input, 1)
        self.btn_get_pkg = QPushButton("Current Package")
        self.btn_get_pkg.setIcon(get_themed_icon("target.svg"))
        self.btn_get_pkg.setIconSize(QSize(14, 14))
        self.btn_get_pkg.setToolTip("Fetch current foreground app package")
        self.btn_get_pkg.setMinimumWidth(120)
        self.btn_get_pkg.clicked.connect(self._fetch_current_pkg)
        f1.addWidget(self.btn_get_pkg)
        f1.addWidget(QLabel("Tag:"))
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("ActivityManager")
        f1.addWidget(self.tag_input, 1)
        layout.addLayout(f1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(get_themed_icon("play.svg"))
        self.start_btn.setIconSize(QSize(14, 14))
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(get_themed_icon("stop-circle.svg"))
        self.stop_btn.setIconSize(QSize(14, 14))
        self.stop_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setIcon(get_themed_icon("broom.svg"))
        self.clear_btn.setIconSize(QSize(14, 14))
        self.export_btn = QPushButton("Export")
        self.export_btn.setIcon(get_themed_icon("file-arrow-down.svg"))
        self.export_btn.setIconSize(QSize(14, 14))
        self.wrap_btn = QPushButton("Wrap")
        self.wrap_btn.setIcon(get_themed_icon("arrows-left-right.svg"))
        self.wrap_btn.setIconSize(QSize(14, 14))
        self.wrap_btn.setCheckable(True)
        self.wrap_btn.setChecked(True)
        self.wrap_btn.setToolTip("Toggle line wrapping")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)
        self.clear_btn.clicked.connect(self._clear)
        self.export_btn.clicked.connect(self._export)
        self.wrap_btn.clicked.connect(self._toggle_wrap)
        for b in (self.start_btn, self.stop_btn, self.clear_btn, self.export_btn, self.wrap_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.output.setUndoRedoEnabled(False)
        self.output.document().setMaximumBlockCount(self.MAX_BUFFER)
        layout.addWidget(self.output, 1)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        layout.addWidget(self.status_bar)

        self.highlighter = LogcatHighlighter(self.output.document())

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self)
        BS = BaseStyles
        ui_font = BS.font_for_role(FontRole.UI)
        mono_font = BS.font_for_role(FontRole.MONO)
        log_font = BS.font_for_role(FontRole.LOG)
        self.setStyleSheet(BS.PANEL_BASE_STYLE())
        self.setFont(ui_font)
        for field in (self.pkg_input, self.tag_input):
            field.setFont(mono_font)
        fg = BS.color("TEXT_PRIMARY")
        border = BS.color("BORDER_COLOR")
        self.output.setStyleSheet(
            f"background-color: {BS.color('LOG_BACKGROUND')}; "
            f"color: {BS.color('LOG_TEXT_COLOR')}; "
            f"border: 1px solid {border}; border-radius: {BS.RADIUS_MD}px;"
        )
        self.output.setFont(log_font)
        self.output.document().setDefaultFont(log_font)
        self.status_bar.setStyleSheet(BS.STATUS_BAR_STYLE())
        self.level_combo.setMinimumWidth(120)
        self.level_combo.setMinimumWidth(max(120, self.level_combo.sizeHint().width()))
        self.btn_get_pkg.setMinimumWidth(120)
        self.btn_get_pkg.setMinimumWidth(max(120, self.btn_get_pkg.sizeHint().width()))

        # Logcat 等级颜色跟随当前主题更新。
        hl_colors = {
            "V": "#8899aa",
            "D": "#6db3d8",
            "I": "#6cc76c",
            "W": "#e0a040",
            "E": "#e05555",
            "F": "#ee55aa",
            "S": BS.color("TEXT_SECONDARY"),
            "U": fg,
        }
        self.highlighter.set_theme(hl_colors)

    # ── 筛选 ────────────────────────────────────────────────────────────

    def _min_level(self):
        code = self.level_combo.currentData()
        return LEVEL_ORDER.get(code, -1) if code else None

    def _passes(self, level: str, tag_part: str) -> bool:
        minimum = self._min_level()
        if minimum is not None and LEVEL_ORDER.get(level, -1) < minimum:
            return False
        tag_filter = self.tag_input.text().strip()
        if tag_filter and tag_filter.lower() not in tag_part.lower():
            return False
        return True

    def _rebuild(self):
        self._line_flush_timer.stop()
        self._pending_visible_lines.clear()
        self.output.clear()
        visible = [t for t, lv, tg, _ in self.entries if self._passes(lv, tg)]
        if visible:
            self.output.setPlainText("\n".join(visible) + "\n")

    # ── 操作 ────────────────────────────────────────────────────────────

    def _fetch_current_pkg(self):
        if self._pkg_worker and self._pkg_worker.isRunning():
            return
        self.status_bar.showMessage("Fetching current package...")
        self.btn_get_pkg.setEnabled(False)
        worker = CurrentPackageWorker(self.device_ip)
        worker.package_ready.connect(self._on_current_pkg)
        worker.status_changed.connect(self._on_status)
        finished_handler = self._on_pkg_worker_finished_signal
        worker._dialog_finished_handler = finished_handler
        worker.finished.connect(finished_handler, Qt.ConnectionType.QueuedConnection)
        task_id = f"current-package-{uuid.uuid4()}"
        worker._supervisor_task_id = task_id
        try:
            self._task_supervisor.supervisor.register(
                task_id,
                owner_id=self._supervisor_owner_id,
                kind="current_package_probe",
                request_stop=worker.requestInterruption,
                wait=lambda timeout, _worker=worker: _worker.wait(max(0, ceil(timeout * 1000))),
                is_running=worker.isRunning,
            )
        except Exception:
            self._disconnect_pkg_worker(worker)
            worker.deleteLater()
            self.btn_get_pkg.setEnabled(True)
            self.status_bar.showMessage("Unable to supervise package lookup")
            return
        self._pkg_worker = worker
        worker.start()

    def _start(self):
        if self.worker and self.worker.is_active():
            return
        self.entries.clear()
        self._pending_visible_lines.clear()
        self._line_flush_timer.stop()
        self.output.clear()
        pkg = self.pkg_input.text().strip()
        tag = self.tag_input.text().strip()
        worker = LogcatWorker(self.device_ip, package=pkg, tag=tag)
        task_id = f"live-logcat-{uuid.uuid4()}"
        lines_handler = self._on_lines_signal
        dropped_handler = self._on_dropped_signal
        status_handler = self._on_worker_status_signal
        ended_handler = self._on_worker_terminated_signal
        finished_handler = self._on_worker_finished_signal
        worker._dialog_lines_handler = lines_handler
        worker._dialog_dropped_handler = dropped_handler
        worker._dialog_status_handler = status_handler
        worker._dialog_ended_handler = ended_handler
        worker._dialog_finished_handler = finished_handler
        worker._supervisor_task_id = task_id
        connection_type = Qt.ConnectionType.QueuedConnection
        worker.lines_ready.connect(lines_handler, connection_type)
        worker.dropped_ready.connect(dropped_handler, connection_type)
        worker.status_changed.connect(status_handler, connection_type)
        worker.terminated.connect(ended_handler, connection_type)
        worker.finished.connect(finished_handler, connection_type)
        try:
            self._task_supervisor.supervisor.register(
                task_id,
                owner_id=self._supervisor_owner_id,
                kind="live_logcat",
                request_stop=worker.request_stop,
                wait=worker.wait_for_stop,
                is_running=worker.is_active,
                force_stop=worker.force_stop,
            )
        except Exception:
            self.status_bar.showMessage("Unable to supervise logcat task")
            worker.deleteLater()
            return
        self.worker = worker
        self._supervisor_task_id = task_id
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        worker.start()

    def _stop(self):
        if self.worker and self._supervisor_task_id:
            self.status_bar.showMessage("Stopping...")
            self.stop_btn.setEnabled(False)
            self._task_supervisor.stop_async(self._supervisor_task_id)

    def _clear(self):
        self.entries.clear()
        self._pending_visible_lines.clear()
        self._line_flush_timer.stop()
        self.output.clear()
        self.status_bar.showMessage("Cleared")

    def _toggle_wrap(self):
        if self.wrap_btn.isChecked():
            self.output.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            self.output.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.wrap_btn.setText("Wrap")
            self.status_bar.showMessage("Line wrap: ON")
        else:
            self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.output.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            self.wrap_btn.setText("No Wrap")
            self.status_bar.showMessage("Line wrap: OFF - horizontal scroll enabled")

    def _export(self):
        from core.settings_manager import AppSettings

        save_dir = AppSettings.instance().save_directory
        name = f"logcat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fp, _ = QFileDialog.getSaveFileName(
            self,
            "Export",
            os.path.join(save_dir, name),
            "Text Files (*.txt);;All Files (*)",
        )
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(self.output.toPlainText())
                self.status_bar.showMessage(f"Exported to {fp}")
            except OSError as e:
                QMessageBox.critical(self, "Error", str(e))

    # ── 信号槽 ──────────────────────────────────────────────────────────

    @Slot(object)
    def _on_lines_signal(self, batch: LogcatBatch):
        """通过对话框 QObject 槽接收批次，避免匿名回调越过窗口生命周期。"""
        worker = self.sender()
        if worker is not None:
            self._on_lines(worker, batch)

    @Slot(int)
    def _on_dropped_signal(self, count: int):
        """接收当前工作线程报告的背压丢弃数量。"""
        worker = self.sender()
        if worker is not None:
            self._on_dropped(worker, count)

    @Slot(str)
    def _on_worker_status_signal(self, message: str):
        """接收当前工作线程的状态变更。"""
        worker = self.sender()
        if worker is not None:
            self._on_worker_status(worker, message)

    @Slot(object)
    def _on_worker_terminated_signal(self, result: LogcatTermination):
        """接收当前工作线程的终止语义。"""
        worker = self.sender()
        if worker is not None:
            self._on_worker_terminated(worker, result)

    @Slot()
    def _on_worker_finished_signal(self):
        """在线程 finished 信号到达 GUI 线程后释放工作对象。"""
        worker = self.sender() or self.worker
        if worker is not None:
            self._on_worker_finished(worker)

    @Slot()
    def _on_pkg_worker_finished_signal(self):
        """在包名查询线程 finished 信号到达 GUI 线程后释放工作对象。"""
        worker = self.sender() or self._pkg_worker
        if worker is not None:
            self._on_pkg_worker_finished(worker)

    @staticmethod
    def _extract_tag(line: str) -> str:
        """从 threadtime 格式日志中提取 TAG 字段。"""
        parts = line.split(None, 6)
        if len(parts) >= 6:
            tag_raw = parts[5]
            if tag_raw.endswith(":"):
                return tag_raw[:-1]
        return ""

    def _on_line(self, text: str, level: str, pid: int = 0):
        if self._closing:
            return
        tag_part = self._extract_tag(text)
        self.entries.append((text, level, tag_part, pid))
        if len(self.entries) > self.MAX_BUFFER:
            self.entries = self.entries[-self.MAX_BUFFER :]
        if self._passes(level, tag_part):
            self._pending_visible_lines.append(text)
            if len(self._pending_visible_lines) > self.MAX_BUFFER:
                self._pending_visible_lines = self._pending_visible_lines[-self.MAX_BUFFER :]
            self._schedule_line_flush()

    def _on_lines(self, worker: LogcatWorker, batch: LogcatBatch):
        try:
            if self._closing or self.worker is not worker:
                return
            if batch.dropped_before:
                self.status_bar.showMessage(
                    f"Logcat running; {batch.dropped_before} lines dropped under load"
                )
            for text, level, pid in batch.lines:
                self._on_line(text, level, pid)
        finally:
            worker.acknowledge_batch()

    def _on_dropped(self, worker: LogcatWorker, count: int):
        if not self._closing and self.worker is worker:
            self.status_bar.showMessage(f"Logcat running; {count} lines dropped under load")

    def _schedule_line_flush(self):
        if not self._line_flush_timer.isActive():
            self._line_flush_timer.start(75)

    def _flush_pending_lines(self):
        if self._closing or not self._pending_visible_lines:
            return
        lines = self._pending_visible_lines
        self._pending_visible_lines = []
        # 高频 logcat 输出合并成一次 QTextDocument 更新，Stop/过滤按钮会更容易抢到事件循环。
        self.output.appendPlainText("\n".join(lines))
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.ensureCursorVisible()

    def _on_status(self, msg: str):
        if self._closing:
            return
        self.status_bar.showMessage(msg)

    def _on_worker_status(self, worker: LogcatWorker, msg: str):
        if self.worker is worker:
            self._on_status(msg)

    def _on_worker_terminated(self, worker: LogcatWorker, result: LogcatTermination):
        if self._closing or self.worker is not worker:
            return
        if result.kind is LogcatTerminationKind.CANCELLED:
            self.status_bar.showMessage("Logcat stop requested")
        elif result.kind is LogcatTerminationKind.START_FAILED:
            self.status_bar.showMessage("Logcat failed to start")
        else:
            self.status_bar.showMessage("Logcat ended unexpectedly")

    def _on_task_stopped(self, result: TaskStopResult):
        if (
            self._closing
            or result.owner_id != self._supervisor_owner_id
            or result.task_id != self._supervisor_task_id
        ):
            return
        if result.disposition is StopDisposition.GRACEFUL:
            self.status_bar.showMessage("Logcat stopped")
        elif result.disposition is StopDisposition.FORCED:
            self.status_bar.showMessage("Logcat force-stopped")
        elif result.disposition is StopDisposition.TIMED_OUT:
            self.status_bar.showMessage("Logcat cleanup timed out; task remains supervised")
        elif result.disposition is StopDisposition.ALREADY_STOPPED:
            self.status_bar.showMessage("Logcat already stopped")
        else:
            self.status_bar.showMessage("Logcat cleanup failed")

    def _on_current_pkg(self, package: str):
        if self._closing:
            return
        self.pkg_input.setText(package)
        self.status_bar.showMessage(f"Package: {package}")

    def _release_pkg_worker(self, worker: CurrentPackageWorker) -> bool:
        """释放已经停止的包名查询线程，并返回它是否仍是当前线程。"""
        self._disconnect_pkg_worker(worker)
        task_id = getattr(worker, "_supervisor_task_id", None)
        if task_id:
            self._task_supervisor.supervisor.unregister(task_id)
        was_current = self._pkg_worker is worker
        if was_current:
            self._pkg_worker = None
        if is_qobject_alive(worker):
            worker.deleteLater()
        return was_current

    def _on_pkg_worker_finished(self, worker: CurrentPackageWorker):
        if (
            self._closing
            and self._owner_cleanup_requested
            and not self._owner_cleanup_completed
        ):
            self._debug_lifecycle("worker_finished_waiting", worker_kind="package_probe")
            return
        was_current = self._release_pkg_worker(worker)
        if self._closing:
            self._try_finalize_close("package_worker_finished")
        elif was_current:
            self.btn_get_pkg.setEnabled(True)

    def _release_logcat_worker(self, worker: LogcatWorker) -> bool:
        """仅在线程和受跟踪进程都停止后释放 Logcat 工作对象。"""
        if worker.is_active():
            return False
        self._disconnect_worker(worker)
        task_id = getattr(worker, "_supervisor_task_id", None)
        if task_id:
            self._task_supervisor.supervisor.unregister(task_id)
        was_current = self.worker is worker
        if was_current:
            self.worker = None
            self._supervisor_task_id = None
        if is_qobject_alive(worker):
            worker.deleteLater()
        return was_current

    def _on_worker_finished(self, worker: LogcatWorker | None = None):
        worker = worker or self.worker
        if worker is None:
            return
        if (
            self._closing
            and self._owner_cleanup_requested
            and not self._owner_cleanup_completed
        ):
            self._debug_lifecycle("worker_finished_waiting", worker_kind="live_logcat")
            return
        was_current = self._release_logcat_worker(worker)
        if self.worker is worker:
            self._debug_lifecycle("worker_retained", reason="process_still_active")
            return
        if self._closing:
            self._try_finalize_close("logcat_worker_finished")
            return
        if was_current:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _owner_residual_tasks(self):
        """返回仍由当前日志窗口负责的受监督资源。"""
        try:
            snapshots = self._task_supervisor.supervisor.active_snapshot()
        except Exception:
            return (None,)
        return tuple(
            item for item in snapshots if item.owner_id == self._supervisor_owner_id
        )

    def _schedule_cleanup_recheck(self) -> None:
        """在停止流程返回后继续观察晚退出的线程或外部进程。"""
        if (
            self._close_pending
            and not self._close_ready
            and not self._cleanup_recheck_timer.isActive()
        ):
            self._cleanup_recheck_timer.start(self.CLEANUP_RECHECK_MS)

    def _poll_close_cleanup(self) -> None:
        """重新核对资源屏障，避免线程先结束而进程晚退出时丢失唤醒。"""
        if self._try_finalize_close("cleanup_recheck", log_deferred=False):
            return
        if self._owner_cleanup_completed:
            self._schedule_cleanup_recheck()

    def _prune_stopped_owner_tasks(self, residual) -> None:
        """注销已确认停止但仍残留在监督注册表中的当前窗口任务。"""
        for item in residual:
            if item is not None and not item.running:
                self._task_supervisor.supervisor.unregister(item.task_id)

    def _try_finalize_close(self, trigger: str, *, log_deferred: bool = True) -> bool:
        """仅在工作对象和监督注册均清零后允许销毁窗口。"""
        if not self._close_pending or self._close_ready:
            return False
        if self._owner_cleanup_requested and not self._owner_cleanup_completed:
            if log_deferred:
                self._debug_lifecycle(
                    "close_deferred",
                    reason="owner_cleanup_running",
                    trigger=trigger,
                )
            return False
        if self.worker is not None and not self.worker.is_active():
            self._release_logcat_worker(self.worker)
        if self._pkg_worker is not None and not self._pkg_worker.isRunning():
            self._release_pkg_worker(self._pkg_worker)
        residual = self._owner_residual_tasks()
        self._prune_stopped_owner_tasks(residual)
        residual = self._owner_residual_tasks()
        if self.worker is not None or self._pkg_worker is not None or residual:
            if log_deferred:
                self._debug_lifecycle(
                    "close_deferred",
                    package_worker_retained=self._pkg_worker is not None,
                    residual_count=len(residual),
                    trigger=trigger,
                    worker_retained=self.worker is not None,
                )
            if self._owner_cleanup_completed:
                self._schedule_cleanup_recheck()
            return False
        if self._cleanup_recheck_timer.isActive():
            self._cleanup_recheck_timer.stop()
        self._close_ready = True
        safe_disconnect(self._task_supervisor.owner_stopped, self._on_owner_stopped)
        self._debug_lifecycle("resources_stopped", trigger=trigger)
        QTimer.singleShot(0, self.close)
        return True

    def _on_owner_stopped(self, owner_id: str, results):
        """停止流程返回后复核真实资源屏障，不把超时误判为已停止。"""
        if owner_id != self._supervisor_owner_id or not self._close_pending or self._close_ready:
            return
        results = tuple(results or ())
        unresolved = tuple(result for result in results if not result.stopped)
        self._owner_cleanup_completed = True
        residual = self._owner_residual_tasks()
        self._debug_lifecycle(
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
            (worker.package_ready, self._on_current_pkg),
            (worker.status_changed, self._on_status),
        ):
            if handler is not None:
                safe_disconnect(signal_, handler)
        handler = getattr(worker, "_dialog_finished_handler", None)
        if handler is not None and not keep_finished:
            safe_disconnect(worker.finished, handler)
            worker._dialog_finished_handler = None

    def closeEvent(self, event):
        """先隐藏并清理后台资源，完成后再销毁日志窗口。"""
        if self._close_ready:
            self._debug_lifecycle("close_accepted")
            event.accept()
            super().closeEvent(event)
            return
        if self._close_pending:
            self._debug_lifecycle("close_ignored", reason="cleanup_pending")
            event.ignore()
            return
        self._debug_lifecycle(
            "close_requested",
            package_worker_active=bool(
                self._pkg_worker is not None and self._pkg_worker.isRunning()
            ),
            worker_active=bool(self.worker is not None and self.worker.is_active()),
        )
        self._close_pending = True
        self._closing = True
        should_stop_owner = False
        self._line_flush_timer.stop()
        self._pending_visible_lines.clear()
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        safe_disconnect(self._task_supervisor.task_stopped, self._on_task_stopped)
        if self.worker:
            w = self.worker
            if w.is_active():
                # 数据信号停止进入界面，但 finished 槽必须保留为真实资源屏障。
                self._disconnect_worker(w, keep_finished=True)
                should_stop_owner = True
            else:
                self._release_logcat_worker(w)
        if self._pkg_worker:
            w = self._pkg_worker
            if w.isRunning():
                self._disconnect_pkg_worker(w, keep_finished=True)
                should_stop_owner = True
            else:
                self._release_pkg_worker(w)
        residual = self._owner_residual_tasks()
        if should_stop_owner or residual:
            # 关闭动作必须立即反馈，但 QObject 要保留到线程和进程停止完成。
            self._owner_cleanup_requested = True
            self._debug_lifecycle(
                "hidden_for_cleanup",
                residual_count=len(residual),
            )
            event.ignore()
            self.hide()
            self._task_supervisor.stop_owner_async(
                self._supervisor_owner_id,
                deadline=6.0,
            )
            return
        self._close_ready = True
        self._debug_lifecycle("close_accepted", reason="no_active_resource")
        safe_disconnect(self._task_supervisor.owner_stopped, self._on_owner_stopped)
        super().closeEvent(event)
