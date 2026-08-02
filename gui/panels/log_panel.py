"""提供支持主题切换、自动滚动和批量渲染的用户日志面板。"""

from datetime import datetime
from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from core.log_service import LogLevel, LogService
from gui.styles import BaseStyles, FontRole


class LogPanel(QWidget):
    RENDER_DEBOUNCE_MS = 16
    IMMEDIATE_BATCH_SIZE = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.settings_manager import AppSettings

        self._max_lines = AppSettings.instance().get("log_max_lines", 2000)
        self._entries = []
        self._line_count = 0
        self._pending_rows = []
        self._pending_scroll_to_bottom = False
        self._pending_trim_count = 0
        self._render_pending_timer = QTimer(self)
        self._render_pending_timer.setSingleShot(True)
        self._render_pending_timer.timeout.connect(self._flush_pending_rows)
        self._init_ui()
        self._connect_services()
        BaseStyles.theme_changed.connect(self._on_theme_changed)
        BaseStyles.log_font_changed.connect(self._on_log_font_changed)

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

        self._max_lines = AppSettings.instance().get("log_max_lines", 2000)
        self._apply_style()
        self._cancel_pending_render()
        self._rerender_all()

    def _on_log_font_changed(self, _config):
        """仅更新日志字体，避免字体调整触发整份日志重新渲染。"""

        self.text_output.setFont(BaseStyles.font_for_role(FontRole.LOG))

    def _init_ui(self):
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        self.text_output.setUndoRedoEnabled(False)

        self.text_output.setFont(BaseStyles.font_for_role(FontRole.LOG))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text_output)
        self._apply_style()

    def _connect_services(self):
        LogService().logs_received.connect(self._append_logs, Qt.ConnectionType.AutoConnection)

    def _append_log(self, level: str, message: str):
        self._append_logs([(level, message)])

    def _append_logs(self, records: list[tuple[str, str]]):
        # 面板边界再次过滤 DEBUG，防止尚未迁移的直连信号绕过日志服务。
        visible_records = [
            (level, message) for level, message in records if str(level).upper() != LogLevel.DEBUG
        ]
        if not visible_records:
            return
        sb = self.text_output.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20

        timestamp = datetime.now().strftime("%H:%M:%S")
        rows = [(timestamp, level, message) for level, message in visible_records]
        self._entries.extend(rows)
        if len(rows) >= self.IMMEDIATE_BATCH_SIZE:
            self._flush_pending_rows()
            self._render_rows(rows, at_bottom, len(rows))
            return

        self._pending_rows.extend(rows)
        self._pending_scroll_to_bottom = self._pending_scroll_to_bottom or at_bottom
        self._pending_trim_count += len(rows)
        if not self._render_pending_timer.isActive():
            self._render_pending_timer.start(self.RENDER_DEBOUNCE_MS)

    def _render_rows(self, rows: list[tuple[str, str, str]], at_bottom: bool, added_count: int):
        self._render_entries(rows)
        if at_bottom:
            sb = self.text_output.verticalScrollBar()
            sb.setValue(sb.maximum())
        self._trim_excess_lines(added_count)

    def _flush_pending_rows(self):
        if not self._pending_rows:
            return
        rows = self._pending_rows
        at_bottom = self._pending_scroll_to_bottom
        added_count = self._pending_trim_count
        self._pending_rows = []
        self._pending_scroll_to_bottom = False
        self._pending_trim_count = 0
        self._render_rows(rows, at_bottom, added_count)

    def _cancel_pending_render(self):
        if self._render_pending_timer.isActive():
            self._render_pending_timer.stop()
        self._pending_rows = []
        self._pending_scroll_to_bottom = False
        self._pending_trim_count = 0

    def _render_entries(self, rows: list[tuple[str, str, str]]):
        if not rows:
            return
        c = BaseStyles.color
        cursor = self.text_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.beginEditBlock()
        try:
            cursor.insertHtml("".join(self._entry_html(ts, level, msg) for ts, level, msg in rows))
        finally:
            cursor.endEditBlock()

    def _entry_html(self, timestamp: str, level: str, message: str) -> str:
        c = BaseStyles.color
        lv_key = (
            f"LOG_{level}"
            if level in ("DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")
            else "LOG_INFO"
        )
        msg = escape(str(message)).replace("\n", "<br>")
        return (
            f'<span style="color:{c("LOG_TIMESTAMP")}">{escape(timestamp)}</span> '
            f'<span style="color:{c(lv_key)}">[{escape(str(level))}]</span> '
            f'<span style="color:{c("LOG_TEXT_COLOR")}">{msg}</span><br>'
        )

    def _rerender_all(self):
        """主题变化时通过单次 setHtml 批量重绘。"""
        self.text_output.setHtml(
            "".join(self._entry_html(ts, level, msg) for ts, level, msg in self._entries)
        )
        self.text_output.ensureCursorVisible()
        sb = self.text_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _trim_excess_lines(self, added_count: int = 1):
        """超过上限时批量删除旧日志，常规情况下每五十行检查一次。"""
        force_trim = added_count <= 0
        if not force_trim:
            self._line_count += added_count
        if (
            not force_trim
            and self._line_count % 50 != 0
            and len(self._entries) <= self._max_lines + 100
        ):
            return
        if len(self._entries) <= self._max_lines:
            return
        excess = len(self._entries) - self._max_lines
        self._entries = self._entries[excess:]
        self._rerender_all()

    def clear(self):
        self._cancel_pending_render()
        self._entries.clear()
        self.text_output.clear()
        self._line_count = 0

    def set_max_lines(self, max_lines: int):
        self._max_lines = max(max_lines, 100)
        self._flush_pending_rows()
        self._trim_excess_lines(0)
