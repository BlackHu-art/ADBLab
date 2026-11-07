"""提供设置页内嵌的应用版本、项目链接与支持信息。"""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QTextLayout
from PySide6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
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


class _UpdateCardPresentation(SettingsCardPresentation):
    """状态说明共用包含回退字体的行高，避免相同四行文字切换时推移按钮。"""

    def _label_height(self, label: QLabel, width: int) -> int:
        natural_height = super()._label_height(label, width)
        if label is not self.card.contentLabel:
            return natural_height
        # QLabel 的末行字形会影响总高度；用同一说明中全部字形的回退字体
        # 测量单行上限，不能只用主字体的 QFontMetrics 或硬补一个像素。
        text_layout = QTextLayout(label.text().replace("\n", " "), label.font())
        text_layout.beginLayout()
        line = text_layout.createLine()
        line.setLineWidth(16777215)
        line_height = ceil(line.height())
        text_layout.endLayout()
        return max(natural_height, line_height * (label.text().count("\n") + 1))


class _SupportCardPresentation(SettingsCardPresentation):
    """标题行独立测量，二维码仅增加下方裁剪区，避免展开时挤动标题和按钮。"""

    def __init__(self, card: SettingCard, button: QAbstractButton, reveal: ContentReveal) -> None:
        super().__init__(card, button)
        button.setAccessibleName(button.text())
        self.reveal = reveal
        self.header = QWidget(card)
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(16)
        while card.hBoxLayout.count():
            item = card.hBoxLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.header_layout.addWidget(widget, 1 if widget is self.body else 0)
        self.column = QWidget(card)
        # 裁剪高先于卡高变化；纵向布局会在这一瞬间压缩或居中子项，再把
        # 二维码和标题移回。两段内容固定自然起点，只让外层卡片改变高度。
        self.header.setParent(self.column)
        reveal.setParent(self.column)
        card.hBoxLayout.addWidget(self.column, 1, Qt.AlignmentFlag.AlignTop)

    def reflow(self, width: int) -> None:
        super().reflow(width)
        self.header.setFixedHeight(self.card.height() - 32)
        self.header.setFixedWidth(max(1, width - 32))
        self.reveal.setFixedWidth(max(1, width - 32))
        self.header.move(0, 0)
        self.reveal.move(0, self.header.height())
        self.header_layout.setAlignment(
            self.card.iconLabel,
            Qt.AlignmentFlag.AlignTop if self.compact else Qt.AlignmentFlag.AlignVCenter,
        )
        self.sync_height()

    def sync_height(self) -> None:
        """只提交外层卡高，不重新挂载标题行控件或测量其他设置卡。"""
        height = self.header.height() + self.reveal.height()
        self.column.setFixedHeight(height)
        self.card.setFixedHeight(height + 32)
        self.card.updateGeometry()


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
        self.support_action_layout = QHBoxLayout(self.support_actions)
        self.support_action_layout.setContentsMargins(24, 24, 24, 8)
        self.support_body = QWidget(self.support_actions)
        self.support_body_layout = QHBoxLayout(self.support_body)
        self.support_body_layout.setContentsMargins(0, 0, 0, 0)
        self.support_body_layout.setSpacing(32)
        self.support_copy = QWidget(self.support_body)
        copy_layout = QVBoxLayout(self.support_copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(12)
        self.support_heading = QLabel(tr("支付宝扫码支持"), self.support_copy)
        self.support_hint = QLabel(tr("打开支付宝「扫一扫」扫描二维码"), self.support_copy)
        self.support_thanks = QLabel(tr("感谢你支持 ADBLab 的开发与维护。"), self.support_copy)
        for label in (self.support_heading, self.support_hint, self.support_thanks):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            copy_layout.addWidget(label)
        self.support_body_layout.addWidget(self.support_copy, 1, Qt.AlignmentFlag.AlignVCenter)
        self.support_action_layout.addWidget(self.support_body, 0, Qt.AlignmentFlag.AlignHCenter)
        self.support_button = PushButton(tr("显示二维码"), self.support_card)
        self.support_button.setCheckable(True)
        configure_button(
            self.support_button,
            text=tr("显示二维码"),
            tooltip=tr("展开或收起作者支持二维码"),
        )
        self.support_qr = ImageLabel(self.support_body)
        self.support_qr.setObjectName("aboutSupportQr")
        self.support_qr.setBorderRadius(8, 8, 8, 8)
        source = QPixmap(resource_path("resources/ZFB.jpg"))
        if not source.isNull():
            # 原收款截图的码区为 41×41 模块；只裁掉装饰，不重新生成付款内容。
            # 四周保留四个模块的白色静区，196px 下每模块恰好占四个逻辑像素。
            code = source.copy(QRect(335, 215, 1036, 1036))
            dpr = max(1.0, self.support_qr.devicePixelRatioF())
            module = max(1, round(4 * dpr))
            side = 49 * module
            square = QPixmap(side, side)
            square.fill(Qt.GlobalColor.white)
            painter = QPainter(square)
            painter.drawPixmap(
                4 * module, 4 * module,
                code.scaled(41 * module, 41 * module, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.FastTransformation),
            )
            painter.end()
            square.setDevicePixelRatio(dpr)
            self.support_qr.setPixmap(square)
        self.support_qr.setFixedSize(QSize(196, 196))
        self.support_qr.setScaledContents(True)
        self.support_body_layout.addWidget(self.support_qr, 0, Qt.AlignmentFlag.AlignCenter)
        self.support_reveal = ContentReveal(
            self.support_actions, self.support_button, self.support_card,
        )
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
        self._support_presentation = _SupportCardPresentation(
            self.support_card, self.support_button, self.support_reveal,
        )
        self._presentations = (
            _UpdateCardPresentation(self.project_card, self.update_actions),
            SettingsCardPresentation(self.installer_card, self.installer_actions),
            self._support_presentation,
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
        apply_setting_text_style(self.support_heading, FontRole.TITLE, bold=True)
        for label in (self.support_hint, self.support_thanks):
            apply_setting_text_style(label, FontRole.UI_SMALL)
            label.setStyleSheet(
                label.styleSheet() + f"color: {BaseStyles.get_color('TEXT_SECONDARY').name()};"
            )
        for button in (
            self.project_button, self.check_update_button, self.release_button, self.support_button,
            self.installer_download_button, self.installer_cancel_button,
            self.installer_install_button,
        ):
            self._style_action_button(button)
        # 两种译文共用尺寸，避免英文 Show/Hide 的字宽差使按钮在切换时横移。
        self.support_button.setFixedWidth(max(
            self.support_button.fontMetrics().horizontalAdvance(tr(text))
            for text in ("显示二维码", "收起二维码")
        ) + 28)
        self.reflow(self.width())
        self.layoutChanged.emit()

    def _set_support_expanded(self, expanded: bool) -> None:
        """只切换本页二维码的可见性，并同步卡片高度与设置页滚动范围。"""

        text = tr("收起二维码") if expanded else tr("显示二维码")
        self.support_button.setText(text)
        self.support_button.setAccessibleName(text)
        # macOS 原生窗口在嵌套卡片逐帧改高时会短暂漏画、错裁上方内容。
        # 二维码作为静态辅助信息一次提交完整状态，避免进入该绘制路径。
        self.support_reveal.set_expanded(expanded, animated=False)
        self._sync_support_geometry()

    def _sync_support_geometry(self) -> None:
        """显隐只更新本卡与分组高度，标题行布局保持不动。"""
        self._support_presentation.sync_height()
        self._sync_group_height()
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
        self._reflow_support_content(width)
        for presentation in self._presentations:
            presentation.reflow(width)
        self._sync_group_height()

    def _reflow_support_content(self, width: int) -> None:
        """图文组按可读列宽切换横排与竖排；动画帧只裁剪已布局的完整内容。"""
        body_width = max(196, min(640, width - 32 - 48))
        self.support_body.setFixedWidth(body_width)
        text_width = max(220, self.support_hint.fontMetrics().averageCharWidth() * 24)
        stacked = body_width < 196 + 32 + text_width
        self.support_body_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        )
        self.support_body_layout.setSpacing(20 if stacked else 32)
        for label in (self.support_heading, self.support_hint, self.support_thanks):
            label.setAlignment(
                Qt.AlignmentFlag.AlignCenter if stacked
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            label.ensurePolished()
        self.support_body_layout.invalidate()
        # 外层横排布局会用整行可用宽度询问换行高；正文已封顶，必须按实际
        # 图文宽度落实自然高度，否则宽窗大字号会低估说明所需行数。
        self.support_body.setFixedHeight(max(
            self.support_qr.height(), self.support_body_layout.heightForWidth(body_width),
        ))

    def _sync_group_height(self) -> None:
        """让分组随可见卡片取高，不改变各卡片内部排布。"""
        visible = [item for item in self._presentations if not item.card.isHidden()]
        cards_height = sum(item.card.height() for item in visible)
        self.setFixedHeight(
            cards_height + max(0, len(visible) - 1) * 2 + self.titleLabel.height() + 12
        )
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_presentations") and event.size().width() != event.oldSize().width():
            self.reflow(self.width())


__all__ = ["AboutPanel"]
