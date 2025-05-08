from typing import Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QTextEdit, QVBoxLayout
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from labgui.widgets.style.base_styles import BaseStyles
from common.log_service import LogService


class LogPanel(QWidget):
    """优化后的日志显示面板，保持原有样式和功能"""
    
    # 日志等级颜色映射（保持原有样式）
    LEVEL_COLORS: Dict[str, str] = {
        "DEBUG": BaseStyles.DEBUG_COLOR,
        "INFO": BaseStyles.INFO_COLOR,
        "SUCCESS": BaseStyles.SUCCESS_COLOR,
        "WARNING": BaseStyles.WARNING_COLOR,
        "ERROR": BaseStyles.ERROR_COLOR,
        "CRITICAL": BaseStyles.CRITICAL_COLOR
    }

    # 自定义信号
    log_appended = Signal(str, str)  # (level, message)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()
        self._setup_styles()
        self._connect_services()
        self._max_lines = 1000  # 默认最大行数

    def _init_ui(self) -> None:
        """初始化UI组件（保持原有结构）"""
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        self.text_output.setUndoRedoEnabled(False)  # 禁用撤销重做提高性能
        self._configure_font()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text_output)
        self.setLayout(layout)

    def _configure_font(self) -> None:
        """配置日志字体（保持原有样式）"""
        log_font = QFont(BaseStyles.LOG_FONT, BaseStyles.LOG_FONT_SIZE)
        log_font.setStyleHint(QFont.Monospace)
        self.text_output.setFont(log_font)

    def _setup_styles(self) -> None:
        """设置样式表（保持原有样式）"""
        self.text_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BaseStyles.LOG_BACKGROUND};
                color: {BaseStyles.LOG_TEXT_COLOR};
                border: none;
                padding: 5px;
            }}
            {BaseStyles.SCROLLBAR_STYLE}
        """)

    def _connect_services(self) -> None:
        """连接日志服务信号"""
        self.log_service = LogService()
        self.log_service.log_received.connect(
            self._append_log,
            Qt.ConnectionType.QueuedConnection  # 确保线程安全
        )
        self.log_appended.connect(
            self._handle_log_append,
            Qt.ConnectionType.QueuedConnection
        )

    def log_message(self, level: str, message: str) -> None:
        """
        线程安全的日志记录方法
        参数:
            level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
            message: 日志消息
        """
        self.log_appended.emit(level.upper(), str(message))

    def _append_log(self, level: str, message: str) -> None:
        """日志服务信号处理适配方法"""
        self.log_message(level, message)

    def _handle_log_append(self, level: str, message: str) -> None:
        """实际处理日志追加（主线程执行）"""
        if not hasattr(self, 'text_output'):  # 防止UI未初始化
            return

        try:
            self._append_formatted_text(level, message)
            self._trim_excess_lines()
        except Exception as e:
            print(f"Log append error: {e}")  # 防止日志记录本身崩溃

    def _append_formatted_text(self, level: str, message: str) -> None:
        """添加带格式的日志文本"""
        cursor = self.text_output.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.LEVEL_COLORS.get(level, BaseStyles.INFO_COLOR)))
        
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"[{level}] {message}\n", fmt)
        self._auto_scroll(cursor)

    def _auto_scroll(self, cursor: QTextCursor) -> None:
        """自动滚动到底部"""
        self.text_output.ensureCursorVisible()
        scrollbar = self.text_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.text_output.setTextCursor(cursor)

    def _trim_excess_lines(self) -> None:
        """定期修剪多余日志行"""
        cursor = self.text_output.textCursor()
        cursor.select(QTextCursor.Document)
        text = cursor.selectedText()
        
        if text.count('\n') > self._max_lines:
            lines = text.split('\n')
            new_text = '\n'.join(lines[-self._max_lines:])
            self.text_output.setPlainText(new_text)

    def clear(self) -> None:
        """清空日志内容"""
        if hasattr(self, 'text_output'):
            self.text_output.clear()

    def set_max_lines(self, max_lines: int) -> None:
        """设置最大保留日志行数"""
        self._max_lines = max(max_lines, 1000)  # 最小100行
        self._trim_excess_lines()

    def get_log_content(self) -> str:
        """获取当前日志内容（线程安全）"""
        if hasattr(self, 'text_output'):
            return self.text_output.toPlainText()
        return ""