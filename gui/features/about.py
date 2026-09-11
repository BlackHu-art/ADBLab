"""提供设置页内嵌的应用版本、项目链接与支持信息。"""

from __future__ import annotations

from PySide6.QtCore import QSize, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QAbstractButton, QBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    HyperlinkCard,
    ImageLabel,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SettingCardGroup,
    setCustomStyleSheet,
)

from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import apply_font_role, configure_button, refresh_fluent_widget_style
from gui.styles.typography import FontRole
from gui.widgets.setting_card_layout import SettingsCardPresentation, apply_setting_text_style
from services.app_update import UpdateSnapshot
from utils.app_metadata import APP_PROJECT_URL, APP_VERSION
from utils.resource_path import resource_path


class AboutPanel(SettingCardGroup):
    """按 Gallery 的关于分组展示项目与支持信息，不主动访问网络。"""

    updateRequested = Signal()
    layoutChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("关于"), parent)
        self.setObjectName("aboutPanel")
        self._download_url: str | None = None
        self._app_description = tr(
            "当前版本 {version} · 开源项目\nAndroid 设备管理、应用操作与诊断工作台"
        ).format(version=APP_VERSION)
        self.project_card = HyperlinkCard(
            APP_PROJECT_URL,
            tr("项目主页"),
            FluentIcon.INFO,
            "ADBLab",
            self._app_description,
            self,
        )
        self.title_label = self.project_card.titleLabel
        self.version_label = self.project_card.contentLabel
        self.project_button = self.project_card.linkButton
        configure_button(
            self.project_button,
            text=tr("项目主页"),
            tooltip=tr("在浏览器中打开 ADBLab 项目主页"),
        )
        self.update_actions = QWidget(self.project_card)
        self.check_update_button = PushButton(tr("检查更新"), self.update_actions)
        self.update_action_layout = QHBoxLayout(self.update_actions)
        self.update_action_layout.setContentsMargins(0, 0, 0, 0)
        self.update_action_layout.setSpacing(8)
        self.release_button = PrimaryPushButton(tr("前往下载"), self.update_actions)
        self.update_action_layout.addWidget(self.project_button)
        self.update_action_layout.addWidget(self.check_update_button)
        self.update_action_layout.addWidget(self.release_button)
        self.check_update_button.clicked.connect(self.updateRequested)
        self.release_button.clicked.connect(self._open_release)
        configure_button(
            self.check_update_button, text=tr("检查更新"), tooltip=tr("检查是否有新的正式版本"),
        )
        self.support_card = SettingCard(
            FluentIcon.HEART,
            tr("支持作者"),
            tr("扫描二维码支持 ADBLab 的开发与维护"),
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
            SettingsCardPresentation(self.project_card, self.update_actions),
            SettingsCardPresentation(self.support_card, self.support_qr),
        )
        self.support_qr.setAccessibleName(tr("作者支持二维码"))
        self.addSettingCards([self.project_card, self.support_card])
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        BaseStyles.theme_changed.connect(self._refresh_typography)
        self.set_update_snapshot(UpdateSnapshot())

    def _refresh_typography(self, *_args) -> None:
        """独立嵌入时也响应字号与主题，控件仍由本组的 QObject 树释放。"""

        apply_font_role(self, FontRole.UI)
        apply_setting_text_style(self.titleLabel, FontRole.UI, bold=True)
        self.titleLabel.adjustSize()
        for presentation in self._presentations:
            apply_setting_text_style(presentation.card.titleLabel, FontRole.UI)
            apply_setting_text_style(presentation.card.contentLabel, FontRole.UI_SMALL)
        for button in (self.project_button, self.check_update_button, self.release_button):
            self._style_action_button(button)
        self.reflow(self.width())
        self.layoutChanged.emit()

    @staticmethod
    def _style_action_button(button: QAbstractButton) -> None:
        """让原生操作跟随项目字号，保留参考界面的配色、悬停和焦点样式。"""

        apply_font_role(button, FontRole.UI)
        # SettingCard 的第三方 QSS 固定按钮为 14px；局部覆盖字号，
        # 避免大字号下操作仍缩成小字，同时保留原生样式和项目焦点规则。
        refresh_fluent_widget_style(button)
        font = BaseStyles.font_for_role(FontRole.UI)
        family = font.family().replace("'", "\\'")
        font_rule = (
            f"{type(button).__name__} {{ font-family: '{family}'; "
            f"font-size: {font.pointSizeF()}pt; }}"
        )
        setCustomStyleSheet(
            button,
            str(button.property("lightCustomQss") or "") + font_rule,
            str(button.property("darkCustomQss") or "") + font_rule,
        )
        button.ensurePolished()
        # 原生按钮左右各有 12px 内边距，再为项目的 2px 焦点框预留空间。
        # 尺寸只随文字和字号变化，避免禁用导致焦点转移时整组操作横向跳动。
        button.setFixedWidth(button.fontMetrics().horizontalAdvance(button.text()) + 28)
        button.setFixedHeight(max(32, button.fontMetrics().height() + 16))

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 的 Slot stub 未计入方法 self。
    def set_update_snapshot(self, snapshot: UpdateSnapshot) -> None:
        """只呈现检查器已校验的状态；改文案后重新测量卡片和设置页滚动范围。"""

        status = tr("更新状态：尚未检查")
        detail = ""
        if snapshot.status == "idle":
            detail = tr("检查后，有新版本时可前往下载")
        elif snapshot.status == "checking":
            status = tr("正在检查更新…")
            detail = tr("正在获取最新正式版信息")
        elif snapshot.status == "error":
            errors = {
                "network": tr("检查失败：请检查网络后重试"),
                "tls": tr("检查失败：请检查系统时间或网络设置"),
                "timeout": tr("检查超时：请稍后重试"),
                "rate_limited": tr("检查受限：请稍后重试"),
                "unavailable": tr("更新服务暂不可用，请稍后重试"),
                "invalid_response": tr("版本信息异常，请稍后重试"),
            }
            status = errors.get(snapshot.error, tr("检查更新失败，请稍后重试"))
            if snapshot.release is not None:
                detail = tr("上次检查版本：{version}（历史结果）").format(
                    version=snapshot.release.version,
                )
        elif snapshot.release is not None:
            if snapshot.status == "available":
                status = tr("可更新至 {version} · {date} 发布").format(
                    version=snapshot.release.version,
                    # 发布日沿用服务端时区，避免平台本地时间转换拒绝边界年份。
                    date=snapshot.release.published_at.date().isoformat(),
                )
            elif snapshot.status == "current":
                status = tr("已是最新正式版，无需更新")
            else:
                status = tr("当前版本领先于正式版 {version}").format(
                    version=snapshot.release.version,
                )
            if snapshot.checked_at is not None:
                detail = tr("检查时间：{time}").format(
                    time=snapshot.checked_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                )
        # 保留原四行说明的高度；末行为空时仍占位，避免状态切换推动下方卡片。
        content = "\n".join((self._app_description, status, detail))
        self.project_card.setContent(content)
        self.update_actions.setAccessibleDescription(content)
        configure_button(
            self.check_update_button,
            text=tr("检查更新"),
            tooltip=tr("检查是否有新的正式版本") if snapshot.can_check else tr("请稍后再检查"),
        )
        self.check_update_button.setEnabled(snapshot.can_check and snapshot.status != "checking")
        # 重查及失败快照会保留历史发布信息；只有本次确认新版才能开放下载。
        self._download_url = (
            snapshot.release.url
            if snapshot.status == "available" and snapshot.release is not None else None
        )
        self.release_button.setEnabled(self._download_url is not None)
        configure_button(
            self.release_button,
            text=tr("前往下载"),
            tooltip=(
                tr("在浏览器中查看发布说明和下载文件") if self._download_url is not None
                else tr("检查到新版本后可前往下载")
            ),
        )
        self._refresh_typography()

    def _open_release(self) -> None:
        """显式点击才打开本次确认的新版页面，历史结果不提供下载准入。"""

        if self._download_url is not None:
            QDesktopServices.openUrl(QUrl(self._download_url))

    def reflow(self, width: int) -> None:
        """使用现有卡片度量，让短窗可以滚动到完整主页按钮和二维码。"""

        action_width = (
            sum(button.width() for button in (
                self.check_update_button, self.project_button, self.release_button,
            )) + 2 * self.update_action_layout.spacing()
        )
        self.update_action_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if action_width > max(1, width - 64)
            else QBoxLayout.Direction.LeftToRight
        )
        self.update_action_layout.invalidate()
        for presentation in self._presentations:
            presentation.reflow(width)
        cards_height = sum(item.card.height() for item in self._presentations)
        self.setFixedHeight(
            cards_height + max(0, len(self._presentations) - 1) * 2 + self.titleLabel.height() + 12
        )
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_presentations"):
            self.reflow(self.width())


__all__ = ["AboutPanel"]
