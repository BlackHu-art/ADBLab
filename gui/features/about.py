"""提供设置页内嵌的应用版本、项目链接与支持信息。"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIcon,
    HyperlinkCard,
    ImageLabel,
    SettingCard,
    SettingCardGroup,
    setCustomStyleSheet,
)

from gui.styles import BaseStyles
from gui.styles.fluent import apply_font_role, configure_button, refresh_fluent_widget_style
from gui.styles.typography import FontRole
from gui.widgets.setting_card_layout import SettingsCardPresentation, apply_setting_text_style
from utils.app_metadata import APP_VERSION
from utils.resource_path import resource_path


class AboutPanel(SettingCardGroup):
    """按 Gallery 的关于分组展示项目与支持信息，不主动访问网络。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("关于", parent)
        self.setObjectName("aboutPanel")
        self.project_card = HyperlinkCard(
            "https://github.com/BlackHu-art/ADBLab",
            "项目主页",
            FluentIcon.INFO,
            "ADBLab",
            f"版本 {APP_VERSION} · 开源项目\nAndroid 设备管理、应用操作与诊断工作台",
            self,
        )
        self.title_label = self.project_card.titleLabel
        self.version_label = self.project_card.contentLabel
        self.project_button = self.project_card.linkButton
        configure_button(
            self.project_button,
            text="项目主页",
            tooltip="在浏览器中打开 ADBLab 项目主页",
        )
        self.support_card = SettingCard(
            FluentIcon.HEART,
            "支持作者",
            "扫描二维码支持 ADBLab 的开发与维护",
            self,
        )
        self.support_qr = ImageLabel(self.support_card)
        self.support_qr.setObjectName("aboutSupportQr")
        pixmap = QPixmap(resource_path("resources/ZFB.jpg"))
        if not pixmap.isNull():
            self.support_qr.setPixmap(pixmap)
        self.support_qr.setFixedSize(QSize(132, 132))
        self.support_qr.setScaledContents(True)
        self._presentations = (
            SettingsCardPresentation(self.project_card, self.project_button),
            SettingsCardPresentation(self.support_card, self.support_qr),
        )
        self.support_qr.setAccessibleName("作者支持二维码")
        self.addSettingCards([self.project_card, self.support_card])
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        BaseStyles.theme_changed.connect(self._refresh_typography)
        self._refresh_typography()

    def _refresh_typography(self, *_args) -> None:
        """独立嵌入时也响应字号与主题，控件仍由本组的 QObject 树释放。"""

        apply_font_role(self, FontRole.UI)
        apply_setting_text_style(self.titleLabel, FontRole.UI, bold=True)
        self.titleLabel.adjustSize()
        for presentation in self._presentations:
            apply_setting_text_style(presentation.card.titleLabel, FontRole.UI)
            apply_setting_text_style(presentation.card.contentLabel, FontRole.UI_SMALL)
        apply_font_role(self.project_button, FontRole.UI)
        # HyperlinkCard 的第三方 QSS 固定按钮为 14px；只覆盖字号并保留
        # 原生链接配色及项目焦点样式，避免大字号下仍出现一枚微小链接。
        refresh_fluent_widget_style(self.project_button)
        font = BaseStyles.font_for_role(FontRole.UI)
        family = font.family().replace("'", "\\'")
        font_rule = (
            f"HyperlinkButton {{ font-family: '{family}'; "
            f"font-size: {font.pointSizeF()}pt; }}"
        )
        setCustomStyleSheet(
            self.project_button,
            str(self.project_button.property("lightCustomQss") or "") + font_rule,
            str(self.project_button.property("darkCustomQss") or "") + font_rule,
        )
        self.project_button.ensurePolished()
        self.project_button.setMaximumHeight(16777215)
        self.project_button.setMinimumHeight(
            max(32, self.project_button.fontMetrics().height() + 14)
        )
        self.reflow(self.width())

    def reflow(self, width: int) -> None:
        """使用现有卡片度量，让短窗可以滚动到完整主页按钮和二维码。"""

        for presentation in self._presentations:
            presentation.reflow(width)
        cards_height = sum(item.card.height() for item in self._presentations)
        self.setFixedHeight(cards_height + 2 + self.titleLabel.height() + 12)
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_presentations"):
            self.reflow(self.width())


__all__ = ["AboutPanel"]
