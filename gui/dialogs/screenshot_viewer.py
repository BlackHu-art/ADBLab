from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QPushButton, QHBoxLayout, QApplication, QFrame
)
from PySide6.QtGui import QPixmap, QGuiApplication, QFont, QMouseEvent
from PySide6.QtCore import Qt, QTimer, QPoint
from gui.styles.base_styles import BaseStyles


class ScreenshotViewer(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.drag_position = QPoint()

        self.init_window()
        self.init_ui()
        self.load_image()

    def init_window(self):
        self.setWindowTitle("Screenshot Viewer")
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Dialog
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(self.window_style())

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFrameShape(QFrame.StyledPanel)
        self.image_label.setStyleSheet(
            f"background-color: {BaseStyles.color('INPUT_BG')}; "
            f"border-radius: {BaseStyles.RADIUS_XL}px; padding: 10px;"
        )
        layout.addWidget(self.image_label)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        button_layout.setAlignment(Qt.AlignCenter)

        self.copy_button = self.create_button("Copy to Clipboard", self.copy_to_clipboard)
        self.close_button = self.create_button("Close", self.close)

        button_layout.addWidget(self.copy_button)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def window_style(self) -> str:
        C = BaseStyles.color
        return f"""
        QDialog {{
            background-color: {C('PANEL_BG')};
            border-radius: {BaseStyles.RADIUS_XL}px;
            border: 1px solid {C('BORDER_COLOR')};
        }}
        QPushButton {{
            background-color: {C('BUTTON_ACCENT')};
            color: white;
            padding: 8px 18px;
            border: none;
            border-radius: {BaseStyles.RADIUS_LG}px;
            font-size: 14px;
        }}
        QPushButton:hover {{
            background-color: {C('BUTTON_ACCENT_HOVER')};
        }}
        QPushButton:pressed {{
            background-color: {C('BUTTON_ACCENT_PRESSED')};
        }}
        """

    def create_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedWidth(150)
        btn.setFixedHeight(36)
        btn.setFont(QFont("Arial", 10))
        btn.clicked.connect(slot)
        return btn

    def load_image(self):
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
        pixmap = self.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return

        screen = QGuiApplication.primaryScreen().availableGeometry()
        padding = 100

        self.resize(
            min(pixmap.width() + 80, screen.width() - 40),
            min(pixmap.height() + padding, screen.height() - 40)
        )

        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull():
            clipboard.setPixmap(pixmap)
            self.copy_button.setText("Copied!")
            self.copy_button.setStyleSheet("background-color: #2196F3;")
            QTimer.singleShot(2000, self.reset_copy_button)

    def reset_copy_button(self):
        self.copy_button.setText("Copy to Clipboard")
        self.copy_button.setStyleSheet("")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
