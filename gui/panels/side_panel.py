"""协调设备、应用、系统和 Remote 子面板的延迟加载与信号连接。"""

from typing import cast

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QPushButton,
    QWidget,
)
from qfluentwidgets import HeaderCardWidget, PushButton, SmoothScrollArea

from gui.panels.app_panel import AppPanel
from gui.panels.device_manager import DeviceManager
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.system_panel import SystemPanel
from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_fluent_icon
from gui.widgets.responsive_controller import (
    _EVENT_REASONS,
    ReflowReason,
    ResponsiveCoordinator,
)
from gui.widgets.responsive_layout import prepare_responsive_content


class SidePanel(QWidget):
    """创建并管理功能标签页，同时保持 MainFrame 使用的兼容接口。"""

    _DISCOVERY_STATES = frozenset({"scanning", "empty", "unavailable", "ready"})
    selected_devices_changed = Signal(list)
    device_discovery_state_changed = Signal(str)
    responsive_layout_settled = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.signals = SidePanelSignals()
        self._package_history = []
        self._connected_device_cache = []
        self._device_discovery_state = "scanning"
        self._user_selected_ip = False
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

    # ── 界面构建 ─────────────────────────────────────────────────────────

    def _create_ui(self):
        # SidePanel 只保留跨页面状态与信号协调职责，不再创建可见页签/页面栈。
        # 设备面板与三个功能页由 MainFrame 直接注册为 FluentWindow 子页面。
        self._devices_tab = DeviceManager(self)
        self._devices_tab.setParent(self)
        self._devices_tab.hide()
        self._device_widget = self._devices_tab.build_ui()

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
        self._ensure_tab_loaded(0)

    def _create_tab_scroll_area(self) -> SmoothScrollArea:
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        # 响应式重排优先；极窄宽度或超大字体下保留可访问的横向兜底。
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 纵向滚动条预留（AlwaysOn）：页面栈迁移后页签头占用少量高度，内容溢出时
        # 滚动条若在 settle 后弹出会吃掉 viewport 宽度，破坏"一次 settle 即最终几何"
        # 契约；预留空间后滚动条出现与否都不改变内容宽度（P1 页面栈迁移）。
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        # SmoothScrollArea 用自定义 SmoothScrollBar 承接滚动，滚动条样式由其
        # FluentStyleSheet 提供，这里只保留透明容器边框。
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return scroll

    def _ensure_tab_loaded(self, index: int):
        if index < 0 or index >= len(self._lazy_tab_specs):
            return None
        attr, cls, _name = self._lazy_tab_specs[index]
        tab = getattr(self, attr, None)
        if tab is not None:
            return tab
        tab = cls(self)
        # 控制器属于共享状态协调器；可见根控件随后交给工作区宿主。
        # 显式隐藏控制器，销毁协调器时 Qt 自动断开其全局样式连接。
        tab.setParent(self)
        tab.hide()
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
        if watched is getattr(self, "_responsive_top_level", None):
            if event.type() in _EVENT_REASONS and not self._responsive_settle_timer.isActive():
                self._responsive_settle_timer.start()
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
                apply_responsive_width(cast(QResizeEvent, event).size().width())
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
        """新操作只用已选在线设备；ADB 不可用时拒绝提交，扫描中保留最近快照。"""

        if self._device_discovery_state == "unavailable":
            return []
        connected = set(self._connected_device_cache)
        return list(dict.fromkeys(
            device for device in self._devices_tab.selected_devices if device in connected
        ))

    @property
    def ip_address(self) -> str:
        return self._devices_tab.ip_address

    @property
    def device_widget(self) -> QWidget:
        return self._device_widget

    # ── MainFrame 使用的公共接口 ─────────────────────────────────────────

    def update_device_list(self, devices: list[str] | None = None):
        self._devices_tab.update_device_list(devices)
        self.set_device_discovery_state("ready" if devices else "empty")

    def set_device_discovery_state(self, state: str) -> None:
        """提交并渲染唯一的设备发现状态。"""

        normalized = str(state or "empty").lower()
        if normalized not in self._DISCOVERY_STATES:
            normalized = "empty"
        previous = self._device_discovery_state
        self._device_discovery_state = normalized
        self._devices_tab.set_discovery_state(normalized)
        if normalized != previous:
            self._refresh_loaded_action_states()
            self.device_discovery_state_changed.emit(normalized)

    def request_device_refresh(self) -> bool:
        """进入扫描态并只发送一次刷新请求；扫描结束前拒绝重复请求。"""

        if self._device_discovery_state == "scanning":
            return False
        self.set_device_discovery_state("scanning")
        self.signals.refresh_devices_requested.emit()
        return True

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

    def attach_responsive_top_level(self, widget: QWidget) -> None:
        """让协调器直接观察顶层窗口的 Resize/Font/Theme/LayoutRequest 事件。

        仅依赖 viewport 事件过滤器会漏掉未加载 tab 与 Devices 面板，窗口缩放时
        这些区域不会重排；挂到顶层后协调器通过事件过滤器统一感知尺寸变化。
        """

        previous = getattr(self, "_responsive_top_level", None)
        if previous is not None and previous is not widget:
            previous.removeEventFilter(self)
        self._responsive_top_level = widget
        widget.installEventFilter(self)
        self._responsive_coordinator.attach_top_level(widget)

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
        top_level = getattr(self, "_responsive_top_level", None)
        if top_level is not None:
            top_level.removeEventFilter(self)
            self._responsive_coordinator.detach_top_level(top_level)
            self._responsive_top_level = None
        settle_timer = getattr(self, "_responsive_settle_timer", None)
        if settle_timer is not None:
            settle_timer.stop()
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

    def _visual_roots(self) -> list[QWidget]:
        """返回被 FluentWindow 页面托管的全部已创建视觉根。"""

        roots: list[QWidget] = [self]
        device_widget = getattr(self, "_device_widget", None)
        if device_widget is not None and not self.isAncestorOf(device_widget):
            roots.append(device_widget)
        for index in sorted(self._loaded_lazy_tabs):
            scroll = self._tab_scroll_areas.get(index)
            widget = scroll.widget() if scroll is not None else None
            if widget is not None and widget not in roots:
                roots.append(widget)
        return roots

    def _on_theme_changed(self, _):
        visited = set()
        # 视觉根已由 FluentWindow 各页面托管，主题刷新必须显式覆盖全部控件树。
        for root in self._visual_roots():
            for child in (root, *root.findChildren(QWidget)):
                child_id = id(child)
                if child_id in visited:
                    continue
                visited.add(child_id)
                if isinstance(child, HeaderCardWidget):
                    child.update()
                elif isinstance(child, QPushButton):
                    # qfluentwidgets 按钮自维护主题，这里同步原生 Fluent 操作图标。
                    icon_name = child.property("iconName")
                    if icon_name:
                        icon = get_fluent_icon(icon_name)
                        if isinstance(child, PushButton):
                            child.setIcon(icon)
                        else:
                            child.setIcon(icon.qicon())
        self.apply_device_theme()
        if self._apps_tab is not None:
            self._apps_tab._update_pct_total()
        self._responsive_style_generation = getattr(self, "_responsive_style_generation", 0) + 1
        request_reflow = getattr(self, "request_responsive_reflow", None)
        if callable(request_reflow):
            request_reflow(ReflowReason.THEME)

    def _on_fonts_changed(self, _config):
        """字体配置变化时更新已创建控件，不借用主题刷新路径。"""

        self._create_fonts()
        self.setFont(self._font_base)
        for root in self._visual_roots():
            root.setFont(self._font_base)
            for child in (root, *root.findChildren(QWidget)):
                role = child.property("fontRole")
                if role:
                    try:
                        child.setFont(BaseStyles.font_for_role(role))
                    except ValueError:
                        child.setFont(self._font_base)
                if isinstance(child, HeaderCardWidget):
                    title_label = child.headerLabel
                    title_label.setFont(BaseStyles.font_for_role(FontRole.TITLE))
                    # 隐藏页不会立即收到布局事件；主动激活标题区，避免首次
                    # 切入页面时仍沿用旧字号高度而裁掉字形底部。
                    title_label.updateGeometry()
                    child.headerLayout.invalidate()
                    child.headerLayout.activate()
                    child.updateGeometry()
        for index in sorted(self._loaded_lazy_tabs):
            attr, _cls, _name = self._lazy_tab_specs[index]
            tab = getattr(self, attr, None)
            refresh_metrics = getattr(tab, "refresh_responsive_metrics", None)
            if callable(refresh_metrics):
                refresh_metrics()
        self._devices_tab.apply_fonts()
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
