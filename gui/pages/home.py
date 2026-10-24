"""首页入口、快捷操作卡与设备摘要，保持现有页面及 Qt 所有权契约。

源自原 PyQt-Fluent-Widgets Gallery 示例（GPL-3.0）移植页面；
来源与许可说明见仓库根目录 ``THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FlowLayout,
    FluentIcon,
    IconWidget,
    InfoBadge,
    InfoLevel,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_font_role, apply_label_role, use_smooth_scroll
from gui.styles.icon_loader import DEVICE_ICON, cached_fluent_icon
from gui.widgets.home_banner import HomeBanner


class ActionCard(CardWidget):
    """由 Gallery ``SampleCard`` 改写的 ADBLab 快捷操作卡片。"""

    activated = Signal()

    def __init__(
        self,
        icon,
        title: str,
        content: str,
        callback: Callable[[], object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._preferred_width = 300
        self.setMinimumWidth(0)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(content)

        icon_widget = IconWidget(cached_fluent_icon(icon), self)
        icon_widget.setFixedSize(36, 36)
        title_label = StrongBodyLabel(title, self)
        content_label = CaptionLabel(content, self)
        self.title_label = title_label
        self.content_label = content_label
        title_label.setWordWrap(True)
        content_label.setWordWrap(True)
        for label in (title_label, content_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 12, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(title_label)
        text_layout.addWidget(content_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 12, 12)
        layout.setSpacing(14)
        layout.addWidget(icon_widget)
        layout.addLayout(text_layout, 1)
        self.activated.connect(callback)
        BaseStyles.ui_font_changed.connect(self._sync_font)
        self._sync_font()

    def _sync_font(self, _config=None) -> None:
        """快捷卡片跟随界面字体，并重新测量标题与说明的换行高度。"""

        apply_label_role(self.title_label, FontRole.UI, bold=True)
        apply_label_role(self.content_label, FontRole.UI_SMALL)
        self.updateGeometry()

    def set_preferred_width(self, width: int) -> None:
        """由分组统一分配行宽；不锁定最小宽度，允许极窄窗口继续收缩。"""

        width = max(1, width)
        if width != self._preferred_width:
            self._preferred_width = width
            self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        text_width = max(1, width - 92)
        text_height = sum(
            max(label.fontMetrics().height(), label.heightForWidth(text_width))
            for label in (self.title_label, self.content_label)
        )
        return max(92, text_height + 28)

    def sizeHint(self) -> QSize:
        return QSize(self._preferred_width, self.heightForWidth(self._preferred_width))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 92)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        released_inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and released_inside:
            self.activated.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ActionCardView(QWidget):
    """参考 Gallery ``SampleCardView`` 的流式卡片分组。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[ActionCard] = []
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_label = StrongBodyLabel(title, self)
        self.flow_layout = FlowLayout()
        self.flow_layout.setContentsMargins(0, 0, 0, 0)
        self.flow_layout.setHorizontalSpacing(12)
        self.flow_layout.setVerticalSpacing(12)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 0, 32, 0)
        layout.setSpacing(12)
        layout.addWidget(self.title_label)
        layout.addLayout(self.flow_layout)
        BaseStyles.ui_font_changed.connect(self._sync_font)
        self._sync_font()

    def _sync_font(self, _config=None) -> None:
        apply_label_role(self.title_label, FontRole.UI, bold=True)
        self._sync_card_widths()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_card_widths()

    def sizeHint(self) -> QSize:
        """按当前行宽报告高度，避免父滚动容器用单列估算锁住多余空白。"""

        layout = self.layout()
        if layout is None:
            return super().sizeHint()
        width = max(1, self.width())
        return QSize(width, layout.heightForWidth(width))

    def _sync_card_widths(self) -> None:
        """让同一行均分可用宽度，保留卡片对象、业务回调和键盘顺序。"""

        layout = self.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        width = max(1, self.width() - margins.left() - margins.right() - 1)
        spacing = self.flow_layout.horizontalSpacing()
        columns = min(3, max(1, (width + spacing) // (300 + spacing)))
        card_width = max(1, (width - (columns - 1) * spacing) // columns)
        for card in self._cards:
            card.set_preferred_width(card_width)
        self.flow_layout.invalidate()
        self.updateGeometry()

    def add_card(
        self, icon, title: str, content: str, callback: Callable[[], object]
    ) -> ActionCard:
        card = ActionCard(icon, title, content, callback, self)
        self._cards.append(card)
        self.flow_layout.addWidget(card)
        self._sync_card_widths()
        return card


class DeviceContextCard(CardWidget):
    """在首页和工作台持续展示当前操作设备。"""

    manageRequested = Signal()
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceContextCard")
        self.setMinimumHeight(96)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        icon = IconWidget(DEVICE_ICON, self)
        icon.setFixedSize(36, 36)
        self.title_label = StrongBodyLabel(tr("操作设备"), self)
        self.summary_label = BodyLabel(tr("尚未选择设备"), self)
        self.detail_label = CaptionLabel(tr("先选择设备，再执行应用、系统或远程操作"), self)
        self.summary_label.setWordWrap(True)
        self.detail_label.setWordWrap(True)
        for label in (self.title_label, self.summary_label, self.detail_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.badge = InfoBadge(self, InfoLevel.ATTENTION)
        self.badge.setText(tr("0 台"))

        self.refresh_button = PushButton(self)
        self.refresh_button.setIcon(FluentIcon.SYNC)
        self.refresh_button.setText(tr("刷新"))
        self.refresh_button.setToolTip(tr("重新扫描已连接的 Android 设备"))
        self.refresh_button.setAccessibleName(tr("刷新设备"))
        self.manage_button = PrimaryPushButton(self)
        self.manage_button.setIcon(DEVICE_ICON)
        self.manage_button.setText(tr("选择设备"))
        self.manage_button.setToolTip(tr("打开设备页并选择本次操作目标"))
        self.manage_button.setAccessibleName(tr("选择设备"))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.summary_label)
        text_layout.addWidget(self.detail_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 16, 12)
        layout.setSpacing(14)
        layout.addWidget(icon)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.badge)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.manage_button)

        self.manage_button.clicked.connect(self.manageRequested)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self._manage_text = tr("选择设备")
        BaseStyles.ui_font_changed.connect(self._sync_font)
        self._sync_font()

    def _sync_font(self, _config=None) -> None:
        apply_label_role(self.title_label, FontRole.UI, bold=True)
        apply_label_role(self.summary_label, FontRole.UI)
        apply_label_role(self.detail_label, FontRole.UI_SMALL)
        for button in (self.refresh_button, self.manage_button):
            apply_font_role(button, FontRole.UI, ensure_height=True)
        self._sync_responsive_state()
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        actions = (self.badge, self.refresh_button, self.manage_button)
        action_width = sum(
            action.sizeHint().width() + 14
            for action in actions if not action.isHidden()
        )
        text_width = max(1, width - 84 - action_width)
        text_height = sum(
            max(label.fontMetrics().height(), label.heightForWidth(text_width))
            for label in (self.title_label, self.summary_label, self.detail_label)
        )
        return max(96, text_height + 28)

    def sizeHint(self) -> QSize:
        return QSize(600, self.heightForWidth(max(1, self.width())))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 96)

    def set_context(
        self,
        selected_devices: list[str],
        connected_devices: list[str],
        discovery_state: str = "ready",
    ) -> None:
        """同步已连接、已选择和扫描状态，不改变设备选择真源。"""

        selected = list(selected_devices or [])
        connected = list(connected_devices or [])
        scanning = discovery_state == "scanning"
        self.refresh_button.setEnabled(not scanning)
        self.refresh_button.setText(tr("扫描中") if scanning else tr("刷新"))
        self.refresh_button.setToolTip(
            tr("正在扫描已连接的 Android 设备")
            if scanning
            else tr("重新扫描已连接的 Android 设备")
        )
        if discovery_state == "scanning":
            self.badge.setText(tr("扫描中"))
            self.badge.setLevel(InfoLevel.INFOAMTION)
        elif discovery_state == "unavailable":
            self.badge.setText(tr("ADB 不可用"))
            self.badge.setLevel(InfoLevel.ERROR)
        elif selected:
            self.badge.setText(tr("已选 {count} 台").format(count=len(selected)))
            self.badge.setLevel(InfoLevel.SUCCESS)
        elif connected:
            self.badge.setText(tr("在线 {count} 台").format(count=len(connected)))
            self.badge.setLevel(InfoLevel.ATTENTION)
        else:
            self.badge.setText(tr("未发现设备"))
            self.badge.setLevel(InfoLevel.WARNING)

        if selected:
            visible = "、".join(selected[:2])
            if len(selected) > 2:
                visible += tr(" 等 {count} 台").format(count=len(selected))
            self.summary_label.setText(tr("当前将操作 {count} 台设备").format(count=len(selected)))
            self.detail_label.setText(visible)
            self._manage_text = tr("更改选择")
        elif connected:
            self.summary_label.setText(tr("已有设备在线，但尚未选择操作目标"))
            self.detail_label.setText(tr("进入设备页勾选一台或多台设备"))
            self._manage_text = tr("选择设备")
        else:
            self.summary_label.setText(tr("尚未发现可操作设备"))
            self.detail_label.setText(tr("连接 USB 或无线 ADB 后点击刷新"))
            self._manage_text = tr("连接设备")
        self._sync_responsive_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_responsive_state()

    def _sync_responsive_state(self) -> None:
        """窄屏保留设备语义与短文本主动作，折叠次要状态。"""

        width = self.width()
        compact = width < 620
        self.refresh_button.setVisible(width >= 720)
        self.badge.setVisible(not compact)
        compact_text = tr("连接") if self._manage_text == tr("连接设备") else tr("选择")
        self.manage_button.setText(compact_text if compact else self._manage_text)
        self.manage_button.setAccessibleName(self._manage_text)
        if compact:
            # PushButton 的图标位置依赖样式最小宽度；压成正方形会把图标绘制到边界外。
            # 保留短动词并尊重最小尺寸，使窄屏主动作仍能直接辨认。
            self.manage_button.setFixedWidth(self.manage_button.minimumSizeHint().width())
        else:
            self.manage_button.setMinimumWidth(0)
            self.manage_button.setMaximumWidth(16777215)


