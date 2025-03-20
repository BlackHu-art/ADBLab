from PySide6.QtWidgets import QWidget, QTextEdit, QVBoxLayout
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from gui.styles import Styles

class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        log_font = QFont(Styles.LOG_FONT, Styles.LOG_FONT_SIZE)
        self.text_output.setFont(log_font)
        # 设置整体样式及竖直滚动条样式
        self.text_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Styles.LOG_BACKGROUND};
                color: {Styles.LOG_TEXT_COLOR};
                border: none;
                padding: 5px;
            }}
            QScrollBar:vertical {{
                background: #2d2d2d;
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: #666666;
                min-height: 10px;
                border-radius: 6px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none;
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text_output)
        self.setLayout(layout)

    def log_message(self, level, message):
        cursor = self.text_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(self.get_color_by_level(level))
        cursor.setCharFormat(fmt)
        cursor.insertText(f"[{level}] {message}\n")
        # 自动滚动到底部
        self.text_output.verticalScrollBar().setValue(self.text_output.verticalScrollBar().maximum())

    def get_color_by_level(self, level):
        level = level.upper()
        if level == "INFO":
            return QColor(Styles.INFO_COLOR)
        elif level == "WARNING":
            return QColor(Styles.WARNING_COLOR)
        elif level == "ERROR":
            return QColor(Styles.ERROR_COLOR)
        return QColor(Styles.LOG_TEXT_COLOR)

    def clear(self):
        self.text_output.clear()
