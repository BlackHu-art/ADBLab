from typing import Dict, Optional
from PySide6.QtWidgets import QWidget, QTextEdit, QVBoxLayout
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from PySide6.QtCore import Qt
from gui.styles import Styles

class LogPanel(QWidget):
    """带颜色分级和自动滚动的日志显示面板"""
    
    # 日志等级颜色映射
    LEVEL_COLORS: Dict[str, str] = {
        "DEBUG": Styles.DEBUG_COLOR,
        "INFO": Styles.INFO_COLOR,
        "SUCCESS": Styles.SUCCESS_COLOR,
        "WARNING": Styles.WARNING_COLOR,
        "ERROR": Styles.ERROR_COLOR,
        "CRITICAL": Styles.CRITICAL_COLOR
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()
        self._setup_styles()

    def _init_ui(self) -> None:
        """初始化UI组件"""
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        self._configure_font()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text_output)
        self.setLayout(layout)

    def _configure_font(self) -> None:
        """配置日志字体"""
        log_font = QFont(Styles.LOG_FONT, Styles.LOG_FONT_SIZE)
        log_font.setStyleHint(QFont.Monospace)  # 等宽字体保证对齐
        self.text_output.setFont(log_font)

    def _setup_styles(self) -> None:
        """设置组件样式"""
        self.text_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Styles.LOG_BACKGROUND};
                color: {Styles.LOG_TEXT_COLOR};
                border: none;
                padding: 5px;
            }}
            {Styles.SCROLLBAR_STYLE}  # 从styles.py导入滚动条样式
        """)

    def log_message(self, level: str, message: str) -> None:
        """记录带格式的日志消息
        :param level: 日志级别(DEBUG/INFO/SUCCESS/WARNING/ERROR/CRITICAL)
        :param message: 日志内容
        """
        cursor = self.text_output.textCursor()
        self._append_formatted_text(cursor, level, message)
        self._auto_scroll(cursor)

    def _append_formatted_text(self, cursor: QTextCursor, level: str, message: str) -> None:
        """插入带格式的文本"""
        full_message = f"[{level.upper()}] {message}"
        
        fmt = QTextCharFormat()
        fmt.setForeground(self._get_log_color(level))
        
        # 保存当前格式
        old_fmt = cursor.charFormat()
        
        cursor.movePosition(QTextCursor.End)
        cursor.setCharFormat(fmt)
        cursor.insertText(full_message + "\n")
        
        # 恢复原有格式
        cursor.setCharFormat(old_fmt)

    def _get_log_color(self, level: str) -> QColor:
        """获取日志等级对应的颜色"""
        return QColor(self.LEVEL_COLORS.get(level.upper(), Styles.LOG_TEXT_COLOR))

    def _auto_scroll(self, cursor: QTextCursor) -> None:
        """优化后的智能滚动控制"""
        # 确保光标可见
        self.text_output.ensureCursorVisible()
        
        # 直接操作滚动条到最底部
        scrollbar = self.text_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # 更新光标位置确保视图同步
        cursor.movePosition(QTextCursor.End)
        self.text_output.setTextCursor(cursor)

    def clear(self) -> None:
        """清空日志内容"""
        self.text_output.clear()

    def set_max_lines(self, max_lines: int = 1000) -> None:
        """设置最大保留日志行数"""
        cursor = self.text_output.textCursor()
        cursor.select(QTextCursor.Document)
        text = cursor.selectedText().split('\n')
        
        if len(text) > max_lines:
            new_text = '\n'.join(text[-max_lines:])
            self.text_output.setPlainText(new_text)