class HomePage(ScrollArea):
    """按参考 Gallery 首页组织的 ADBLab 入口页。"""

    def __init__(self, frame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        use_smooth_scroll(self)
        self._top_left_radius = 0
        self.setObjectName("homePage")
        self.setAccessibleName(tr("首页"))
        # Windows 原生滚动区在透明窗口上仍会绘制 Base 底色，须限定清除首页承载层。
        self.setStyleSheet("#homePage, #homeView { background: transparent; border: none; }")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)

        view = QWidget(self)
        view.setObjectName("homeView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 52)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.device_context = DeviceContextCard(view)
        self.device_context.manageRequested.connect(
            lambda: frame._on_nav_requested("devices")
        )
        self.device_context.refreshRequested.connect(frame._request_device_refresh)
        context_host = QWidget(view)
        context_layout = QVBoxLayout(context_host)
        context_layout.setContentsMargins(32, 0, 32, 0)
        context_layout.addWidget(self.device_context)
        context_host.setVisible(not hasattr(frame, "_global_device_bar"))

        tools = ActionCardView(tr("常用工具"), view)
        tools_layout = tools.layout()
        assert tools_layout is not None
        tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tool_cards: dict[str, ActionCard] = {}
        for key, icon, title, content, callback in (
            (
                "app_mgr",
                FluentIcon.APPLICATION,
                tr("应用管理"),
                tr("查看、安装和卸载设备应用"),
                lambda: frame._open_workspace_feature("apps", "manager"),
            ),
            (
                "file_explorer",
                FluentIcon.FOLDER,
                tr("文件浏览器"),
                tr("浏览设备文件并传输内容"),
                lambda: frame._open_workspace_feature("devices", "files"),
            ),
            (
                "remote",
                FluentIcon.PROJECTOR,
                tr("远程控制"),
                tr("屏幕镜像、按键和手势在同一页面操作"),
                lambda: frame._open_workspace_feature("devices", "remote"),
            ),
            (
                "logcat",
                FluentIcon.SCROLL,
                tr("实时 Logcat"),
                tr("按设备查看实时 Android 日志"),
                lambda: frame._open_workspace_feature("system", "logcat"),
            ),
            (
                "performance",
                FluentIcon.SPEED_HIGH,
                tr("性能监控"),
                tr("启动性能采样与图表分析"),
                lambda: frame._open_workspace_feature("system", "performance"),
            ),
            (
                "cmd",
                FluentIcon.COMMAND_PROMPT,
                tr("终端"),
                tr("在项目目录打开命令行"),
                frame._open_cmd,
            ),
        ):
            self.tool_cards[key] = tools.add_card(icon, title, content, callback)
        self.banner = HomeBanner(tools, view)
        layout.addWidget(self.banner)
        layout.addWidget(context_host)

        workspace = ActionCardView(tr("设备工作流"), view)
        workspace_layout = workspace.layout()
        assert workspace_layout is not None
        workspace_layout.setContentsMargins(32, 0, 32, 0)
        for key, icon, title, content in (
            (
                "devices",
                DEVICE_ICON,
                tr("设备概览"),
                tr("查看连接状态，选择设备并打开工具"),
            ),
            ("apps", FluentIcon.CODE, tr("应用与诊断"), tr("应用包操作、Monkey 测试与诊断报告")),
            (
                "system", FluentIcon.DEVELOPER_TOOLS,
                tr("系统工具"), tr("系统命令、设备配置与网络操作"),
            ),
        ):
            workspace.add_card(
                icon,
                title,
                content,
                lambda route=key: frame._on_nav_requested(route),
            )
        self.tool_cards["save_path"] = workspace.add_card(
            FluentIcon.SAVE,
            tr("输出目录"),
            tr("修改截图、录屏等默认保存位置"),
            frame._on_save_path_clicked,
        )
        layout.addWidget(workspace)

        self.setWidget(view)

    def set_top_left_radius(self, radius: int) -> None:
        """把材质圆角固定在视口边界，避免滚动中的横幅或卡片覆盖主窗口圆角。"""

        self._top_left_radius = max(0, radius)
        self.banner.set_top_left_radius(self._top_left_radius)
        self._update_viewport_mask()

    def _update_viewport_mask(self) -> None:
        viewport = self.viewport()
        radius = min(self._top_left_radius, viewport.width() // 2, viewport.height() // 2)
        if radius == 0:
            viewport.clearMask()
            return
        # 只裁掉左上角圆弧之外的区域，其他三角及贴边滚动条仍占用完整视口。
        # QWidget 只能二值裁剪；不能为抗锯齿直接去掉 mask，否则滚动内容会在
        # 左上角覆盖云母背景。
        corner = QRegion(QRect(0, 0, radius, radius))
        circle = QRegion(QRect(0, 0, radius * 2, radius * 2), QRegion.RegionType.Ellipse)
        viewport.setMask(QRegion(viewport.rect()).subtracted(corner.subtracted(circle)))

    def viewportEvent(self, event: QEvent) -> bool:
        result = super().viewportEvent(event)
        if event.type() == QEvent.Type.Resize and hasattr(self, "_top_left_radius"):
            self._update_viewport_mask()
        return result

    def set_device_context(
        self,
        selected_devices: list[str],
        connected_devices: list[str],
        discovery_state: str,
    ) -> None:
        self.device_context.set_context(
            selected_devices,
            connected_devices,
            discovery_state,
        )


__all__ = ["ActionCard", "ActionCardView", "DeviceContextCard", "HomePage"]
