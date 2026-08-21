"""提供 Logcat 日志等级语法高亮器。"""

from typing import cast

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from gui.dialogs.live_logcat_worker import LogcatWorker


class LogcatHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(cast(QObject, parent))
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
