# log_panel.py
from typing import Dict, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QTextEdit, QVBoxLayout
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from gui.styles import Styles
from services.log_service import LogService

class LogPanel(QWidget):
    """带颜色分级和自动滚动的日志显示面板"""
    
    # 日志等级颜色映射（保持原有样式）
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
        self.log_service = LogService()  # 添加日志服务
        self._init_ui()
        self._setup_styles()
        self._connect_signals()  # 添加信号连接

    def _init_ui(self) -> None:
        """初始化UI组件（保持原有结构）"""
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        self._configure_font()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text_output)
        self.setLayout(layout)

    def _configure_font(self) -> None:
        """保持原有字体配置"""
        log_font = QFont(Styles.LOG_FONT, Styles.LOG_FONT_SIZE)
        log_font.setStyleHint(QFont.Monospace)
        self.text_output.setFont(log_font)

    def _setup_styles(self) -> None:
        """保持原有样式表"""
        self.text_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Styles.LOG_BACKGROUND};
                color: {Styles.LOG_TEXT_COLOR};
                border: none;
                padding: 5px;
            }}
            {Styles.SCROLLBAR_STYLE}
        """)

    def _connect_signals(self):
        """更安全的信号连接方式"""
        # 使用UniqueConnection确保只连接一次
        self.log_service.log_received.connect(
            self._handle_log, 
            Qt.ConnectionType.UniqueConnection  # 关键修改点
        )

    def log_message(self, level: str, message: str) -> None:
        """统一的外部接口（保持兼容性）"""
        self._append_formatted_text(level, message)

    def _handle_log(self, level: str, message: str):
        """信号处理适配方法"""
        self.log_message(level, message)

    def _append_formatted_text(self, level: str, message: str) -> None:
        """优化后的日志添加方法"""
        cursor = self.text_output.textCursor()
        full_message = f"[{level.upper()}] {message}"
        
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.LEVEL_COLORS[level.upper()]))
        
        # 保存当前格式状态
        old_fmt = cursor.charFormat()
        
        cursor.movePosition(QTextCursor.End)
        cursor.setCharFormat(fmt)
        cursor.insertText(full_message + "\n")
        cursor.setCharFormat(old_fmt)  # 恢复原始格式
        
        self._auto_scroll(cursor)

    def _auto_scroll(self, cursor: QTextCursor) -> None:
        """优化滚动控制逻辑"""
        self.text_output.ensureCursorVisible()
        scrollbar = self.text_output.verticalScrollBar()
        if scrollbar.maximum() > 0:
            scrollbar.setValue(scrollbar.maximum())
        cursor.movePosition(QTextCursor.End)
        self.text_output.setTextCursor(cursor)

    def clear(self) -> None:
        """保持原有清空功能"""
        self.text_output.clear()

    def set_max_lines(self, max_lines: int = 1000) -> None:
        """优化性能的日志截断"""
        cursor = self.text_output.textCursor()
        cursor.select(QTextCursor.Document)
        content = cursor.selectedText().split('\u2029')  # Qt的换行符表示
        
        if len(content) > max_lines:
            new_content = '\n'.join(content[-max_lines:])
            self.text_output.setPlainText(new_content)