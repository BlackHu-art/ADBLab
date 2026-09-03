"""提供应用版本、项目链接和二维码信息对话框。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ImageLabel,
    InfoBadge,
    PrimaryPushButton,
    SmoothScrollArea,
)

from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role, configure_button
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from utils.app_metadata import APP_VERSION
from utils.resource_path import resource_path


class AboutDialog(QDialog):
    _BASELINE_SIZE = QSize(340, 380)
    _SCREEN_MARGIN = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About ADBLab")
        self.setWindowIcon(get_themed_icon("info.svg"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self._applying_geometry = False
        self._initial_show_pending = True

        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._scroll_area = SmoothScrollArea()
        self._scroll_area.setObjectName("aboutScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(self._scroll_area)

        self._content_host = QWidget()
        self._content_host.setObjectName("aboutContentHost")
        self._content_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._scroll_area.setWidget(self._content_host)

        self._header = CardWidget()
        self._header.setObjectName("aboutHeader")
        self._header.setBorderRadius(BaseStyles.RADIUS_LG)
        header_layout = QVBoxLayout(self._header)
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setSpacing(4)

        self._title = apply_label_role(
            BodyLabel('<a href="https://github.com/BlackHu-art/ADBLab">ADBLab</a>'),
            FontRole.TITLE,
            color_key="TITLE_COLOR",
        )
        self._title.setObjectName("aboutTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setOpenExternalLinks(True)
        self._title.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self._title.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._title.setAccessibleName("Open the ADBLab project page")
        header_layout.addWidget(self._title)

        self._version = apply_label_role(
            BodyLabel(f"Version {APP_VERSION}"),
            FontRole.UI_SMALL,
            color_key="TEXT_SECONDARY",
        )
        self._version.setObjectName("aboutVer")
        self._version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version.setWordWrap(True)
        header_layout.addWidget(self._version)

        # ── 页头统一：状态徽标（开源许可）────────────────────────────────
        # 视觉重设计：改用 qfluentwidgets InfoBadge，跟随 Fluent 主题自动配色。
        self._status_badge = InfoBadge.success("Open Source", self)
        self._status_badge.setProperty("fontRole", FontRole.UI.value)
        self._status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._status_badge.setToolTip("Licensed for open source use")
        header_layout.addWidget(self._status_badge, 0, Qt.AlignmentFlag.AlignHCenter)

        self._content_layout.addWidget(self._header)

        body = QVBoxLayout()
        body.setSpacing(6)

        self._qr = ImageLabel()
        self._qr.setObjectName("aboutQR")
        self._qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr.setFixedSize(220, 220)
        self._qr.setScaledContents(True)
        self._qr.setAccessibleName("Author support QR code")
        self._qr.setAccessibleDescription("Scan this QR code to support the author.")
        pix = QPixmap(resource_path("resources/ZFB.jpg"))
        if not pix.isNull():
            self._qr.setPixmap(pix)
        body.addWidget(self._qr, 0, Qt.AlignmentFlag.AlignHCenter)

        self._hint = apply_label_role(
            BodyLabel("Scan to support the author"),
            FontRole.UI,
            color_key="BUTTON_ACCENT",
        )
        self._hint.setObjectName("aboutHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        body.addWidget(self._hint)

        self._content_layout.addLayout(body)

        footer_layout = QVBoxLayout()
        footer_layout.setSpacing(2)
        footer_layout.setContentsMargins(0, 0, 0, 12)

        self._footer = apply_label_role(
            BodyLabel("Copyright © 2026 Frankie Hu"),
            FontRole.UI_SMALL,
            color_key="TEXT_SECONDARY",
        )
        self._footer.setObjectName("aboutFooter")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setWordWrap(True)
        footer_layout.addWidget(self._footer)

        self._close_btn = PrimaryPushButton()
        configure_button(
            self._close_btn,
            text="Close",
            tooltip="Close the application information window",
        )
        self._close_btn.setIcon(get_themed_icon("x.svg"))
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setObjectName("aboutCloseBtn")
        self._close_btn.setMinimumWidth(100)
        self._close_btn.clicked.connect(self.close)
        button_row = QVBoxLayout()
        button_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        button_row.addWidget(self._close_btn)
        footer_layout.addLayout(button_row)

        self._content_layout.addLayout(footer_layout)
        # 常规屏幕保留自然布局提示，小屏则由滚动区的可缩放内容策略压窄页面。
        self._content_host.setMinimumSize(QSize())

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_geometry(initial=self._initial_show_pending)
        self._initial_show_pending = False

    def closeEvent(self, event):
        for signal in (BaseStyles.theme_changed, BaseStyles.fonts_changed):
            try:
                signal.disconnect(self._apply_theme)
            except (TypeError, RuntimeError):
                pass
        super().closeEvent(event)

    def _screen_available_size(self) -> QSize | None:
        candidates = [self.screen]
        parent = self.parentWidget()
        if parent is not None:
            candidates.append(parent.screen)
        for get_screen in candidates:
            try:
                screen = get_screen()
                geometry = screen.availableGeometry() if screen is not None else None
                if geometry is None or not geometry.isValid():
                    continue
                return QSize(
                    max(1, geometry.width() - self._SCREEN_MARGIN),
                    max(1, geometry.height() - self._SCREEN_MARGIN),
                )
            except (AttributeError, RuntimeError, TypeError):
                continue
        return None

    def _content_size_hint(self) -> QSize:
        self._content_layout.activate()
        frame_width = self._scroll_area.frameWidth() * 2
        return self._content_layout.sizeHint().expandedTo(self._BASELINE_SIZE) + QSize(
            frame_width,
            frame_width,
        )

    def _update_geometry(self, *, initial: bool = False) -> None:
        if self._applying_geometry:
            return
        self._applying_geometry = True
        try:
            self.setMinimumSize(QSize())
            self._content_host.setMinimumSize(QSize())
            content_hint = self._content_size_hint()
            self._content_host.setMinimumSize(0, content_hint.height())
            available_size = self._screen_available_size()
            target_size = (
                content_hint if available_size is None else content_hint.boundedTo(available_size)
            )
            self.setMinimumSize(target_size)
            if initial:
                self.resize(target_size)
            else:
                current_size = self.size()
                desired_size = QSize(
                    max(current_size.width(), target_size.width()),
                    max(current_size.height(), target_size.height()),
                )
                if available_size is not None:
                    desired_size = desired_size.boundedTo(available_size)
                if desired_size != current_size:
                    self.resize(desired_size)
        finally:
            self._applying_geometry = False

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
        if hasattr(self, "_status_badge"):
            self._status_badge.setFont(ui_font)

        def c(key):
            return BaseStyles.color(key)

        radius = BaseStyles.RADIUS_MD

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c("PANEL_BG")};
            }}
            QLabel#aboutQR {{
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {radius}px;
                background-color: #ffffff;
            }}
        """)
        self._close_btn.setMinimumHeight(30)
        text_height = QFontMetrics(close_font).height() + 10
        self._close_btn.setMinimumHeight(max(30, self._close_btn.sizeHint().height(), text_height))
        self._header.setMinimumHeight(56)
        self._header.setMinimumHeight(max(56, self._header.sizeHint().height()))
        self._update_geometry(initial=self._initial_show_pending)
