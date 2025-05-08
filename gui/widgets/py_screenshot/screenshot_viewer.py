# views/screenshot_viewer.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QPushButton, QHBoxLayout, QApplication, QFrame
)
from PySide6.QtGui import QPixmap, QGuiApplication, QFont, QMouseEvent
from PySide6.QtCore import Qt, QTimer, QPoint

class ScreenshotViewer(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.drag_position = QPoint()

        self.init_window()
        self.init_ui()
        self.load_image()

    def init_window(self):
        """初始化窗口属性"""
        self.setWindowTitle("Screenshot Viewer")
        self.setWindowFlags(
            Qt.FramelessWindowHint |    # 无边框
            Qt.WindowStaysOnTopHint |   # 保持置顶
            Qt.Dialog
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # 背景透明
        self.setStyleSheet(self.window_style())

    def init_ui(self):
        """初始化界面布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 图片显示区
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFrameShape(QFrame.StyledPanel)
        self.image_label.setStyleSheet("background-color: #f9f9f9; border-radius: 12px; padding: 10px;")
        layout.addWidget(self.image_label)

        # 按钮区
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        button_layout.setAlignment(Qt.AlignCenter)

        self.copy_button = self.create_button("Copy to Clipboard", self.copy_to_clipboard)
        self.close_button = self.create_button("Close", self.close)

        button_layout.addWidget(self.copy_button)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def window_style(self) -> str:
        """整体窗口样式"""
        return """
        QDialog {
            background-color: #ffffff;
            border-radius: 12px;
            border: 1px solid #dddddd;
        }
        QPushButton {
            background-color: #4CAF50;
            color: white;
            padding: 8px 18px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
        QPushButton:pressed {
            background-color: #3e8e41;
        }
        """

    def create_button(self, text: str, slot) -> QPushButton:
        """创建一个带统一风格的按钮"""
        btn = QPushButton(text)
        btn.setFixedWidth(150)
        btn.setFixedHeight(36)
        btn.setFont(QFont("Arial", 10))
        btn.clicked.connect(slot)
        return btn

    def load_image(self):
        """加载并自适应图片"""
        pixmap = QPixmap(self.image_path)
        if pixmap.isNull():
            return
        
        screen = QGuiApplication.primaryScreen().availableGeometry()
        max_width, max_height = screen.width() * 0.7, screen.height() * 0.7
        
        if pixmap.width() > max_width or pixmap.height() > max_height:
            pixmap = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        self.image_label.setPixmap(pixmap)
        self.adjust_window_size()

    def adjust_window_size(self):
        """根据图片大小调整窗口尺寸"""
        pixmap = self.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        
        screen = QGuiApplication.primaryScreen().availableGeometry()
        padding = 100  # 给按钮和边缘留的空间

        self.resize(
            min(pixmap.width() + 80, screen.width() - 40),
            min(pixmap.height() + padding, screen.height() - 40)
        )
        
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )

    def copy_to_clipboard(self):
        """复制图片到剪贴板"""
        clipboard = QApplication.clipboard()
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull():
            clipboard.setPixmap(pixmap)
            self.copy_button.setText("Copied!")
            self.copy_button.setStyleSheet("background-color: #2196F3;")
            QTimer.singleShot(2000, self.reset_copy_button)

    def reset_copy_button(self):
        """重置按钮"""
        self.copy_button.setText("Copy to Clipboard")
        self.copy_button.setStyleSheet("")  # 恢复原样式

    # ========= 实现无边框窗口的拖动 =========
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
