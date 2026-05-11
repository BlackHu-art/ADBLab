"""About dialog -- header, QR code, footer."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gui.styles.base_styles import BaseStyles
from gui.styles.theme import apply_dark_title_bar
from gui.styles.icon_loader import get_themed_icon
from utils.resource_path import resource_path

VERSION = "2.8.0"


class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About ADBLab")
        self.setWindowIcon(get_themed_icon("info.svg"))
        self.setFixedSize(340, 380)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)

        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # ── Header ──
        self._header = QFrame()
        self._header.setObjectName("aboutHeader")
        self._header.setFixedHeight(56)
        hl = QVBoxLayout(self._header)
        hl.setContentsMargins(0, 8, 0, 0)
        hl.setSpacing(0)

        title = QLabel("ADBLab")
        title.setObjectName("aboutTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont(BaseStyles.DEFAULT_FONT_FAMILY, 24, QFont.Bold))
        hl.addWidget(title)

        ver = QLabel(f"Version {VERSION}")
        ver.setObjectName("aboutVer")
        ver.setAlignment(Qt.AlignCenter)
        hl.addWidget(ver)

        lo.addWidget(self._header)

        # ── QR Code ──
        body = QVBoxLayout()
        body.setAlignment(Qt.AlignCenter)
        body.setSpacing(6)

        self._qr = QLabel()
        self._qr.setObjectName("aboutQR")
        self._qr.setAlignment(Qt.AlignCenter)
        self._qr.setFixedSize(220, 220)
        self._qr.setScaledContents(True)
        pix = QPixmap(resource_path("resources/ZFB.jpg"))
        if not pix.isNull():
            self._qr.setPixmap(pix)
        body.addWidget(self._qr)

        hint = QLabel("Scan to support the author")
        hint.setObjectName("aboutHint")
        hint.setAlignment(Qt.AlignCenter)
        body.addWidget(hint)

        lo.addLayout(body)

        # ── Footer ──
        ft = QVBoxLayout()
        ft.setSpacing(2)
        ft.setContentsMargins(0, 0, 0, 12)

        footer = QLabel("Copyright © 2026 Frankie Hu")
        footer.setObjectName("aboutFooter")
        footer.setAlignment(Qt.AlignCenter)
        ft.addWidget(footer)

        close_btn = QPushButton("Close")
        close_btn.setIcon(get_themed_icon("x.svg"))
        close_btn.setIconSize(QSize(14, 14))
        close_btn.setObjectName("aboutCloseBtn")
        close_btn.setFixedSize(100, 30)
        close_btn.clicked.connect(self.close)
        btn_row = QVBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.addWidget(close_btn)
        ft.addLayout(btn_row)

        lo.addLayout(ft)

    def closeEvent(self, event):
        BaseStyles.theme_changed.disconnect(self._apply_theme)
        super().closeEvent(event)

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        def c(k):
            return BaseStyles.color(k)
        accent = c("BUTTON_ACCENT")
        r = BaseStyles.RADIUS_MD

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c('PANEL_BG')};
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
            }}
            QFrame#aboutHeader {{
                background-color: transparent;
                border: none;
            }}
            QLabel#aboutTitle {{
                color: {c('TITLE_COLOR')};
                background: transparent;
            }}
            QLabel#aboutVer {{
                font-size: 11px;
                color: {c('TEXT_SECONDARY')};
                background: transparent;
            }}
            QLabel#aboutQR {{
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                background-color: #ffffff;
            }}
            QLabel#aboutHint {{
                font-size: 12px;
                color: {c('BUTTON_ACCENT')};
                background: transparent;
            }}
            QLabel#aboutFooter {{
                font-size: 10px;
                color: {c('TEXT_DISABLED')};
                background: transparent;
            }}
            QPushButton#aboutCloseBtn {{
                background-color: {accent};
                color: #ffffff;
                border: none;
                border-radius: {r}px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#aboutCloseBtn:hover {{
                background-color: {c('BUTTON_ACCENT_HOVER')};
            }}
            QPushButton#aboutCloseBtn:pressed {{
                background-color: {c('BUTTON_ACCENT_PRESSED')};
            }}
        """)
