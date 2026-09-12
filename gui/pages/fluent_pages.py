"""基于 PyQt-Fluent-Widgets Gallery 示例（GPL-3.0）移植的主界面页面组件。

页面骨架和流式操作卡片直接沿用参考项目的组织方式，并改写为
PySide6 与 ADBLab 业务入口。这里不再复刻旧主窗口的分栏、工具条或页签体系。
来源与许可说明见仓库根目录 ``THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QRect, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QPainter,
    QPalette,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
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
    setCustomStyleSheet,
)

from core.exec import reset_adb_program_cache
from core.settings_manager import AppSettings, normalise_language, normalise_ui_scale
from gui.features import AboutPanel
from gui.i18n import tr
from gui.notifications import show_toast
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_font_role, apply_label_role
from gui.styles.icon_loader import DEVICE_ICON
from gui.widgets.adb_client_card import AdbClientSettingCard, AdbEnvironmentSettingCard
from gui.widgets.home_banner import HomeBanner
from gui.widgets.setting_card_layout import (
    SettingsCardPresentation as _SettingsCardPresentation,
)
from gui.widgets.setting_card_layout import apply_setting_text_style
from gui.window_effects import is_mica_supported
from services.adb_clients import clear_client_probe_cache
from utils.adb_resolver import (
    CLIENT_PREFERENCE_AUTO,
    CLIENT_SOURCE_TOKENS,
    invalidate_adb_path_cache,
    set_client_preference,
)


class GalleryPage(QWidget):
    """参考 GalleryInterface 的独立功能页，内容直接占满页面承载区。"""

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
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

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
            body_layout.setContentsMargins(0, 0, 0, 0)
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
        self._preferred_width = 300
        self.setMinimumWidth(0)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(content)

        icon_widget = IconWidget(icon, self)
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

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.hasFocus():
            # CardWidget 自行绘制边框，QSS 的 :focus 不会覆盖它；显式呈现键盘位置。
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(BaseStyles.color("BORDER_FOCUS")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 4, 4)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

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
        # 正文留白随页面滚动，外层滚动容器始终占满内容区。
        wrapper_layout.setContentsMargins(32, 8, 32, 44)
        wrapper_layout.setSpacing(18)
        wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content.setParent(wrapper)
        wrapper_layout.addWidget(content)
        content.show()
        body.setWidget(wrapper)
        # setWidget 会自动开启实色填充，普通留白容器必须继续透出宿主材质。
        wrapper.setAutoFillBackground(False)

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
        self._route_presentations: dict[str, tuple[str, str]] = {}
        self._feature_host = feature_host
        self._current_route = WorkspaceRoute(self.section_key)
        self._queued_route: WorkspaceRoute | None = None
        self._active = False
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

        content.setParent(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
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
            feature_host.route_changed.connect(self._on_feature_route_changed)
            feature_host.deactivate("page_hidden")

    @property
    def current_route(self) -> WorkspaceRoute:
        return self._current_route

    def set_route_presentation(self, feature: str, title: str, subtitle: str) -> None:
        """为一级导航保留具体功能的可访问名称，物理宿主仅作为内部资源容器。"""

        self._route_presentations[feature] = (title, subtitle)
        if self._current_route.feature == feature:
            self._set_route_presentation(self._current_route)

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
            route = WorkspaceRoute(
                route.section, self._feature_host.canonical_feature(route.feature),
                route.device_id, route.payload,
            )
            if not self._active:
                queued_route = route
                pending_route = self._feature_host.pending_route
                if (
                    route.payload is None
                    and pending_route is not None
                    and self._stable_route(pending_route) == self._stable_route(route)
                ):
                    # 历史返回只携带稳定位置；同一路由仍在等待设备时，不能用
                    # 这个无 payload 的恢复请求覆盖尚未实际消费的一次性参数。
                    queued_route = pending_route
                self._queued_route = queued_route
                self._set_route_presentation(route)
                return True
            self._queued_route = None
            return self._feature_host.open_route(route)
        stable_route = self._stable_route(route)
        self._current_route = stable_route
        self._set_route_presentation(stable_route)
        self.routeChanged.emit(stable_route)
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
        stable_route = self._stable_route(route)
        self._set_route_presentation(stable_route)
        self.routeChanged.emit(stable_route)

    def _set_route_presentation(self, route: WorkspaceRoute) -> None:
        """同步已选路由和可访问名称，不触发功能会话生命周期。"""

        self._current_route = self._stable_route(route)
        host = self._feature_host
        presentation = self._route_presentations.get(route.feature)
        if presentation is not None:
            self.setAccessibleName(presentation[0])
            self.setAccessibleDescription(presentation[1])
            return
        title = self._base_title
        if route.feature == "overview":
            subtitle = self._base_subtitle
        elif host is not None and host.is_overview_feature(route.feature):
            label = host.feature_label(route.feature) or route.feature
            if host.feature_requires_device(route.feature):
                context = tr("会话设备已选择") if route.device_id else tr("请选择会话设备")
            else:
                context = tr("使用顶部设备栏中勾选的操作目标")
            subtitle = f"{label} · {context}"
        else:
            label = (
                host.feature_label(route.feature) if host is not None else ""
            ) or route.feature
            if host is not None and host.feature_requires_device(route.feature):
                context = tr("会话设备已选择") if route.device_id else tr("请选择会话设备")
                subtitle = f"{label} · {context}"
            else:
                subtitle = label
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

    @staticmethod
    def _stable_route(route: WorkspaceRoute) -> WorkspaceRoute:
        """移除一次性激活参数，只保留可恢复的工作区位置。"""

        return WorkspaceRoute(route.section, route.feature, route.device_id)

class HomePage(ScrollArea):
    """按参考 Gallery 首页组织的 ADBLab 入口页。"""

    def __init__(self, frame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
            (
                "save_path",
                FluentIcon.SAVE,
                tr("输出目录"),
                tr("修改截图、录屏等默认保存位置"),
                frame._on_save_path_clicked,
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


class _SettingsPathLabel(QLabel):
    """长路径中间省略，完整配置仍由文本、悬停提示和辅助技术读取。"""

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)
        self.setAccessibleDescription(text)

    def heightForWidth(self, _width: int) -> int:
        return self.fontMetrics().height()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideMiddle, self.contentsRect().width(),
        )
        painter.drawText(
            self.contentsRect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )




class _SettingsContentLayout(ExpandLayout):
    """将页尾留白计入内容高度，避免可调整滚动区按尺寸提示裁掉底边距。"""

    def heightForWidth(self, width: int) -> int:
        # 当前 Fluent ExpandLayout 的高度测量只计算到最后一个控件底部。
        return super().heightForWidth(width) + self.contentsMargins().bottom()


class SettingsPage(ScrollArea):
    """使用参考项目 SettingCardGroup 体系重写的设置页。"""

    THEME_LABELS = {
        "System": "跟随系统",
        "Light": "浅色",
        "Dark": "深色",
    }
    THEME_MODES = {label: mode for mode, label in THEME_LABELS.items()}
    SCALE_LABELS = {
        "Auto": "跟随系统", 1.0: "100%", 1.25: "125%", 1.5: "150%",
        1.75: "175%", 2.0: "200%",
    }
    SCALE_VALUES = {label: value for value, label in SCALE_LABELS.items()}
    LANGUAGE_LABELS = {
        "Auto": "跟随系统", "zh_CN": "简体中文", "zh_HK": "繁體中文", "en_US": "English",
    }

    def __init__(self, frame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = frame
        self._settings = AppSettings.instance()
        # 只翻译显示标签；持久化值与路由标识不随界面语言变化。
        self.THEME_LABELS = {mode: tr(label) for mode, label in type(self).THEME_LABELS.items()}
        self.THEME_MODES = {label: mode for mode, label in self.THEME_LABELS.items()}
        self.SCALE_LABELS = {value: tr(label) for value, label in type(self).SCALE_LABELS.items()}
        self.SCALE_VALUES = {label: value for value, label in self.SCALE_LABELS.items()}
        self.LANGUAGE_LABELS = {**type(self).LANGUAGE_LABELS, "Auto": tr("跟随系统")}
        self._language_values = {label: value for value, label in self.LANGUAGE_LABELS.items()}
        self.setObjectName("settingsPage")
        self.setAccessibleName(tr("设置"))
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        # 内容和底部留白使用同一透明表面，避免滚动区出现独立色带。
        self.setStyleSheet(
            "#settingsPage, #settingsView { background: transparent; border: none; }"
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)

        view = QWidget(self)
        view.setObjectName("settingsView")
        self.expand_layout = _SettingsContentLayout(view)
        self.expand_layout.setSpacing(28)
        # 留白随内容滚动，滚动条保持原生定位及完整视口高度。
        self.expand_layout.setContentsMargins(32, 16, 32, 44)

        general = SettingCardGroup(tr("常规"), view)
        self.save_card = PushSettingCard(
            tr("选择文件夹"),
            FluentIcon.FOLDER,
            tr("默认输出目录"),
            str(self._settings.get("save_directory", "") or tr("系统默认目录")),
            general,
        )
        self.scan_card = _LocalizedSwitchSettingCard(
            FluentIcon.SYNC,
            tr("持续扫描设备"),
            tr("后台定期刷新已连接的 Android 设备"),
            parent=general,
        )
        self.scan_card.setChecked(bool(self._settings.get("continuous_device_scan", True)))
        general.addSettingCard(self.save_card)
        general.addSettingCard(self.scan_card)
        self.log_lines_card = ComboSettingCard(
            FluentIcon.SCROLL,
            tr("性能采集输出行数"),
            tr("限制新打开的性能采集页保留的过程输出行数"),
            ["500", "1000", "2000", "5000", "10000"],
            str(self._settings.get("log_max_lines", 2000)),
            general,
        )
        general.addSettingCard(self.log_lines_card)

        appearance = SettingCardGroup(tr("个性化"), view)
        theme_mode = str(self._settings.get("theme", "System"))
        self.theme_card = ComboSettingCard(
            FluentIcon.BRUSH,
            tr("应用主题"),
            tr("选择浅色、深色或跟随 Windows 设置"),
            list(self.THEME_MODES),
            self.THEME_LABELS.get(theme_mode, tr("跟随系统")),
            appearance,
        )
        self.scale_card = ComboSettingCard(
            FluentIcon.ZOOM,
            tr("显示缩放"),
            tr("调整控件与文字的整体比例，重启应用后生效；窗口布局随宽度自动调整"),
            list(self.SCALE_VALUES),
            self.SCALE_LABELS[normalise_ui_scale(self._settings.get("ui_scale", "Auto"))],
            appearance,
        )
        self.accent_card = AccentColorSettingCard(
            FluentIcon.PALETTE,
            tr("强调色"),
            tr("应用到主要按钮、选中状态和键盘焦点"),
            str(self._settings.get("accent_color", "#0F6CBD")),
            appearance,
        )
        self.mica_card = _LocalizedSwitchSettingCard(
            FluentIcon.TRANSPARENT,
            tr("云母效果"),
            tr("让窗口和表面呈现半透明材质") if is_mica_supported()
            else tr("云母效果需要 Windows 11，当前系统使用实色背景"),
            parent=appearance,
        )
        self.mica_card.setChecked(bool(self._settings.get("mica_enabled", True)))
        self.mica_card.setEnabled(is_mica_supported())
        self.language_card = ComboSettingCard(
            FluentIcon.LANGUAGE,
            tr("语言"),
            tr("选择界面使用的语言，重启应用后生效"),
            list(self._language_values),
            self.LANGUAGE_LABELS[normalise_language(self._settings.get("language", "Auto"))],
            appearance,
        )
        self.pin_card = _LocalizedSwitchSettingCard(
            FluentIcon.PIN,
            tr("窗口置顶"),
            tr("让 ADBLab 保持在其他窗口上方"),
            parent=appearance,
        )
        self.pin_card.setChecked(bool(frame._always_on_top))
        for card in (self.scan_card, self.mica_card, self.pin_card):
            card.switchButton.setOnText(tr("开"))
            card.switchButton.setOffText(tr("关"))
        appearance.addSettingCard(self.mica_card)
        appearance.addSettingCard(self.theme_card)
        appearance.addSettingCard(self.accent_card)
        appearance.addSettingCard(self.scale_card)
        appearance.addSettingCard(self.language_card)
        appearance.addSettingCard(self.pin_card)

        typography = SettingCardGroup(tr("字体"), view)
        configured_family = str(self._settings.get("font_family", "") or tr("系统默认"))
        installed = set(QFontDatabase.families())
        families = [tr("系统默认")]
        for family in (
            "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Arial", configured_family,
        ):
            if family != tr("系统默认") and family in installed and family not in families:
                families.append(family)
        self.font_family_card = ComboSettingCard(
            FluentIcon.FONT,
            tr("界面字体"),
            tr("应用到导航、页面与对话框文字"),
            families,
            configured_family,
            typography,
        )
        self.ui_size_card = ComboSettingCard(
            FluentIcon.FONT_SIZE,
            tr("界面字号（pt）"),
            tr("即时调整正文大小；推荐 11 pt，已有字号保持不变"),
            [str(value) for value in range(8, 23)],
            str(self._settings.get("ui_font_size", 12)),
            typography,
        )
        self.log_size_card = ComboSettingCard(
            FluentIcon.CODE,
            tr("输出文本字号（pt）"),
            tr("即时调整操作结果、文件预览和采集输出的等宽文字大小"),
            [str(value) for value in range(7, 17)],
            str(self._settings.get("log_font_size", 9)),
            typography,
        )
        typography.addSettingCard(self.font_family_card)
        typography.addSettingCard(self.ui_size_card)
        typography.addSettingCard(self.log_size_card)

        application = SettingCardGroup(tr("应用"), view)
        self.reset_card = PushSettingCard(
            tr("恢复"),
            FluentIcon.UPDATE,
            tr("恢复默认设置"),
            tr("恢复窗口、主题、字体和常规选项"),
            application,
        )
        application.addSettingCard(self.reset_card)
        self.diagnostics_card = PushSettingCard(
            tr("导出诊断"), FluentIcon.INFO, tr("应用诊断"),
            tr("本次运行尚无应用异常记录"), application,
        )
        application.addSettingCard(self.diagnostics_card)
        self.diagnostics_card.button.setEnabled(False)

        maintenance = SettingCardGroup(tr("ADB 维护"), view)
        self._last_adb_environment_text = ""
        # 三张卡平铺：客户端选择 → 执行环境（模式 + 状态 + 重新检测）→ 重启本机服务。
        self.adb_client_card = AdbClientSettingCard(maintenance)
        self.adb_check_card = AdbEnvironmentSettingCard(maintenance)
        self.restart_adb_card = PushSettingCard(
            tr("重启 ADB"), FluentIcon.SYNC, tr("重启本机 ADB 服务"),
            tr(
                "用当前选择的 ADB 客户端重启本机 5037 服务；"
                "会中断当前连接与投屏，完成后自动重新检测"
            ),
            maintenance,
        )
        maintenance.addSettingCard(self.adb_client_card)
        maintenance.addSettingCard(self.adb_check_card)
        maintenance.addSettingCard(self.restart_adb_card)

        self.adb_check_card.recheck_requested.connect(
            lambda: frame.recheck_adb_environment()
        )
        self.adb_check_card.mode_requested.connect(self._apply_adb_mode)
        self.adb_client_card.client_selected.connect(self._apply_adb_client)
        self.adb_client_card.custom_requested.connect(self._pick_custom_adb)
        self.adb_client_card.rescan_requested.connect(self._rescan_adb_clients)
        # 展开动画结束后卡片高度才稳定，需要重排分组，否则展开内容会被分组固定高度裁掉。
        self.adb_client_card.expandAni.finished.connect(self._reflow_settings)
        self.adb_check_card.expandAni.finished.connect(self._reflow_settings)
        self.restart_adb_card.clicked.connect(
            lambda: frame.left_panel.signals.restart_adb_requested.emit()
        )
        current_client = str(self._settings.get("adb_client", CLIENT_PREFERENCE_AUTO))
        if current_client not in CLIENT_SOURCE_TOKENS:
            self.adb_client_card.set_custom_path(current_client)
        self.adb_client_card.set_selection(current_client)
        # 空闲时预热一次客户端识别：冷启动的第一次 adb 调用偏慢，提前跑完，
        # 用户展开卡片时通常已能看到结果（结果按 (路径, mtime, size) 缓存）。
        QTimer.singleShot(0, self.adb_client_card.start_detection)
        self.about_panel = AboutPanel(view)
        self.about_panel.layoutChanged.connect(self._reflow_settings)

        self.expand_layout.addWidget(general)
        self.expand_layout.addWidget(appearance)
        self.expand_layout.addWidget(typography)
        self.expand_layout.addWidget(application)
        self.expand_layout.addWidget(maintenance)
        self.expand_layout.addWidget(self.about_panel)
        self.setWidget(view)

        self.save_card.clicked.connect(self._pick_save_directory)
        self.scan_card.checkedChanged.connect(self._set_continuous_scan)
        self.theme_card.valueChanged.connect(self._set_theme)
        self.scale_card.valueChanged.connect(self._set_ui_scale)
        self.language_card.valueChanged.connect(self._set_language)
        self.accent_card.colorChanged.connect(self._set_accent_color)
        self.mica_card.checkedChanged.connect(self._set_mica_enabled)
        self.pin_card.checkedChanged.connect(frame.set_always_on_top)
        self.log_lines_card.valueChanged.connect(self._set_log_max_lines)
        self.font_family_card.valueChanged.connect(self._apply_typography)
        self.ui_size_card.valueChanged.connect(self._apply_typography)
        self.log_size_card.valueChanged.connect(self._apply_typography)
        self.reset_card.clicked.connect(self._reset_settings)
        # ADB 分组内含页签容器，卡片不是分组的直接子控件：它的高度由页签内容决定，
        # 不参与下面的固定高度循环，只在字号刷新时统一处理标题。
        self._setting_groups = (general, appearance, typography, application)
        self._adb_group = maintenance
        original_path = self.save_card.contentLabel
        self.save_card.vBoxLayout.removeWidget(original_path)
        self.save_card.contentLabel = _SettingsPathLabel(self.save_card)
        self.save_card.contentLabel.setObjectName("contentLabel")
        self.save_card.contentLabel.setText(original_path.text())
        original_path.hide()
        original_path.deleteLater()
        self._card_presentations = [
            _SettingsCardPresentation(card, control)
            for card, control in (
                (self.save_card, self.save_card.button),
                (self.scan_card, self.scan_card.switchButton),
                (self.log_lines_card, self.log_lines_card.combo_box),
                (self.theme_card, self.theme_card.combo_box),
                (self.scale_card, self.scale_card.combo_box),
                (self.language_card, self.language_card.combo_box),
                (self.accent_card, self.accent_card.color_button),
                (self.mica_card, self.mica_card.switchButton),
                (self.pin_card, self.pin_card.switchButton),
                (self.font_family_card, self.font_family_card.combo_box),
                (self.ui_size_card, self.ui_size_card.combo_box),
                (self.log_size_card, self.log_size_card.combo_box),
                (self.reset_card, self.reset_card.button),
                (self.restart_adb_card, self.restart_adb_card.button),
            )
        ]
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        BaseStyles.theme_changed.connect(self._refresh_typography)
        self._refresh_typography()

    # ── ADB 页签与客户端选择 ─────────────────────────────────────────────

    def _apply_adb_mode(self, mode: str) -> None:
        """切换执行模式：只影响后续命令，不重放在途请求。"""

        self.adb_check_card.set_mode(mode)
        self._frame.set_adb_selection_mode(mode)

    def _apply_adb_client(self, value: str) -> None:
        """应用客户端选择：写配置、清两层路径缓存并重新检测执行环境。"""

        text = str(value or "").strip() or CLIENT_PREFERENCE_AUTO
        set_client_preference(text)
        clear_client_probe_cache()
        invalidate_adb_path_cache()
        reset_adb_program_cache()
        self._settings.set("adb_client", text)
        self.adb_client_card.set_selection(text)
        self._frame.recheck_adb_environment()

    def _pick_custom_adb(self) -> None:
        """选择自定义 adb 可执行文件；取消选择时恢复原显示。"""

        path, _filter = QFileDialog.getOpenFileName(
            self, tr("选择 ADB 可执行文件"), "", tr("所有文件 (*)")
        )
        if not path:
            self.adb_client_card.set_selection(
                str(self._settings.get("adb_client", CLIENT_PREFERENCE_AUTO))
            )
            return
        self.adb_client_card.set_custom_path(path)
        self._apply_adb_client(path)

    def _rescan_adb_clients(self) -> None:
        """重新识别本地 ADB 环境：清缓存并让卡片重新探测。"""

        invalidate_adb_path_cache()
        clear_client_probe_cache()
        self.adb_client_card.start_detection()

    def update_adb_environment(self, snapshot) -> None:
        """自动模式跟随有效后端；手动模式保留选择，能力回退只更新执行状态说明。"""
        # 手动模式回显用户选择；自动模式只显示实际模式，不改变开关类控件状态。
        self.adb_check_card.set_mode(snapshot.selection_mode)
        mode = {
            "auto": tr("自动选择"),
            "fast": tr("手动快速"),
            "native": tr("手动原生"),
        }[snapshot.selection_mode]
        # 这里的分段只描述"用哪条通道"，与设置里的"持续扫描设备"无关：
        # fast_devices 表示设备列表查询可走 5037 直连，fast_shell_devices 表示
        # 逐设备 Shell 已验证通过的数量。
        segments = [tr("模式：{mode}").format(mode=mode)]
        if snapshot.fast_devices:
            segments.append(tr("设备列表：快速直连"))
        else:
            segments.append(tr("设备列表：原生 ADB"))
        if snapshot.checked_devices:
            segments.append(
                tr("设备 Shell {count}/{checked} 台已验证").format(
                    count=snapshot.fast_shell_devices,
                    checked=snapshot.checked_devices,
                )
            )
        else:
            segments.append(tr("设备 Shell 未检查"))
        status = {
            "idle": tr("等待执行环境检测"),
            "checking": tr("正在检查执行环境"),
            "starting_server": tr("正在启动本机 ADB 服务"),
            "retrying": tr("正在恢复执行环境"),
            "ready": tr("执行环境已就绪"),
            "missing_adb": tr("未找到 ADB，请检查安装环境"),
            "custom_server": tr("已配置自定义 ADB 服务，保留原生执行"),
            "host_timeout": tr("本机 ADB 服务响应超时，可重新检测"),
            "host_unavailable": tr("本机 ADB 服务不可用，可重新检测或重启服务"),
            "host_protocol": tr("本机 ADB 服务协议不兼容，保留原生执行"),
            "host_transport": tr("本机 ADB 服务通信异常，可重新检测"),
            "shell_unavailable": tr("部分设备 Shell 未通过验证，保留原生执行"),
        }[snapshot.status]
        segments.append(status)
        content = " · ".join(segments)
        if snapshot.checking and self._last_adb_environment_text:
            # 检测期间保留上一次稳定结果，避免状态行在"检查中"与结果之间来回跳。
            content = tr("检测中…（上次：{previous}）").format(
                previous=self._last_adb_environment_text
            )
        elif not snapshot.checking:
            self._last_adb_environment_text = content
        self.adb_check_card.set_status(content)
        self.adb_check_card.set_recheck_enabled(not snapshot.checking)
        self._reflow_settings()

    def _refresh_typography(self, _config=None) -> None:
        """设置字号本身也可即时阅读；仅更新呈现，不触发任何配置写入。"""

        for group in (*self._setting_groups, self._adb_group):
            apply_label_role(group.titleLabel, FontRole.UI, bold=True)
            self._set_setting_font(group.titleLabel, FontRole.UI, bold=True)
            group.titleLabel.adjustSize()
        for card in (self.adb_client_card, self.adb_check_card):
            self._set_setting_font(card.card.titleLabel, FontRole.UI)
            self._set_setting_font(card.card.contentLabel, FontRole.UI_SMALL)
            for label in card.findChildren(QLabel):
                self._set_setting_font(label, FontRole.UI_SMALL)
            for label in (card.card.titleLabel, card.card.contentLabel):
                # 字号放大后标题可能比 HeaderSettingCard 原算高度高 1-2px，这里补齐。
                label.setMinimumHeight(
                    max(label.height(), label.heightForWidth(max(1, label.width())))
                )
            card._adjustViewSize()
        for presentation in self._card_presentations:
            card, control = presentation.card, presentation.control
            apply_label_role(card.titleLabel, FontRole.UI)
            apply_label_role(card.contentLabel, FontRole.UI_SMALL)
            self._set_setting_font(card.titleLabel, FontRole.UI)
            self._set_setting_font(card.contentLabel, FontRole.UI_SMALL)
            control.setMaximumHeight(16777215)
            apply_font_role(control, FontRole.UI)
            if type(control) is QPushButton:
                self._set_setting_font(control, FontRole.UI)
            elif isinstance(control, ComboBox):
                font = BaseStyles.font_for_role(FontRole.UI)
                family = font.family().replace("'", "\\'")
                rule = f"ComboBox {{ font-family: '{family}'; font-size: {font.pointSizeF()}pt; }}"
                setCustomStyleSheet(control, rule, rule)
            for child in control.findChildren(QWidget):
                child.setFont(control.font())
                if isinstance(child, QLabel):
                    self._set_setting_font(child, FontRole.UI)
            control.ensurePolished()
            control.setMinimumHeight(max(32, control.fontMetrics().height() + 14))
        self._reflow_settings()

    @staticmethod
    def _set_setting_font(widget: QWidget, role: FontRole, *, bold: bool = False) -> None:
        """局部覆盖 SettingCard 给普通 QLabel 固定的像素字号，保留其主题颜色。"""

        apply_setting_text_style(widget, role, bold=bold)

    def _reflow_settings(self) -> None:
        """ExpandLayout 使用当前控件高度，先测量卡片再更新分组与页面总高。"""

        if not hasattr(self, "_card_presentations"):
            return
        margins = self.expand_layout.contentsMargins()
        width = max(1, self.viewport().width() - margins.left() - margins.right())
        for presentation in self._card_presentations:
            presentation.reflow(width)
        for group in self._setting_groups:
            cards = [item.card for item in self._card_presentations if item.card.parent() is group]
            height = sum(card.height() for card in cards) + max(0, len(cards) - 1) * 2
            group.setFixedHeight(height + group.titleLabel.sizeHint().height() + 12)
        if hasattr(self, "_adb_group"):
            # 两张展开卡不在 _card_presentations 里（该类会重建卡片内部布局），
            # 因此 ADB 分组高度在这里按三张卡的实际高度单独测量。
            adb_cards = (self.adb_client_card, self.adb_check_card, self.restart_adb_card)
            content = sum(card.height() for card in adb_cards) + 2 * (len(adb_cards) - 1)
            self._adb_group.setFixedHeight(
                content + self._adb_group.titleLabel.sizeHint().height() + 12
            )
        self.about_panel.reflow(width)
        view = self.widget()
        if view is not None:
            view.resize(
                self.viewport().width(),
                self.expand_layout.heightForWidth(self.viewport().width()),
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_settings()

    def _pick_save_directory(self) -> None:
        self._frame._on_save_path_clicked()
        value = str(self._settings.get("save_directory", "") or tr("系统默认目录"))
        self.save_card.setContent(value)
        self._reflow_settings()

    def _set_continuous_scan(self, checked: bool) -> None:
        self._settings.set("continuous_device_scan", bool(checked))
        self._frame.set_continuous_scan(bool(checked))

    def _set_theme(self, label: str) -> None:
        mode = self.THEME_MODES.get(label, "System")
        BaseStyles.switch_theme(mode)

    def _set_ui_scale(self, label: str) -> None:
        """只保存下次启动比例，当前窗口继续使用创建 QApplication 时的 DPI。"""

        self._settings.set("ui_scale", self.SCALE_VALUES[label])

    def _set_language(self, label: str) -> None:
        """保存语言偏好并提示重启，避免重建正在持有设备任务的页面。"""
        language = self._language_values[label]
        if language == self._settings.get("language", "Auto"):
            return
        self._settings.set("language", language)
        self._show_language_restart_hint()

    def _show_language_restart_hint(self) -> None:
        show_toast(
            self.window() or self,
            tr("设置已保存"),
            tr("语言设置将在重启应用后生效"),
            level="success",
        )

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

    def _apply_typography(self, _value: str) -> None:
        family = self.font_family_card.value()
        self._settings.set_many(
            {
                "font_family": "" if family == tr("系统默认") else family,
                "ui_font_size": int(self.ui_size_card.value()),
                "log_font_size": int(self.log_size_card.value()),
            }
        )
        BaseStyles.reload_from_settings()

    def _reset_settings(self) -> None:
        previous_language = self._settings.get("language", "Auto")
        self._settings.reset()

        # reset() 会直接替换配置快照；显式回填全部可见卡片，避免页面仍显示
        # 重置前的值。阻断卡片信号后再统一应用运行态，防止重复写盘。
        blocked_cards = (
            self.scan_card,
            self.theme_card,
            self.scale_card,
            self.language_card,
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
            self.THEME_LABELS.get(theme, tr("跟随系统"))
        )
        self.scale_card.combo_box.setCurrentText(
            self.SCALE_LABELS[normalise_ui_scale(self._settings.get("ui_scale", "Auto"))]
        )
        self.language_card.combo_box.setCurrentText(
            self.LANGUAGE_LABELS[normalise_language(self._settings.get("language", "Auto"))]
        )
        self.accent_card.set_color(
            str(self._settings.get("accent_color", "#0F6CBD"))
        )
        self.mica_card.setChecked(bool(self._settings.get("mica_enabled", True)))
        self.pin_card.setChecked(bool(self._settings.get("always_on_top", False)))
        self.log_lines_card.combo_box.setCurrentText(
            str(self._settings.get("log_max_lines", 2000))
        )
        family = str(self._settings.get("font_family", "") or tr("系统默认"))
        self.font_family_card.combo_box.setCurrentText(family)
        self.ui_size_card.combo_box.setCurrentText(
            str(self._settings.get("ui_font_size", 12))
        )
        self.log_size_card.combo_box.setCurrentText(
            str(self._settings.get("log_font_size", 9))
        )

        self.save_card.setContent(
            str(self._settings.get("save_directory", "") or tr("系统默认目录"))
        )
        del blockers

        self.adb_check_card.set_mode("auto")
        self.adb_client_card.set_selection(CLIENT_PREFERENCE_AUTO)
        set_client_preference(CLIENT_PREFERENCE_AUTO)
        clear_client_probe_cache()
        invalidate_adb_path_cache()
        reset_adb_program_cache()

        BaseStyles.switch_theme(theme)
        BaseStyles.set_accent_color(
            str(self._settings.get("accent_color", "#0F6CBD"))
        )
        BaseStyles.reload_from_settings()
        self._frame.setMicaEffectEnabled(
            bool(self._settings.get("mica_enabled", True))
        )
        self._frame.set_continuous_scan(
            bool(self._settings.get("continuous_device_scan", True))
        )
        self._frame.set_always_on_top(bool(self._settings.get("always_on_top", False)))
        self._frame.restore_default_window_size()
        if previous_language != self._settings.get("language", "Auto"):
            self._show_language_restart_hint()


class _LocalizedSwitchSettingCard(SwitchSettingCard):
    """保持原生设置开关的信号契约，更新状态后仍使用当前语言标签。"""

    def setValue(self, isChecked: bool) -> None:
        # 上游 setValue 会覆盖 SwitchButton.onText/offText；恢复默认和手动
        # 切换都会经过此边界，因此在原生更新后统一还原当前语言并重新度量。
        super().setValue(isChecked)
        # 同步策略可能在 checkedChanged 内修正有效状态，标签必须读取最终投影。
        self.switchButton.setText(tr("开") if self.isChecked() else tr("关"))


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
            tr("选择 ADBLab 强调色"),
            self,
        )
        self.color_button.setToolTip(tr("选择主要按钮和选中状态使用的颜色"))
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
    "ComboSettingCard",
    "DeviceContextCard",
    "GalleryPage",
    "HomePage",
    "SettingsPage",
    "WorkspaceAreaPage",
    "WorkspaceSectionPage",
]
