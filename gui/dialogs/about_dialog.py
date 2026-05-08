"""About dialog with theme-aware styling and fade animation."""

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gui.styles.base_styles import BaseStyles


class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedSize(480, 350)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._setup_ui()
        self._setup_animations()
        self._setup_shadow()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)

    def _apply_theme(self, _name: str = ""):
        bg = BaseStyles.color("PANEL_BG")
        fg = BaseStyles.color("TEXT_PRIMARY")
        sec = BaseStyles.color("TEXT_SECONDARY")
        accent = BaseStyles.color("BUTTON_ACCENT")
        border = BaseStyles.color("BORDER_COLOR")

        self.setStyleSheet("")
        self._bg_frame.setStyleSheet(f"""
            QFrame#aboutBg {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {BaseStyles.RADIUS_LG}px;
            }}
            QLabel#title {{
                font-size: 20px;
                font-weight: bold;
                color: {fg};
                padding-top: 24px;
                background: transparent;
            }}
            QLabel#version {{
                font-size: 12px;
                color: {accent};
                padding-bottom: 12px;
                background: transparent;
            }}
            QLabel#content {{
                font-size: 12px;
                color: {fg};
                background-color: {BaseStyles.color('INPUT_BG')};
                border-radius: {BaseStyles.RADIUS_MD}px;
                padding: 14px 18px;
                margin: 0 32px;
            }}
            QLabel#footer {{
                font-size: 11px;
                color: {sec};
                padding: 14px 0 6px 0;
                background: transparent;
            }}
            QPushButton#close_btn {{
                background-color: {accent};
                color: #fff;
                border: none;
                border-radius: {BaseStyles.RADIUS_MD}px;
                padding: 8px 32px;
                font-size: 13px;
                font-weight: bold;
                margin: 10px 0 20px 0;
            }}
            QPushButton#close_btn:hover {{
                background-color: {BaseStyles.color('BUTTON_ACCENT_HOVER')};
            }}
        """)

        is_dark = BaseStyles.current_theme() == "Dark"
        self._shadow.setColor(QColor(0, 0, 0, 200 if is_dark else 100))

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._bg_frame = QFrame()
        self._bg_frame.setObjectName("aboutBg")
        layout = QVBoxLayout(self._bg_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("ADBLab")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont(BaseStyles.DEFAULT_FONT_FAMILY, 20, QFont.Bold))

        version = QLabel("Version 2.6.0")
        version.setObjectName("version")
        version.setAlignment(Qt.AlignCenter)

        content = QLabel()
        content.setObjectName("content")
        content.setAlignment(Qt.AlignCenter)
        content.setTextFormat(Qt.RichText)
        content.setText(
            "<p style='margin:0;'>Android Debug Bridge GUI Toolkit</p>"
            "<p style='margin:8px 0 0 0;'>"
            "Batch device management &middot; Automated testing<br>"
            "Performance diagnostics &middot; File Explorer<br>"
            "App Manager &middot; Live Logcat</p>"
        )

        footer = QLabel("Copyright © 2025 Frankie Hu. All rights reserved.")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignCenter)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self._fade_out)

        layout.addWidget(title, 0, Qt.AlignCenter)
        layout.addWidget(version, 0, Qt.AlignCenter)
        layout.addWidget(content, 0, Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(footer, 0, Qt.AlignCenter)
        layout.addWidget(close_btn, 0, Qt.AlignCenter)

        outer.addWidget(self._bg_frame)

    def _setup_animations(self):
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(180)

    def _setup_shadow(self):
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(20)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(4)
        self.setGraphicsEffect(self._shadow)

    def _fade_out(self):
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
            self._fade_out()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if hasattr(self, "_drag_pos") and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        if hasattr(self, "_drag_pos"):
            del self._drag_pos
        super().mouseReleaseEvent(event)
