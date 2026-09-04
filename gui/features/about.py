"""提供设置页内嵌的应用版本、项目链接与支持信息。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ImageLabel, InfoBadge, StrongBodyLabel

from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role
from gui.styles.typography import FontRole
from utils.app_metadata import APP_VERSION
from utils.resource_path import resource_path


class AboutPanel(CardWidget):
    """在设置页面中展示 About 信息，不创建额外顶层窗口。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutPanel")
        self.setBorderRadius(BaseStyles.RADIUS_LG)

        self.title_label = apply_label_role(
            StrongBodyLabel(
                '<a href="https://github.com/BlackHu-art/ADBLab">ADBLab</a>',
                self,
            ),
            FontRole.TITLE,
            color_key="TITLE_COLOR",
        )
        self.title_label.setOpenExternalLinks(True)
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.title_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.title_label.setAccessibleName("打开 ADBLab 项目主页")

        self.version_label = apply_label_role(
            BodyLabel(f"版本 {APP_VERSION}", self),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self.open_source_badge = InfoBadge.success("开源项目", self)

        summary = apply_label_role(
            BodyLabel(
                "面向 Windows 的 Android 设备管理、应用操作与诊断工作台。",
                self,
            ),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        summary.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.version_label)
        text_layout.addWidget(self.open_source_badge, 0, Qt.AlignmentFlag.AlignLeft)
        text_layout.addWidget(summary)
        text_layout.addStretch(1)

        self.support_qr = ImageLabel(self)
        self.support_qr.setObjectName("aboutSupportQr")
        self.support_qr.setAccessibleName("作者支持二维码")
        self.support_qr.setAccessibleDescription("扫描二维码支持作者")
        pixmap = QPixmap(resource_path("resources/ZFB.jpg"))
        if not pixmap.isNull():
            self.support_qr.setPixmap(pixmap)
        self.support_qr.setFixedSize(QSize(132, 132))
        self.support_qr.setScaledContents(True)

        content_layout = QHBoxLayout(self)
        content_layout.setContentsMargins(20, 18, 20, 18)
        content_layout.setSpacing(20)
        content_layout.addLayout(text_layout, 1)
        content_layout.addWidget(self.support_qr, 0, Qt.AlignmentFlag.AlignRight)


__all__ = ["AboutPanel"]
