"""Theme-aware log panel with auto-scroll, line trimming, and re-render on theme change."""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from core.log_service import LogService
from gui.styles import BaseStyles


class LogPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.settings_manager import AppSettings
        self._max_lines = AppSettings.instance().get("log_max_lines", 2000)
        self._entries = []
        self._init_ui()
        self._connect_services()
        BaseStyles.theme_changed.connect(self._on_theme_changed)

    def _apply_style(self):
        c = BaseStyles.color
        self.text_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: {c('LOG_BACKGROUND')};
                color: {c('LOG_TEXT_COLOR')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {BaseStyles.RADIUS_LG}px;
                padding: 4px;
            }}
            {BaseStyles.SCROLLBAR_STYLE()}
        """)

    def _on_theme_changed(self, _name: str):
        from core.settings_manager import AppSettings
        log_size = AppSettings.instance().get("log_font_size", 9)
        log_font = QFont(BaseStyles.LOG_FONT, log_size)
        log_font.setStyleHint(QFont.Monospace)
        self.text_output.setFont(log_font)
        self._max_lines = AppSettings.instance().get("log_max_lines", 2000)
        self._apply_style()
        self._rerender_all()

    def _init_ui(self):
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        self.text_output.setUndoRedoEnabled(False)

        from core.settings_manager import AppSettings
        log_size = AppSettings.instance().get("log_font_size", 9)
        log_font = QFont(BaseStyles.LOG_FONT, log_size)
        log_font.setStyleHint(QFont.Monospace)
        self.text_output.setFont(log_font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text_output)
        self._apply_style()

    def _connect_services(self):
        LogService().log_received.connect(self._append_log, Qt.ConnectionType.AutoConnection)

    def _append_log(self, level: str, message: str):
        sb = self.text_output.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20

        timestamp = datetime.now().strftime("%H:%M:%S")
        self._entries.append((timestamp, level, message))
        self._render_entry(timestamp, level, message)

        if at_bottom:
            sb.setValue(sb.maximum())
        self._trim_excess_lines()

    def _render_entry(self, timestamp: str, level: str, message: str):
        c = BaseStyles.color
        cursor = self.text_output.textCursor()
        cursor.movePosition(QTextCursor.End)

        ts_fmt = QTextCharFormat()
        ts_fmt.setForeground(QColor(c("LOG_TIMESTAMP")))
        cursor.insertText(f"{timestamp} ", ts_fmt)

        lv_key = f"LOG_{level}" if level in ("DEBUG","INFO","SUCCESS","WARNING","ERROR","CRITICAL") else "LOG_INFO"
        lv_fmt = QTextCharFormat()
        lv_fmt.setForeground(QColor(c(lv_key)))
        cursor.insertText(f"[{level}]", lv_fmt)

        msg_fmt = QTextCharFormat()
        msg_fmt.setForeground(QColor(c("LOG_TEXT_COLOR")))
        cursor.insertText(f" {message}\n", msg_fmt)

    def _rerender_all(self):
        """Batch re-render via setHtml for performance on theme change."""
        c = BaseStyles.color
        lines = []
        for ts, level, msg in self._entries:
            lv_key = f"LOG_{level}" if level in ("DEBUG","INFO","SUCCESS","WARNING","ERROR","CRITICAL") else "LOG_INFO"
            lv_color = c(lv_key)
            ts_color = c("LOG_TIMESTAMP")
            msg_color = c("LOG_TEXT_COLOR")
            lines.append(
                f'<span style="color:{ts_color}">{ts}</span> '
                f'<span style="color:{lv_color}">[{level}]</span> '
                f'<span style="color:{msg_color}">{msg}</span>'
            )
        self.text_output.setHtml("<br>".join(lines) + "<br>")
        self.text_output.ensureCursorVisible()
        sb = self.text_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _trim_excess_lines(self):
        """Trim oldest lines when exceeding max. Batched: check only every 50 lines."""
        if not hasattr(self, '_line_count'):
            self._line_count = 0
        self._line_count += 1
        if self._line_count % 50 != 0:
            return
        block_count = self.text_output.document().blockCount()
        if block_count > self._max_lines:
            excess = block_count - self._max_lines + 100
            cursor = self.text_output.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, excess)
            cursor.removeSelectedText()
            self._entries = self._entries[excess:]

    def clear(self):
        self._entries.clear()
        self.text_output.clear()
        self._line_count = 0

    def set_max_lines(self, max_lines: int):
        self._max_lines = max(max_lines, 100)
        self._trim_excess_lines()
