"""协调设备、应用、系统和 Remote 子面板的延迟加载与信号连接。"""

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.panels.app_panel import AppPanel
from gui.panels.device_manager import DeviceManager
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.system_panel import SystemPanel
from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.responsive_controller import ReflowReason, ResponsiveCoordinator
from gui.widgets.responsive_layout import prepare_responsive_content


class SidePanel(QWidget):
    """创建并管理功能标签页，同时保持 MainFrame 使用的兼容接口。"""

    PANEL_WIDTH = 600
    selected_devices_changed = Signal(list)
    responsive_layout_settled = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.signals = SidePanelSignals()
        self._package_history = []
        self._connected_device_cache = []
        self._user_selected_ip = False
        self._current_ip = ""
        self._tabs_connected = False
        self._connected_lazy_tabs = set()
        self._loaded_lazy_tabs = set()
        self._restricted_width_mode = False
        self._responsive_style_generation = 0
        self._responsive_coordinator = ResponsiveCoordinator()
        self._last_settled_generation = 0
        self._responsive_settle_timer = QTimer(self)
        self._responsive_settle_timer.setSingleShot(True)
        self._responsive_settle_timer.setInterval(8)
        self._responsive_settle_timer.timeout.connect(self._poll_responsive_settled)

        self.setMinimumWidth(300)
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        BaseStyles.theme_changed.connect(self._on_theme_changed)
        BaseStyles.fonts_changed.connect(self._on_fonts_changed)

        self._create_fonts()
        self._create_ui()
        self.selected_devices_changed.connect(self._refresh_loaded_action_states)
        self._connect_all_signals()

    # ── 字体 ─────────────────────────────────────────────────────────────

    def _create_fonts(self):
        # 兼容旧面板属性名；普通交互控件必须与全局界面字号保持一致。
        self._font_sm = BaseStyles.font_for_role(FontRole.UI)
        self._font_mono = BaseStyles.font_for_role(FontRole.MONO)
        self._font_base = BaseStyles.font_for_role(FontRole.UI)
        self._font_tab = BaseStyles.font_for_role(FontRole.UI)

    # ── 界面构建 ─────────────────────────────────────────────────────────

    def _create_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # 设备面板由 MainFrame 放入左栏；这里提前构建，确保初始化时可以连接信号。
        self._devices_tab = DeviceManager(self)
        self._device_widget = self._devices_tab.build_ui()

        self.tabs = QTabWidget()
        self.tabs.setFont(self._font_tab)
        self._apply_tab_style()

        self._apps_tab = None
        self._advanced_tab = None
        self._scrcpy_tab = None
        self._tab_scroll_areas = {}
        self._responsive_viewports = {}
        self._lazy_tab_specs = [
            ("_apps_tab", AppPanel, "Apps"),
            ("_advanced_tab", SystemPanel, "System"),
            ("_scrcpy_tab", RemotePanel, "Remote"),
        ]
        for index, (_attr, _cls, name) in enumerate(self._lazy_tab_specs):
            scroll = self._create_tab_scroll_area()
            self._tab_scroll_areas[index] = scroll
            self._responsive_viewports[scroll.viewport()] = index
            scroll.viewport().installEventFilter(self)
            self.tabs.addTab(scroll, name)
        self.tabs.currentChanged.connect(self._ensure_tab_loaded)
        self._ensure_tab_loaded(0)

        lo.addWidget(self.tabs, stretch=1)

    def _create_tab_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # 响应式重排优先；极窄宽度或超大字体下保留可访问的横向兜底。
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }\n"
            f"{BaseStyles.SCROLLBAR_STYLE()}"
        )
        return scroll

    def _ensure_tab_loaded(self, index: int):
        if index < 0 or index >= len(self._lazy_tab_specs):
            return None
        attr, cls, _name = self._lazy_tab_specs[index]
        tab = getattr(self, attr, None)
        if tab is not None:
            return tab
        tab = cls(self)
        tab_widget = tab.build_ui()
        prepare_responsive_content(tab_widget)
        tab_widget.setMinimumWidth(0)
        self._tab_scroll_areas[index].setWidget(tab_widget)
        setattr(self, attr, tab)
        self._loaded_lazy_tabs.add(index)
        activate_bindings = getattr(tab, "activate_responsive_bindings", None)
        if callable(activate_bindings):
            activate_bindings()
        if self._tabs_connected:
            self._connect_lazy_tab_signals(index, tab)
        self._refresh_tab_action_states(tab)
        return tab

    def eventFilter(self, watched, event):
        index = self._responsive_viewports.get(watched)
        if index is not None and event.type() == QEvent.Type.Resize:
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            # 当前代会在每轮重新读取真实 viewport；此时产生的 Resize 属于布局反馈，
            # 不得排入下一代。稳定后到达的排队事件则由页面门面判断是否仍有新几何。
            if not self._responsive_coordinator.diagnostics.stable:
                return super().eventFilter(watched, event)
            geometry_is_applied = getattr(tab, "responsive_geometry_is_applied", None)
            if callable(geometry_is_applied) and geometry_is_applied():
                return super().eventFilter(watched, event)
            apply_responsive_width = getattr(tab, "apply_responsive_width", None)
            if callable(apply_responsive_width):
                apply_responsive_width(event.size().width())
        return super().eventFilter(watched, event)

    def _connect_lazy_tab_signals(self, index: int, tab=None):
        if index in self._connected_lazy_tabs:
            return
        tab = tab or self._ensure_tab_loaded(index)
        if tab is None:
            return
        tab.connect_signals()
        self._connected_lazy_tabs.add(index)

    @staticmethod
    def _refresh_tab_action_states(tab) -> None:
        """刷新一个功能页公开的动作可用状态。"""

        refresh = getattr(tab, "update_action_states", None)
        if not callable(refresh):
            refresh = getattr(tab, "_update_action_states", None)
        if callable(refresh):
            refresh()

    def _refresh_loaded_action_states(self, _devices=None) -> None:
        """设备选择变化时同步刷新所有已加载功能页。"""

        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            if tab is not None:
                self._refresh_tab_action_states(tab)

    # ── 委托给子标签页的共享属性 ─────────────────────────────────────────

    @property
    def selected_devices(self) -> list[str]:
        return self._devices_tab.selected_devices

    @property
    def ip_address(self) -> str:
        return self._devices_tab.ip_address

    @property
    def device_widget(self) -> QWidget:
        return self._device_widget

    # ── MainFrame 使用的公共接口 ─────────────────────────────────────────

    def update_device_list(self, devices: list[str] = None):
        self._devices_tab.update_device_list(devices)

    def set_device_discovery_state(self, state: str) -> None:
        self._devices_tab.set_discovery_state(state)

    def set_restricted_width_mode(self, restricted: bool) -> None:
        """受限工作区允许右侧页签缩小，并由滚动条保证内容可达。"""

        restricted = bool(restricted)
        if restricted == self._restricted_width_mode:
            return
        self._restricted_width_mode = restricted
        minimum_width = 160 if restricted else 300
        if self.minimumWidth() != minimum_width:
            self.setMinimumWidth(minimum_width)
        self.request_responsive_reflow(ReflowReason.RESIZE)

    def request_responsive_reflow(self, reason: ReflowReason) -> None:
        """把所有设备布局事件合并到本面板唯一的响应式协调器。"""

        self._responsive_coordinator.request_reflow(reason)
        if not self._responsive_settle_timer.isActive():
            self._responsive_settle_timer.start()

    def _poll_responsive_settled(self) -> None:
        """在协调器真实收口后，为测试和诊断发布一次稳定代次。"""

        diagnostics = self._responsive_coordinator.diagnostics
        if not diagnostics.stable:
            self._responsive_settle_timer.start()
            return
        if diagnostics.generation > self._last_settled_generation:
            self._last_settled_generation = diagnostics.generation
            self.responsive_layout_settled.emit(diagnostics.generation)

    def refresh_device_choices(self):
        self._devices_tab._refresh_device_combobox()

    def apply_device_theme(self):
        self._devices_tab._apply_device_list_style()
        if hasattr(self._devices_tab, "ip_entry"):
            self._apply_completer_style(self._devices_tab.ip_entry.completer())

    def apply_responsive_widths(
        self,
        left_width: int,
        _right_width: int,
        *,
        reason: ReflowReason = ReflowReason.RESIZE,
    ) -> None:
        """刷新分栏布局；功能页始终以各自 viewport 实际宽度为准。"""

        del left_width
        self.request_responsive_reflow(reason)

    def current_package_text(self) -> str:
        apps_tab = self._apps_tab
        if apps_tab is None:
            return ""
        return apps_tab.package_text

    def update_current_package(self, device_ip: str, package_name: str):
        self._devices_tab.update_current_package(device_ip, package_name)

    def on_recording_finished(self):
        apps_tab = self._ensure_tab_loaded(0)
        if apps_tab:
            apps_tab.on_recording_finished()

    def on_recording_target_finished(self, batch_id: str, device: str) -> None:
        apps_tab = self._ensure_tab_loaded(0)
        if apps_tab:
            apps_tab.on_recording_target_finished(batch_id, device)

    def on_monkey_target_finished(self, batch_id: str, device: str) -> None:
        apps_tab = self._ensure_tab_loaded(0)
        if apps_tab:
            apps_tab.on_monkey_target_finished(batch_id, device)

    def on_operation_completed(self, operation: str, success: bool, message: str):
        apps_tab = self._ensure_tab_loaded(0)
        if apps_tab:
            apps_tab.on_operation_completed(operation, success, message)

    def refresh_from_settings(self) -> None:
        """只通知已加载且声明了设置刷新钩子的功能页。"""

        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            for method_name in ("refresh_from_settings", "reload_from_settings"):
                refresh = getattr(tab, method_name, None)
                if callable(refresh):
                    refresh()
                    break

    def shutdown(self):
        """依次关闭已加载标签页拥有的后台资源。"""
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            shutdown = getattr(tab, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def register_shutdown_tasks(self, supervisor, *, owner_id: str) -> tuple[str, ...]:
        """将已加载标签页的异步关闭任务注册到统一监督器。"""
        registered = []
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            register = getattr(tab, "register_shutdown_task", None)
            if not callable(register):
                continue
            task_id = f"{owner_id}-panel-{index}"
            if register(supervisor, owner_id=owner_id, task_id=task_id):
                registered.append(task_id)
        return tuple(registered)

    # ── 主题 ─────────────────────────────────────────────────────────────

    def _apply_tab_style(self):
        bs = BaseStyles
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid "
            f"{bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_MD}px;"
            f"background:{bs.color('WINDOW_BG')}"
            ";}QTabBar::tab{background:"
            f"{bs.color('BUTTON_BG')};color:{bs.color('TEXT_PRIMARY')};"
            "border:1px solid "
            f"{bs.color('BORDER_COLOR')};border-bottom:none;padding:3px 12px;"
            f"border-radius:{bs.RADIUS_SM}px {bs.RADIUS_SM}px 0 0;margin-right:1px"
            ";}QTabBar::tab:selected{background:"
            f"{bs.color('WINDOW_BG')};border-bottom:2px solid {bs.color('BUTTON_ACCENT')}"
            ";}QTabBar::tab:hover{background:"
            f"{bs.color('BUTTON_HOVER')}"
            ";}"
        )

    def _apply_completer_style(self, c):
        """为 Devices/Apps 标签页的 QCompleter 弹窗应用样式。"""
        if c is None:
            return
        p = c.popup()
        if p is None:
            return
        p.setFont(self._font_mono)
        bs = BaseStyles
        p.setStyleSheet(
            "QListView{background-color:"
            f"{bs.color('INPUT_BG')};color:{bs.color('TEXT_PRIMARY')};"
            "border:1px solid "
            f"{bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_SM}px;padding:2px;outline:none"
            ";}QListView::item{padding:4px 8px;}"
            "QListView::item:selected{background-color:"
            f"{bs.color('SELECTION_BG')};color:{bs.color('SELECTION_TEXT')}"
            ";}QListView::item:hover{background-color:"
            f"{bs.color('BUTTON_HOVER')}"
            ";}"
        )

    def _on_theme_changed(self, _):
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        self._apply_tab_style()
        scrollbar_qss = BaseStyles.SCROLLBAR_STYLE()
        group_qss = BaseStyles.GROUP_BOX_STYLE()
        roots = [self]
        device_widget = getattr(self, "_device_widget", None)
        if device_widget is not None and not self.isAncestorOf(device_widget):
            roots.append(device_widget)
        visited = set()
        # Devices 视觉根由 MainFrame 托管，主题刷新必须显式覆盖两个控件树。
        for root in roots:
            for child in (root, *root.findChildren(QWidget)):
                child_id = id(child)
                if child_id in visited:
                    continue
                visited.add(child_id)
                if isinstance(child, QGroupBox):
                    child.setStyleSheet(group_qss)
                elif isinstance(child, QPushButton):
                    variant = child.property("buttonVariant")
                    if variant:
                        child.setObjectName(str(variant))
                        child.setStyleSheet(BaseStyles.BUTTON_QSS())
                        child.style().unpolish(child)
                        child.style().polish(child)
                    icon_name = child.property("iconName")
                    if icon_name:
                        child.setIcon(get_themed_icon(icon_name))
                elif isinstance(child, QScrollArea):
                    child.setStyleSheet(
                        f"QScrollArea {{ border: none; background: transparent; }}\n{scrollbar_qss}"
                    )
        self.apply_device_theme()
        if self._apps_tab is not None:
            if hasattr(self._apps_tab, "completer"):
                self._apply_completer_style(self._apps_tab.completer)
            self._apps_tab._update_pct_total()
        self._responsive_style_generation = getattr(self, "_responsive_style_generation", 0) + 1
        request_reflow = getattr(self, "request_responsive_reflow", None)
        if callable(request_reflow):
            request_reflow(ReflowReason.THEME)

    def _on_fonts_changed(self, _config):
        """字体配置变化时更新已创建控件，不借用主题刷新路径。"""

        self._create_fonts()
        self.setFont(self._font_base)
        self.tabs.setFont(self._font_tab)
        group_qss = BaseStyles.GROUP_BOX_STYLE()
        roots = [self]
        device_widget = getattr(self, "_device_widget", None)
        if device_widget is not None and not self.isAncestorOf(device_widget):
            roots.append(device_widget)
        for root in roots:
            root.setFont(self._font_base)
            for child in root.findChildren(QWidget):
                role = child.property("fontRole")
                if role:
                    try:
                        child.setFont(BaseStyles.font_for_role(role))
                    except ValueError:
                        child.setFont(self._font_base)
                if isinstance(child, QGroupBox):
                    # 分组标题净空依赖当前字体度量，字号变化后必须同步刷新 QSS。
                    child.setStyleSheet(group_qss)
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            refresh_metrics = getattr(tab, "refresh_responsive_metrics", None)
            if callable(refresh_metrics):
                refresh_metrics()
        self._devices_tab.apply_fonts()
        self._apply_completer_style(
            self._apps_tab.completer if self._apps_tab is not None else None
        )
        self._responsive_style_generation = getattr(self, "_responsive_style_generation", 0) + 1
        request_reflow = getattr(self, "request_responsive_reflow", None)
        if callable(request_reflow):
            request_reflow(ReflowReason.FONT)

    # ── 信号连接 ──────────────────────────────────────────────────────────

    def _connect_all_signals(self):
        """委托各标签页连接各自的信号。"""
        self._devices_tab.connect_signals()
        self._tabs_connected = True
        for index in sorted(self._loaded_lazy_tabs):
            self._connect_lazy_tab_signals(index)
