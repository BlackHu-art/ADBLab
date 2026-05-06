"""Theme-aware log panel with auto-scroll, line trimming, and re-render on theme change."""

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QTextEdit, QVBoxLayout
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from gui.styles.base_styles import BaseStyles
from core.log_service import LogService


class LogPanel(QWidget):

    LEVEL_COLORS = {
        "DEBUG": BaseStyles.DEBUG_COLOR,
        "INFO": BaseStyles.INFO_COLOR,
        "SUCCESS": BaseStyles.SUCCESS_COLOR,
        "WARNING": BaseStyles.WARNING_COLOR,
        "ERROR": BaseStyles.ERROR_COLOR,
        "CRITICAL": BaseStyles.CRITICAL_COLOR,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._max_lines = 1000
        self._entries = []  # (timestamp_str, level, message) for re-render
        self._init_ui()
        self._connect_services()
        BaseStyles.theme_changed.connect(self._on_theme_changed)

    def _apply_style(self):
        """Apply theme colors to the text area stylesheet."""
        self.text_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BaseStyles.color('LOG_BACKGROUND')};
                color: {BaseStyles.color('LOG_TEXT_COLOR')};
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
                border-radius: {BaseStyles.RADIUS_LG}px;
                padding: 8px;
            }}
            {BaseStyles.SCROLLBAR_STYLE()}
        """)

    def _on_theme_changed(self, _name: str):
        """Re-render all entries so text colors match the new theme."""
        self._apply_style()
        self._rerender_all()

    def _init_ui(self):
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        self.text_output.setUndoRedoEnabled(False)

        log_font = QFont(BaseStyles.LOG_FONT, BaseStyles.LOG_FONT_SIZE)
        log_font.setStyleHint(QFont.Monospace)
        self.text_output.setFont(log_font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 8, 8)
        layout.addWidget(self.text_output)

        self._apply_style()

    def _connect_services(self):
        LogService().log_received.connect(
            self._append_log, Qt.ConnectionType.QueuedConnection
        )

    def _append_log(self, level: str, message: str):
        """Add a log entry and render it with theme-appropriate colors."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._entries.append((timestamp, level, message))
        self._render_entry(timestamp, level, message)
        self._auto_scroll()
        self._trim_excess_lines()

    def _render_entry(self, timestamp: str, level: str, message: str):
        """Render a single log line with correct colors for the current theme."""
        cursor = self.text_output.textCursor()
        cursor.movePosition(QTextCursor.End)

        ts_fmt = QTextCharFormat()
        ts_fmt.setForeground(QColor(BaseStyles.TIMESTAMP_COLOR))
        cursor.insertText(f"{timestamp} ", ts_fmt)

        lv_fmt = QTextCharFormat()
        lv_fmt.setForeground(QColor(self.LEVEL_COLORS.get(level, BaseStyles.INFO_COLOR)))
        cursor.insertText(f"[{level}]", lv_fmt)

        msg_fmt = QTextCharFormat()
        msg_fmt.setForeground(QColor(BaseStyles.color('LOG_TEXT_COLOR')))
        cursor.insertText(f" {message}\n", msg_fmt)

    def _rerender_all(self):
        """Clear and re-render all stored entries (called on theme change)."""
        self.text_output.clear()
        for ts, level, msg in self._entries:
            self._render_entry(ts, level, msg)
        self._auto_scroll()

    def _auto_scroll(self):
        self.text_output.ensureCursorVisible()
        scrollbar = self.text_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _trim_excess_lines(self):
        """Remove oldest lines when exceeding the max line count."""
        block_count = self.text_output.document().blockCount()
        if block_count > self._max_lines:
            excess = block_count - self._max_lines
            cursor = self.text_output.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, excess)
            cursor.removeSelectedText()
            # Trim stored entries as well
            self._entries = self._entries[excess:]

    def clear(self):
        """Clear all log content."""
        self._entries.clear()
        self.text_output.clear()

    def set_max_lines(self, max_lines: int):
        self._max_lines = max(max_lines, 100)
        self._trim_excess_lines()
