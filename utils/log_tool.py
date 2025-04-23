# log_tool.py
from typing import Optional
from gui.widgets.style.base_styles import Styles
from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Qt

class LogTool:
    def __init__(self, log_widget: Optional[QTextEdit] = None):
        self.log_widget = log_widget

    def log_message(self, level: str, message: str) -> None:
        """记录日志信息"""
        if self.log_widget:
            color = self._get_color_by_level(level)
            formatted_message = self._format_message(level, message, color)
            self._append_message(formatted_message)

    def _get_color_by_level(self, level: str) -> str:
        """根据日志级别返回对应的颜色"""
        level_colors = {
            "DEBUG": Styles.DEBUG_COLOR,
            "INFO": Styles.INFO_COLOR,
            "SUCCESS": Styles.SUCCESS_COLOR,
            "WARNING": Styles.WARNING_COLOR,
            "ERROR": Styles.ERROR_COLOR,
            "CRITICAL": Styles.CRITICAL_COLOR
        }
        return level_colors.get(level, Styles.INFO_COLOR)  # 默认使用 INFO 颜色

    def _format_message(self, level: str, message: str, color: str) -> str:
        """格式化日志消息"""
        return f'<font color="{color}">{level}: {message}</font>'

    def _append_message(self, message: str) -> None:
        """将消息追加到日志显示区"""
        if self.log_widget:
            self.log_widget.append(message)
            self.log_widget.verticalScrollBar().setValue(self.log_widget.verticalScrollBar().maximum())  # 自动滚动到最新
