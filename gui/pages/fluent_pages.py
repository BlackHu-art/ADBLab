"""基于 PyQt-Fluent-Widgets Gallery 示例（GPL-3.0）移植的主界面页面组件。

页面骨架、标题区和流式操作卡片直接沿用参考项目的组织方式，并改写为
PySide6 与 ADBLab 业务入口。这里不再复刻旧主窗口的分栏、工具条或页签体系。
来源与许可说明见仓库根目录 ``THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ColorPickerButton,
    ComboBox,
    ExpandLayout,
    FlowLayout,
    FluentIcon,
    IconWidget,
    InfoBadge,
    InfoLevel,
    PrimaryPushButton,
    PushButton,
    PushSettingCard,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SmoothScrollArea,
    StrongBodyLabel,
    SwitchSettingCard,
    TitleLabel,
    ToolButton,
    isDarkTheme,
)

from core.settings_manager import AppSettings
from gui.features import AboutPanel
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute
from gui.styles import BaseStyles


class PageHeader(QWidget):
    """参考 Gallery ``ToolBar`` 的页面标题区。"""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(88)
        self.title_label = TitleLabel(title, self)
        self.subtitle_label = CaptionLabel(subtitle, self)
        self.theme_button = ToolButton(FluentIcon.CONSTRACT, self)
        self.sync_theme_action()
        for label in (self.title_label, self.subtitle_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.theme_button)
        self.actions_layout = actions

        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 14, 32, 12)
        layout.setSpacing(16)
        layout.addLayout(text_layout, 1)
        layout.addLayout(actions)

    def set_subtitle(self, text: str) -> None:
        """更新页面位置说明，为内嵌功能切换提供即时反馈。"""

        self.subtitle_label.setText(text)
        self.subtitle_label.setToolTip(text)

    def set_title(self, text: str) -> None:
        """更新当前功能标题，使左侧叶节点与内容标题保持一致。"""

        self.title_label.setText(text)
        self.title_label.setToolTip(text)

    def add_action_widget(self, widget: QWidget) -> None:
        """把页面状态或动作放到主题按钮之前，避免重复构建业务页头。"""

        widget.setParent(self)
        self.actions_layout.insertWidget(self.actions_layout.count() - 1, widget)
        widget.show()

    def sync_theme_action(self) -> None:
        """按已解析主题显示切换目标，避免固定图标造成动作语义含糊。"""

        dark = BaseStyles.resolved_theme() == "Dark"
        target = "浅色" if dark else "深色"
        self.theme_button.setIcon(
            FluentIcon.BRIGHTNESS if dark else FluentIcon.QUIET_HOURS
        )
        self.theme_button.setToolTip(f"切换到{target}主题")
        self.theme_button.setAccessibleName(f"切换到{target}主题")


class GalleryPage(QWidget):
    """参考 GalleryInterface 的独立功能页，标题和内容不再共享旧分栏。"""

    def __init__(
        self,
        route_key: str,
        title: str,
        subtitle: str,
        content: QWidget,
        *,
        scroll_area: SmoothScrollArea | None = None,
        scroll: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(route_key)
        self.header = PageHeader(title, subtitle, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)

        if scroll:
            body = scroll_area or SmoothScrollArea(self)
            body.setObjectName(f"{route_key}ScrollArea")
            body.setWidgetResizable(True)
            body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            body.setFrameShape(SmoothScrollArea.Shape.NoFrame)
            body.setStyleSheet("QScrollArea { border: none; background: transparent; }")

            wrapper = QWidget(body)
            wrapper.setObjectName(f"{route_key}View")
            content_layout = QVBoxLayout(wrapper)
            content_layout.setContentsMargins(32, 16, 32, 28)
            content_layout.setSpacing(20)
            content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            content.setParent(wrapper)
            content_layout.addWidget(content)
            # QScrollArea.takeWidget() 会保留旧页面的 hidden 状态；参考项目在把
            # 示例控件移入卡片后同样显式 show，确保迁移后的内容立即可见。
            content.show()
            body.setWidget(wrapper)
            self.body = body
        else:
            body_wrapper = QWidget(self)
            body_layout = QVBoxLayout(body_wrapper)
            body_layout.setContentsMargins(32, 12, 32, 28)
            body_layout.addWidget(content)
            self.body = body_wrapper

        layout.addWidget(self.body, 1)
        # 从旧宿主转移出的滚动容器本身也可能保留 hidden 状态。
        self.body.show()


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
        self.setFixedSize(300, 92)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(content)

        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(36, 36)
        title_label = StrongBodyLabel(title, self)
        content_label = CaptionLabel(content, self)
        content_label.setWordWrap(True)

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

    def add_card(
        self, icon, title: str, content: str, callback: Callable[[], object]
    ) -> ActionCard:
        card = ActionCard(icon, title, content, callback, self)
        self.flow_layout.addWidget(card)
        return card


class BannerWidget(QWidget):
    """参考 Gallery BannerWidget 的 ADBLab 首页横幅。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(204)

        title = TitleLabel("ADBLab", self)
        title.setStyleSheet("font-size: 42px; font-weight: 600; background: transparent;")
        subtitle = BodyLabel("Android 设备实验室", self)
        description = CaptionLabel(
            "选择设备后，在三个任务领域完成设备控制、应用自动化和系统诊断。", self
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(description)
        layout.addStretch(1)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        accent = QColor(BaseStyles.accent_color())
        accent.setAlpha(165 if isDarkTheme() else 72)
        surface = QColor("#202020" if isDarkTheme() else "#FBFBFB")
        surface.setAlpha(24)
        gradient.setColorAt(0, accent)
        gradient.setColorAt(1, surface)
        painter.fillPath(path, gradient)
        # 参考 Gallery 把横幅插画作为绘制层，不让它参与文字布局；窄屏隐藏，
        # 避免大字号把首页撑出水平滚动条。
        if self.width() >= 600:
            FluentIcon.PHONE.render(
                painter,
                QRectF(self.width() - 164, (self.height() - 112) / 2, 112, 112),
            )


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

        icon = IconWidget(FluentIcon.PHONE, self)
        icon.setFixedSize(36, 36)
        self.title_label = StrongBodyLabel("操作设备", self)
        self.summary_label = BodyLabel("尚未选择设备", self)
        self.detail_label = CaptionLabel("先选择设备，再执行应用、系统或远程操作", self)
        self.detail_label.setWordWrap(True)
        for label in (self.title_label, self.summary_label, self.detail_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.badge = InfoBadge(self, InfoLevel.ATTENTION)
        self.badge.setText("0 台")

        self.refresh_button = PushButton(self)
        self.refresh_button.setIcon(FluentIcon.SYNC)
        self.refresh_button.setText("刷新")
        self.refresh_button.setToolTip("重新扫描已连接的 Android 设备")
        self.refresh_button.setAccessibleName("刷新设备")
        self.manage_button = PrimaryPushButton(self)
        self.manage_button.setIcon(FluentIcon.PHONE)
        self.manage_button.setText("选择设备")
        self.manage_button.setToolTip("打开设备页并选择本次操作目标")
        self.manage_button.setAccessibleName("选择设备")

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
        self._manage_text = "选择设备"

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
        self.refresh_button.setText("扫描中" if scanning else "刷新")
        self.refresh_button.setToolTip(
            "正在扫描已连接的 Android 设备"
            if scanning
            else "重新扫描已连接的 Android 设备"
        )
        if discovery_state == "scanning":
            self.badge.setText("扫描中")
            self.badge.setLevel(InfoLevel.INFOAMTION)
        elif discovery_state == "unavailable":
            self.badge.setText("ADB 不可用")
            self.badge.setLevel(InfoLevel.ERROR)
        elif selected:
            self.badge.setText(f"已选 {len(selected)} 台")
            self.badge.setLevel(InfoLevel.SUCCESS)
        elif connected:
            self.badge.setText(f"在线 {len(connected)} 台")
            self.badge.setLevel(InfoLevel.ATTENTION)
        else:
            self.badge.setText("未发现设备")
            self.badge.setLevel(InfoLevel.WARNING)

        if selected:
            visible = "、".join(selected[:2])
            if len(selected) > 2:
                visible += f" 等 {len(selected)} 台"
            self.summary_label.setText(f"当前将操作 {len(selected)} 台设备")
            self.detail_label.setText(visible)
            self._manage_text = "更改选择"
        elif connected:
            self.summary_label.setText("已有设备在线，但尚未选择操作目标")
            self.detail_label.setText("进入设备页勾选一台或多台设备")
            self._manage_text = "选择设备"
        else:
            self.summary_label.setText("尚未发现可操作设备")
            self.detail_label.setText("连接 USB 或无线 ADB 后点击刷新")
            self._manage_text = "连接设备"
        self._sync_responsive_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_responsive_state()

    def _sync_responsive_state(self) -> None:
        """窄屏保留设备语义与主动作，把次要控件收进图标表达。"""

        width = self.width()
        compact = width < 620
        self.refresh_button.setVisible(width >= 720)
        self.badge.setVisible(not compact)
        self.manage_button.setText("" if compact else self._manage_text)
        self.manage_button.setAccessibleName(self._manage_text)
        if compact:
            height = max(36, self.manage_button.sizeHint().height())
            self.manage_button.setFixedWidth(height)
        else:
            self.manage_button.setMinimumWidth(0)
            self.manage_button.setMaximumWidth(16777215)


class WorkspaceSectionPage(QWidget):
    """工作台内的一个可滚动任务分区。"""

    def __init__(
        self,
        route_key: str,
        content: QWidget,
        *,
        scroll_area: SmoothScrollArea | None = None,
        scroll: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(route_key)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not scroll:
            content.setParent(self)
            layout.addWidget(content)
            content.show()
            self.body = content
            return
        body = scroll_area or SmoothScrollArea(self)
        body.setWidgetResizable(True)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        body.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        wrapper = QWidget(body)
        wrapper.setObjectName(f"{route_key}View")
        wrapper_layout = QVBoxLayout(wrapper)
        # WorkspaceFeatureHost 已提供 24px 外边距；这里补足到与 32px
        # 页头基线一致，避免嵌套滚动页再次叠加一整层 32px 留白。
        wrapper_layout.setContentsMargins(8, 8, 8, 20)
        wrapper_layout.setSpacing(18)
        wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content.setParent(wrapper)
        wrapper_layout.addWidget(content)
        content.show()
        body.setWidget(wrapper)

        layout.addWidget(body)
        self.body = body

    def reset_scroll_position(self) -> None:
        """分类路由变化后从内容起点展示，避免继承上一分类的中段位置。"""

        horizontal = getattr(self.body, "horizontalScrollBar", None)
        vertical = getattr(self.body, "verticalScrollBar", None)
        if callable(horizontal):
            set_horizontal = getattr(horizontal(), "setValue", None)
            if callable(set_horizontal):
                set_horizontal(0)
        if callable(vertical):
            set_vertical = getattr(vertical(), "setValue", None)
            if callable(set_vertical):
                set_vertical(0)


class WorkspaceAreaPage(QWidget):
    """主导航中的独立设备任务页，并承载该领域的设备功能会话。"""

    routeChanged = Signal(object)

    def __init__(
        self,
        route_key: str,
        section_key: str,
        title: str,
        subtitle: str,
        content: QWidget,
        *,
        feature_host: WorkspaceFeatureHost | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(route_key)
        self.section_key = section_key.strip()
        if not self.section_key:
            raise ValueError("section_key must not be empty")
        self._base_title = title
        self._base_subtitle = subtitle
        self._feature_host = feature_host
        self._current_route = WorkspaceRoute(self.section_key)
        self._queued_route: WorkspaceRoute | None = None
        self._active = False
        self.header = PageHeader(title, subtitle, self)

        content.setParent(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(content, 1)
        content.show()
        self.body = content

        if feature_host is not None:
            if feature_host.section_key != self.section_key:
                raise ValueError("feature_host section does not match page section")
            self._current_route = WorkspaceRoute(
                self.section_key,
                feature_host.current_feature,
                feature_host.current_device_id,
            )
            self.header.add_action_widget(feature_host.take_session_badge())
            feature_host.route_changed.connect(self._on_feature_route_changed)
            feature_host.deactivate("page_hidden")

    @property
    def current_route(self) -> WorkspaceRoute:
        return self._current_route

    def supports_route(self, route: WorkspaceRoute) -> bool:
        """只读判断路由是否属于当前领域及其已登记功能。"""

        if route.section != self.section_key:
            return False
        if self._feature_host is None:
            return route.feature == "overview"
        return self._feature_host.has_feature(route.feature)

    def open_route(self, route: WorkspaceRoute) -> bool:
        """选择目标路由；页面在后台时延迟到进入前台后再激活会话。"""

        if not self.supports_route(route):
            return False
        if self._feature_host is not None:
            if not self._active:
                self._queued_route = route
                self._set_route_presentation(route)
                return True
            self._queued_route = None
            return self._feature_host.open_route(route)
        self._current_route = route
        self.header.set_subtitle(self._base_subtitle)
        self.routeChanged.emit(route)
        return True

    def activate(self) -> None:
        """页面进入前台时恢复当前功能的前台生命周期。"""

        if self._active:
            return
        self._active = True
        host = self._feature_host
        if host is None:
            return

        route = self._queued_route or host.pending_route or self._current_route
        self._queued_route = None
        host.activate_route(route)

    def deactivate(self, reason: str = "top_level_navigation") -> None:
        """页面离开前台时暂停瞬态工作，但保留设备会话。"""

        if not self._active:
            return
        self._active = False
        if self._feature_host is not None:
            self._feature_host.deactivate(reason)

    def set_device_context(
        self,
        selected_devices: list[str],
        connected_devices: list[str],
        _discovery_state: str,
    ) -> None:
        if self._feature_host is not None:
            self._feature_host.set_device_context(selected_devices, connected_devices)

    def _on_feature_route_changed(self, route: WorkspaceRoute) -> None:
        self._set_route_presentation(route)
        self.routeChanged.emit(route)

    def _set_route_presentation(self, route: WorkspaceRoute) -> None:
        """同步已选路由及页头，不触发功能会话生命周期。"""

        self._current_route = route
        host = self._feature_host
        if route.feature == "overview":
            title = self._base_title
            subtitle = self._base_subtitle
        elif host is not None and host.is_overview_feature(route.feature):
            label = host.feature_label(route.feature) or route.feature
            title = label
            if host.feature_requires_device(route.feature):
                context = "会话设备已选择" if route.device_id else "请选择会话设备"
            else:
                context = "使用设备页中勾选的批量操作目标"
            subtitle = f"{self._base_title} · {context}"
        else:
            label = (
                host.feature_label(route.feature) if host is not None else ""
            ) or route.feature
            title = label
            if host is not None and host.feature_requires_device(route.feature):
                context = "会话设备已选择" if route.device_id else "请选择会话设备"
                subtitle = f"{self._base_title} · {context}"
            else:
                subtitle = self._base_title
        self.header.set_title(title)
        self.header.set_subtitle(subtitle)

class HomePage(ScrollArea):
    """按参考 Gallery 首页组织的 ADBLab 入口页。"""

    def __init__(self, frame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)

        view = QWidget(self)
        view.setObjectName("homeView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 28)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(BannerWidget(view))

        self.device_context = DeviceContextCard(view)
        self.device_context.manageRequested.connect(
            lambda: frame._on_nav_requested("devices")
        )
        self.device_context.refreshRequested.connect(frame._request_device_refresh)
        context_host = QWidget(view)
        context_layout = QVBoxLayout(context_host)
        context_layout.setContentsMargins(32, 0, 32, 0)
        context_layout.addWidget(self.device_context)
        layout.addWidget(context_host)

        tools = ActionCardView("常用工具", view)
        self.tool_cards: dict[str, ActionCard] = {}
        for key, icon, title, content, callback in (
            (
                "app_mgr",
                FluentIcon.APPLICATION,
                "应用管理",
                "查看、安装和卸载设备应用",
                lambda: frame._open_workspace_feature("apps", "manager"),
            ),
            (
                "file_explorer",
                FluentIcon.FOLDER,
                "文件浏览器",
                "浏览设备文件并传输内容",
                lambda: frame._open_workspace_feature("devices", "files"),
            ),
            (
                "logcat",
                FluentIcon.SCROLL,
                "实时 Logcat",
                "按设备查看实时 Android 日志",
                lambda: frame._open_workspace_feature("system", "logcat"),
            ),
            (
                "performance",
                FluentIcon.SPEED_HIGH,
                "性能监控",
                "启动性能采样与图表分析",
                lambda: frame._open_workspace_feature("system", "performance"),
            ),
            (
                "cmd",
                FluentIcon.COMMAND_PROMPT,
                "终端",
                "在项目目录打开命令行",
                frame._open_cmd,
            ),
            (
                "save_path",
                FluentIcon.SAVE,
                "输出目录",
                "修改截图、录屏等默认保存位置",
                frame._on_save_path_clicked,
            ),
        ):
            self.tool_cards[key] = tools.add_card(icon, title, content, callback)
        layout.addWidget(tools)

        workspace = ActionCardView("设备工作流", view)
        for key, icon, title, content in (
            (
                "devices",
                FluentIcon.PHONE,
                "设备与控制",
                "连接设备、管理文件并使用远程控制",
            ),
            ("apps", FluentIcon.APPLICATION, "应用与自动化", "应用、录屏、Monkey 与包操作"),
            ("system", FluentIcon.DEVELOPER_TOOLS, "系统与诊断", "系统信息、设置和调试工具"),
        ):
            workspace.add_card(
                icon,
                title,
                content,
                lambda route=key: frame._on_nav_requested(route),
            )
        layout.addWidget(workspace)

        self.setWidget(view)

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


class SettingsPage(ScrollArea):
    """使用参考项目 SettingCardGroup 体系重写的设置页。"""

    THEME_LABELS = {
        "System": "跟随系统",
        "Light": "浅色",
        "Dark": "深色",
    }
    THEME_MODES = {label: mode for mode, label in THEME_LABELS.items()}

    def __init__(self, frame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = frame
        self._settings = AppSettings.instance()
        self.setObjectName("settingsPage")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setViewportMargins(0, 80, 0, 20)

        self.title_label = TitleLabel("设置", self)
        self.title_label.move(36, 30)
        view = QWidget(self)
        view.setObjectName("settingsView")
        self.expand_layout = ExpandLayout(view)
        self.expand_layout.setSpacing(28)
        self.expand_layout.setContentsMargins(36, 10, 36, 0)

        general = SettingCardGroup("常规", view)
        self.save_card = PushSettingCard(
            "选择文件夹",
            FluentIcon.FOLDER,
            "默认输出目录",
            str(self._settings.get("save_directory", "") or "系统默认目录"),
            general,
        )
        self.scan_card = SwitchSettingCard(
            FluentIcon.SYNC,
            "持续扫描设备",
            "后台定期刷新已连接的 Android 设备",
            parent=general,
        )
        self.scan_card.setChecked(bool(self._settings.get("continuous_device_scan", True)))
        general.addSettingCard(self.save_card)
        general.addSettingCard(self.scan_card)
        self.log_lines_card = ComboSettingCard(
            FluentIcon.SCROLL,
            "日志保留行数",
            "限制主界面操作日志的最大行数",
            ["500", "1000", "2000", "5000", "10000"],
            str(self._settings.get("log_max_lines", 2000)),
            general,
        )
        general.addSettingCard(self.log_lines_card)

        appearance = SettingCardGroup("个性化", view)
        theme_mode = str(self._settings.get("theme", "System"))
        self.theme_card = ComboSettingCard(
            FluentIcon.BRUSH,
            "应用主题",
            "选择浅色、深色或跟随 Windows 设置",
            list(self.THEME_MODES),
            self.THEME_LABELS.get(theme_mode, "跟随系统"),
            appearance,
        )
        self.accent_card = AccentColorSettingCard(
            FluentIcon.PALETTE,
            "强调色",
            "应用到主要按钮、选中状态和键盘焦点",
            str(self._settings.get("accent_color", "#0F6CBD")),
            appearance,
        )
        self.mica_card = SwitchSettingCard(
            FluentIcon.TRANSPARENT,
            "Mica 窗口材质",
            "在支持的 Windows 版本上启用 FluentWindow 窗口材质",
            parent=appearance,
        )
        self.mica_card.setChecked(bool(self._settings.get("mica_enabled", True)))
        self.pin_card = SwitchSettingCard(
            FluentIcon.PIN,
            "窗口置顶",
            "让 ADBLab 保持在其他窗口上方",
            parent=appearance,
        )
        self.pin_card.setChecked(bool(frame._always_on_top))
        for card in (self.scan_card, self.mica_card, self.pin_card):
            card.switchButton.setOnText("开")
            card.switchButton.setOffText("关")
        appearance.addSettingCard(self.theme_card)
        appearance.addSettingCard(self.accent_card)
        appearance.addSettingCard(self.mica_card)
        appearance.addSettingCard(self.pin_card)

        typography = SettingCardGroup("字体", view)
        configured_family = str(self._settings.get("font_family", "") or "系统默认")
        installed = set(QFontDatabase.families())
        families = ["系统默认"]
        for family in ("Segoe UI", "Microsoft YaHei UI", "Arial", configured_family):
            if family != "系统默认" and family in installed and family not in families:
                families.append(family)
        self.font_family_card = ComboSettingCard(
            FluentIcon.FONT,
            "界面字体",
            "应用到导航、页面与对话框文字",
            families,
            configured_family,
            typography,
        )
        self.ui_size_card = ComboSettingCard(
            FluentIcon.FONT_SIZE,
            "界面字号",
            "调整界面控件和正文的字号",
            [str(value) for value in range(8, 23)],
            str(self._settings.get("ui_font_size", 12)),
            typography,
        )
        self.log_size_card = ComboSettingCard(
            FluentIcon.CODE,
            "日志字号",
            "调整等宽日志文字大小",
            [str(value) for value in range(7, 17)],
            str(self._settings.get("log_font_size", 9)),
            typography,
        )
        typography.addSettingCard(self.font_family_card)
        typography.addSettingCard(self.ui_size_card)
        typography.addSettingCard(self.log_size_card)

        application = SettingCardGroup("应用", view)
        self.reset_card = PushSettingCard(
            "恢复",
            FluentIcon.UPDATE,
            "恢复默认设置",
            "恢复窗口、主题、字体和常规选项",
            application,
        )
        application.addSettingCard(self.reset_card)

        self.about_panel = AboutPanel(view)

        self.expand_layout.addWidget(general)
        self.expand_layout.addWidget(appearance)
        self.expand_layout.addWidget(typography)
        self.expand_layout.addWidget(application)
        self.expand_layout.addWidget(self.about_panel)
        self.setWidget(view)

        self.save_card.clicked.connect(self._pick_save_directory)
        self.scan_card.checkedChanged.connect(self._set_continuous_scan)
        self.theme_card.valueChanged.connect(self._set_theme)
        self.accent_card.colorChanged.connect(self._set_accent_color)
        self.mica_card.checkedChanged.connect(self._set_mica_enabled)
        self.pin_card.checkedChanged.connect(frame.set_always_on_top)
        self.log_lines_card.valueChanged.connect(self._set_log_max_lines)
        self.font_family_card.valueChanged.connect(self._apply_typography)
        self.ui_size_card.valueChanged.connect(self._apply_typography)
        self.log_size_card.valueChanged.connect(self._apply_typography)
        self.reset_card.clicked.connect(self._reset_settings)

    def _pick_save_directory(self) -> None:
        self._frame._on_save_path_clicked()
        value = str(self._settings.get("save_directory", "") or "系统默认目录")
        self.save_card.setContent(value)

    def _set_continuous_scan(self, checked: bool) -> None:
        self._settings.set("continuous_device_scan", bool(checked))
        self._frame.set_continuous_scan(bool(checked))

    def _set_theme(self, label: str) -> None:
        mode = self.THEME_MODES.get(label, "System")
        BaseStyles.switch_theme(mode)

    def _set_accent_color(self, color: QColor) -> None:
        value = BaseStyles.set_accent_color(color.name())
        self._settings.set("accent_color", value)

    def _set_mica_enabled(self, checked: bool) -> None:
        enabled = bool(checked)
        self._settings.set("mica_enabled", enabled)
        self._frame.setMicaEffectEnabled(enabled)
        self._frame._refresh_window_chrome_theme()

    def _set_log_max_lines(self, value: str) -> None:
        lines = int(value)
        self._settings.set("log_max_lines", lines)
        self._frame.log_panel.set_max_lines(lines)

    def _apply_typography(self, _value: str) -> None:
        family = self.font_family_card.value()
        self._settings.set_many(
            {
                "font_family": "" if family == "系统默认" else family,
                "ui_font_size": int(self.ui_size_card.value()),
                "log_font_size": int(self.log_size_card.value()),
            }
        )
        BaseStyles.reload_from_settings()

    def _reset_settings(self) -> None:
        self._settings.reset()

        # reset() 会直接替换配置快照；显式回填全部可见卡片，避免页面仍显示
        # 重置前的值。阻断卡片信号后再统一应用运行态，防止重复写盘。
        blocked_cards = (
            self.scan_card,
            self.theme_card,
            self.accent_card,
            self.mica_card,
            self.pin_card,
            self.log_lines_card,
            self.font_family_card,
            self.ui_size_card,
            self.log_size_card,
        )
        blockers = [QSignalBlocker(card) for card in blocked_cards]
        self.scan_card.setChecked(bool(self._settings.get("continuous_device_scan", True)))
        theme = str(self._settings.get("theme", "System"))
        self.theme_card.combo_box.setCurrentText(
            self.THEME_LABELS.get(theme, "跟随系统")
        )
        self.accent_card.set_color(
            str(self._settings.get("accent_color", "#0F6CBD"))
        )
        self.mica_card.setChecked(bool(self._settings.get("mica_enabled", True)))
        self.pin_card.setChecked(bool(self._settings.get("always_on_top", False)))
        self.log_lines_card.combo_box.setCurrentText(
            str(self._settings.get("log_max_lines", 2000))
        )
        family = str(self._settings.get("font_family", "") or "系统默认")
        self.font_family_card.combo_box.setCurrentText(family)
        self.ui_size_card.combo_box.setCurrentText(
            str(self._settings.get("ui_font_size", 12))
        )
        self.log_size_card.combo_box.setCurrentText(
            str(self._settings.get("log_font_size", 9))
        )

        self.save_card.setContent(
            str(self._settings.get("save_directory", "") or "系统默认目录")
        )
        del blockers

        BaseStyles.switch_theme(theme)
        BaseStyles.set_accent_color(
            str(self._settings.get("accent_color", "#0F6CBD"))
        )
        BaseStyles.reload_from_settings()
        self._frame.setMicaEffectEnabled(
            bool(self._settings.get("mica_enabled", True))
        )
        self._frame.log_panel.set_max_lines(int(self._settings.get("log_max_lines", 2000)))
        self._frame.set_continuous_scan(
            bool(self._settings.get("continuous_device_scan", True))
        )
        self._frame.set_always_on_top(bool(self._settings.get("always_on_top", False)))
        self._frame.restore_default_window_size()


class ComboSettingCard(SettingCard):
    """参考 ComboBoxSettingCard 的项目设置适配版，不引入第二套配置系统。"""

    valueChanged = Signal(str)

    def __init__(
        self,
        icon,
        title: str,
        content: str,
        values: list[str],
        current: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(icon, title, content, parent)
        self.combo_box = ComboBox(self)
        self.combo_box.addItems(values)
        if self.combo_box.findText(current) < 0:
            self.combo_box.addItem(current)
        self.combo_box.setCurrentText(current)
        self.hBoxLayout.addWidget(self.combo_box, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.combo_box.currentTextChanged.connect(self.valueChanged)

    def value(self) -> str:
        return self.combo_box.currentText()


class AccentColorSettingCard(SettingCard):
    """参考 CustomColorSettingCard 的 AppSettings 适配版。"""

    colorChanged = Signal(QColor)

    def __init__(
        self,
        icon,
        title: str,
        content: str,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(icon, title, content, parent)
        self.color_button = ColorPickerButton(
            QColor(color),
            "选择 ADBLab 强调色",
            self,
        )
        self.color_button.setToolTip("选择主要按钮和选中状态使用的颜色")
        self.hBoxLayout.addWidget(self.color_button, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.color_button.colorChanged.connect(self.colorChanged.emit)

    def set_color(self, color: str) -> None:
        blocker = QSignalBlocker(self.color_button)
        self.color_button.setColor(QColor(color))
        del blocker


__all__ = [
    "ActionCard",
    "ActionCardView",
    "AccentColorSettingCard",
    "BannerWidget",
    "ComboSettingCard",
    "DeviceContextCard",
    "GalleryPage",
    "HomePage",
    "PageHeader",
    "SettingsPage",
    "WorkspaceAreaPage",
    "WorkspaceSectionPage",
]
