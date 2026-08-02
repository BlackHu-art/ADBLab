"""提供应用版本、项目链接和二维码信息对话框。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from utils.app_metadata import APP_VERSION
from utils.resource_path import resource_path


class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About ADBLab")
        self.setWindowIcon(get_themed_icon("info.svg"))
        self.setMinimumSize(340, 380)
        self.resize(340, 380)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)

        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._header = QFrame()
        self._header.setObjectName("aboutHeader")
        self._header.setMinimumHeight(56)
        hl = QVBoxLayout(self._header)
        hl.setContentsMargins(0, 8, 0, 0)
        hl.setSpacing(0)

        self._title = QLabel('<a href="https://github.com/BlackHu-art/ADBLab">ADBLab</a>')
        self._title.setObjectName("aboutTitle")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setOpenExternalLinks(True)
        hl.addWidget(self._title)

        self._version = QLabel(f"Version {APP_VERSION}")
        self._version.setObjectName("aboutVer")
        self._version.setAlignment(Qt.AlignCenter)
        hl.addWidget(self._version)

        lo.addWidget(self._header)

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

        self._hint = QLabel("Scan to support the author")
        self._hint.setObjectName("aboutHint")
        self._hint.setAlignment(Qt.AlignCenter)
        body.addWidget(self._hint)

        lo.addLayout(body)

        ft = QVBoxLayout()
        ft.setSpacing(2)
        ft.setContentsMargins(0, 0, 0, 12)

        self._footer = QLabel("Copyright © 2026 Frankie Hu")
        self._footer.setObjectName("aboutFooter")
        self._footer.setAlignment(Qt.AlignCenter)
        ft.addWidget(self._footer)

        self._close_btn = QPushButton("Close")
        self._close_btn.setIcon(get_themed_icon("x.svg"))
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setObjectName("aboutCloseBtn")
        self._close_btn.setMinimumWidth(100)
        self._close_btn.clicked.connect(self.close)
        btn_row = QVBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.addWidget(self._close_btn)
        ft.addLayout(btn_row)

        lo.addLayout(ft)

    def closeEvent(self, event):
        for signal in (BaseStyles.theme_changed, BaseStyles.fonts_changed):
            try:
                signal.disconnect(self._apply_theme)
            except (TypeError, RuntimeError):
                pass
        super().closeEvent(event)

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self)
        ui_font = BaseStyles.font_for_role(FontRole.UI)
        title_font = BaseStyles.font_for_role(
            FontRole.TITLE, size=max(24, BaseStyles.DEFAULT_FONT_SIZE + 12)
        )
        version_font = BaseStyles.font_for_role(
            FontRole.UI_SMALL, size=max(8, BaseStyles.DEFAULT_FONT_SIZE - 1)
        )
        footer_font = BaseStyles.font_for_role(
            FontRole.UI_SMALL, size=max(8, BaseStyles.DEFAULT_FONT_SIZE - 2)
        )
        close_font = QFont(ui_font)
        close_font.setBold(True)

        self.setFont(ui_font)
        self._title.setFont(title_font)
        self._version.setFont(version_font)
        self._hint.setFont(ui_font)
        self._footer.setFont(footer_font)
        self._close_btn.setFont(close_font)

        def c(k):
            return BaseStyles.color(k)
        accent = c("BUTTON_ACCENT")
        r = BaseStyles.RADIUS_MD

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c('PANEL_BG')};
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
                color: {c('TEXT_SECONDARY')};
                background: transparent;
            }}
            QLabel#aboutQR {{
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                background-color: #ffffff;
            }}
            QLabel#aboutHint {{
                color: {c('BUTTON_ACCENT')};
                background: transparent;
            }}
            QLabel#aboutFooter {{
                color: {c('TEXT_DISABLED')};
                background: transparent;
            }}
            QPushButton#aboutCloseBtn {{
                background-color: {accent};
                color: #ffffff;
                border: none;
                border-radius: {r}px;
            }}
            QPushButton#aboutCloseBtn:hover {{
                background-color: {c('BUTTON_ACCENT_HOVER')};
            }}
            QPushButton#aboutCloseBtn:pressed {{
                background-color: {c('BUTTON_ACCENT_PRESSED')};
            }}
        """)
        self._close_btn.setMinimumHeight(30)
        text_height = QFontMetrics(close_font).height() + 10
        self._close_btn.setMinimumHeight(max(30, self._close_btn.sizeHint().height(), text_height))
        self._header.setMinimumHeight(56)
        self._header.setMinimumHeight(max(56, self._header.sizeHint().height()))
