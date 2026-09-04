"""提供 MobilePerf 日志区的追加、批量渲染与最大行数配置。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QTextCursor

from core.settings_manager import AppSettings


class PerformanceLauncherLog:
    """组合进 PerformancePage 的日志控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame

    def _append_log(self, level: str, message: str):
        if self._frame._closing:
            return
        scrollbar = self._frame.log_view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 20
        message_lines = str(message).splitlines() or [str(message)]
        rows = [self._format_log_line(level, line) for line in message_lines if line.strip()]
        if not rows:
            return
        self._frame._pending_log_rows.extend(rows)
        if len(self._frame._pending_log_rows) > self._frame.MAX_PENDING_LOG_ROWS:
            del self._frame._pending_log_rows[
                : len(self._frame._pending_log_rows) - self._frame.MAX_PENDING_LOG_ROWS
            ]
        self._frame._pending_log_scroll_to_bottom = (
            self._frame._pending_log_scroll_to_bottom or at_bottom
        )
        if len(self._frame._pending_log_rows) >= self._frame.IMMEDIATE_LOG_BATCH_SIZE:
            self._flush_pending_logs()
        elif not self._frame._log_flush_timer.isActive():
            self._frame._log_flush_timer.start(self._frame.LOG_RENDER_DEBOUNCE_MS)

    def _flush_pending_logs(self):
        if not self._frame._pending_log_rows:
            return
        rows = self._frame._pending_log_rows
        at_bottom = self._frame._pending_log_scroll_to_bottom
        self._frame._pending_log_rows = []
        self._frame._pending_log_scroll_to_bottom = False
        self._render_log_rows(rows)
        if at_bottom:
            scrollbar = self._frame.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _render_log_rows(self, rows: list[str]):
        cursor = self._frame.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
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
