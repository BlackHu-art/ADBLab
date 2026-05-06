"""About dialog with theme-aware styling, fade animation, and shadow effect."""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                               QPushButton, QWidget, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QColor

from gui.styles.base_styles import BaseStyles


class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedSize(500, 400)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._setup_content()
        self._setup_animations()
        self._setup_shadow_effect()
        self._apply_theme()

        # Respond to theme changes while dialog is open
        BaseStyles.theme_changed.connect(self._on_theme_changed)

    def _apply_theme(self):
        """Apply theme-aware stylesheet and shadow color."""
        self.setStyleSheet(BaseStyles.ABOUT_DIALOG_STYLE())

        # Adjust shadow opacity based on theme (darker needs stronger shadow)
        is_dark = BaseStyles.current_theme() == "Dark"
        alpha = 200 if is_dark else 120
        self._shadow.setColor(QColor(0, 0, 0, alpha))

    def _on_theme_changed(self, _name: str):
        self._apply_theme()

    def _setup_content(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("ADB Manager")
        title.setObjectName("title")

        version = QLabel("Version 2.4.0")
        version.setObjectName("version")

        content = QLabel()
        content.setObjectName("content")
        content.setTextFormat(Qt.RichText)
        content.setText(self._get_content_html())

        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.addWidget(content)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("close_btn")
        btn_close.clicked.connect(self._fade_out_and_close)

        layout.addWidget(title, 0, Qt.AlignCenter)
        layout.addWidget(version, 0, Qt.AlignCenter)
        layout.addWidget(content_container, 1)
        layout.addWidget(btn_close, 0, Qt.AlignCenter)

    def _get_content_html(self):
        C = BaseStyles.color
        return f"""
        <div style='line-height: 1.6;'>
            <p style='margin-bottom: 15px; font-size: 13px;'>
                Advanced Device Management Platform
            </p>
            <ul style='margin-left: 20px; font-size: 12px;'>
                <li>Multi-device control and monitoring</li>
                <li>Real-time performance analytics</li>
                <li>Automated testing framework</li>
                <li>Secure log collection system</li>
            </ul>
            <p style='margin-top: 20px; color: {C('TEXT_SECONDARY')}; font-size: 11px;'>
                Copyright &copy; 2025.4 Frankie Hu. All rights reserved.
            </p>
        </div>
        """

    def _setup_animations(self):
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(200)

    def _setup_shadow_effect(self):
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(15)
        self._shadow.setXOffset(3)
        self._shadow.setYOffset(3)
        self.setGraphicsEffect(self._shadow)

    def _fade_out_and_close(self):
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.finished.connect(self.close)
        self.fade_animation.start()

    def showEvent(self, event):
        self.setWindowOpacity(1.0)
        self._apply_theme()
        super().showEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._fade_out_and_close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_position = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if hasattr(self, '_drag_position') and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_position
            self.move(self.pos() + delta)
            self._drag_position = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        if hasattr(self, '_drag_position'):
            del self._drag_position
        super().mouseReleaseEvent(event)
