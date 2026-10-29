"""提供设置页内嵌的应用版本、项目链接与支持信息。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractButton, QBoxLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    HyperlinkCard,
    ImageLabel,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SettingCardGroup,
)

from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import apply_font_role, configure_button, set_fluent_font_rule
from gui.styles.typography import FontRole
from gui.widgets.collapsible_tools import ContentReveal
from gui.widgets.setting_card_layout import SettingsCardPresentation, apply_setting_text_style
from services.app_update import UpdateSnapshot
from utils.app_metadata import APP_PROJECT_URL, APP_VERSION
from utils.resource_path import resource_path

if TYPE_CHECKING:
    from gui.adapters.installer_update import InstallerSnapshot


class AboutPanel(SettingCardGroup):
    """按 Gallery 的关于分组展示项目与支持信息，不主动访问网络。"""

    updateRequested = Signal()
    installerDownloadRequested = Signal()
    installerCancelRequested = Signal()
    installerInstallRequested = Signal()
    layoutChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("关于"), parent)
        self.setObjectName("aboutPanel")
        self._download_url: str | None = None
        self._installer_enabled = False
        self._update_snapshot = UpdateSnapshot()
        self._installer_snapshot: InstallerSnapshot | None = None
        self._handoff_state = "idle"
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
        self.update_actions.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.update_actions.setAccessibleName("ADBLab")
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
        self.support_actions = QWidget(self.support_card)
        self.support_action_layout = QVBoxLayout(self.support_actions)
        self.support_action_layout.setContentsMargins(0, 0, 0, 0)
        self.support_action_layout.setSpacing(12)
        self.support_button = PushButton(tr("显示二维码"), self.support_actions)
        self.support_button.setCheckable(True)
        configure_button(
            self.support_button,
            text=tr("显示二维码"),
            tooltip=tr("展开或收起作者支持二维码"),
        )
        self.support_qr = ImageLabel(self.support_actions)
        self.support_qr.setObjectName("aboutSupportQr")
        source = QPixmap(resource_path("resources/ZFB.jpg"))
        if not source.isNull():
            # ImageLabel 绘制时按 IgnoreAspectRatio 铺满；先等比缩放并居中到方形
            # 画布，既避免二维码纵向拉伸，也避免每次重绘缩放整张 1706x1815 原图。
            dpr = max(1.0, self.support_qr.devicePixelRatioF())
            side = max(1, round(132 * dpr))
            square = QPixmap(side, side)
            square.fill(Qt.GlobalColor.white)
            painter = QPainter(square)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scaled = source.scaled(
                square.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled,
            )
            painter.end()
            square.setDevicePixelRatio(dpr)
            self.support_qr.setPixmap(square)
        self.support_qr.setFixedSize(QSize(132, 132))
        self.support_qr.setScaledContents(True)
        self.support_action_layout.addWidget(self.support_button, 0, Qt.AlignmentFlag.AlignRight)
        self.support_reveal = ContentReveal(
            self.support_qr, self.support_button, self.support_actions,
        )
        self.support_reveal.setFixedWidth(132)
        self.support_action_layout.addWidget(self.support_reveal, 0, Qt.AlignmentFlag.AlignRight)
        self.support_button.toggled.connect(self._set_support_expanded)
        self.installer_card = SettingCard(
            FluentIcon.DOWNLOAD, tr("安装版更新"), tr("检查到可用安装包后可在此下载"), self,
        )
        self.installer_actions = QWidget(self.installer_card)
        self.installer_actions.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.installer_actions.setAccessibleName(tr("安装版更新"))
        self.installer_action_layout = QHBoxLayout(self.installer_actions)
        self.installer_action_layout.setContentsMargins(0, 0, 0, 0)
        self.installer_action_layout.setSpacing(8)
        self.installer_download_button = PushButton(tr("下载安装包"), self.installer_actions)
        self.installer_cancel_button = PushButton(tr("取消下载"), self.installer_actions)
        self.installer_install_button = PrimaryPushButton(tr("退出并安装"), self.installer_actions)
        for button, signal in (
            (self.installer_download_button, self.installerDownloadRequested),
            (self.installer_cancel_button, self.installerCancelRequested),
            (self.installer_install_button, self.installerInstallRequested),
        ):
            self.installer_action_layout.addWidget(button)
            button.clicked.connect(signal)
            configure_button(button, text=button.text(), tooltip=button.text())
        self._presentations = (
            SettingsCardPresentation(self.project_card, self.update_actions),
            SettingsCardPresentation(self.installer_card, self.installer_actions),
            SettingsCardPresentation(self.support_card, self.support_actions),
        )
        self.support_reveal.geometry_changed.connect(self._sync_support_geometry)
        self.support_qr.setAccessibleName(tr("作者支持二维码"))
        self.addSettingCards([self.project_card, self.installer_card, self.support_card])
        self.installer_card.hide()
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
        for button in (
            self.project_button, self.check_update_button, self.release_button, self.support_button,
            self.installer_download_button, self.installer_cancel_button,
            self.installer_install_button,
        ):
            self._style_action_button(button)
        self.reflow(self.width())
        self.layoutChanged.emit()

    def _set_support_expanded(self, expanded: bool) -> None:
        """只切换本页二维码的可见性，并同步卡片高度与设置页滚动范围。"""

        self.support_reveal.set_expanded(expanded)
        configure_button(
            self.support_button,
            text=tr("收起二维码") if expanded else tr("显示二维码"),
            tooltip=tr("展开或收起作者支持二维码"),
        )
        self._style_action_button(self.support_button)
        self._sync_support_geometry()

    def _sync_support_geometry(self) -> None:
        """固定高度设置卡随裁剪范围同步取高，保留二维码原始尺寸。"""
        self.reflow(self.width())
        self.layoutChanged.emit()

    @staticmethod
    def _style_action_button(button: QAbstractButton) -> None:
        """让原生操作跟随项目字号，保留参考界面的配色、悬停和焦点样式。"""

        apply_font_role(button, FontRole.UI)
        # SettingCard 的第三方 QSS 固定按钮为 14px；局部覆盖字号，
        # 避免大字号下操作仍缩成小字，同时保留原生样式和项目焦点规则。
        font = BaseStyles.font_for_role(FontRole.UI)
        family = font.family().replace("'", "\\'")
        font_rule = (
            f"{type(button).__name__} {{ font-family: '{family}'; "
            f"font-size: {font.pointSizeF()}pt; }}"
        )
        set_fluent_font_rule(button, font_rule)
        button.ensurePolished()
        # 原生按钮左右各有 12px 内边距，再为项目的 2px 焦点框预留空间。
        # 尺寸只随文字和字号变化，避免禁用导致焦点转移时整组操作横向跳动。
        button.setFixedWidth(button.fontMetrics().horizontalAdvance(button.text()) + 28)
        button.setFixedHeight(max(32, button.fontMetrics().height() + 16))

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 的 Slot stub 未计入方法 self。
    def set_update_snapshot(self, snapshot: UpdateSnapshot) -> None:
        """只呈现检查器已校验的状态；改文案后重新测量卡片和设置页滚动范围。"""

        self._update_snapshot = snapshot
        status = tr("更新状态：尚未检查")
        detail = tr("检查后，有新版本时可前往下载")
        if snapshot.status == "checking":
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
        elif snapshot.status != "idle" and snapshot.release is not None:
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
        # 未取得发布信息时仍给出下一步提示；空末行的回退字体测高可能更小，导致卡片跳动。
        content = "\n".join((self._app_description, status, detail))
        self.project_card.setContent(content)
        self.update_actions.setAccessibleDescription(content)
        configure_button(
            self.check_update_button,
            text=tr("检查更新"),
            tooltip=tr("检查是否有新的正式版本") if snapshot.can_check else tr("请稍后再检查"),
        )
        can_check = (
            snapshot.can_check and snapshot.status != "checking"
            and self._handoff_state not in {"preparing", "ready"}
        )
        # 重查及失败快照会保留历史发布信息；只有本次确认新版才能开放下载。
        self._download_url = (
            snapshot.release.url
            if snapshot.status == "available" and snapshot.release is not None else None
        )
        # 先承接即将禁用的操作焦点，避免 Qt 沿全窗 Tab 顺序跳到侧栏主题入口。
        # 状态通知不抢占其他页面或控件的焦点；空白操作组不执行 Enter/Space 动作。
        if (
            self.check_update_button.hasFocus() and not can_check
            or self.release_button.hasFocus() and self._download_url is None
        ):
            self.update_actions.setFocus(Qt.FocusReason.OtherFocusReason)
        self.check_update_button.setEnabled(can_check)
        self.release_button.setEnabled(self._download_url is not None)
        configure_button(
            self.release_button,
            text=tr("前往下载"),
            tooltip=(
                tr("在浏览器中查看发布说明和下载文件") if self._download_url is not None
                else tr("检查到新版本后可前往下载")
            ),
        )
        self._refresh_installer_state()
        self._refresh_typography()

    def set_installer_enabled(self, enabled: bool) -> None:
        """仅组合根确认安装身份后开放卡片；免安装入口保持原浏览器行为。"""
        self._installer_enabled = enabled
        self.installer_card.setVisible(enabled)
        self._refresh_installer_state()
        self._refresh_typography()

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 的 Slot stub 未计入方法 self。
    def set_installer_snapshot(self, snapshot: InstallerSnapshot) -> None:
        """呈现下载器的进度与已校验结果，历史发布不能恢复安装准入。"""
        self._installer_snapshot = snapshot
        self._refresh_installer_state()
        self._refresh_typography()

    @Slot(str)  # type: ignore[reportArgumentType]  # PySide6 的 Slot stub 未计入方法 self。
    def set_handoff_state(self, status: str) -> None:
        """准备期间合并点击并保持焦点；准备失败仍可重新请求退出安装。"""
        self._handoff_state = status
        self.set_update_snapshot(self._update_snapshot)

    def _refresh_installer_state(self) -> None:
        """按钮只由当前发布、下载状态和交接准备共同授予可操作性。"""
        release = self._update_snapshot
        asset = getattr(release, "installer_asset", None)
        fresh = self._installer_enabled and release.status == "available" and asset is not None
        snapshot = self._installer_snapshot
        state = snapshot.status if snapshot is not None else "idle"
        verified = snapshot.verified if snapshot is not None else None
        busy = self._handoff_state in {"preparing", "ready"}
        ready = fresh and state == "ready" and verified is not None and verified.asset == asset
        content = tr("检查到可用安装包后可在此下载")
        if fresh:
            content = tr("下载安装包后，确认退出即可打开安装向导")
        if state == "downloading" and snapshot is not None:
            percent = min(100, max(0, snapshot.received * 100 // max(1, snapshot.total)))
            content = tr("正在下载安装包：{percent}% · 可继续使用应用").format(percent=percent)
        elif ready:
            content = tr("安装包已校验。安装前将停止本实例任务并保存数据")
        elif state == "cancelled":
            content = tr("下载已取消，可重新下载")
        elif state == "error":
            content = tr("下载或校验失败，请检查网络与可用空间后重试")
        if self._handoff_state == "preparing":
            content = tr("正在准备安装交接，请稍候…")
        elif self._handoff_state == "error":
            content = tr("安装交接准备失败，可重新点击“退出并安装”")
        elif self._handoff_state == "ready":
            content = tr("正在停止任务并保存数据；失败时保留安装包供下次重试")
        states = (
            (self.installer_download_button,
             fresh and state != "downloading" and not ready and not busy),
            (self.installer_cancel_button, state == "downloading" and not busy),
            (self.installer_install_button, ready and not busy),
        )
        if any(button.hasFocus() and not enabled for button, enabled in states):
            self.installer_actions.setFocus(Qt.FocusReason.OtherFocusReason)
        for button, enabled in states:
            button.setEnabled(bool(enabled))
        self.installer_card.setContent(content)
        self.installer_actions.setAccessibleDescription(content)

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
        installer_width = sum(button.width() for button in (
            self.installer_download_button, self.installer_cancel_button,
            self.installer_install_button,
        )) + 2 * self.installer_action_layout.spacing()
        self.installer_action_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if installer_width > max(1, width - 64)
            else QBoxLayout.Direction.LeftToRight
        )
        self.installer_action_layout.invalidate()
        # 隐藏图片后重新测量容器，避免沿用展开时的 sizeHint 留下空白。
        self.support_action_layout.invalidate()
        for presentation in self._presentations:
            presentation.reflow(width)
        visible = [item for item in self._presentations if not item.card.isHidden()]
        cards_height = sum(item.card.height() for item in visible)
        self.setFixedHeight(
            cards_height + max(0, len(visible) - 1) * 2 + self.titleLabel.height() + 12
        )
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_presentations"):
            self.reflow(self.width())


__all__ = ["AboutPanel"]
