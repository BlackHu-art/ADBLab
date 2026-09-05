"""独立设备任务页中的路由目录和按设备会话宿主。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    FluentIconBase,
    InfoBadge,
    InfoLevel,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
)

from gui.features import FeatureSessionKey, FeatureSessionRegistry
from gui.styles.icon_loader import DEVICE_ICON
from gui.widgets.adaptive_navigation import AdaptiveNavigation


@dataclass(frozen=True, slots=True)
class WorkspaceRoute:
    """描述工作台中的分区、功能和稳定设备会话。"""

    section: str
    feature: str = "overview"
    device_id: str = ""
    payload: object | None = None

    def __post_init__(self) -> None:
        section = self.section.strip()
        feature = self.feature.strip() or "overview"
        if not section:
            raise ValueError("section must not be empty")
        object.__setattr__(self, "section", section)
        object.__setattr__(self, "feature", feature)
        object.__setattr__(self, "device_id", self.device_id.strip())


@dataclass(frozen=True, slots=True)
class WorkspaceNavigationItem:
    """供工作区功能导航注册的稳定入口。"""

    feature: str
    label: str
    icon: FluentIconBase | QIcon | str


@dataclass(frozen=True, slots=True)
class _FeatureDefinition:
    label: str
    icon: FluentIconBase | QIcon | str
    factory: Callable[[FeatureSessionKey], QWidget]
    requires_device: bool
    close_label: str


@dataclass(frozen=True, slots=True)
class _OverviewDefinition:
    label: str
    icon: FluentIconBase | QIcon | str
    page: QWidget
    requires_device: bool
    activate: Callable[[str], object] | None


class _NoDevicePage(CardWidget):
    choose_device_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceFeatureNoDevice")
        self.setBorderRadius(10)
        self.title_label = StrongBodyLabel("需要选择设备", self)
        self.message_label = BodyLabel(
            "此功能需要一个稳定的设备会话。选择后将自动返回并在当前面板打开。",
            self,
        )
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.choose_button = PrimaryPushButton(DEVICE_ICON, "选择设备", self)
        self.choose_button.clicked.connect(self.choose_device_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.message_label)
        layout.addWidget(self.choose_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def set_feature_label(self, label: str) -> None:
        self.title_label.setText(f"{label}需要选择设备")

    def set_candidates_available(self, available: bool) -> None:
        """区分存在多台候选设备与完全没有设备的空态。"""

        if available:
            self.message_label.setText(
                "请在上方设备选项中明确选择当前查看的一台，或在设备概览中选择操作设备。"
            )
            self.choose_button.setVisible(False)
            return
        self.message_label.setText(
            "当前没有可用设备。请使用顶部设备栏连接或刷新，选择后即可打开此功能。"
        )
        self.choose_button.setVisible(True)


class _ClosingSessionPage(CardWidget):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceFeatureClosing")
        self.setBorderRadius(10)
        self.title_label = StrongBodyLabel("正在关闭会话", self)
        self.message_label = BodyLabel(
            "后台资源仍在退出。完成后可重新打开此功能，不会复用正在关闭的页面。",
            self,
        )
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.back_button = PushButton(FluentIcon.LEFT_ARROW, "返回概览", self)
        self.back_button.clicked.connect(self.back_requested)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.message_label)
        layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def set_feature_label(self, label: str) -> None:
        self.title_label.setText(f"正在关闭{label}会话")


class _FeatureStack(QStackedWidget):
    """仅由当前功能页决定滚动内容的最小尺寸。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content_minimum = QSize()

    def set_content_minimum_size(self, size: QSize) -> None:
        normalized = QSize(max(0, size.width()), max(0, size.height()))
        if normalized == self._content_minimum:
            return
        self._content_minimum = normalized
        self.setMinimumSize(normalized)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        # QStackedWidget 默认合并所有隐藏页面的最小尺寸，会导致
        # 回到概览页后仍保留深层页的滚动范围。
        return QSize(self._content_minimum)

    def sizeHint(self) -> QSize:
        return QSize(self._content_minimum)


