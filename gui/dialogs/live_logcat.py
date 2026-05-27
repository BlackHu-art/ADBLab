"""
Live Logcat viewer - stream, filter, highlight and export device logs.

Adapted to use ADBLab's BaseStyles theme system.
"""

import os
import re
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
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

from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar

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


class LogcatWorker(QThread):
    line_ready = Signal(str, str, int)
    status_changed = Signal(str)

    def __init__(self, device_ip: str, package: str = "", tag: str = ""):
        super().__init__()
        self.device_ip = device_ip
        self.package = package.strip()
        self.tag = tag.strip()
        self._proc = None
        self._stop = False

    def stop(self):
        self._stop = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        cmd = ["adb", "-s", self.device_ip, "logcat", "-T", "1", "-v", "threadtime"]
        # Package filter via PID
        filter_pid = None
        if self.package:
            try:
                cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                r = subprocess.run(
                    ["adb", "-s", self.device_ip, "shell", "pidof", self.package],
                    capture_output=True, text=True,
                    creationflags=cf, timeout=5,
                    encoding="utf-8", errors="ignore",
                )
                pid = r.stdout.strip().split()[0] if r.stdout.strip() else ""
                if pid and pid.isdigit():
                    filter_pid = int(pid)
                    cmd.extend(["--pid", pid])
                    self.status_changed.emit(f"Filtering PID {pid} ({self.package})")
                else:
                    self.status_changed.emit(f"Package {self.package} not running, showing all")
            except Exception:
                self.status_changed.emit(f"Could not find PID for {self.package}")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.status_changed.emit("Starting logcat...")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
                bufsize=1, encoding="utf-8", errors="ignore",
                creationflags=creationflags,
            )
            self.status_changed.emit("Logcat running")
            while not self._stop:
                line = self._proc.stdout.readline()
                if not line:
                    if self._proc.poll() is not None:
                        break
                    continue
                text = line.rstrip("\r\n")
                if text:
                    self.line_ready.emit(text, self._parse_level(text), filter_pid or 0)
        except Exception as e:
            self.status_changed.emit(f"Error: {e}")
        finally:
            if self._proc:
                try:
                    if self._proc.poll() is None:
                        self._proc.terminate()
                        self._proc.wait(2)
                except Exception:
                    pass
                try:
                    self._proc.stdout.close()
                except Exception:
                    pass
            self.status_changed.emit("Logcat stopped" if self._stop else "Logcat ended")
            self._proc = None

    @staticmethod
    def _parse_level(line: str) -> str:
        m = THREADTIME_RE.search(line) or FALLBACK_RE.search(line)
        return m.group(1) if m else "U"


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

    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent, Qt.Window)
        self.device_ip = device_ip
        self.worker = None
        self.entries = []
        self._closing = False

        self.setWindowTitle(f"Live Logcat - {device_ip}")
        self.setWindowIcon(get_themed_icon("scroll.svg"))
        self.setMinimumSize(980, 620)
        self.resize(1000, 650)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        from gui.styles import BaseStyles as BS
        BS.theme_changed.connect(self._apply_theme)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # Filter bar — single row: Level | Package | Tag
        f1 = QHBoxLayout()
        f1.setSpacing(6)
        f1.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        self.level_combo.addItem("All", None)
        for code in ("V", "D", "I", "W", "E", "F"):
            self.level_combo.addItem(LEVEL_LABELS[code], code)
        self.level_combo.currentIndexChanged.connect(self._rebuild)
        self.level_combo.setFixedWidth(120)
        f1.addWidget(self.level_combo)
        f1.addWidget(QLabel("Package:"))
        self.pkg_input = QLineEdit()
        self.pkg_input.setPlaceholderText("com.example.app")
        self.pkg_input.setFont(QFont("Consolas", 9))
        f1.addWidget(self.pkg_input, 1)
        self.btn_get_pkg = QPushButton("Current Package")
        self.btn_get_pkg.setIcon(get_themed_icon("target.svg"))
        self.btn_get_pkg.setIconSize(QSize(14, 14))
        self.btn_get_pkg.setToolTip("Fetch current foreground app package")
        self.btn_get_pkg.setFixedWidth(120)
        self.btn_get_pkg.clicked.connect(self._fetch_current_pkg)
        f1.addWidget(self.btn_get_pkg)
        f1.addWidget(QLabel("Tag:"))
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("ActivityManager")
        self.tag_input.setFont(QFont("Consolas", 9))
        f1.addWidget(self.tag_input, 1)
        layout.addLayout(f1)

        # Buttons
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

        # Output
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.output.setUndoRedoEnabled(False)
        self.output.document().setMaximumBlockCount(self.MAX_BUFFER)
        self.output.setFont(QFont("Consolas", 9))
        layout.addWidget(self.output, 1)

        # Status
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        layout.addWidget(self.status_bar)

        # Highlighter
        self.highlighter = LogcatHighlighter(self.output.document())

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        from gui.styles import BaseStyles as BS

        self.setStyleSheet(BS.PANEL_BASE_STYLE())
        fg = BS.color("TEXT_PRIMARY")
        border = BS.color("BORDER_COLOR")
        self.output.setStyleSheet(
            f"background-color: {BS.color('LOG_BACKGROUND')}; "
            f"color: {BS.color('LOG_TEXT_COLOR')}; "
            f"border: 1px solid {border}; border-radius: {BS.RADIUS_MD}px;"
        )
        self.status_bar.setStyleSheet(BS.STATUS_BAR_STYLE())

        # Logcat level colors - theme-aware
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

    # ── Filter ───────────────────────────────────────────────────────────

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
        self.output.clear()
        visible = [t for t, lv, tg, _ in self.entries if self._passes(lv, tg)]
        if visible:
            self.output.setPlainText("\n".join(visible) + "\n")

    # ── Actions ──────────────────────────────────────────────────────────

    def _fetch_current_pkg(self):
        import re

        try:
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run(
                ["adb", "-s", self.device_ip, "shell", "dumpsys", "window"],
                capture_output=True, text=True,
                creationflags=cf, timeout=5,
                encoding="utf-8", errors="ignore",
            )
            for line in r.stdout.splitlines():
                if "mCurrentFocus" in line:
                    m = re.search(r"Window\{.*?\s(\S+?)/", line)
                    if m:
                        self.pkg_input.setText(m.group(1))
                        self.status_bar.showMessage(f"Package: {m.group(1)}")
                        return
            self.status_bar.showMessage("No foreground app found")
        except Exception as e:
            self.status_bar.showMessage(f"Error: {e}")

    def _start(self):
        if self.worker and self.worker.isRunning():
            return
        self.entries.clear()
        self.output.clear()
        pkg = self.pkg_input.text().strip()
        tag = self.tag_input.text().strip()
        self.worker = LogcatWorker(self.device_ip, package=pkg, tag=tag)
        self.worker.line_ready.connect(self._on_line)
        self.worker.status_changed.connect(self._on_status)
        self.worker.finished.connect(self._on_worker_finished)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()

    def _stop(self):
        if self.worker:
            self.status_bar.showMessage("Stopping...")
            self.worker.stop()

    def _clear(self):
        self.entries.clear()
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
            self.status_bar.showMessage("Line wrap: OFF — horizontal scroll enabled")

    def _export(self):
        from core.settings_manager import AppSettings
        save_dir = AppSettings.instance().save_directory
        name = f"logcat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fp, _ = QFileDialog.getSaveFileName(
            self, "Export", os.path.join(save_dir, name),
            "Text Files (*.txt);;All Files (*)",
        )
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(self.output.toPlainText())
                self.status_bar.showMessage(f"Exported to {fp}")
            except OSError as e:
                QMessageBox.critical(self, "Error", str(e))

    # ── Slots ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_tag(line: str) -> str:
        """Extract tag from threadtime: MM-DD HH:MM:SS.mmm PID TID L TAG: msg"""
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
            self.output.appendPlainText(text)
            self.output.moveCursor(QTextCursor.MoveOperation.End)
            self.output.ensureCursorVisible()

    def _on_status(self, msg: str):
        if self._closing:
            return
        self.status_bar.showMessage(msg)

    def _on_worker_finished(self):
        self.worker = None
        if self._closing:
            return
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ── Cleanup ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._closing = True
        from gui.styles import BaseStyles as BS
        try:
            BS.theme_changed.disconnect(self._apply_theme)
        except (TypeError, RuntimeError):
            pass
        if self.worker:
            w = self.worker
            self.worker = None
            try:
                w.finished.disconnect(self._on_worker_finished)
            except (TypeError, RuntimeError):
                pass
            if w.isRunning():
                w.stop()
                w.setParent(None)
                import threading
                threading.Thread(target=lambda: w.wait(3000), daemon=True).start()
        super().closeEvent(event)