class WorkspaceFeatureHost(QWidget):
    """在一个任务领域页内承载概览和按设备懒创建的功能页面。"""

    route_changed = Signal(object)
    route_requested = Signal(object)
    choose_device_requested = Signal()
    FEATURE_SELECTOR_MIN_PIVOT_WIDTH = 520
    controls_changed = Signal()

    def __init__(
        self,
        section_key: str,
        overview_label: str,
        overview: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.section_key = section_key.strip()
        if not self.section_key:
            raise ValueError("section_key must not be empty")
        self._definitions: dict[str, _FeatureDefinition] = {}
        self._feature_aliases: dict[str, str] = {}
        self._external_device_controls = False
        self._overview_definitions: dict[str, _OverviewDefinition] = {}
        self._navigation_order: list[str] = ["overview"]
        self._selected_devices: tuple[str, ...] = ()
        self._connected_devices: tuple[str, ...] = ()
        self._current_feature = "overview"
        self._active_device_id = ""
        self._active_device_explicit = False
        self._device_selection_locks: dict[str, str] = {}
        self._last_device_by_feature: dict[str, str] = {}
        self._generation_by_pair: dict[tuple[str, str], int] = {}
        self._page_keys: dict[QWidget, FeatureSessionKey] = {}
        self._synchronizing_controls = False
        self._shutting_down = False
        self._active = True
        self._activating_route_from_background = False
        self._pending_route: WorkspaceRoute | None = None
        self._extent_update_scheduled = False
        self._extent_timer = QTimer(self)
        self._extent_timer.setSingleShot(True)
        self._extent_timer.timeout.connect(self._finish_content_extent_sync)
        self._session_badge_in_toolbar = True

        self.registry = FeatureSessionRegistry(self)
        self.registry.session_removed.connect(self._on_session_removed)

        self.feature_selector = AdaptiveNavigation(
            f"{self.section_key}:feature",
            accessible_name="工作区功能",
            minimum_pivot_width=self.FEATURE_SELECTOR_MIN_PIVOT_WIDTH,
            parent=self,
        )
        self.feature_pivot = self.feature_selector.pivot
        self.feature_pivot.setObjectName(f"{self.section_key}FeaturePivot")
        self.feature_pivot.setAccessibleName("工作区功能")
        self.feature_combo = self.feature_selector.combo
        self.feature_combo.setObjectName(f"{self.section_key}FeatureCombo")
        self.feature_combo.setAccessibleName("工作区功能")
        self.feature_combo.setToolTip("选择当前工作区功能")
        self.feature_selector.current_requested.connect(self._open_selected_feature)

        self.session_toolbar = QWidget(self)
        self.session_toolbar.setObjectName(f"{self.section_key}SessionToolbar")
        self.device_label = BodyLabel("会话设备", self.session_toolbar)
        self.device_label.setAccessibleName("会话设备")
        self.device_combo = ComboBox(self.session_toolbar)
        self.device_combo.setObjectName(f"{self.section_key}FeatureDevice")
        self.device_combo.setAccessibleName("会话设备")
        self.device_combo.setToolTip("选择当前单设备功能使用的设备")
        self.device_combo.setMinimumWidth(220)
        self.device_combo.setMaximumWidth(420)
        self.device_label.setBuddy(self.device_combo)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.session_badge = InfoBadge(self.session_toolbar, InfoLevel.INFOAMTION)
        self.session_badge.setAccessibleName("会话状态")
        self.session_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            False,
        )
        self.close_session_button = PushButton("关闭会话", self.session_toolbar)
        self.close_session_button.setAccessibleName("关闭当前功能会话")
        self.close_session_button.setToolTip("释放当前功能为此设备保留的后台资源")
        self.close_session_button.clicked.connect(self.close_current_session)
        toolbar_layout = QHBoxLayout(self.session_toolbar)
        toolbar_layout.setContentsMargins(0, 2, 0, 2)
        toolbar_layout.setSpacing(8)
        toolbar_layout.addWidget(self.device_label)
        toolbar_layout.addWidget(self.device_combo)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.session_badge)
        toolbar_layout.addWidget(self.close_session_button)

        self.content_scroll = SmoothScrollArea(self)
        self.content_scroll.setObjectName(f"{self.section_key}FeatureScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.content_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.content_scroll.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        self.content_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self.stack = _FeatureStack(self.content_scroll)
        self.stack.setObjectName(f"{self.section_key}FeatureStack")
        self.stack.installEventFilter(self)
        self.overview = overview
        self.overview.setParent(self.stack)
        self.stack.addWidget(self.overview)
        self.no_device_page = _NoDevicePage(self.stack)
        self.no_device_page.choose_device_requested.connect(self.choose_device_requested)
        self.stack.addWidget(self.no_device_page)
        self.closing_page = _ClosingSessionPage(self.stack)
        self.closing_page.back_requested.connect(self.show_overview)
        self.stack.addWidget(self.closing_page)
        self.content_scroll.setWidget(self.stack)

        self.content_column = QWidget(self)
        content_layout = QVBoxLayout(self.content_column)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(self.feature_selector)
        content_layout.addWidget(self.session_toolbar)
        content_layout.addWidget(self.content_scroll, 1)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 8, 24, 24)
        self._layout.setSpacing(10)
        self._layout.addWidget(self.content_column, 1)

        self._overview_definitions["overview"] = _OverviewDefinition(
            overview_label,
            FluentIcon.HOME,
            overview,
            False,
            None,
        )
        self._register_feature_selector_item("overview", overview_label)
        self._sync_feature_selector("overview")
        self.stack.currentChanged.connect(self._on_current_page_changed)
        self.show_overview()

    @property
    def current_feature(self) -> str:
        return self._current_feature

    @property
    def current_device_id(self) -> str:
        return self._active_device_id

    def take_session_badge(self) -> InfoBadge:
        """把会话状态交给页面标题区，宿主只保留设备和关闭动作。"""

        if self._session_badge_in_toolbar:
            layout = self.session_toolbar.layout()
            if layout is not None:
                layout.removeWidget(self.session_badge)
            self._session_badge_in_toolbar = False
            definition = self._definitions.get(self._current_feature)
            overview = self._overview_definitions.get(self._current_feature)
            self._sync_feature_controls(definition or overview)
        return self.session_badge

    def feature_label(self, feature: str) -> str:
        feature = self.canonical_feature(feature)
        definition = self._definitions.get(feature)
        if definition is not None:
            return definition.label
        overview = self._overview_definitions.get(feature)
        return overview.label if overview is not None else ""

    def navigation_items(self) -> tuple[WorkspaceNavigationItem, ...]:
        """按工作区内部信息架构顺序返回功能入口。"""

        items: list[WorkspaceNavigationItem] = []
        for feature in self._navigation_order:
            definition = self._definitions.get(feature)
            if definition is None:
                definition = self._overview_definitions.get(feature)
            if definition is None:
                continue
            items.append(
                WorkspaceNavigationItem(feature, definition.label, definition.icon)
            )
        return tuple(items)

    def _register_feature_selector_item(self, feature: str, label: str) -> None:
        """把功能登记到宽屏 Pivot 和窄屏 ComboBox 的同一顺序。"""

        self.feature_selector.add_item(feature, label)

    def _sync_feature_selector(self, feature: str) -> None:
        """原子同步两种选择控件，不重复触发功能切换。"""

        self.feature_selector.set_current(feature)

    def _open_selected_feature(self, feature: str) -> None:
        """处理页面内功能选择；当前项不重复启动或重置会话。"""

        if (
            not feature
            or feature == self._current_feature
        ):
            return
        self.route_requested.emit(WorkspaceRoute(self.section_key, feature))

    def is_overview_feature(self, feature: str) -> bool:
        """返回路由是否属于不创建独立会话的概览内容。"""

        return self.canonical_feature(feature) in self._overview_definitions

    def feature_requires_device(self, feature: str) -> bool:
        """返回功能是否要求一个明确的单设备上下文。"""

        feature = self.canonical_feature(feature)
        definition = self._definitions.get(feature)
        if definition is not None:
            return definition.requires_device
        overview = self._overview_definitions.get(feature)
        return bool(overview and overview.requires_device)

    def is_device_connected(self, device_id: str) -> bool:
        """返回设备是否包含在最近一次工作区在线快照中。"""

        return str(device_id).strip() in self._connected_devices

    def has_feature(self, feature: str) -> bool:
        """返回此宿主是否支持给定二级功能。"""

        feature = self.canonical_feature(feature)
        return feature in self._overview_definitions or feature in self._definitions

    def canonical_feature(self, feature: str) -> str:
        """旧入口解析到合并后的功能，不增加导航项或复制会话。"""

        return self._feature_aliases.get(feature, feature)

    def register_alias(self, alias: str, target: str) -> None:
        """只接受已有真实功能，避免别名循环和隐藏的重复页面。"""

        if not alias or self.has_feature(alias) or target not in self._navigation_order:
            raise ValueError("invalid feature alias")
        self._feature_aliases[alias] = target

    def set_external_device_controls(self, enabled: bool) -> None:
        """主窗口可投影设备控件到全局栏；独立宿主保留原工具栏契约。"""

        self._external_device_controls = bool(enabled)
        self._sync_session_toolbar_visibility()

    @property
    def pending_route(self) -> WorkspaceRoute | None:
        return self._pending_route

    def register_feature(
        self,
        key: str,
        label: str,
        icon,
        factory: Callable[[FeatureSessionKey], QWidget],
        *,
        requires_device: bool = True,
        close_label: str = "关闭会话",
    ) -> None:
        key = key.strip()
        if (
            not key
            or key in self._overview_definitions
            or key in self._definitions
        ):
            raise ValueError(f"invalid or duplicate feature key: {key!r}")
        self._definitions[key] = _FeatureDefinition(
            label=label,
            icon=icon,
            factory=factory,
            requires_device=requires_device,
            close_label=str(close_label).strip() or "关闭会话",
        )
        self._navigation_order.append(key)
        self._register_feature_selector_item(key, label)

    def register_overview_category(
        self,
        key: str,
        label: str,
        icon,
        *,
        page: QWidget | None = None,
        requires_device: bool = False,
        activate: Callable[[str], object] | None = None,
    ) -> None:
        """把概览分类加入同一套本地导航，不创建或销毁功能会话。"""

        key = key.strip()
        if not key or key in self._overview_definitions or key in self._definitions:
            raise ValueError(f"invalid or duplicate overview key: {key!r}")
        target_page = self.overview if page is None else page
        if self.stack.indexOf(target_page) < 0:
            target_page.setParent(self.stack)
            self.stack.addWidget(target_page)
        self._overview_definitions[key] = _OverviewDefinition(
            str(label),
            icon,
            target_page,
            bool(requires_device),
            activate,
        )
        self._navigation_order.append(key)
        self._register_feature_selector_item(key, label)

    def configure_overview_category(
        self,
        key: str,
        *,
        icon=None,
        requires_device: bool | None = None,
        activate: Callable[[str], object] | None = None,
    ) -> None:
        """为构造时创建的默认概览补充分区激活行为。"""

        definition = self._overview_definitions.get(key)
        if definition is None:
            raise ValueError(f"unknown overview key: {key!r}")
        self._overview_definitions[key] = _OverviewDefinition(
            definition.label,
            definition.icon if icon is None else icon,
            definition.page,
            definition.requires_device if requires_device is None else requires_device,
            activate,
        )

    def set_device_context(
        self,
        selected_devices: Iterable[str],
        connected_devices: Iterable[str],
    ) -> None:
        self._selected_devices = self._normalized_devices(selected_devices)
        self._connected_devices = self._normalized_devices(connected_devices)
        for key in self.registry.keys():
            page = self.registry.get(key)
            self._sync_page_device_context(page, key.device_id)

        resumed_pending = False
        if self._pending_route is not None:
            # 隐藏分区必须保留一次性 payload，交给首次前台激活消费，
            # 避免设备快照更新在后台提前创建页面。
            if self._active:
                resumed_pending = self._resume_pending_route_if_possible()
            if self._pending_route is not None:
                self._refresh_pending_route_state()
                return

        current_definition = self._definitions.get(self._current_feature)
        current_overview = self._overview_definitions.get(self._current_feature)
        if (
            not resumed_pending
            and current_overview is not None
            and current_overview.requires_device
            and current_overview.activate is not None
            and self._active_device_id
        ):
            current_overview.activate(self._active_device_id)
        self._sync_feature_controls(current_definition or current_overview)
        self._sync_device_combo()

    def _sync_page_device_context(self, page: QWidget | None, device_id: str) -> None:
        """先撤销操作资格再更新在线状态，避免重连回调沿用历史会话启动命令。"""

        selected = getattr(page, "set_device_selected", None)
        if callable(selected):
            selected(device_id in self._selected_devices)
        connected = getattr(page, "set_device_connected", None)
        if callable(connected):
            connected(device_id in self._connected_devices)

    def set_device_selection_locked(
        self,
        feature: str,
        locked: bool,
        reason: str = "",
    ) -> None:
        """锁定指定功能的会话设备，供运行中的单设备任务维持目标。"""

        feature = self.canonical_feature(feature)
        if not self.has_feature(feature):
            raise ValueError(f"unknown feature key: {feature!r}")
        if locked:
            self._device_selection_locks[feature] = str(reason).strip()
        else:
            self._device_selection_locks.pop(feature, None)
        if feature == self._current_feature:
            definition = self._definitions.get(feature)
            overview = self._overview_definitions.get(feature)
            self._sync_feature_controls(definition or overview)
            self._sync_device_combo()

    def open_route(self, route: WorkspaceRoute) -> bool:
        if route.section != self.section_key:
            return False
        route = WorkspaceRoute(
            route.section, self.canonical_feature(route.feature), route.device_id, route.payload
        )
        if route.feature in self._overview_definitions:
            return self.show_overview(
                route.feature,
                preferred_device=route.device_id,
            )
        return self.open_feature(
            route.feature,
            preferred_device=route.device_id,
            payload=route.payload,
        )

    def activate_route(self, route: WorkspaceRoute) -> bool:
        """从后台原子打开目标路由，不短暂恢复上一个会话。"""

        if route.section != self.section_key or not self.has_feature(route.feature):
            return False
        if self._active:
            return self.open_route(route)
        self._active = True
        self._activating_route_from_background = True
        try:
            return self.open_route(route)
        finally:
            self._activating_route_from_background = False

    def open_feature(
        self,
        feature: str,
        *,
        preferred_device: str = "",
        payload=None,
    ) -> bool:
        definition = self._definitions.get(feature)
        if definition is None:
            return False
        self._current_feature = feature
        self._sync_feature_selector(feature)
        self._sync_feature_controls(definition)

        device_id = preferred_device.strip()
        if device_id:
            self._active_device_explicit = True
        if definition.requires_device:
            candidates = self._device_candidates(feature)
            if device_id and device_id not in candidates:
                candidates = (device_id, *candidates)
            if not device_id:
                remembered = self._last_device_by_feature.get(feature, "")
                if remembered in candidates:
                    device_id = remembered
                elif self._active_device_id in candidates:
                    device_id = self._active_device_id
                else:
                    device_id = self._automatic_device_candidate()
                    if device_id:
                        self._active_device_explicit = False
            if not device_id:
                self.registry.deactivate_current(
                    "no_device",
                    current_is_inactive=self._activating_route_from_background,
                )
                self._pending_route = WorkspaceRoute(
                    self.section_key,
                    feature,
                    payload=payload,
                )
                self._refresh_pending_route_state()
                self.route_changed.emit(WorkspaceRoute(self.section_key, feature))
                return True
            self._last_device_by_feature[feature] = device_id
            self._active_device_id = device_id
        self._pending_route = None

        pair = (feature, device_id)
        generation = self._generation_by_pair.get(pair, 0)
        key = FeatureSessionKey(feature, device_id, generation)
        if self.registry.is_disposing(key):
            self._show_disposing_session(key, definition)
            return True
        page, created = self.registry.get_or_create(key, definition.factory)
        if created:
            prepare = getattr(page, "prepare_for_workspace", None)
            if callable(prepare):
                prepare()
            page.setParent(self.stack)
            self.stack.addWidget(page)
            page.installEventFilter(self)
            self._page_keys[page] = key
        if definition.requires_device:
            self._sync_page_device_context(page, device_id)
        self.registry.activate(
            key,
            payload,
            previous_is_inactive=self._activating_route_from_background,
        )
        self.stack.setCurrentWidget(page)
        self._sync_feature_controls(definition)
        self._sync_device_combo()
        self.route_changed.emit(
            WorkspaceRoute(self.section_key, feature, device_id, payload)
        )
        return True

    def update_feature(
        self,
        feature: str,
        payload,
        *,
        preferred_device: str = "",
    ) -> QWidget | None:
        """在后台更新一个会话，不改变当前分区、功能或前台生命周期。"""

        definition = self._definitions.get(feature)
        if definition is None:
            return None
        device_id = preferred_device.strip()
        if definition.requires_device:
            candidates = self._device_candidates(feature)
            if not device_id:
                remembered = self._last_device_by_feature.get(feature, "")
                if remembered in candidates:
                    device_id = remembered
                elif self._active_device_id in candidates:
                    device_id = self._active_device_id
                else:
                    device_id = self._automatic_device_candidate()
            if not device_id:
                return None
        pair = (feature, device_id)
        generation = self._generation_by_pair.get(pair, 0)
        key = FeatureSessionKey(feature, device_id, generation)
        if self.registry.is_disposing(key):
            return None
        page, created = self.registry.get_or_create(key, definition.factory)
        if created:
            prepare = getattr(page, "prepare_for_workspace", None)
            if callable(prepare):
                prepare()
            page.setParent(self.stack)
            self.stack.addWidget(page)
            page.installEventFilter(self)
            self._page_keys[page] = key
        if definition.requires_device:
            self._sync_page_device_context(page, device_id)
        receiver = getattr(page, "receive_payload", None)
        if callable(receiver):
            receiver(payload)
            return page
        if created:
            activate = getattr(page, "activate", None)
            deactivate = getattr(page, "deactivate", None)
            if callable(activate):
                activate(payload)
            if callable(deactivate):
                deactivate("background_update")
        return page

    def show_overview(
        self,
        category: str = "overview",
        *,
        preferred_device: str = "",
    ) -> bool:
        category = self.canonical_feature(category)
        definition = self._overview_definitions.get(category)
        if definition is None:
            return False
        self.registry.deactivate_current(
            "overview",
            current_is_inactive=self._activating_route_from_background,
        )
        self._pending_route = None
        self._current_feature = category
        self._sync_feature_selector(category)

        device_id = preferred_device.strip()
        if device_id:
            self._active_device_explicit = True
        if definition.requires_device:
            candidates = self._device_candidates(category)
            if device_id and device_id not in candidates:
                candidates = (device_id, *candidates)
            if not device_id:
                automatic = self._automatic_device_candidate()
                if automatic and not self._active_device_explicit:
                    device_id = automatic
                    self._active_device_explicit = False
                elif self._active_device_id in candidates:
                    device_id = self._active_device_id
                else:
                    device_id = automatic
                    if device_id:
                        self._active_device_explicit = False
            if not device_id:
                self._pending_route = WorkspaceRoute(self.section_key, category)
                self._refresh_pending_route_state()
                self.route_changed.emit(WorkspaceRoute(self.section_key, category))
                return True
            self._active_device_id = device_id

        if definition.activate is not None:
            activated_device = definition.activate(device_id)
            if (
                definition.requires_device
                and isinstance(activated_device, str)
                and activated_device.strip()
                and activated_device.strip() != device_id
            ):
                device_id = activated_device.strip()
                self._active_device_id = device_id
        self.stack.setCurrentWidget(definition.page)
        reset_scroll = getattr(definition.page, "reset_scroll_position", None)
        if callable(reset_scroll):
            reset_scroll()
        self._sync_feature_controls(definition)
        self._sync_device_combo()
        self.route_changed.emit(
            WorkspaceRoute(self.section_key, category, device_id)
        )
        return True

    def close_current_session(self) -> None:
        key = self.registry.current_key
        if key is None:
            self.show_overview()
            return
        self.close_session_button.setEnabled(False)
        self.session_badge.setText("正在关闭")
        self.session_badge.setLevel(InfoLevel.WARNING)
        if not self.registry.request_dispose(key, "user"):
            self.registry.deactivate_current("disposing")
            definition = self._definitions.get(key.feature)
            if definition is not None:
                self._show_disposing_session(key, definition)

    def register_shutdown_tasks(
        self,
        supervisor,
        *,
        owner_id: str,
        task_prefix: str,
    ) -> tuple[str, ...]:
        return self.registry.register_shutdown_tasks(
            supervisor,
            owner_id=owner_id,
            task_prefix=task_prefix,
        )

    def shutdown(self) -> None:
        self._shutting_down = True
        self._pending_route = None
        self.registry.request_dispose_all("application_shutdown")

    def activate(self) -> None:
        """恢复当前可见功能页的前台生命周期。"""

        if self._active:
            return
        self._active = True
        if self._pending_route is not None:
            if not self._resume_pending_route_if_possible():
                self._refresh_pending_route_state()
            return
        key = self.registry.current_key
        if key is None or self._current_feature == "overview":
            return
        page = self.registry.get(key)
        callback = getattr(page, "activate", None)
        if callable(callback):
            callback(None)

    def deactivate(self, reason: str = "section_navigation") -> None:
        """暂停当前页瞬态工作，但保留其稳定设备会话和后台任务。"""

        if not self._active:
            return
        self._active = False
        key = self.registry.current_key
        page = self.registry.get(key) if key is not None else None
        callback = getattr(page, "deactivate", None)
        if callable(callback):
            callback(reason)

    def _on_device_changed(self, _index: int) -> None:
        if self._synchronizing_controls:
            return
        device_id = str(self.device_combo.currentData() or "")
        if not device_id or device_id == self._active_device_id:
            return
        pending = self._pending_route
        self._active_device_id = device_id
        self._active_device_explicit = True
        if self._current_feature in self._overview_definitions:
            self.show_overview(
                self._current_feature,
                preferred_device=device_id,
            )
            return
        payload = (
            pending.payload
            if pending is not None and pending.feature == self._current_feature
            else None
        )
        self.open_feature(
            self._current_feature,
            preferred_device=device_id,
            payload=payload,
        )

    def _sync_device_combo(self) -> None:
        definition = self._definitions.get(self._current_feature)
        overview = self._overview_definitions.get(self._current_feature)
        requires_device = bool(
            (definition and definition.requires_device)
            or (overview and overview.requires_device)
        )
        if not requires_device:
            self.device_label.setVisible(False)
            self.device_combo.setVisible(False)
            self._sync_session_toolbar_visibility()
            return
        candidates = list(self._device_candidates(self._current_feature))
        current = self._active_device_id or self._last_device_by_feature.get(
            self._current_feature,
            "",
        )
        if current and current not in candidates:
            candidates.insert(0, current)
        self._synchronizing_controls = True
        blocker = QSignalBlocker(self.device_combo)
        self.device_combo.clear()
        if not current and candidates:
            self.device_combo.addItem("请选择一台设备", userData="")
        for device_id in candidates:
            label = device_id
            if device_id not in self._connected_devices:
                label = f"{device_id}（离线会话）"
            self.device_combo.addItem(label, userData=device_id)
        if current:
            for index in range(self.device_combo.count()):
                if self.device_combo.itemData(index) == current:
                    self.device_combo.setCurrentIndex(index)
                    break
        del blocker
        self._synchronizing_controls = False
        has_candidates = bool(candidates)
        lock_reason = self._device_selection_locks.get(self._current_feature, "")
        self.device_label.setVisible(has_candidates)
        self.device_combo.setVisible(has_candidates)
        can_choose = bool(candidates) and (not current or len(candidates) > 1)
        self.device_combo.setEnabled(can_choose and not lock_reason)
        if lock_reason:
            tooltip = lock_reason
        elif not current and candidates:
            tooltip = "请选择当前功能使用的一台设备"
        elif len(candidates) <= 1:
            tooltip = "当前只有这一台会话设备"
        else:
            tooltip = "选择当前单设备功能使用的设备"
        self.device_combo.setToolTip(tooltip)
        self.device_combo.setAccessibleDescription(tooltip)
        self._sync_session_toolbar_visibility()

    def _sync_session_toolbar_visibility(self) -> None:
        """仅在工具栏仍有实际控件时占用内容区高度。"""

        if self._external_device_controls:
            self.session_toolbar.hide()
            self.controls_changed.emit()
            return
        controls = [
            self.device_label,
            self.device_combo,
            self.close_session_button,
        ]
        if self._session_badge_in_toolbar:
            controls.append(self.session_badge)
        self.session_toolbar.setVisible(
            any(not control.isHidden() for control in controls)
        )
        self.controls_changed.emit()

    def _sync_feature_controls(
        self,
        definition: _FeatureDefinition | _OverviewDefinition | None,
    ) -> None:
        requires_device = bool(definition and definition.requires_device)
        closable = isinstance(definition, _FeatureDefinition)
        is_overview = isinstance(definition, _OverviewDefinition)
        self.device_label.setVisible(requires_device)
        self.device_combo.setVisible(requires_device)
        lock_reason = self._device_selection_locks.get(self._current_feature, "")
        self.device_combo.setEnabled(not lock_reason)
        self.close_session_button.setVisible(closable)
        self.close_session_button.setEnabled(closable)
        # 外置设备栏和设备概览摘要已呈现目标数量，页头只保留会话相关状态。
        self.session_badge.setVisible(
            requires_device or closable or (is_overview and not self._external_device_controls)
        )
        if closable:
            self.close_session_button.setText(definition.close_label)
        connected = bool(
            self._active_device_id
            and self._active_device_id in self._connected_devices
        )
        if requires_device and self._active_device_id:
            selected = self._active_device_id in self._selected_devices
            status = ("在线" if selected else "未选为操作目标") if connected else "离线"
            level = InfoLevel.SUCCESS if connected and selected else InfoLevel.WARNING
            description = (
                "当前设备可执行操作" if connected and selected
                else "请选择当前设备作为操作目标后再执行；已有内容仍可查看，原任务仍可停止"
            )
        elif requires_device:
            status = "等待选择设备"
            level = InfoLevel.INFOAMTION
            description = "请明确选择当前功能使用的一台设备"
        elif is_overview:
            count = len(self._selected_devices)
            status = f"操作目标：{count} 台" if count else "操作目标：未选择"
            level = InfoLevel.SUCCESS if count else InfoLevel.INFOAMTION
            description = (
                f"已勾选 {count} 台操作目标"
                if count
                else "可在顶部设备栏中勾选操作目标"
            )
        else:
            status = "已打开"
            level = InfoLevel.INFOAMTION
            description = "当前功能已打开"
        self.session_badge.setText(status)
        self.session_badge.setLevel(level)
        self.session_badge.setToolTip(description)
        self.session_badge.setAccessibleDescription(description)
        self._sync_session_toolbar_visibility()

    def eventFilter(self, watched, event) -> bool:
        """当前功能页在主题、字体或布局变化后重新计算可滚动范围。"""

        page = self.stack.currentWidget()
        page_event = watched is page and event.type() in {
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        }
        layout_event = (
            watched in {page, self.stack}
            and event.type() == QEvent.Type.LayoutRequest
        )
        if page_event or layout_event:
            self._schedule_content_extent_sync()
        return super().eventFilter(watched, event)

    def _on_current_page_changed(self, _index: int) -> None:
        self._sync_content_extent()
        self.content_scroll.horizontalScrollBar().setValue(0)
        self.content_scroll.verticalScrollBar().setValue(0)
        self._schedule_content_extent_sync()

    def _schedule_content_extent_sync(self) -> None:
        if self._extent_update_scheduled:
            return
        self._extent_update_scheduled = True
        # 定时器属于宿主，宿主销毁时 Qt 自动取消排队回调。
        self._extent_timer.start(0)

    def _finish_content_extent_sync(self) -> None:
        self._extent_update_scheduled = False
        self._sync_content_extent()

    def _sync_content_extent(self) -> None:
        """让短屏滚动承载完整功能页，不把内部控件强行压缩到重叠。"""

        page = self.stack.currentWidget()
        overview_pages = {
            definition.page for definition in self._overview_definitions.values()
        }
        if page is None or page in overview_pages | {
            self.no_device_page,
            self.closing_page,
        }:
            self.stack.set_content_minimum_size(QSize())
            return

        provider = getattr(page, "workspace_content_minimum_size", None)
        size = provider() if callable(provider) else page.minimumSizeHint()
        if not isinstance(size, QSize):
            size = QSize()
        size = size.expandedTo(page.minimumSize())
        self.stack.set_content_minimum_size(size)

    def _device_candidates(self, feature: str) -> tuple[str, ...]:
        current = self._last_device_by_feature.get(feature, "")
        values = list(self._connected_devices)
        for device_id in self._selected_devices:
            if device_id not in values:
                values.append(device_id)
        if self._active_device_id and self._active_device_id not in values:
            values.append(self._active_device_id)
        if current and current not in values:
            values.append(current)
        for key in self.registry.keys():
            if key.feature == feature and key.device_id and key.device_id not in values:
                values.append(key.device_id)
        return tuple(values)

    def _automatic_device_candidate(self) -> str:
        """仅沿用唯一且在线的操作目标；连接状态本身不代表用户选择。"""

        if (len(self._selected_devices) == 1
                and self._selected_devices[0] in self._connected_devices):
            return self._selected_devices[0]
        return ""

    def _resume_pending_route_if_possible(self) -> bool:
        """只在前台且存在唯一自动候选时恢复待打开路由。"""

        route = self._pending_route
        if route is None or not self._active:
            return False
        device_id = self._automatic_device_candidate()
        if not device_id:
            return False
        return self.open_route(
            WorkspaceRoute(
                route.section,
                route.feature,
                device_id,
                route.payload,
            )
        )

    def _refresh_pending_route_state(self) -> None:
        """按最新候选刷新等待页，不消费路由携带的一次性 payload。"""

        route = self._pending_route
        if route is None:
            return
        definition = self._definitions.get(route.feature)
        overview = self._overview_definitions.get(route.feature)
        current_definition = definition or overview
        if current_definition is None:
            return
        self._current_feature = route.feature
        self._sync_feature_selector(route.feature)
        candidates = self._device_candidates(route.feature)
        self.no_device_page.set_feature_label(current_definition.label)
        self.no_device_page.set_candidates_available(bool(candidates))
        self.stack.setCurrentWidget(self.no_device_page)
        self._sync_feature_controls(current_definition)
        self._sync_device_combo()
        self.close_session_button.setVisible(False)
        self.close_session_button.setEnabled(False)
        self.session_badge.setText("等待选择设备")
        self.session_badge.setLevel(InfoLevel.INFOAMTION)
        self.session_badge.setToolTip("请在会话设备列表中明确选择一台设备")
        self.session_badge.setAccessibleDescription(
            "请在会话设备列表中明确选择一台设备"
        )
        self._sync_session_toolbar_visibility()

    @staticmethod
    def _normalized_devices(devices: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(device).strip() for device in devices if str(device).strip()
            )
        )

    def _on_session_removed(self, key: FeatureSessionKey, page: QWidget) -> None:
        if self.stack.indexOf(page) >= 0:
            self.stack.removeWidget(page)
        self._page_keys.pop(page, None)
        pair = (key.feature, key.device_id)
        self._generation_by_pair[pair] = key.generation + 1
        if self._last_device_by_feature.get(key.feature) == key.device_id:
            self._last_device_by_feature.pop(key.feature, None)
        if (
            self._active_device_id == key.device_id
            and key.device_id not in self._connected_devices
            and not any(
                session_key.device_id == key.device_id
                for session_key in self.registry.keys()
            )
        ):
            self._active_device_id = ""
        if (
            not self._shutting_down
            and self._current_feature == key.feature
            and self.registry.current_key is None
        ):
            self.show_overview()

    def _show_disposing_session(
        self,
        key: FeatureSessionKey,
        definition: _FeatureDefinition,
    ) -> None:
        """显示资源退出屏障，禁止重新激活正在销毁的页面。"""

        self._current_feature = key.feature
        self._sync_feature_selector(key.feature)
        self._active_device_id = key.device_id
        self._last_device_by_feature[key.feature] = key.device_id
        self.closing_page.set_feature_label(definition.label)
        self.stack.setCurrentWidget(self.closing_page)
        self._sync_feature_controls(definition)
        self.close_session_button.setEnabled(False)
        self.session_badge.setText("正在关闭")
        self.session_badge.setLevel(InfoLevel.WARNING)
        self._sync_device_combo()
        self.route_changed.emit(
            WorkspaceRoute(self.section_key, key.feature, key.device_id)
        )


__all__ = ["WorkspaceFeatureHost", "WorkspaceNavigationItem", "WorkspaceRoute"]
